// =============================================================
//  Anemo - Nodo IoT de calidad del aire (ESP32)
//  CC3108 Internet of Things - Proyecto Fase 03
//
//  Que hace este programa:
//   1. Lee CO2 (MH-Z19C), PM2.5 (PMS5003), COV (SGP40),
//      temperatura/humedad/presion (BME280) y el estado de
//      puerta y ventana (sensores 433 MHz).
//   2. Valida las lecturas y promedia PM2.5 y COV en cada ventana
//      de envio.
//   3. Controla localmente el LED (estado del aire) y el
//      ventilador (CO2 o PM2.5 sobre el umbral), aunque no haya red.
//   4. Publica telemetria y eventos en JSON por MQTT hacia el
//      broker de la Raspberry Pi y recibe comandos (aforo, modo,
//      ventilador).
//   5. Si se pierde el broker, guarda los mensajes en un buffer y
//      los reenvia al reconectar.
//
//  Librerias (Gestor de bibliotecas de Arduino IDE):
//   PubSubClient (Nick O'Leary), ArduinoJson 7 (Benoit Blanchon),
//   Adafruit BME280 Library, Adafruit SGP40 Sensor,
//   MH-Z19 (Jonathan Dempsey), PMS Library (Mariusz Kacki),
//   rc-switch (sui77), Adafruit NeoPixel
//  Placa: "ESP32 Dev Module"
// =============================================================
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_BME280.h>
#include <Adafruit_SGP40.h>
#include <MHZ19.h>
#include <PMS.h>
#include <RCSwitch.h>
#include <Adafruit_NeoPixel.h>
#include <time.h>
#include <math.h>
#include "config.h"

// ---------------- Topicos MQTT ----------------
// anemo/<aula>/<nodo>/<tipo>
#define BASE_TOPIC "anemo/" AULA_ID "/" NODE_ID
const char* T_TELEMETRIA = BASE_TOPIC "/telemetria";  // publica
const char* T_EVENTO     = BASE_TOPIC "/evento";      // publica
const char* T_ESTADO     = BASE_TOPIC "/estado";      // publica (retenido + LWT)
const char* T_CMD        = BASE_TOPIC "/cmd/#";       // suscribe
const char* T_CMD_AFORO  = BASE_TOPIC "/cmd/aforo";
const char* T_CMD_MODO   = BASE_TOPIC "/cmd/modo";
const char* T_CMD_VENT   = BASE_TOPIC "/cmd/ventilador";

// ---------------- Objetos ----------------
WiFiClient        net;
PubSubClient      mqtt(net);
Adafruit_BME280   bme;
Adafruit_SGP40    sgp;
MHZ19             mhz;
PMS               pms(Serial1);
PMS::DATA         pmsData;
RCSwitch          rf;
Adafruit_NeoPixel led(LED_COUNT, PIN_LED, NEO_GRB + NEO_KHZ800);

// ---------------- Estado del sistema ----------------
struct Estado {
  // ultimas lecturas validas (NAN = sin dato valido)
  float co2 = NAN, temp = NAN, hum = NAN, pres = NAN;
  // acumuladores para promediar PM2.5 y COV entre envios
  float pmSuma = 0, vocSuma = 0;
  uint16_t pmN = 0, vocN = 0;
  float pmUltimo = NAN, vocUltimo = NAN;
  // entradas digitales / manuales
  int  ocupacion = -1;          // -1 = sin dato; lo envia la Raspberry Pi
  int8_t puerta = -1;           // -1 desconocido, 0 cerrada, 1 abierta
  int8_t ventana = -1;
  // salidas
  bool ventilador = false;
  String ventModo = "auto";     // auto | on | off (comando remoto)
  String aire = "sin_dato";     // bueno | moderado | malo
  // operacion
  bool ahorro = false;
  uint32_t seq = 0;             // numero de mensaje (detecta perdidas)
  uint16_t erroresSensor = 0;
  bool bmeOk = false, sgpOk = false;
} st;

// ---------------- Buffer offline ----------------
String buffer[BUFFER_MAX];
uint8_t bufIni = 0, bufCant = 0;

// ---------------- Temporizadores ----------------
uint32_t tSgp = 0, tPms = 0, tCo2 = 0, tBme = 0, tTx = 0, tMqtt = 0, tLed = 0;
uint32_t tArranque = 0;
bool parpadeo = false;

// =============================================================
//  Utilidades
// =============================================================
bool enRango(float v, float lo, float hi) { return !isnan(v) && v >= lo && v <= hi; }

// Agrega un numero al JSON o null si no hay dato valido
void setNum(JsonDocument& d, const char* k, float v, int dec = 1) {
  if (isnan(v)) d[k] = nullptr;
  else d[k] = roundf(v * powf(10, dec)) / powf(10, dec);
}

