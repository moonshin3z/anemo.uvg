# Anemo: monitoreo de calidad del aire en aulas
## Proyecto CC3108 · Fase 03: implementación del hardware y comunicación MQTT
Integrantes: Iván, Jair, Daniel · Universidad del Valle de Guatemala · Octubre 2026

> Borrador. Las marcas [PENDIENTE] se completan cuando se tenga la Raspberry Pi, los sensores BME280/SGP40 y las fotos.

---

## 1. Descripción del sistema implementado

Anemo es un nodo IoT que mide la calidad del aire dentro de un aula para avisar cuándo hace falta ventilar. En las aulas cerradas el CO2 que exhalamos se acumula y, a partir de unas 1000 ppm, baja la concentración y el rendimiento de los estudiantes. El nodo mide CO2, partículas, compuestos orgánicos volátiles (VOC), temperatura y humedad, detecta si la puerta está abierta y responde con un semáforo LED y un ventilador. Los datos viajan por MQTT a una Raspberry Pi que guarda el historial, calcula la tasa de ventilación del aula y los sincroniza con Firebase.

En esta fase implementamos el nodo completo en protoboard, el firmware, el broker MQTT y el programa suscriptor.

**Placa del nodo:** ESP32 NodeMCU-32 de 38 pines (ESP32-WROOM-32, Wi-Fi 2.4 GHz, conversor USB CH340). La programamos con Arduino IDE 2.3 y el core esp32 3.3; elegimos Arduino sobre ESP-IDF porque ya existen librerías probadas para todos nuestros sensores, lo que nos dejó concentrarnos en la lógica del sistema.

| Componente | Tipo | Función en el sistema |
|---|---|---|
| MH-Z19C | Sensor NDIR (UART) | CO2 real en ppm; es la variable principal para decidir si ventilar. También da una temperatura interna que usamos como respaldo |
| PMS5003 | Sensor láser de partículas (UART) | PM1.0, PM2.5 y PM10 en µg/m³ |
| SGP40 | Sensor MOX (I2C, bus 2) | Índice VOC de 0 a 500 |
| BME280 | Sensor ambiental (I2C, bus 1) | Temperatura, humedad y presión; también compensa al SGP40 |
| MC-38 | Interruptor magnético (reed) | Estado de la puerta: abierta o cerrada |
| Tira WS2812 de 8 LED | Actuador / indicador | Semáforo verde, naranja y rojo; parpadea cuando hay que abrir la puerta |
| Ventilador 5 V con 2N2222A | Actuador | Ventilación forzada cuando el CO2 es alto |
| Adaptador 5 V / 2 A | Alimentación | Alimenta sensores, tira y ventilador; la ESP32 va por USB |

**Cambios respecto a la Fase 02 y por qué:**

| Antes | Ahora | Razón |
|---|---|---|
| Sensor de puerta inalámbrico 433 MHz + receptor MX-RM-5V | MC-38 cableado a GPIO32 | El sensor inalámbrico llegó con la batería muerta y sellado. Validamos el enlace 433 MHz con un transmisor FS1000A, pero el cable es más confiable y simple |
| BME280 y SGP40 en el mismo bus I2C | Cada uno en su propio bus (21/22 y 19/23) | Un SGP40 dañado jalaba la línea SDA y "escondía" al BME280. Con buses separados, una falla no tumba al otro sensor |
| MOSFET AO3400 para el ventilador | Transistor 2N2222A con resistencia de 1 kΩ y diodo 1N4007 | Disponibilidad; el ventilador de 5 V consume menos de 150 mA, que el 2N2222A maneja sin problema |
| Solo BME280 | BME280, con BME680 como respaldo detectado automáticamente | Los primeros módulos BME280 y SGP40 se dañaron (ver sección 8) |
| Temperatura solo del BME280 | Si falta el BME280, se usa la temperatura interna del MH-Z19C | El nodo nunca se queda sin temperatura |

