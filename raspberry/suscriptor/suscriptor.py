#!/usr/bin/env python3
"""
AireAula - Suscriptor MQTT en la Raspberry Pi
=============================================
1. Se suscribe a todos los topicos del sistema (aireaula/#).
2. Valida cada mensaje (JSON, rangos, secuencia) y mide la latencia.
3. Guarda todo en SQLite (funciona sin internet) y en un CSV de evidencia.
4. Calcula la tasa de ventilacion (ACH) a partir de la caida del CO2
   y la publica en .../procesado.
5. Un hilo aparte sube los datos a Firebase Firestore cuando hay internet.
   Si no hay internet, los datos esperan en SQLite con sync=0.

Uso:  python suscriptor.py          (variables en .env, ver .env.ejemplo)
"""
import csv
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta

import paho.mqtt.client as mqtt

# ---------------- Configuracion ----------------
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "pi_sub")
MQTT_PASS = os.getenv("MQTT_PASS", "")
CLIENT_ID = "aireaula-pi-suscriptor"
TOPICO = "aireaula/#"

DB_PATH = os.getenv("DB_PATH", "aireaula.db")
CSV_PATH = os.getenv("CSV_PATH", "mensajes.csv")
FIREBASE_KEY = os.getenv("FIREBASE_KEY", "firebase-key.json")
FB_TELEMETRIA_S = int(os.getenv("FIREBASE_TELEMETRIA_S", "60"))

TZ_GT = timezone(timedelta(hours=-6))
CO2_EXTERIOR = 420.0          # ppm, aire exterior de referencia
ACH_VENTANA_S = int(os.getenv("ACH_VENTANA_S", "600"))  # se analiza la caida de los ultimos 10 min
ACH_CAIDA_MIN = 100.0         # ppm minimos de caida para calcular