const char* txtPuerta(int8_t v) { return v < 0 ? "desconocido" : (v ? "abierta" : "cerrada"); }

// Marca de tiempo ISO 8601 con zona horaria; null si aun no hay hora (NTP)
void setTimestamp(JsonDocument& d) {
  time_t ahora = time(nullptr);
  if (ahora > 1700000000) {           // hora ya sincronizada por NTP
    struct tm tmLocal;
    localtime_r(&ahora, &tmLocal);
    char ts[30];
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%S-06:00", &tmLocal);
    d["ts"] = ts;
  } else {
    d["ts"] = nullptr;                // la Pi usa su hora de recepcion
  }
  d["uptime_s"] = millis() / 1000;
}

// =============================================================
//  MQTT: publicar con respaldo en buffer
// =============================================================
void guardarEnBuffer(const String& msg) {
  uint8_t pos = (bufIni + bufCant) % BUFFER_MAX;
  buffer[pos] = msg;
  if (bufCant < BUFFER_MAX) bufCant++;
  else bufIni = (bufIni + 1) % BUFFER_MAX;   // lleno: se descarta el mas viejo
}

// Cada elemento del buffer guarda "topico\npayload"
void publicarODiferir(const char* topico, JsonDocument& doc) {
  doc["diferido"] = !mqtt.connected();
  String payload;
  serializeJson(doc, payload);
  Serial.printf("[TX] %s %s\n", topico, payload.c_str());
  if (mqtt.connected() && mqtt.publish(topico, payload.c_str())) return;
  guardarEnBuffer(String(topico) + "\n" + payload);
}

void vaciarBuffer() {
  while (bufCant > 0 && mqtt.connected()) {
    String& item = buffer[bufIni];
    int sep = item.indexOf('\n');
    if (!mqtt.publish(item.substring(0, sep).c_str(), item.substring(sep + 1).c_str())) break;
    bufIni = (bufIni + 1) % BUFFER_MAX;
    bufCant--;
    mqtt.loop();
  }
  if (bufCant == 0) Serial.println("[MQTT] buffer vaciado");
}

// =============================================================
//  Mensajes
// =============================================================
void publicarEvento(const char* tipo, const char* detalle) {
  JsonDocument d;
  d["nodo"] = NODE_ID; d["aula"] = AULA_ID; d["seq"] = ++st.seq;
  setTimestamp(d);
  d["tipo"] = tipo; d["detalle"] = detalle;
  setNum(d, "co2_ppm", st.co2, 0);
  publicarODiferir(T_EVENTO, d);
}

void publicarTelemetria() {
  JsonDocument d;
  d["nodo"] = NODE_ID; d["aula"] = AULA_ID; d["seq"] = ++st.seq;
  setTimestamp(d);
  d["modo"] = st.ahorro ? "ahorro" : "normal";
  setNum(d, "co2_ppm", st.co2, 0);
  // PM2.5 y COV: promedio de las lecturas de 1 s de esta ventana
  setNum(d, "pm25_ugm3", st.pmN ? st.pmSuma / st.pmN : NAN, 1);
  setNum(d, "voc_index", st.vocN ? st.vocSuma / st.vocN : NAN, 0);
  d["n_pm25"] = st.pmN; d["n_voc"] = st.vocN;
  setNum(d, "temp_c", st.temp, 1);
  setNum(d, "hum_pct", st.hum, 1);
  setNum(d, "pres_hpa", st.pres, 1);
  if (st.ocupacion < 0) d["ocupacion"] = nullptr; else d["ocupacion"] = st.ocupacion;
  d["puerta"] = txtPuerta(st.puerta);
  d["ventana"] = txtPuerta(st.ventana);
  d["ventilador"] = st.ventilador;
  d["vent_modo"] = st.ventModo;
  d["aire"] = st.aire;
  d["errores"] = st.erroresSensor;
  publicarODiferir(T_TELEMETRIA, d);
  st.pmSuma = st.vocSuma = 0; st.pmN = st.vocN = 0;   // nueva ventana
}

void publicarEstado(bool online) {
  JsonDocument d;
  d["nodo"] = NODE_ID; d["estado"] = online ? "online" : "offline";
  d["ip"] = WiFi.localIP().toString();
  d["buffer"] = bufCant;
  String s; serializeJson(d, s);
  mqtt.publish(T_ESTADO, s.c_str(), true);   // retenido
}

