# Anemo

Nodo IoT para monitorear la calidad del aire en aulas. Proyecto del curso CC3108 Internet of Things, Universidad del Valle de Guatemala (sección 10, equipo 04).

Integrantes: Iván Roblero, Jair Morales y Daniel Hernández.

## Qué hace

Un ESP32 mide CO2 (MH-Z19C), partículas PM1, PM2.5 y PM10 (PMS5003), temperatura, humedad y presión (BME280), VOC (SGP40) y el estado de la puerta (MC-38). Con esas lecturas controla un semáforo LED (WS2812) y un ventilador. El control funciona aunque no haya internet.

Los datos viajan así:

ESP32 -> Mosquitto en la Raspberry Pi -> Greengrass (MQTT Bridge) -> AWS IoT Core -> DynamoDB -> dashboard en CloudWatch

## Carpetas

- `anemo_nodo/`: firmware final del nodo (Arduino IDE).
- `aws/`: configuración del MQTT Bridge, regla de IoT Core y script del dashboard.
- `firmware/`: versiones anteriores y sketches de prueba.
- `raspberry/`: configuración de Mosquitto y suscriptor local.
- `docs/`: informes, diagramas y catálogo de mensajes MQTT.

## Firmware

Abrir `anemo_nodo/anemo_nodo.ino` en Arduino IDE con la placa ESP32 Dev Module. Bibliotecas: PubSubClient, ArduinoJson 7, Adafruit BME280, Adafruit BMP280, Adafruit BME680, Adafruit SGP40, MH-Z19 (Jonathan Dempsey), PMS Library (Mariusz Kacki), rc-switch y Adafruit NeoPixel.

Antes de cargar, completar en `config.h` la contraseña del Wi-Fi (`WIFI_PASS`) y la IP de la Raspberry Pi (`MQTT_HOST`). No subir ese archivo con la contraseña.

## AWS

- Región: us-east-1
- Thing: seccion20-equipo4
- Tópico: anemo/aula01/nodo01/telemetria
- Tabla: Telemetria_Anemo_equipo4
- Regla: GuardarTelemetriaAnemo
- Dashboard: Anemo_Aula01_Equipo04

El repositorio no incluye certificados, llaves ni credenciales de AWS.
