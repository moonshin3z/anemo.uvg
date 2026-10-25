// Anemo - prueba de los sensores I2C nuevos, uno a la vez
// Bus 1 (GPIO21 SDA, GPIO22 SCL): BME280, BME680 o BMP280
// Bus 2 (GPIO19 SDA, GPIO23 SCL): SGP40
// Sirve igual en la ESP32 de 38 pines y en la de 30 pines.
#include <Wire.h>
#include <Adafruit_BME280.h>
#include <Adafruit_BMP280.h>
#include <Adafruit_BME680.h>
#include <Adafruit_SGP40.h>

Adafruit_BME280 bme; Adafruit_BMP280 bmp(&Wire); Adafruit_BME680 bme680(&Wire); Adafruit_SGP40 sgp;
int tipo = 0;            // 0 nada, 1 BME280, 2 BME680, 3 BMP280
bool sgpOk = false;
uint32_t tScan = 0, tLect = 0, inicio = 0;
uint16_t caidas = 0;

void escanear(TwoWire& w, const char* nombre) {
  Serial.printf("%s:", nombre);
  for (uint8_t a = 1; a < 127; a++) { w.beginTransmission(a); if (w.endTransmission() == 0) Serial.printf(" 0x%02X", a); }
  Serial.println();
}

void iniciar() {
  tipo = 0;
  if (bme.begin(0x76, &Wire) || bme.begin(0x77, &Wire)) tipo = 1;
  else if (bme680.begin(0x77) || bme680.begin(0x76)) {
    tipo = 2; bme680.setTemperatureOversampling(BME680_OS_8X); bme680.setHumidityOversampling(BME680_OS_2X);
    bme680.setPressureOversampling(BME680_OS_4X); bme680.setIIRFilterSize(BME680_FILTER_SIZE_3); bme680.setGasHeater(320, 150);
  }
  else if (bmp.begin(0x76) || bmp.begin(0x77)) tipo = 3;
  if (!sgpOk) sgpOk = sgp.begin(&Wire1);
}

void setup() {
  Serial.begin(115200); delay(1000);
  Wire.begin(21, 22, 50000);  Wire.setTimeOut(50);
  Wire1.begin(19, 23, 50000); Wire1.setTimeOut(50);
  Serial.println("\n=== Anemo: prueba de sensores I2C ===");
  Serial.println("Esperado -> bus1: 0x76 o 0x77 (BME)   bus2: 0x59 (SGP40)");
  escanear(Wire, "bus1"); escanear(Wire1, "bus2");
  iniciar(); inicio = millis();
}

void loop() {
  if (millis() - tScan > 10000) { tScan = millis(); escanear(Wire, "bus1"); escanear(Wire1, "bus2"); }
  if (millis() - tLect < 1000) return;
  tLect = millis();
  if (tipo == 0 || !sgpOk) iniciar();

  float t = NAN, h = NAN, p = NAN, gas = NAN; int voc = -1;
  if (tipo == 1) { t = bme.readTemperature(); h = bme.readHumidity(); p = bme.readPressure() / 100.0; }
  if (tipo == 2 && bme680.performReading()) { t = bme680.temperature; h = bme680.humidity; p = bme680.pressure / 100.0; gas = bme680.gas_resistance / 1000.0; }
  if (tipo == 3) { t = bmp.readTemperature(); p = bmp.readPressure() / 100.0; }
  if (tipo && (isnan(t) || t < -20 || t > 80 || p < 300 || p > 1100)) {
    caidas++; Serial.printf("!! %s dio basura (T=%.1f P=%.1f), reintentando\n", tipo == 2 ? "BME680" : tipo == 3 ? "BMP280" : "BME280", t, p);
    tipo = 0; return;
  }
  if (sgpOk) {
    if (sgp.measureRaw(isnan(t) ? 25 : t, isnan(h) ? 50 : h) == 0) { sgpOk = false; caidas++; Serial.println("!! SGP40 dejo de responder"); }
    else voc = sgp.measureVocIndex(isnan(t) ? 25 : t, isnan(h) ? 50 : h);
  }
  const char* n = tipo == 1 ? "BME280" : tipo == 2 ? "BME680" : tipo == 3 ? "BMP280" : "------";
  Serial.printf("%4lus | %s T=%.1f H=%.1f P=%.1f Gas=%.0fk | SGP40:%s VOC=%d | caidas=%u\n",
    (millis() - inicio) / 1000, n, t, h, p, gas, sgpOk ? "OK" : "--", voc, caidas);
}