# Rangos validos (los mismos que filtra el nodo)
RANGOS = {
    "co2_ppm": (350, 5100),
    "pm25_ugm3": (0, 1000),
    "voc_index": (1, 500),
    "temp_c": (-10, 60),
    "hum_pct": (0, 100),
    "pres_hpa": (300, 1100),
    "ocupacion": (0, 50),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aireaula")


# ---------------- Base de datos local ----------------
class BaseDatos:
    def __init__(self, ruta):
        self.lock = threading.Lock()
        self.con = sqlite3.connect(ruta, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS mensajes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            recibido  TEXT NOT NULL,      -- hora de la Pi (ISO, UTC-6)
            topico    TEXT NOT NULL,
            tipo      TEXT NOT NULL,      -- telemetria | evento | estado | procesado
            nodo      TEXT,
            aula      TEXT,
            seq       INTEGER,
            ts_nodo   TEXT,               -- hora que puso el nodo (puede ser NULL)
            latencia_s REAL,
            valido    INTEGER,
            obs       TEXT,
            payload   TEXT NOT NULL,
            sync      INTEGER DEFAULT 0   -- 0 pendiente, 1 subido, 2 omitido
        );
        CREATE INDEX IF NOT EXISTS ix_sync ON mensajes(sync, tipo);
        """)

    def guardar(self, fila):
        with self.lock:
            cur = self.con.execute(
                "INSERT INTO mensajes(recibido,topico,tipo,nodo,aula,seq,ts_nodo,"
                "latencia_s,valido,obs,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (fila["recibido"], fila["topico"], fila["tipo"], fila["nodo"],
                 fila["aula"], fila["seq"], fila["ts_nodo"], fila["latencia_s"],
                 fila["valido"], fila["obs"], fila["payload"]))
            self.con.commit()
            return cur.lastrowid

    def pendientes(self, tipo, limite=400):
        with self.lock:
            return self.con.execute(
                "SELECT id, recibido, nodo, aula, payload FROM mensajes "
                "WHERE sync=0 AND tipo=? ORDER BY id LIMIT ?", (tipo, limite)).fetchall()

    def marcar(self, ids, valor):
        if not ids:
            return
        with self.lock:
            self.con.executemany("UPDATE mensajes SET sync=? WHERE id=?",
                                 [(valor, i) for i in ids])
            self.con.commit()


# ---------------- Validacion ----------------
ultimo_seq = {}      # nodo -> ultimo seq recibido


def validar(tipo, d):
    """Devuelve (valido, observaciones)."""
    obs = []
    if tipo == "telemetria":
        for campo, (lo, hi) in RANGOS.items():
            v = d.get(campo)
            if v is not None and not (lo <= v <= hi):
                obs.append(f"{campo} fuera de rango ({v})")
    nodo, seq = d.get("nodo"), d.get("seq")
    if nodo and isinstance(seq, int):
        prev = ultimo_seq.get(nodo)
        if prev is not None:
            if seq == prev + 1:
                pass
            elif seq <= 1 or seq < prev - 100:
                obs.append(f"nodo reiniciado (seq {prev} -> {seq})")
            elif seq <= prev:
                obs.append(f"duplicado o desordenado (seq {seq}, ultimo {prev})")
            else:
                obs.append(f"perdidos {seq - prev - 1} mensajes (seq {prev} -> {seq})")
        if prev is None or seq > prev or seq <= 1:
            ultimo_seq[nodo] = seq
    valido = not any("fuera de rango" in o for o in obs)
    return valido, "; ".join(obs)


def latencia(ts_nodo, ahora):
    if not ts_nodo:
        return None
    try:
        return round((ahora - datetime.fromisoformat(ts_nodo)).total_seconds(), 2)
    except ValueError:
        return None


# ---------------- Procesamiento: ACH por caida de CO2 ----------------
historial_co2 = {}   # nodo -> deque[(t_epoch, co2)]


def calcular_ach(nodo, t, co2):
    """
    ACH = (1/t) * ln((C0 - Cext) / (Ct - Cext)), con t en horas.
    Solo se calcula si el CO2 viene bajando de forma sostenida.
    """
    h = historial_co2.setdefault(nodo, deque())
    h.append((t, co2))
    while h and t - h[0][0] > ACH_VENTANA_S:
        h.popleft()
    if len(h) < 6 or t - h[0][0] < ACH_VENTANA_S * 0.8:
        return None
    t0, c0 = max(h, key=lambda x: x[1])          # pico de la ventana
    tramo = [c for (ti, c) in h if ti >= t0]
    if c0 - co2 < ACH_CAIDA_MIN or co2 <= CO2_EXTERIOR + 20:
        return None
    # caida sostenida: al menos 80 % de los pasos bajan o se mantienen
    bajadas = sum(1 for a, b in zip(tramo, tramo[1:]) if b <= a)
    if len(tramo) < 4 or bajadas < 0.8 * (len(tramo) - 1):
        return None
    horas = (t - t0) / 3600.0
    if horas <= 0:
        return None
    return round(math.log((c0 - CO2_EXTERIOR) / (co2 - CO2_EXTERIOR)) / horas, 2)


def tendencia_ppm_min(nodo):
    h = historial_co2.get(nodo)
    if not h or len(h) < 2:
        return None
    (ta, ca), (tb, cb) = h[0], h[-1]
    return round((cb - ca) / ((tb - ta) / 60.0), 1) if tb > ta else None


# ---------------- MQTT ----------------
db = BaseDatos(DB_PATH)
csv_nuevo = not os.path.exists(CSV_PATH)
csv_f = open(CSV_PATH, "a", newline="", encoding="utf-8")
csv_w = csv.writer(csv_f)
if csv_nuevo:
    csv_w.writerow(["recibido", "topico", "seq", "ts_nodo", "latencia_s", "valido", "obs", "payload"])


def tipo_de(topico):
    partes = topico.split("/")
    if len(partes) >= 4 and partes[3] == "cmd":
        return "cmd"
    return partes[3] if len(partes) >= 4 else "otro"


def al_conectar(cliente, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        log.error("No se pudo conectar al broker: %s", reason_code)
        return
    log.info("Conectado al broker %s:%s", MQTT_HOST, MQTT_PORT)
    cliente.subscribe(TOPICO, qos=1)


def al_desconectar(cliente, userdata, flags, reason_code, properties):
    log.warning("Desconectado del broker (%s); reintentando...", reason_code)


def al_recibir(cliente, userdata, msg):
    ahora = datetime.now(TZ_GT)
    tipo = tipo_de(msg.topic)
    if tipo in ("cmd", "procesado"):
        log.info("%-38s %s", msg.topic, msg.payload.decode(errors="replace"))
        return                                     # no se guardan nuestros propios mensajes
    texto = msg.payload.decode("utf-8", errors="replace")
    try:
        d = json.loads(texto)
    except json.JSONDecodeError:
        log.warning("Payload no es JSON en %s: %s", msg.topic, texto)
        d, tipo = {}, "invalido"

    valido, obs = validar(tipo, d) if d else (False, "JSON invalido")
    if d.get("diferido"):
        obs = (obs + "; " if obs else "") + "enviado desde buffer"
    lat = latencia(d.get("ts"), ahora)
    partes = (msg.topic.split("/") + ["?", "?", "?"])[:3]
    fila = {
        "recibido": ahora.isoformat(timespec="seconds"), "topico": msg.topic,
        "tipo": tipo, "nodo": d.get("nodo") or partes[2], "aula": d.get("aula") or partes[1],
        "seq": d.get("seq"), "ts_nodo": d.get("ts"), "latencia_s": lat,
        "valido": int(valido), "obs": obs, "payload": texto,
    }
    db.guardar(fila)
    csv_w.writerow([fila[k] for k in ("recibido", "topico", "seq", "ts_nodo",
                                      "latencia_s", "valido", "obs", "payload")])
    csv_f.flush()

    # Salida legible en consola (evidencia para el informe)
    if tipo == "telemetria":
        log.info("TEL seq=%s CO2=%s PM2.5=%s VOC=%s T=%s HR=%s aire=%s lat=%ss %s",
                 d.get("seq"), d.get("co2_ppm"), d.get("pm25_ugm3"), d.get("voc_index"),
                 d.get("temp_c"), d.get("hum_pct"), d.get("aire"), lat, obs)
        procesar(cliente, msg.topic, d, ahora)
    elif tipo == "evento":
        log.info("EVT seq=%s %s=%s %s", d.get("seq"), d.get("tipo"), d.get("detalle"), obs)
    else:
        log.info("%s %s", tipo.upper(), texto)


ultimo_proc_min = {}   # nodo -> minuto del ultimo ACH guardado


def procesar(cliente, topico, d, ahora):
    co2, nodo = d.get("co2_ppm"), d.get("nodo")
    if co2 is None or nodo is None:
        return
    ach = calcular_ach(nodo, ahora.timestamp(), float(co2))
    salida = {
        "nodo": nodo, "aula": d.get("aula"), "ts": ahora.isoformat(timespec="seconds"),
        "seq_origen": d.get("seq"), "co2_ppm": co2,
        "tendencia_ppm_min": tendencia_ppm_min(nodo),
        "ach": ach,
        "ventilacion": None if ach is None else
                       ("buena" if ach >= 4 else "regular" if ach >= 2 else "insuficiente"),
        "co2_por_persona": round((co2 - CO2_EXTERIOR) / d["ocupacion"], 1)
                           if d.get("ocupacion") else None,
    }
    base = topico.rsplit("/", 1)[0]
    cliente.publish(base + "/procesado", json.dumps(salida), qos=0)
    # En la base local (y Firebase) se guarda un resultado de ACH por minuto
    minuto = salida["ts"][:16]
    if ach is not None and ultimo_proc_min.get(nodo) != minuto:
        ultimo_proc_min[nodo] = minuto
        fila = {"recibido": salida["ts"], "topico": base + "/procesado", "tipo": "procesado",
                "nodo": nodo, "aula": d.get("aula"), "seq": d.get("seq"), "ts_nodo": None,
                "latencia_s": None, "valido": 1, "obs": "", "payload": json.dumps(salida)}
        db.guardar(fila)


# ---------------- Firebase (hilo aparte) ----------------
def hilo_firebase():
    if not os.path.exists(FIREBASE_KEY):
        log.warning("Sin llave de Firebase (%s): solo se guarda en SQLite", FIREBASE_KEY)
        return
    import firebase_admin
    from firebase_admin import credentials, firestore

    firebase_admin.initialize_app(credentials.Certificate(FIREBASE_KEY))
    fs = firestore.client()
    log.info("Firebase listo; telemetria cada %s s, eventos al instante", FB_TELEMETRIA_S)
    ultimo_tel = 0.0

    while True:
        try:
            # Eventos, estado y ACH (ya limitado a 1/min): se suben en cuanto hay internet
            for tipo, coleccion in (("evento", "eventos"), ("estado", "estado"),
                                    ("procesado", "procesado")):
                filas = db.pendientes(tipo)
                if filas:
                    lote = fs.batch()
                    for _id, recibido, nodo, aula, payload in filas:
                        doc = json.loads(payload)
                        doc["recibido"] = datetime.fromisoformat(recibido)
                        lote.set(fs.collection("aulas").document(aula or "sin_aula")
                                 .collection(coleccion).document(f"{nodo}-{_id}"), doc)
                        if tipo == "estado":
                            lote.set(fs.collection("nodos").document(doc.get("nodo", "?")),
                                     {"estado": doc.get("estado"), "estado_desde": doc["recibido"]},
                                     merge=True)
                    lote.commit()
                    db.marcar([f[0] for f in filas], 1)

            # Telemetria: maximo un documento por minuto y por nodo (cuota gratuita)
            if time.time() - ultimo_tel >= FB_TELEMETRIA_S:
                ultimo_tel = time.time()
                filas = db.pendientes("telemetria", limite=2000)
                por_minuto = {}
                for f in filas:
                    por_minuto[(f[2], f[1][:16])] = f        # (nodo, AAAA-MM-DDTHH:MM)
                subir = list(por_minuto.values())[:400]      # los mas antiguos primero
                if subir:
                    lote = fs.batch()
                    for _id, recibido, nodo, aula, payload in subir:
                        doc = json.loads(payload)
                        doc["recibido"] = datetime.fromisoformat(recibido)
                        lote.set(fs.collection("aulas").document(aula or "sin_aula")
                                 .collection("telemetria").document(f"{nodo}-{_id}"), doc)
                    ultimo = json.loads(subir[-1][4])
                    ultimo["actualizado"] = datetime.fromisoformat(subir[-1][1])
                    lote.set(fs.collection("nodos").document(subir[-1][2]),
                             {"ultimo": ultimo}, merge=True)
                    lote.commit()
                    ids_subidos = {f[0] for f in subir}
                    db.marcar(list(ids_subidos), 1)
                    hasta = max(ids_subidos)
                    db.marcar([f[0] for f in filas if f[0] not in ids_subidos and f[0] < hasta], 2)
                    log.info("Firebase: %d documentos de telemetria subidos", len(subir))
        except Exception as e:                       # sin internet, cuota, etc.
            log.warning("Firebase no disponible (%s); se reintenta en 30 s", e.__class__.__name__)
            time.sleep(30)
            continue
        time.sleep(5)


# ---------------- Programa principal ----------------
def main():
    threading.Thread(target=hilo_firebase, daemon=True).start()
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)
    cliente.username_pw_set(MQTT_USER, MQTT_PASS)
    cliente.on_connect = al_conectar
    cliente.on_disconnect = al_desconectar
    cliente.on_message = al_recibir
    cliente.reconnect_delay_set(min_delay=1, max_delay=5)
    cliente.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    try:
        cliente.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        log.info("Saliendo")
    finally:
        csv_f.close()


if __name__ == "__main__":
    main()
