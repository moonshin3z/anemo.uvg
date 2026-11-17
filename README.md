# Anemo · Integración con AWS

Código del nodo ESP32, configuración de integración y dashboard ambiental.

## Archivos

- `anemo_nodo/anemo_nodo.ino`: versión de firmware disponible en los archivos de esta conversación. No es una exportación verificada de la última versión cargada en la placa; los ajustes posteriores de diagnóstico compartidos por chat pueden diferir.
- `anemo_nodo/config.h`: configuración para el SSID `Galaxy S10+a89b`, sin contraseña ni IP de broker predefinida.
- `aws/greengrass_actualizacion.json`: actualización del MQTT Bridge observada en AWS; no representa toda la configuración efectiva del componente.
- `aws/regla_dynamodb.json` y `aws/guardar_telemetria.sql`: regla GuardarTelemetriaAnemo y acción DynamoDBv2.
- `aws/instalar_panel_amigable_anemo.py`: instalador del dashboard entregado durante el proyecto.
- `aws/lambda/anemo_widget.py`: código de Lambda extraído del mismo instalador.

## Arduino IDE

Abrir `anemo_nodo/anemo_nodo.ino` y seleccionar ESP32 Dev Module. Instalar PubSubClient, ArduinoJson 7, Adafruit BME280 Library, Adafruit BMP280 Library, Adafruit BME680 Library, Adafruit SGP40 Sensor, MH-Z19 (Jonathan Dempsey), PMS Library (Mariusz Kacki), rc-switch y Adafruit NeoPixel, con sus dependencias.

Antes de cargar la placa, completar en una copia local de config.h la contraseña WIFI_PASS y la IP actual de la Raspberry Pi en MQTT_HOST. Ambas placas deben alcanzar la misma red local. No publicar esa copia con la contraseña. La IP puede cambiar al cambiar de red. La entrega de este paquete no incluye una nueva compilación ni una prueba física.

## Flujo y recursos

ESP32 → Mosquitto en Raspberry Pi → Greengrass MQTT Bridge → AWS IoT Core → DynamoDB. CloudWatch presenta un widget personalizado generado por Lambda a partir de las consultas a DynamoDB.

- Región: us-east-1
- Thing: seccion20-equipo4
- Tema reenviado: anemo/aula01/nodo01/telemetria
- Tabla: Telemetria_Anemo_equipo4
- Regla: GuardarTelemetriaAnemo
- Dashboard: Anemo_Aula01_Equipo04
- Lambda: customWidgetAnemoAmbiente
- Rol de Lambda: AnemoDashboardLecturaRole

El instalador modifica recursos AWS: crea o actualiza la función y su rol, respalda el panel anterior y actualiza su presentación. No hace falta ejecutarlo de nuevo para subir este repositorio.

## Alcance de las pruebas

Se observaron lecturas de CO₂, partículas, temperatura, humedad y presión; recepción en AWS IoT Core; almacenamiento en DynamoDB y visualización en el dashboard. Los eventos de puerta y el estado del nodo se verificaron en Mosquitto local. VOC permaneció sin lectura. Una orden de ventilador en telemetría no demuestra por sí sola el movimiento físico del ventilador. No se incluyen certificados, llaves privadas ni credenciales AWS.
