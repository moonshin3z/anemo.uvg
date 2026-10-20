# AireAula: Fase 03 (nodo + MQTT + Raspberry Pi + Firebase)

```
ESP32 (sensores, LED, ventilador)
   |  Wi-Fi LAN, MQTT 1883
Raspberry Pi: Mosquitto (broker) + chrony (hora) + suscriptor.py
   |  SQLite local (siempre)      |  internet (cuando hay)
   +------------------------------+--> Firebase Firestore
```

## Estructura

| Archivo | Que es |
|---|---|
| `firmware/aireaula_nodo/config.h` | Red, broker, pines, umbrales, codigos 433 MHz. Lo unico que se edita |
| `firmware/aireaula_nodo/aireaula_nodo.ino` | Firmware del ESP32 |
| `raspberry/setup_pi.sh` | Instala y configura todo en la Pi |
| `raspberry/mosquitto/` | Configuracion del broker y permisos (ACL) |
| `raspberry/suscriptor/suscriptor.py` | Suscriptor: valida, guarda, calcula ACH, sube a Firebase |
| `raspberry/suscriptor/aforo.py` | Envia comandos al nodo (aforo, modo, ventilador) |
| `raspberry/suscriptor/simulador_nodo.py` | Nodo falso para probar la Pi sin hardware |
| `docs/catalogo_mqtt.md` | Catalogo de mensajes y payloads (seccion 6 del informe) |

## 1. Raspberry Pi

1. Raspberry Pi OS en la misma red Wi-Fi que el nodo. Darle **IP fija** (en el router, o con `sudo nmtui`). Esa IP va en `MQTT_HOST` de `config.h`.
2. Copiar la carpeta `raspberry/` a la Pi y correr:
   ```bash
   cd raspberry && sudo bash setup_pi.sh
   ```
   Pide dos claves: `nodo01` (la misma de `config.h`) y `pi_sub`.
3. Editar `/opt/aireaula/.env` (poner la clave de `pi_sub`).
4. Probar el broker en dos terminales:
   ```bash
   mosquitto_sub -h localhost -u pi_sub -P <clave> -t 'aireaula/#' -v
   mosquitto_pub -h localhost -u pi_sub -P <clave> -t aireaula/prueba -m hola
   ```
5. Arrancar el suscriptor: `sudo systemctl start aireaula-suscriptor` y ver `journalctl -u aireaula-suscriptor -f`.
6. Sin hardware: `python3 /opt/aireaula/simulador_nodo.py --password <clave nodo01>`.

## 2. Firebase

1. En console.firebase.google.com: crear proyecto, luego **Firestore Database**, modo produccion, region `us-central1`.
2. Configuracion del proyecto, **Cuentas de servicio**, "Generar nueva clave privada". Se descarga un JSON.
3. Copiarlo a la Pi como `/opt/aireaula/firebase-key.json` y reiniciar el servicio.
4. **No subir esa llave a GitHub** (esta en `.gitignore`).

La Pi usa el Admin SDK, asi que no hace falta abrir reglas de Firestore. Si otro equipo hace una pagina web que lea los datos, las reglas deben permitir solo lectura.

## 3. ESP32

1. Arduino IDE, gestor de placas: URL `https://espressif.github.io/arduino-esp32/package_esp32_index.json`, instalar **esp32 by Espressif**. Placa: **ESP32 Dev Module**. Driver CH340 si la PC no reconoce el puerto.
2. Gestor de bibliotecas: PubSubClient, ArduinoJson (7.x), Adafruit BME280 Library, Adafruit SGP40 Sensor, MH-Z19 (Jonathan Dempsey), PMS Library (Mariusz Kacki), rc-switch, Adafruit NeoPixel.
3. Editar `config.h` (Wi-Fi, IP de la Pi, clave de `nodo01`) y subir el programa. Si no entra en modo carga, mantener **BOOT** presionado al empezar la subida.
4. Monitor serie a 115200: deben salir `BME280: ok  SGP40: ok`, `[MQTT] conectando... ok` y lineas `[TX]`.
5. **Codigos 433 MHz:** abrir y cerrar cada sensor magnetico, anotar los `[RF] codigo ...` del monitor serie, ponerlos en `config.h` y volver a subir.

## 4. Comandos utiles en la Pi

```bash
cd /opt/aireaula && set -a && . ./.env && set +a
venv/bin/python aforo.py aforo 28         # ocupacion actual
venv/bin/python aforo.py modo ahorro      # o normal
venv/bin/python aforo.py ventilador on    # on | off | auto
sqlite3 aireaula.db "select recibido,seq,latencia_s,obs from mensajes order by id desc limit 10;"
mosquitto_sub -h localhost -u pi_sub -P <clave> -t 'aireaula/+/+/estado' -v   # online/offline
```

## 5. Pruebas para el informe

| Prueba | Como hacerla | Evidencia |
|---|---|---|
| Correspondencia enviado/recibido | Comparar `[TX]` del monitor serie con el log del suscriptor (mismo `seq`) | Capturas lado a lado |
| Intervalos | `select recibido from mensajes where tipo='telemetria'` y ver diferencias (10 s / 60 s) | Tabla de tiempos |
| Umbrales | Soplar cerca del MH-Z19C: CO2 > 1000, LED rojo, ventilador on, evento `aire=malo` | Foto + log |
| Sin internet, con LAN | Desconectar el cable/WAN del router: todo sigue; Firebase muestra "no disponible" y sube al volver | Log + consola de Firebase |
| Caida del broker | `sudo systemctl stop mosquitto` 1 min y luego `start`: el nodo guarda en buffer, reenvia con `"diferido":true`, sin huecos de `seq` | Log del suscriptor |
| LWT | Desconectar la energia del ESP32: a los ~22 s aparece `estado: offline` | Captura de `mosquitto_sub` |
| Comandos | `aforo.py aforo 60` responde `cmd_error`; `aforo.py aforo 25` responde `cmd_ok` | Captura |