// =============================================================
//  Comandos recibidos desde la Raspberry Pi
// =============================================================
void alRecibir(char* topic, byte* payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) { Serial.println("[CMD] JSON invalido"); return; }
  String t(topic);
  Serial.printf("[CMD] %s\n", topic);

  if (t == T_CMD_AFORO && d["ocupacion"].is<int>()) {
    int n = d["ocupacion"];
    if (n >= 0 && n <= 50) {
      st.ocupacion = n;
      publicarEvento("cmd_ok", "aforo actualizado");
    } else publicarEvento("cmd_error", "aforo fuera de rango 0-50");
  } else if (t == T_CMD_MODO) {
    String m = d["modo"] | "";
    if (m == "ahorro" || m == "normal") {
      st.ahorro = (m == "ahorro");
      publicarEvento("cmd_ok", st.ahorro ? "modo ahorro" : "modo normal");
    } else publicarEvento("cmd_error", "modo invalido (normal|ahorro)");
  } else if (t == T_CMD_VENT) {
    String m = d["modo"] | "";
    if (m == "auto" || m == "on" || m == "off") {
      st.ventModo = m;
      publicarEvento("cmd_ok", ("ventilador " + m).c_str());
    } else publicarEvento("cmd_error", "ventilador invalido (auto|on|off)");
  } else {
    publicarEvento("cmd_error", "comando desconocido o mal formado");
  }
}

// =============================================================
//  Conectividad (no bloqueante: el control local sigue corriendo)
// =============================================================
void conectarMqtt() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected()) return;
  if (millis() - tMqtt < T_MQTT_RETRY_MS) return;
  tMqtt = millis();
  // Last Will: si el nodo se cae, el broker publica "offline" retenido
  const char* lwt = "{\"nodo\":\"" NODE_ID "\",\"estado\":\"offline\"}";
  Serial.print("[MQTT] conectando... ");
  if (mqtt.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASS, T_ESTADO, 1, true, lwt)) {
    Serial.println("ok");
    mqtt.subscribe(T_CMD, 1);
    publicarEstado(true);
    publicarEvento("conexion", "conectado al broker");
    vaciarBuffer();
  } else {
    Serial.printf("fallo, rc=%d\n", mqtt.state());
  }
}

// =============================================================
//  Lectura de sensores
// =============================================================
void leerSgp40() {                       // cada 1 s
  if (!st.sgpOk) return;
  float t = isnan(st.temp) ? 25 : st.temp, h = isnan(st.hum) ? 50 : st.hum;
  int32_t voc = sgp.measureVocIndex(t, h);   // compensado con el BME280
  // durante el aprendizaje inicial el algoritmo devuelve 0
  if (enRango(voc, 1, 500)) { st.vocSuma += voc; st.vocN++; st.vocUltimo = voc; }
}

void leerPms() {                          // el sensor emite una trama ~1 s
  if (pms.read(pmsData)) {
    float pm = pmsData.PM_AE_UG_2_5;
    if (enRango(pm, 0, 1000)) { st.pmSuma += pm; st.pmN++; st.pmUltimo = pm; }
    else st.erroresSensor++;
  }
}

void leerCo2() {
  if (millis() - tArranque < T_MHZ_PRECALENTAR_MS) return;   // precalentamiento
  int c = mhz.getCO2();
  if (mhz.errorCode == RESULT_OK && enRango(c, 350, 5100)) st.co2 = c;
  else { st.co2 = NAN; st.erroresSensor++; }
}

void leerBme() {
  if (!st.bmeOk) return;
  float t = bme.readTemperature(), h = bme.readHumidity(), p = bme.readPressure() / 100.0f;
  st.temp = enRango(t, -10, 60) ? t : NAN;
  st.hum  = enRango(h, 0, 100) ? h : NAN;
  st.pres = enRango(p, 300, 1100) ? p : NAN;
  if (isnan(st.temp) || isnan(st.hum) || isnan(st.pres)) st.erroresSensor++;
}

void leerRf() {
  if (!rf.available()) return;
  unsigned long c = rf.getReceivedValue();
  rf.resetAvailable();
  Serial.printf("[RF] codigo %lu\n", c);   // usar para llenar config.h
  int8_t p = st.puerta, v = st.ventana;
  if (c == RF_PUERTA_ABIERTA && c)  p = 1;
  if (c == RF_PUERTA_CERRADA && c)  p = 0;
  if (c == RF_VENTANA_ABIERTA && c) v = 1;
  if (c == RF_VENTANA_CERRADA && c) v = 0;
  if (p != st.puerta)  { st.puerta = p;  publicarEvento("puerta",  txtPuerta(p)); }
  if (v != st.ventana) { st.ventana = v; publicarEvento("ventana", txtPuerta(v)); }
}

