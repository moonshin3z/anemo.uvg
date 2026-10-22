// Anemo - prueba de integracion: todos los modulos a la vez, sin Wi-Fi ni MQTT
#include <Wire.h>
#include <Adafruit_BME280.h>
#include <Adafruit_BMP280.h>
#include <Adafruit_SGP40.h>
#include <MHZ19.h>
#include <PMS.h>
#include <RCSwitch.h>
#include <Adafruit_NeoPixel.h>

Adafruit_BME280 bme; Adafruit_BMP280 bmp(&Wire); Adafruit_SGP40 sgp;
MHZ19 mhz; PMS pms(Serial1); PMS::DATA pd;
RCSwitch rx, tx;
Adafruit_NeoPixel led(8, 4, NEO_GRB + NEO_KHZ800);

bool bmeOk, esBmp, sgpOk;
float t = NAN, h = NAN, p = NAN; int voc = -1, co2 = -1, pm1 = -1, pm25 = -1, pm10 = -1;
int puerta = -1; unsigned long ultimoRf = 0;
uint32_t tSgp, tCo2, tImp;

void color(uint8_t r, uint8_t g, uint8_t b) { for (int i = 0; i < 8; i++) led.setPixelColor(i, r, g, b); led.show(); }

void setup() {
  Serial.begin(115200); delay(1000);
  Serial.println("\n=== Anemo: prueba de integracion ===");
  led.begin(); led.setBrightness(40);
  color(255,0,0); delay(500); color(0,255,0); delay(500); color(0,0,255); delay(500); color(0,0,0);
  Serial.println("LED: deberias haber visto rojo, verde y azul");

  Wire.begin(21, 22); Wire.setTimeOut(50);
  Serial.print("I2C encontrados:");
  for (uint8_t a = 1; a < 127; a++) { Wire.beginTransmission(a); if (Wire.endTransmission() == 0) Serial.printf(" 0x%02X", a); }
  Serial.println("   (esperado: 0x59 y 0x76)");
  bmeOk = bme.begin(0x76) || bme.begin(0x77);
  if (!bmeOk && (bmp.begin(0x76) || bmp.begin(0x77))) { bmeOk = true; esBmp = true; }
  sgpOk = sgp.begin();
  Serial.printf("%s: %s   SGP40: %s\n", esBmp ? "BMP280" : "BME280", bmeOk ? "OK" : "FALLA", sgpOk ? "OK" : "FALLA");

  Serial2.begin(9600, SERIAL_8N1, 25, 26); mhz.begin(Serial2);
  Serial1.begin(9600, SERIAL_8N1, 27, 14); pms.activeMode();

  rx.enableReceive(digitalPinToInterrupt(32)); rx.setReceiveTolerance(80);
  tx.enableTransmit(33); tx.setRepeatTransmit(8);
  pinMode(18, INPUT_PULLUP);
  Serial.println("Puerta simulada: cable de fila 30 (GPIO18) al riel - = cerrada, suelto = abierta\n");
}

void loop() {
  uint32_t ahora = millis();
  if (pms.read(pd)) { pm1 = pd.PM_AE_UG_1_0; pm25 = pd.PM_AE_UG_2_5; pm10 = pd.PM_AE_UG_10_0; }

  if (ahora - tSgp >= 1000) { tSgp = ahora;
    if (bmeOk) { t = esBmp ? bmp.readTemperature() : bme.readTemperature();
                 h = esBmp ? 50 : bme.readHumidity();
                 p = (esBmp ? bmp.readPressure() : bme.readPressure()) / 100.0; }
    if (sgpOk) voc = sgp.measureVocIndex(isnan(t) ? 25 : t, isnan(h) ? 50 : h);
  }
  if (ahora - tCo2 >= 5000) { tCo2 = ahora; co2 = mhz.getCO2(); }

  int l = digitalRead(18) == HIGH ? 1 : 0;
  if (l != puerta) { puerta = l; delay(50);
    tx.send(l ? 10101UL : 10100UL, 24);
    Serial.printf(">> [TX] puerta %s enviada\n", l ? "ABIERTA" : "CERRADA"); }
  if (rx.available()) { ultimoRf = rx.getReceivedValue(); rx.resetAvailable();
    Serial.printf("<< [RX] codigo %lu = puerta %s\n", ultimoRf,
      ultimoRf == 10101UL ? "ABIERTA" : ultimoRf == 10100UL ? "CERRADA" : "?"); }

  if (ahora - tImp >= 3000) { tImp = ahora;
    Serial.printf("T=%.1f C  H=%.1f %%  P=%.1f hPa | VOC=%d | CO2=%d ppm | PM1=%d PM2.5=%d PM10=%d\n",
                  t, h, p, voc, co2, pm1, pm25, pm10);
    if (co2 >= 1000) color(255,0,0); else if (co2 >= 800) color(255,120,0); else if (co2 > 0) color(0,255,0); else color(0,0,60);
  }
}