## 2. Listado de entradas y salidas

**Entradas**

| Señal | Componente | Interfaz / pin | Variable | Unidad | Rango esperado |
|---|---|---|---|---|---|
| CO2 | MH-Z19C | UART2, GPIO25 (RX) / GPIO26 (TX) | Concentración de CO2 | ppm | 400 a 5000 |
| Temperatura interna | MH-Z19C | UART2 | Temperatura (respaldo) | °C | 15 a 35 |
| PM1.0 / PM2.5 / PM10 | PMS5003 | UART1, GPIO27 (RX) / GPIO14 (TX) | Partículas | µg/m³ | 0 a 500 |
| VOC | SGP40 | I2C bus 2, GPIO19 (SDA) / GPIO23 (SCL) | Índice VOC | adimensional | 0 a 500 (100 = normal) |
| Temperatura | BME280 | I2C bus 1, GPIO21 (SDA) / GPIO22 (SCL) | Temperatura | °C | 15 a 35 |
| Humedad | BME280 | I2C bus 1 | Humedad relativa | % | 20 a 90 |
| Presión | BME280 | I2C bus 1 | Presión atmosférica | hPa | 830 a 870 (Ciudad de Guatemala) |
| Puerta | MC-38 | GPIO32 con pull-up interno | Abierta / cerrada | binaria | 0 = cerrada, 1 = abierta |
| Aforo | Raspberry Pi (MQTT) | tópico cmd/aforo | Personas en el aula | personas | 0 a 50 |

**Salidas**

| Salida | Componente | Pin | Acción | Condición de activación |
|---|---|---|---|---|
| Semáforo | Tira WS2812 | GPIO4 (con 330 Ω) | Verde / naranja / rojo | Según el peor indicador: CO2 ≥ 800 naranja, ≥ 1000 rojo; PM2.5 ≥ 25 naranja, ≥ 35 rojo; VOC ≥ 150 naranja, ≥ 200 rojo |
| Alerta "ventilar" | Tira WS2812 | GPIO4 | Rojo parpadeante | Aire malo y puerta cerrada |
| Ventilador | Ventilador 5 V + 2N2222A | GPIO13 (con 1 kΩ) | Enciende / apaga | En automático: enciende con CO2 ≥ 1000 o PM2.5 ≥ 35; apaga con CO2 < 900 y PM2.5 < 30 (histéresis). También se puede forzar on/off por MQTT |

## 3. Diagramas de conexión y comunicación

**Diagrama eléctrico:** ver `docs/esquema_final_anemo.png` (nodo completo) y `docs/esquema_ventilador.png` (etapa del ventilador).