// =============================================================
//  Procesamiento local y salidas (funciona sin red)
// =============================================================
void actualizarSalidas() {
  // 1) Clasificacion del aire con el peor de los tres indicadores
  float pm = st.pmUltimo, voc = st.vocUltimo;
  String aire = "sin_dato";
  if (!isnan(st.co2) || !isnan(pm) || !isnan(voc)) {
    aire = "bueno";
    if ((st.co2 >= CO2_MODERADO) || (pm >= PM25_MODERADO) || (voc >= VOC_MODERADO)) aire = "moderado";
    if ((st.co2 >= CO2_MALO) || (pm >= PM25_MALO) || (voc >= VOC_MALO)) aire = "malo";
  }
  if (aire != st.aire) { st.aire = aire; publicarEvento("aire", aire.c_str()); }

  // 2) Ventilador con histeresis (o forzado por comando)
  bool vent = st.ventilador;
  if (st.ventModo == "on") vent = true;
  else if (st.ventModo == "off") vent = false;
  else {
    bool encender = (st.co2 >= CO2_MALO) || (pm >= PM25_MALO);
    bool apagar   = (isnan(st.co2) || st.co2 < CO2_APAGAR) && (isnan(pm) || pm < PM25_APAGAR);
    if (encender) vent = true; else if (apagar) vent = false;
  }
  if (vent != st.ventilador) {
    st.ventilador = vent;
    digitalWrite(PIN_VENT, vent ? HIGH : LOW);
    publicarEvento("ventilador", vent ? "encendido" : "apagado");
  }

  // 3) LED: verde / amarillo / rojo; rojo parpadeante = ventilar
  //    (aire malo con puerta y ventana cerradas)
  uint32_t color = led.Color(0, 0, 60);                    // azul: sin dato
  if (st.aire == "bueno")    color = led.Color(0, 150, 0);
  if (st.aire == "moderado") color = led.Color(180, 120, 0);
  if (st.aire == "malo")     color = led.Color(200, 0, 0);
  bool alertaVentilar = st.aire == "malo" && st.puerta == 0 && st.ventana == 0;
  if (alertaVentilar && parpadeo) color = 0;
  // Solo se refresca si cambia el color: led.show() apaga las
  // interrupciones un instante y podria cortar una trama de 433 MHz.
  static uint32_t colorActual = 0xFFFFFFFF;
  if (color == colorActual) return;
  colorActual = color;
  for (int i = 0; i < LED_COUNT; i++) led.setPixelColor(i, color);
  led.show();
}

// =============================================================
//  setup / loop
// =============================================================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n=== Anemo nodo " NODE_ID " ===");
  tArranque = millis();

  pinMode(PIN_VENT, OUTPUT); digitalWrite(PIN_VENT, LOW);
  led.begin(); led.setBrightness(LED_BRILLO); led.clear(); led.show();

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  st.bmeOk = bme.begin(0x76, &Wire) || bme.begin(0x77, &Wire);
  st.sgpOk = sgp.begin(&Wire);
  Serial.printf("BME280: %s  SGP40: %s\n", st.bmeOk ? "ok" : "NO", st.sgpOk ? "ok" : "NO");

  Serial2.begin(9600, SERIAL_8N1, PIN_MHZ_RX, PIN_MHZ_TX);
  mhz.begin(Serial2);
  mhz.autoCalibration(true);   // ABC: referencia 400 ppm cada 24 h

  Serial1.begin(9600, SERIAL_8N1, PIN_PMS_RX, PIN_PMS_TX);
  pms.activeMode();

  rf.enableReceive(digitalPinToInterrupt(PIN_RF));

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  configTzTime(TZ_INFO, NTP_SERVER_1, NTP_SERVER_2);

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(alRecibir);
  mqtt.setBufferSize(768);
  mqtt.setSocketTimeout(2);     // no bloquear el control local si el broker no responde
  mqtt.setKeepAlive(15);
}

void loop() {
  uint32_t ahora = millis();

  conectarMqtt();
  mqtt.loop();

  leerPms();
  leerRf();

  if (ahora - tSgp >= T_SGP40_MS) { tSgp = ahora; leerSgp40(); }
  if (ahora - tCo2 >= (st.ahorro ? T_CO2_AHORRO_MS : T_CO2_NORMAL_MS)) { tCo2 = ahora; leerCo2(); }
  if (ahora - tBme >= (st.ahorro ? T_BME_AHORRO_MS : T_BME_NORMAL_MS)) { tBme = ahora; leerBme(); }

  if (ahora - tLed >= 500) { tLed = ahora; parpadeo = !parpadeo; actualizarSalidas(); }

  if (ahora - tTx >= (st.ahorro ? T_TX_AHORRO_MS : T_TX_NORMAL_MS)) { tTx = ahora; publicarTelemetria(); }
}
