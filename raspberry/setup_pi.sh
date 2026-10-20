#!/usr/bin/env bash
# =============================================================
#  Anemo - Instalacion en la Raspberry Pi (Raspberry Pi OS)
#  Uso:  sudo bash setup_pi.sh
#  Instala: Mosquitto (broker), chrony (NTP local), Python + venv
# =============================================================
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/anemo
LAN="192.168.1.0/24"      # cambiar si la red usa otro rango

echo "== 1. Paquetes =="
apt-get update
apt-get install -y mosquitto mosquitto-clients chrony python3-venv sqlite3

echo "== 2. Broker Mosquitto =="
cp "$DIR/mosquitto/anemo.conf" /etc/mosquitto/conf.d/anemo.conf
cp "$DIR/mosquitto/anemo.acl"  /etc/mosquitto/anemo.acl
echo "Clave para el usuario MQTT nodo01 (la misma de config.h):"
mosquitto_passwd -c /etc/mosquitto/passwd nodo01
echo "Clave para el usuario MQTT pi_sub (suscriptor):"
mosquitto_passwd /etc/mosquitto/passwd pi_sub
chown mosquitto:mosquitto /etc/mosquitto/passwd /etc/mosquitto/anemo.acl
chmod 640 /etc/mosquitto/passwd
systemctl enable --now mosquitto
systemctl restart mosquitto

echo "== 3. Servidor de hora local (funciona sin internet) =="
grep -q "^allow $LAN" /etc/chrony/chrony.conf || cat >> /etc/chrony/chrony.conf <<EOF
# Anemo: la Pi da la hora a los nodos de la LAN
allow $LAN
local stratum 10
EOF
systemctl restart chrony

echo "== 4. Suscriptor en Python =="
mkdir -p "$APP"
cp "$DIR"/suscriptor/*.py "$DIR"/suscriptor/requirements.txt "$APP"/
[ -f "$APP/.env" ] || cp "$DIR/suscriptor/.env.ejemplo" "$APP/.env"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --upgrade pip
"$APP/venv/bin/pip" install -r "$APP/requirements.txt"
chown -R "${SUDO_USER:-pi}":"${SUDO_USER:-pi}" "$APP"

echo "== 5. Servicio systemd =="
sed "s/__USER__/${SUDO_USER:-pi}/" "$DIR/anemo-suscriptor.service" \
  > /etc/systemd/system/anemo-suscriptor.service
systemctl daemon-reload
systemctl enable anemo-suscriptor

cat <<EOF

Listo. Pasos que faltan:
  1. Editar $APP/.env (clave de pi_sub y ruta de la llave de Firebase)
  2. Copiar la llave de Firebase a $APP/firebase-key.json (opcional)
  3. sudo systemctl start anemo-suscriptor
  4. Ver datos:  mosquitto_sub -h localhost -u pi_sub -P <clave> -t 'anemo/#' -v
  5. Ver log:    journalctl -u anemo-suscriptor -f
EOF
