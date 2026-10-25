// =============================================================
//  Anemo - Configuracion del nodo IoT (ESP32)
//  Cambiar SOLO este archivo para adaptar el nodo a la red,
//  al broker de la Raspberry Pi y a los sensores 433 MHz.
// =============================================================
#pragma once

// ---------- Identificacion del nodo ----------
#define AULA_ID        "aula01"
#define NODE_ID        "nodo01"
#define MQTT_CLIENT_ID "anemo-nodo01"   // identificador del cliente MQTT

// ---------- Red Wi-Fi local (la misma de la Raspberry Pi) ----------
#define WIFI_SSID "Anemo-LAN"
#define WIFI_PASS "cambiar-clave"

// ---------- Broker MQTT en la Raspberry Pi ----------
#define MQTT_HOST "192.168.1.50"     // IP fija de la Raspberry Pi
#define MQTT_PORT 1883
#define MQTT_USER "nodo01"
#define MQTT_PASS "cambiar-clave"

// ---------- Hora (NTP) ----------
// Primero la Raspberry Pi (funciona aunque no haya internet),
// despues un servidor publico como respaldo.
#define NTP_SERVER_1 MQTT_HOST
#define NTP_SERVER_2 "pool.ntp.org"
#define TZ_INFO      "CST6"            // Guatemala, UTC-6, sin horario de verano

// ---------- Pines (ESP32 de 38 pines) ----------
#define PIN_I2C_SDA   21   // bus 1 (Wire): BME280 / BME680
#define PIN_I2C_SCL   22
#define PIN_SGP_SDA   19   // bus 2 (Wire1): SGP40 solo, asi si uno falla
#define PIN_SGP_SCL   23   //                no tumba al otro
#define PIN_MHZ_RX    25   // ESP32 RX  <- TX del MH-Z19C
#define PIN_MHZ_TX    26   // ESP32 TX  -> RX del MH-Z19C
#define PIN_PMS_RX    27   // ESP32 RX  <- TX del PMS5003
#define PIN_PMS_TX    14   // ESP32 TX  -> RX del PMS5003
#define PIN_RF        32   // sensor de puerta MC-38 (un cable aqui, el otro a GND)
                           // o, si PUERTA_CABLEADA = 1, un cable del sensor MC-38 (el otro a GND)

// ---------- Sensor de puerta ----------
// 1 = sensor magnetico con cable (MC-38) directo a PIN_RF y GND (recomendado)
// 0 = sensor inalambrico 433 MHz con receptor
#define PUERTA_CABLEADA 1

// Puerta simulada (demo sin sensor de puerta, solo vale con PUERTA_CABLEADA 0):
// un cable en PIN_SIM_PUERTA hace de "iman". Conectado a GND = cerrada,
// suelto = abierta. Al cambiar, el FS1000A en PIN_RF_TX manda el codigo por
// 433 MHz y el receptor en PIN_RF lo recibe como si fuera un sensor real.
#define PUERTA_SIMULADA 1
#define PIN_RF_TX       33   // DATA del transmisor FS1000A
#define PIN_SIM_PUERTA  18   // cable a GND = puerta cerrada
#define PIN_VENT      13   // base del transistor 2N2222A (via 1k); HIGH = ventilador encendido
#define PIN_LED       4    // DIN de la tarjeta WS2812 (via 330 ohm)
#define LED_COUNT     8
#define LED_BRILLO    40   // 0-255; limita el consumo de los LED

// ---------- Codigos de los sensores 433 MHz ----------
// Se obtienen con la prueba inicial: abrir y cerrar cada sensor
// mirando el monitor serie (el firmware imprime cada codigo recibido).
// Con un solo sensor (puerta), dejar los de ventana en 0: se reporta "desconocido".
#define RF_PUERTA_ABIERTA   10101UL   // codigos de la puerta simulada
#define RF_PUERTA_CERRADA   10100UL
#define RF_VENTANA_ABIERTA  0UL
#define RF_VENTANA_CERRADA  0UL

// ---------- Intervalos (milisegundos) ----------
#define T_SGP40_MS            1000UL   // el algoritmo VOC exige 1 s
#define T_PMS_MS              1000UL   // PM2.5 cada 1 s
#define T_CO2_NORMAL_MS       5000UL   // CO2 cada 5 s (normal)
#define T_CO2_AHORRO_MS      30000UL   //            30 s (ahorro)
#define T_BME_NORMAL_MS       5000UL   // temp/hum/presion cada 5 s
#define T_BME_AHORRO_MS      30000UL
#define T_TX_NORMAL_MS       10000UL   // envio de telemetria cada 10 s
#define T_TX_AHORRO_MS       60000UL   //                     cada 60 s
#define T_MQTT_RETRY_MS       5000UL   // reintento de conexion al broker
#define T_MHZ_PRECALENTAR_MS 60000UL   // el MH-Z19C necesita 1 min

// ---------- Umbrales (set points de la Fase 01/02) ----------
#define CO2_MODERADO   800.0f   // ppm  -> LED amarillo
#define CO2_MALO      1000.0f   // ppm  -> LED rojo + ventilador
#define CO2_APAGAR     900.0f   // ppm  -> histeresis para apagar ventilador
#define PM25_MODERADO   25.0f   // ug/m3
#define PM25_MALO       35.0f
#define PM25_APAGAR     30.0f
#define VOC_MODERADO   150.0f   // indice VOC
#define VOC_MALO       200.0f

// ---------- Ajustes de sensores ----------
#define BME680_T_OFFSET  -1.0f  // el calentador de gas del BME680 lo calienta un poco
#define MHZ_T_OFFSET     -2.0f  // temperatura interna del MH-Z19C (solo respaldo)

// ---------- Buffer para cuando no hay broker ----------
#define BUFFER_MAX 60   // mensajes guardados en RAM (10 min en modo normal)
