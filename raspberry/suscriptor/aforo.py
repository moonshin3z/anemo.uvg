#!/usr/bin/env python3
"""
AireAula - Envio de comandos al nodo desde la Raspberry Pi
Publica el comando y espera la confirmacion (evento cmd_ok / cmd_error).

Ejemplos:
  python aforo.py aforo 25            # hay 25 personas en el aula
  python aforo.py modo ahorro         # o: normal
  python aforo.py ventilador on       # o: off | auto
"""
import argparse
import json
import os
import sys
import time

import paho.mqtt.client as mqtt

HOST = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
USER = os.getenv("MQTT_USER", "pi_sub")
PASS = os.getenv("MQTT_PASS", "")

p = argparse.ArgumentParser(description="Comandos para el nodo AireAula")
p.add_argument("comando", choices=["aforo", "modo", "ventilador"])
p.add_argument("valor")
p.add_argument("--aula", default="aula01")
p.add_argument("--nodo", default="nodo01")
a = p.parse_args()

if a.comando == "aforo":
    if not a.valor.isdigit() or not 0 <= int(a.valor) <= 50:
        sys.exit("El aforo debe ser un entero entre 0 y 50")
    payload = {"ocupacion": int(a.valor)}
elif a.comando == "modo":
    if a.valor not in ("normal", "ahorro"):
        sys.exit("modo: normal | ahorro")
    payload = {"modo": a.valor}
else:
    if a.valor not in ("auto", "on", "off"):
        sys.exit("ventilador: auto | on | off")
    payload = {"modo": a.valor}

base = f"aireaula/{a.aula}/{a.nodo}"
respuesta = {}


def al_recibir(c, u, msg):
    d = json.loads(msg.payload)
    if d.get("tipo") in ("cmd_ok", "cmd_error"):
        respuesta.update(d)


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"aireaula-cli-{os.getpid()}")
c.username_pw_set(USER, PASS)
c.on_message = al_recibir
c.connect(HOST, PORT, 15)
c.subscribe(base + "/evento", qos=1)
c.loop_start()
info = c.publish(f"{base}/cmd/{a.comando}", json.dumps(payload), qos=1)
info.wait_for_publish(5)
print(f"Enviado a {base}/cmd/{a.comando}: {json.dumps(payload)}")

limite = time.time() + 5
while not respuesta and time.time() < limite:
    time.sleep(0.1)
c.loop_stop()
c.disconnect()

if respuesta:
    print(f"Nodo respondio {respuesta['tipo']}: {respuesta.get('detalle')}")
else:
    sys.exit("Sin confirmacion del nodo en 5 s (esta conectado?)")
