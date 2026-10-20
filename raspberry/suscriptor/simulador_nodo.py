#!/usr/bin/env python3
"""
AireAula - Simulador del nodo ESP32
Publica los mismos mensajes que el firmware real (mismos topicos y payloads)
para probar el broker, el suscriptor y Firebase sin el hardware.

Escenario: el CO2 sube con la clase y la puerta cerrada; al pasar
1100 ppm "se abre la puerta" y el CO2 baja con la tasa de ventilacion
indicada (permite comprobar el calculo de ACH en la Pi).

  python simulador_nodo.py                 # telemetria cada 10 s
  python simulador_nodo.py --intervalo 2   # mas rapido para pruebas
"""
import argparse
import json
import math
import os
import random
import time
from datetime import datetime, timezone, timedelta

import paho.mqtt.client as mqtt

p = argparse.ArgumentParser()
p.add_argument("--host", default=os.getenv("MQTT_HOST", "localhost"))
p.add_argument("--user", default="nodo01")
p.add_argument("--password", default=os.getenv("NODO_PASS", ""))
p.add_argument("--intervalo", type=float, default=10.0)
p.add_argument("--subida", type=float, default=0.035, help="ppm/s por persona con puerta cerrada")
p.add_argument("--ach", type=float, default=6.0, help="renovaciones/h con la puerta abierta")
a = p.parse_args()

TZ = timezone(timedelta(hours=-6))
BASE = "aireaula/aula01/nodo01"
st = {"seq": 0, "co2": 600.0, "ocupacion": None, "puerta": "cerrada", "ventana": "cerrada",
      "modo": "normal", "vent_modo": "auto", "ventilador": False, "aire": "sin_dato"}
inicio = time.time()


def ts():
    return datetime.now(TZ).isoformat(timespec="seconds")


def evento(c, tipo, detalle):
    st["seq"] += 1
    c.publish(BASE + "/evento", json.dumps({
        "nodo": "nodo01", "aula": "aula01", "seq": st["seq"], "ts": ts(),
        "uptime_s": int(time.time() - inicio), "tipo": tipo, "detalle": detalle,
        "co2_ppm": round(st["co2"]), "diferido": False}), qos=0)


def al_conectar(c, u, f, rc, pr):
    c.subscribe(BASE + "/cmd/#", qos=1)
    c.publish(BASE + "/estado", json.dumps({"nodo": "nodo01", "estado": "online",
                                            "ip": "simulador", "buffer": 0}), retain=True)
    evento(c, "conexion", "conectado al broker")


def al_recibir(c, u, msg):
    d = json.loads(msg.payload)
    cmd = msg.topic.rsplit("/", 1)[-1]
    if cmd == "aforo" and isinstance(d.get("ocupacion"), int) and 0 <= d["ocupacion"] <= 50:
        st["ocupacion"] = d["ocupacion"]; evento(c, "cmd_ok", "aforo actualizado")
    elif cmd == "modo" and d.get("modo") in ("normal", "ahorro"):
        st["modo"] = d["modo"]; evento(c, "cmd_ok", "modo " + d["modo"])
    elif cmd == "ventilador" and d.get("modo") in ("auto", "on", "off"):
        st["vent_modo"] = d["modo"]; evento(c, "cmd_ok", "ventilador " + d["modo"])
    else:
        evento(c, "cmd_error", "comando desconocido o mal formado")


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aireaula-nodo01")
c.username_pw_set(a.user, a.password)
c.will_set(BASE + "/estado", json.dumps({"nodo": "nodo01", "estado": "offline"}), qos=1, retain=True)
c.on_connect, c.on_message = al_conectar, al_recibir
c.connect(a.host, 1883, 15)
c.loop_start()

try:
    while True:
        t = time.time() - inicio
        if st["co2"] > 1100 and st["puerta"] == "cerrada":
            st["puerta"] = "abierta"; evento(c, "puerta", "abierta")
        personas = st["ocupacion"] or 25
        if st["puerta"] == "cerrada":
            st["co2"] += personas * a.subida * a.intervalo
        else:
            st["co2"] = 420 + (st["co2"] - 420) * math.exp(-a.ach / 3600 * a.intervalo)
        co2 = st["co2"] + random.uniform(-8, 8)
        pm = max(0, random.gauss(14, 3)); voc = random.randint(90, 130)
        aire = "malo" if co2 >= 1000 else "moderado" if co2 >= 800 else "bueno"
        if aire != st["aire"]:
            st["aire"] = aire; evento(c, "aire", aire)
        vent = st["ventilador"]
        if st["vent_modo"] == "on": vent = True
        elif st["vent_modo"] == "off": vent = False
        elif co2 >= 1000: vent = True
        elif co2 < 900: vent = False
        if vent != st["ventilador"]:
            st["ventilador"] = vent; evento(c, "ventilador", "encendido" if vent else "apagado")
        st["seq"] += 1
        c.publish(BASE + "/telemetria", json.dumps({
            "nodo": "nodo01", "aula": "aula01", "seq": st["seq"], "ts": ts(),
            "uptime_s": int(t), "modo": st["modo"], "co2_ppm": round(co2),
            "pm25_ugm3": round(pm, 1), "voc_index": voc, "n_pm25": 10, "n_voc": 10,
            "temp_c": round(random.uniform(23, 25), 1), "hum_pct": round(random.uniform(55, 60), 1),
            "pres_hpa": 845.2, "ocupacion": st["ocupacion"], "puerta": st["puerta"],
            "ventana": st["ventana"], "ventilador": vent, "vent_modo": st["vent_modo"],
            "aire": aire, "errores": 0, "diferido": False}), qos=0)
        print(f"seq={st['seq']} co2={co2:.0f} puerta={st['puerta']} aire={aire}")
        time.sleep(a.intervalo)
except KeyboardInterrupt:
    c.loop_stop(); c.disconnect()