**Diagrama de comunicación:** [PENDIENTE: dibujarlo. Debe mostrar: ESP32 (cliente MQTT `anemo-nodo01`, publicador de telemetria/evento/estado y suscriptor de cmd/#) → Wi-Fi 2.4 GHz, red local → Raspberry Pi (broker Mosquitto, puerto 1883, y programa `suscriptor.py`) → SQLite local + Firebase Firestore por internet. Flechas: telemetría y eventos del nodo a la Pi; comandos y resultado "procesado" de la Pi al nodo.]

**Tabla de conexiones** (protoboard izquierda y derecha; la ESP32 va en las filas 22 a 40, con sus pines izquierdos en la columna j de la protoboard izquierda y los derechos en la columna a de la derecha):

| Componente | Pin del componente | Conexión |
|---|---|---|
| Adaptador 5 V | + / − | Riel + / riel − izquierdo (capacitor 1000 µF entre ambos) |
| ESP32 | 3V3 (h22 izq.) | Riel + derecho (3.3 V) |
| ESP32 | GND (h35 izq., c22 y d28 der.) | Rieles −; los dos rieles − están unidos arriba y abajo |
| MH-Z19C | Vin / GND / Tx / Rx | Riel + izq. / riel − / h30 (GPIO25) / h31 (GPIO26) |
| PMS5003 | VCC / GND / TXD / RXD | Riel + izq. / riel − / h32 (GPIO27) / h33 (GPIO14) |
| BME280 | VCC, CSB / GND, SDO / SCL / SDA | Riel + der. / riel − / c24 (GPIO22) / d27 (GPIO21) |
| SGP40 | VIN / GND / SCL / SDA / 3Vo | Riel + der. / riel − / c23 (GPIO23) / c29 (GPIO19) / sin conectar |
| MC-38 | Cable 1 / cable 2 | g28 (GPIO32) / riel − izq. |
| Tira WS2812 | VCC / GND / DIN | c15 (tras diodo 1N4007 desde el riel +) / riel − / h34 der. tras 330 Ω desde GPIO4 |
| Ventilador | Rojo / negro | i48 (5 V) / i46 (colector del 2N2222A) |
| 2N2222A | E / B / C | g44 → riel − / g45 ← 1 kΩ desde GPIO13 / g46; diodo 1N4007 de j46 a j48 |

## 4. Configuración del nodo y de la Raspberry Pi

**Nodo:** toda la configuración está en `firmware/anemo_nodo/config.h`: red Wi-Fi, IP del broker (`MQTT_HOST`), usuario y clave MQTT, pines, intervalos y umbrales. El identificador del cliente MQTT es **`anemo-nodo01`**. Los tópicos siguen la forma `anemo/<aula>/<nodo>/<tipo>`:

| Tópico | Nodo | Raspberry Pi | Función |
|---|---|---|---|
| anemo/aula01/nodo01/telemetria | Publica | Suscribe | Mediciones periódicas |
| anemo/aula01/nodo01/evento | Publica | Suscribe | Cambios de estado y alertas |
| anemo/aula01/nodo01/estado | Publica (retenido + Last Will) | Suscribe | Online/offline del nodo |
| anemo/aula01/nodo01/cmd/aforo | Suscribe | Publica | Número de personas |
| anemo/aula01/nodo01/cmd/modo | Suscribe | Publica | Modo normal o ahorro |
| anemo/aula01/nodo01/cmd/ventilador | Suscribe | Publica | Ventilador auto / on / off |
| anemo/aula01/nodo01/procesado | – | Publica | Resultado del procesamiento (ACH) |

**Broker:** Mosquitto en la Raspberry Pi, puerto 1883, con usuarios (`nodo01` para el nodo y `pi_sub` para el suscriptor), lista de acceso por tópico y persistencia de mensajes. La Pi también corre `chrony` como servidor de hora para la red local, para que el nodo tenga hora aunque no haya internet. Archivos: `raspberry/mosquitto/anemo.conf` y `anemo.acl`.

**Suscriptor:** `raspberry/suscriptor/suscriptor.py` (Python, paho-mqtt 2). Se suscribe a `anemo/#`, valida cada mensaje, lo guarda en SQLite y en un CSV, calcula la tasa de ventilación (ACH) y sube los datos a Firebase Firestore cuando hay internet.

**Puesta en marcha:**
```bash
# En la Raspberry Pi (una sola vez)
sudo bash raspberry/setup_pi.sh          # instala Mosquitto, chrony, Python y el servicio
sudo nano /opt/anemo/.env                # clave de pi_sub y ruta de la llave de Firebase
sudo systemctl start anemo-suscriptor
# Ver mensajes en vivo
mosquitto_sub -h localhost -u pi_sub -P <clave> -t 'anemo/#' -v
journalctl -u anemo-suscriptor -f
```
En el nodo: se edita `config.h` (Wi-Fi y `MQTT_HOST` con la IP fija de la Pi), se carga el firmware y se abre el monitor serie a 115200 baudios.

Mientras no tuvimos la Raspberry Pi, probamos con Mosquitto en una laptop usando `raspberry/mosquitto/anemo_laptop.conf`. [PENDIENTE: IP fija de la Pi y capturas.]

## 5. Frecuencia de captura y transmisión

| Variable | Captura | Transmisión | Justificación |
|---|---|---|---|
| CO2 | Cada 5 s (30 s en modo ahorro) | En la telemetría cada 10 s | El CO2 cambia en minutos; 5 s basta para ver la tendencia sin desgastar el sensor |
| PM1/PM2.5/PM10 | Cada 1 s (el sensor envía una trama por segundo) | Promedio de la ventana, cada 10 s | El promedio filtra el ruido del sensor láser |
| VOC | Cada 1 s | Promedio de la ventana, cada 10 s | El algoritmo del SGP40 exige una medición por segundo |
| Temperatura, humedad, presión | Cada 5 s (30 s en ahorro) | Cada 10 s | Cambian lento |
| Puerta | Continuo, con 50 ms de antirrebote | Evento inmediato al cambiar | Es un evento, no una medición |
| Calidad del aire / ventilador | Se recalcula cada 0.5 s | Evento inmediato al cambiar | Respuesta rápida ante un umbral |

La telemetría se envía cada 10 s (60 s en modo ahorro). No mandamos lecturas individuales sino **conjuntos**: el último valor válido de CO2 y de temperatura, humedad y presión, y el **promedio** de PM y VOC de la ventana, con la cantidad de muestras usadas (`n_pm25`, `n_voc`). También mandamos resultados de procesamiento: la clasificación del aire y la velocidad de cambio del CO2.

## 6. Catálogo de mensajes y payloads

El catálogo completo, con todos los campos, tipos y unidades, está en `docs/catalogo_mqtt.md`. Todos los mensajes llevan `nodo`, `aula` y `seq` (número de mensaje, para detectar pérdidas). La referencia temporal `ts` es la hora local en formato ISO 8601 (UTC−6), que el nodo obtiene por NTP de la Raspberry Pi o, como respaldo, de pool.ntp.org; si aún no tiene hora, manda `null` y la Pi usa su hora de recepción. `uptime_s` son los segundos desde que encendió.

**Telemetría:** el nodo la publica, la Pi la recibe; es periódica, cada 10 s. Ejemplo real de nuestras pruebas:
```json
{"nodo":"nodo01","aula":"aula01","seq":15,"ts":"2026-10-24T23:12:51-06:00","uptime_s":103,"modo":"normal","co2_ppm":1632,"pm1_ugm3":2.8,"pm25_ugm3":6.8,"pm10_ugm3":6.9,"voc_index":null,"n_pm25":10,"n_voc":0,"temp_c":21.1,"temp_fuente":"mhz19","hum_pct":null,"pres_hpa":null,"gas_kohm":null,"co2_ppm_min":1347,"rssi_dbm":-77,"ocupacion":null,"puerta":"cerrada","ventana":"desconocido","ventilador":true,"vent_modo":"auto","aire":"malo","errores":0,"diferido":false}
```

**Evento:** el nodo lo publica, la Pi lo recibe; se envía cuando algo cambia (puerta, calidad del aire, ventilador, conexión, falla de sensor, respuesta a un comando):
```json
{"nodo":"nodo01","aula":"aula01","seq":13,"ts":"2026-10-24T23:12:36-06:00","uptime_s":88,"tipo":"ventilador","detalle":"encendido","co2_ppm":1079,"diferido":false}
```

**Estado:** el nodo lo publica retenido al conectarse; si el nodo se desconecta sin avisar, el broker publica el Last Will `offline`:
```json
{"nodo":"nodo01","estado":"online","ip":"192.168.1.60","rssi_dbm":-61,"sensor_amb":"bme280","sensor_voc":"sgp40","buffer":0}
```

**Comandos** (la Pi los publica y el nodo responde con un evento `cmd_ok` o `cmd_error`): `cmd/aforo` `{"ocupacion":25}`, `cmd/modo` `{"modo":"ahorro"}`, `cmd/ventilador` `{"modo":"on"}`.

**Procesado:** la Pi lo publica con la tasa de ventilación (ACH) calculada. [PENDIENTE: ejemplo real.]

## 7. Procesamiento inicial y control de salidas

**En el nodo:**
- **Validación:** se descartan lecturas fuera de rango físico (CO2 entre 350 y 5100 ppm, temperatura entre −10 y 60 °C, presión entre 300 y 1100 hPa, PM entre 0 y 1000). Los valores inválidos se mandan como `null` y suman al contador `errores`. El MH-Z19C se ignora el primer minuto mientras se calienta.
- **Filtrado:** promedio por ventana de PM y VOC; la velocidad de cambio del CO2 se suaviza con un promedio exponencial.
- **Compensación:** el SGP40 recibe la temperatura y humedad del BME280.
- **Recuperación:** si un sensor I2C deja de responder, se libera el bus con 9 pulsos de reloj y se reinicia el sensor, sin detener el resto del nodo.
- **Clasificación:** el aire es "bueno", "moderado" o "malo" según el peor de los tres indicadores (CO2, PM2.5, VOC).
- **Control local:** el LED y el ventilador se deciden **en el nodo**, así que funcionan aunque no haya red. El ventilador usa histéresis (enciende en 1000 ppm, apaga en 900) para no prender y apagar seguido.
- **Buffer:** si no hay broker, los mensajes se guardan (hasta 60) y se envían al reconectar, marcados con `diferido: true`.

**En la Raspberry Pi:** valida el formato de cada mensaje, calcula la latencia, guarda en SQLite y CSV, calcula la tasa de ventilación del aula con la caída del CO2 cuando la puerta está abierta y la publica en `procesado`, y sincroniza con Firebase.

$$ACH = \frac{1}{t}\,\ln\!\left(\frac{C_0 - C_{ext}}{C_t - C_{ext}}\right)$$

donde $C_0$ es el CO2 al inicio de la caída, $C_t$ el CO2 después de $t$ horas y $C_{ext} \approx 420$ ppm el CO2 exterior.

**Salidas que dependen de MQTT:** el modo del ventilador (`auto`, `on`, `off`), el modo de ahorro y el aforo llegan como comandos desde la Pi. Todo lo demás se controla localmente.

## 8. Pruebas y resultados

| # | Prueba | Esperado | Obtenido | Evidencia |
|---|---|---|---|---|
| 1 | Lectura de CO2 tras 60 s de calentamiento | Valor entre 400 y 900 ppm en el aula | 674–762 ppm | Log del monitor serie |
| 2 | Soplar al MH-Z19C | CO2 sube, LED pasa a naranja (≥ 800) y a rojo (≥ 1000) | 888 ppm moderado, 1079 ppm malo | Log + video [PENDIENTE] |
| 3 | Ventilador automático | Enciende con CO2 ≥ 1000 y apaga con < 900 | Encendió a 1079 ppm y se apagó al bajar | Log (evento ventilador) + video |
| 4 | Sensor de puerta | Eventos abierta / cerrada al mover el imán | Correcto | Log |
| 5 | Alerta de ventilar | LED parpadea con aire malo y puerta cerrada; deja de parpadear al abrir | Correcto | Video [PENDIENTE] |
| 6 | Partículas | PM2.5 estable en aire limpio | 5–8 µg/m³ | Log |
| 7 | Intervalos | Telemetría cada 10 s | `uptime_s` avanza de 10 en 10 | Log |
| 8 | Sin broker | El nodo sigue midiendo y controlando salidas; guarda mensajes | `diferido: true`, LED y ventilador funcionan | Log |
| 9 | Correspondencia nodo ↔ Pi | Mismos `seq` y valores en ambos lados | [PENDIENTE] | Captura mosquitto_sub |
| 10 | Pérdida y recuperación del broker | Last Will "offline"; al volver se envía el buffer | [PENDIENTE] | Captura |
| 11 | Sin internet, con red local | Todo sigue funcionando (hora por la Pi) | [PENDIENTE] | Captura |
| 12 | BME280 y SGP40 nuevos | 0x76 y 0x59 detectados, sin caídas en 5 min | [PENDIENTE] | Log de prueba_sensores_i2c |
| 13 | Enlace 433 MHz (FS1000A → MX-RM-5V) | Se recibe el código enviado | "RECIBIDO: 12345" | Log |

**Fallas encontradas y ajustes:**
- **Bus I2C caído:** ningún sensor aparecía. Medimos voltajes y encontramos tres causas: una pata 3V3 de la ESP32 doblada, el riel de tierra derecho sin unir a la tierra de la ESP32, y un SGP40 con la pata GND dañada que jalaba SDA a 1 V. Lo resolvimos reforzando las tierras y separando los sensores en dos buses.
- **Sensores dañados:** el BME280 se caía a los pocos segundos y un BMP280 de respaldo marcaba −144.5 °C. Los probamos solos en otra ESP32 y confirmamos que estaban dañados; pedimos reemplazos. Creemos que el daño vino de energizarlos con la tierra floja y de las resoldaduras.
- **Sensor de puerta inalámbrico** muerto: lo reemplazamos por el MC-38 cableado.
- **Caída de voltaje por USB** (4.05 V): pasamos los periféricos de 5 V al adaptador externo.
- **Tira LED apagada tras un corte:** el firmware ahora reenvía el color cada 2 s.
- **No cargaba el firmware:** había que entrar en modo de carga con los botones IO0 + EN.

**Limitaciones:** la temperatura de respaldo del MH-Z19C es aproximada (±2 °C); el MH-Z19C se autocalibra en 24 h; la señal Wi-Fi fue débil (−80 dBm) en algunas pruebas.

## 9. Evidencias, código y conclusiones

**Fotografías y capturas:** [PENDIENTE: foto del montaje completo, foto de cada etapa, captura de mosquitto_sub en la Pi, captura de Firebase.]

**Código fuente:** repositorio github.com/moonshin3z/anemo.uvg.

| Archivo | Qué hace |
|---|---|
| `firmware/anemo_nodo/anemo_nodo.ino` | Firmware del nodo: lectura de sensores, validación, clasificación, control del LED y el ventilador, MQTT con buffer offline |
| `firmware/anemo_nodo/config.h` | Configuración: red, broker, pines, intervalos y umbrales |
| `firmware/pruebas/` | Sketches de prueba de cada módulo |
| `raspberry/setup_pi.sh` | Instalación del broker, NTP y suscriptor en la Pi |
| `raspberry/suscriptor/suscriptor.py` | Recepción, validación, almacenamiento, cálculo de ACH y Firebase |
| `raspberry/suscriptor/aforo.py` | Envío de comandos al nodo |
| `raspberry/suscriptor/simulador_nodo.py` | Simulador del nodo para pruebas sin hardware |

**Conclusiones:**
- Logramos un nodo que mide CO2, partículas y temperatura, detecta la puerta y controla el semáforo y el ventilador de forma local, sin depender de la red. Las pruebas confirmaron los umbrales y la histéresis del ventilador.
- La mayor dificultad fue el bus I2C. Aprendimos a diagnosticar con el multímetro en lugar de cambiar piezas al azar, y a diseñar para que la falla de un sensor no tumbe al sistema.
- Decidir localmente y usar la Raspberry Pi para historial y análisis hace que el aula siga protegida aunque falle la red.
- Pendiente para la siguiente fase: integrar los sensores de reemplazo, la estimación del aforo a partir del CO2 y la puerta, el tablero de visualización en Firebase y el montaje final en una caja.
