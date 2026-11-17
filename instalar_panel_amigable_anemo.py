#!/usr/bin/env python3
"""Instala la vista amigable de Anemo dentro de AWS CloudWatch.

Ejecutar en AWS CloudShell:
    python3 instalar_panel_amigable_anemo.py

Usa la tabla existente. Crea una Lambda con permiso de lectura de ese nodo,
respalda el diseño del panel y actualiza su presentación. No modifica firmware,
datos almacenados ni reglas de IoT. El código del widget está incluido abajo.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ACCOUNT = "803817393393"
REGION = "us-east-1"
TABLE = "Telemetria_Anemo_equipo4"
DEVICE = "device_equipo4"
DASHBOARD = "Anemo_Aula01_Equipo04"
FUNCTION = "customWidgetAnemoAmbiente"
ROLE = "AnemoDashboardLecturaRole"
MANAGED = "AnemoFriendlyDashboard-v1"
DESCRIPTION = "Anemo: vista ambiental para usuarios. " + MANAGED
TABLE_ARN = "arn:aws:dynamodb:{}:{}:table/{}".format(REGION, ACCOUNT, TABLE)
FUNCTION_ARN = "arn:aws:lambda:{}:{}:function:{}".format(REGION, ACCOUNT, FUNCTION)
LOG_ARN = "arn:aws:logs:{}:{}:log-group:/aws/lambda/{}".format(REGION, ACCOUNT, FUNCTION)
PANEL_URL = "https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=" + DASHBOARD

# El generador sustituye esta cadena por el código completo antes de entregar.
WIDGET_SOURCE = '"""Panel de ambiente para un widget personalizado de CloudWatch (Python 3.12)."""\nfrom datetime import datetime, timedelta, timezone\nfrom decimal import Decimal\nfrom html import escape\nimport logging\nimport math\nimport os\n\n\nLOGGER = logging.getLogger(__name__)\nFRESH_SECONDS = 180\nFUTURE_TOLERANCE = 120\nHISTORY_SECONDS = 1800\nLOCAL_TIME = timezone(timedelta(hours=-6))\n\nFIELDS = (\n    ("co2_ppm", "Renovación del aire", "CO₂ · ppm", "Ayuda a observar la renovación del aire.", 800, 1000, "#0284c7"),\n    ("pm25_ugm3", "Polvo fino", "PM2.5 · µg/m³", "Partículas pequeñas suspendidas en el aire.", 25, 35, "#0f766e"),\n    ("voc_index", "Gases y vapores", "VOC · índice del sensor", "Indica cambios; no identifica cada gas.", 150, 200, "#7c3aed"),\n    ("temp_c", "Temperatura", "°C", "Qué tan cálido o frío está el ambiente.", None, None, "#b45309"),\n    ("hum_pct", "Humedad del aire", "%", "Humedad relativa del ambiente.", None, None, "#0369a1"),\n    ("pres_hpa", "Presión del aire", "hPa", "Un dato ambiental complementario.", None, None, "#6d28d9"),\n)\n\n\ndef _escape(value):\n    return escape(str(value), quote=True)\n\n\ndef _utc(value):\n    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)\n\n\ndef _epoch_time(value):\n    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):\n        return None\n    try:\n        number = float(value)\n        if not math.isfinite(number):\n            return None\n        return datetime.fromtimestamp(number / 1000, timezone.utc)\n    except (ValueError, TypeError, OverflowError, OSError):\n        return None\n\n\ndef _measurement_time(record, received):\n    raw = record.get("ts")\n    if raw is None or raw == "":\n        return None if record.get("diferido") is True else received\n    if not isinstance(raw, str):\n        return None\n    try:\n        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))\n        # A timestamp with no offset cannot establish the age of a measurement.\n        return _utc(parsed) if parsed.tzinfo is not None else None\n    except (ValueError, TypeError, OverflowError):\n        return None\n\n\ndef _numeric(record, field):\n    value = record.get(field)\n    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):\n        return None\n    try:\n        number = float(value)\n    except (ValueError, TypeError, OverflowError):\n        return None\n    if not math.isfinite(number):\n        return None\n    if field in ("co2_ppm", "pm25_ugm3", "voc_index") and number < 0:\n        return None\n    if field == "hum_pct" and not 0 <= number <= 100:\n        return None\n    if field == "pres_hpa" and number <= 0:\n        return None\n    if field == "rssi_dbm" and number >= 0:\n        return None\n    return number\n\n\ndef _recent(moment, now):\n    if moment is None:\n        return False\n    age = (now - moment).total_seconds()\n    return -FUTURE_TOLERANCE <= age <= FRESH_SECONDS\n\n\ndef _age(moment, now):\n    if moment is None:\n        return "sin fecha disponible"\n    seconds = max(0, int((now - moment).total_seconds()))\n    if seconds < 60:\n        return "hace unos segundos"\n    if seconds < 3600:\n        n = seconds // 60\n        return "hace {} minuto{}".format(n, "" if n == 1 else "s")\n    if seconds < 86400:\n        n = seconds // 3600\n        return "hace {} hora{}".format(n, "" if n == 1 else "s")\n    n = seconds // 86400\n    return "hace {} día{}".format(n, "" if n == 1 else "s")\n\n\ndef _display_number(value, field):\n    if value is None:\n        return "Sin lectura"\n    digits = 1 if field in ("temp_c", "hum_pct", "pres_hpa", "pm25_ugm3") else 0\n    return ("{:,." + str(digits) + "f}").format(value)\n\n\ndef _level(value, field):\n    spec = next(spec for spec in FIELDS if spec[0] == field)\n    if value is None or spec[4] is None:\n        return None\n    return 2 if value >= spec[5] else 1 if value >= spec[4] else 0\n\n\ndef _status(values, delayed=False):\n    air = FIELDS[:3]\n    available = [spec for spec in air if values.get(spec[0]) is not None]\n    elevated = [spec for spec in available if _level(values[spec[0]], spec[0]) >= 1]\n    if elevated:\n        high = any(_level(values[spec[0]], spec[0]) == 2 for spec in elevated)\n        names = ", ".join(spec[1].lower() for spec in elevated)\n        action = "Revisa posibles fuentes de polvo o vapores y el sistema de ventilación. Observa si las lecturas disminuyen."\n        if any(spec[0] == "co2_ppm" for spec in elevated):\n            action = "Renueva el aire del espacio y observa si las lecturas disminuyen."\n            if any(spec[0] != "co2_ppm" for spec in elevated):\n                action += " Revisa también posibles fuentes de polvo o vapores."\n        return {\n            "tone": "high" if high else "attention",\n            "title": "El ambiente requiere atención" if high else "Conviene revisar el ambiente",\n            "detail": "La lectura de {} alcanzó un umbral configurado del monitor.".format(names),\n            "action": action,\n            "coverage": "{} de 3 indicadores del aire disponibles{}".format(len(available), " · evaluación parcial" if len(available) < 3 else ""),\n        }\n    if len(available) == 3:\n        return {\n            "tone": "good", "title": "Lecturas dentro de los rangos configurados",\n            "detail": "Los tres indicadores del aire están por debajo del primer umbral configurado.",\n            "action": "Mantén la ventilación habitual y continúa observando las lecturas.",\n            "coverage": "3 de 3 indicadores del aire disponibles",\n        }\n    if available:\n        missing = ", ".join(spec[1].lower() for spec in air if values.get(spec[0]) is None)\n        return {\n            "tone": "partial", "title": "La evaluación aún está incompleta",\n            "detail": "Todavía faltan lecturas recientes de {}.".format(missing),\n            "action": "Revisa los sensores pendientes. Aún no podemos evaluar todos los indicadores del aire.",\n            "coverage": "{} de 3 indicadores del aire disponibles".format(len(available)),\n        }\n    return {\n        "tone": "waiting", "title": "Estamos esperando mediciones",\n        "detail": "Recibimos información guardada; aún faltan mediciones recientes." if delayed else "Todavía no hay lecturas recientes para evaluar el aire del aula.",\n        "action": "Comprueba que el monitor esté encendido y sus sensores conectados. Si continúa así, solicita una revisión del equipo.",\n        "coverage": "0 de 3 indicadores del aire disponibles",\n    }\n\n\ndef _card(spec, values):\n    field, title, unit, explanation, moderate, high, color = spec\n    value = values.get(field)\n    level = _level(value, field)\n    if value is None:\n        tone, state = "waiting", "Esperando lectura"\n    elif level == 2:\n        tone, state = "high", "Lectura elevada"\n    elif level == 1:\n        tone, state = "attention", "Conviene prestar atención"\n    elif moderate is not None:\n        tone, state = "good", "Dentro del rango configurado"\n    else:\n        tone, state = "neutral", "Dato disponible"\n    number_class = "number" if value is not None else "number empty"\n    return (\n        \'<article class="card" style="--accent:\' + color + \'">\'\n        \'<h2>\' + _escape(title) + \'</h2>\'\n        \'<div class="\' + number_class + \'">\' + _escape(_display_number(value, field)) + \'</div>\'\n        \'<div class="unit">\' + _escape(unit) + \'</div>\'\n        \'<span class="pill \' + tone + \'">\' + _escape(state) + \'</span>\'\n        \'<p class="explanation">\' + _escape(explanation) + \'</p></article>\'\n    )\n\n\ndef _chart(records, spec, now):\n    field, title, unit, _, moderate, high, color = spec\n    start = now - timedelta(seconds=HISTORY_SECONDS)\n    # Repeated measurements from delayed messages share their original time.\n    # Keeping the newest ingestion at each time avoids duplicate plotted points.\n    entries = {}\n    for record in sorted(records, key=lambda r: _epoch_time(r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)):\n        received = _epoch_time(record.get("timestamp"))\n        measured = _measurement_time(record, received)\n        position = measured or received\n        if position is None or not start <= position <= now:\n            continue\n        value = _numeric(record, field) if measured is not None else None\n        entries[position] = value\n    ordered = sorted(entries.items())\n    numeric = [v for _, v in ordered if v is not None]\n    header = \'<h3>\' + _escape(title) + \'</h3><div class="unit">\' + _escape(unit) + \'</div>\'\n    if not numeric:\n        return \'<article class="history-card">\' + header + \'<div class="chart-empty">Aún no hay mediciones<br><small>El gráfico aparecerá cuando lleguen lecturas.</small></div></article>\'\n    low = min(numeric)\n    upper = max(numeric)\n    padding = max((upper - low) * .15, abs(upper) * .03, 1)\n    lo, hi = max(0, low - padding), upper + padding\n    left, top, width, height = 34, 12, 312, 90\n\n    def xy(moment, value):\n        x = left + (moment - start).total_seconds() / HISTORY_SECONDS * width\n        y = top + height - (value - lo) / (hi - lo) * height\n        return x, y\n\n    segments, segment = [], []\n    previous = None\n    for moment, value in ordered:\n        if value is None or (previous is not None and (moment - previous).total_seconds() > FRESH_SECONDS):\n            if segment:\n                segments.append(segment)\n                segment = []\n        if value is not None:\n            segment.append(xy(moment, value))\n        previous = moment\n    if segment:\n        segments.append(segment)\n    paths = []\n    for points in segments:\n        if len(points) == 1:\n            x, y = points[0]\n            paths.append(\'<circle cx="{:.2f}" cy="{:.2f}" r="3" fill="{}"/>\'.format(x, y, color))\n        else:\n            encoded = " ".join("{:.2f},{:.2f}".format(x, y) for x, y in points)\n            paths.append(\'<polyline points="\' + encoded + \'" fill="none" stroke="\' + color + \'" stroke-width="2.5" stroke-linejoin="round"/>\')\n    svg = (\n        \'<svg viewBox="0 0 360 130" role="img" aria-label="\' + _escape("Historial de " + title.lower() + " de los últimos 30 minutos") + \'">\'\n        \'<line x1="34" y1="102" x2="346" y2="102" class="gridline"/>\'\n        \'<line x1="34" y1="12" x2="346" y2="12" class="gridline"/>\'\n        \'<text x="2" y="17" class="axis">\' + _escape("{:.0f}".format(hi)) + \'</text>\'\n        \'<text x="2" y="105" class="axis">\' + _escape("{:.0f}".format(lo)) + \'</text>\'\n        + "".join(paths)\n        + \'<text x="34" y="123" class="axis">Hace 30 min</text><text x="315" y="123" class="axis">Ahora</text></svg>\'\n    )\n    return \'<article class="history-card">\' + header + svg + \'</article>\'\n\n\nSTYLE = """\n<style>\n .anemo-root *{box-sizing:border-box}.anemo-root{margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:1.45;color:#173043;background:#f3f6f9}\n.anemo{max-width:1500px;margin:auto;padding:18px 20px 14px}.page-head{display:flex;justify-content:space-between;gap:18px;align-items:center;margin-bottom:14px}.brand{font-size:14px;letter-spacing:2px;font-weight:700;color:#0f766e;margin:0 0 2px}.page-head h1{margin:0;font-size:28px;line-height:1.2}.place{color:#53677a;font-size:16px;margin:4px 0 0}.updated{font-size:14px;color:#53677a;text-align:right;max-width:300px}\n.hero{border:1px solid #d8e2eb;border-left:6px solid #64748b;border-radius:14px;background:#fff;padding:15px 20px;margin-bottom:16px}.hero.good{border-left-color:#16804a;background:#f0fdf4}.hero.partial{border-left-color:#0284c7;background:#f0f9ff}.hero.attention{border-left-color:#d97706;background:#fffbeb}.hero.high{border-left-color:#dc2626;background:#fff5f5}.hero h2{font-size:23px;margin:0 0 5px}.hero p{margin:5px 0}.hero .coverage{font-size:14px;color:#53677a;margin-top:8px}.hero .action{font-size:16px}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card{background:#fff;border:1px solid #dbe3ec;border-top:4px solid var(--accent);border-radius:12px;padding:15px 18px;min-width:0}.card h2{font-size:18px;line-height:1.25;margin:0 0 7px}.number{font-size:40px;font-weight:700;letter-spacing:-1px;line-height:1.15}.number.empty{font-size:27px;letter-spacing:0;color:#64748b;min-height:46px;padding-top:6px}.unit{font-size:14px;color:#53677a;margin:2px 0 9px}.pill{display:inline-block;border-radius:20px;padding:4px 10px;font-size:14px;font-weight:700;background:#eef2f6;color:#475569}.pill.good{background:#dcfce7;color:#166534}.pill.partial,.pill.neutral{background:#e0f2fe;color:#075985}.pill.attention{background:#fef3c7;color:#92400e}.pill.high{background:#fee2e2;color:#991b1b}.explanation{font-size:16px;color:#53677a;margin:9px 0 0}.history-head{display:flex;justify-content:space-between;gap:14px;align-items:baseline;margin:19px 0 9px}.history-head h2{font-size:20px;margin:0}.history-head span{font-size:14px;color:#53677a}.history{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.history-card{background:#fff;border:1px solid #dbe3ec;border-radius:12px;padding:12px 15px;min-width:0}.history-card h3{font-size:16px;margin:0}.history-card .unit{margin-bottom:0}.history-card svg{width:100%;height:130px;display:block}.chart-empty{height:130px;display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;color:#64748b;font-weight:700}.chart-empty small{font-weight:400;font-size:13px;padding-top:6px}.axis{font:11px Arial,Helvetica,sans-serif;fill:#64748b}.gridline{stroke:#dbe3ec;stroke-width:1}.foot{font-size:13px;color:#53677a;margin-top:12px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.foot p{margin:2px 0}.unavailable{padding:32px;background:#fff;border-radius:14px;border:1px solid #dbe3ec}.unavailable h1{font-size:25px}.unavailable p{font-size:17px}\n.dark{background:#0f172a;color:#e2e8f0}.dark .anemo{background:#0f172a}.dark .card,.dark .history-card,.dark .hero,.dark .unavailable{background:#172235;border-color:#334155}.dark .hero.good{background:#102d24}.dark .hero.partial{background:#112b40}.dark .hero.attention{background:#362a17}.dark .hero.high{background:#381f27}.dark .place,.dark .updated,.dark .unit,.dark .explanation,.dark .history-head span,.dark .foot,.dark .hero .coverage{color:#b6c5d6}.dark .number.empty,.dark .chart-empty{color:#b6c5d6}.dark .axis{fill:#b6c5d6}.dark .gridline{stroke:#334155}.dark .brand{color:#5eead4}\n@media(max-width:900px){.cards,.history{grid-template-columns:repeat(2,minmax(0,1fr))}.page-head{align-items:flex-start}.updated{max-width:220px}}@media(max-width:560px){.anemo{padding:14px}.cards,.history{grid-template-columns:1fr}.page-head{display:block}.updated{text-align:left;max-width:none;margin-top:8px}.page-head h1{font-size:25px}.hero{padding:14px}.hero h2{font-size:21px}.history-head{display:block}.number{font-size:40px}.foot{display:block}}\n</style>\n"""\n\n\ndef render(records, now, theme="light"):\n    """Renderiza solo datos recibidos. Nunca sustituye mediciones ausentes por cero."""\n    now = _utc(now)\n    records = [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []\n    candidates = []\n    for record in records:\n        received = _epoch_time(record.get("timestamp"))\n        if received is not None and (received - now).total_seconds() <= FUTURE_TOLERANCE:\n            candidates.append((received, record))\n    received, latest = max(candidates, key=lambda pair: pair[0]) if candidates else (None, {})\n    measured = _measurement_time(latest, received)\n    fresh = _recent(received, now) and _recent(measured, now)\n    values = {spec[0]: _numeric(latest, spec[0]) if fresh else None for spec in FIELDS}\n    delayed = bool(latest) and _recent(received, now) and not _recent(measured, now)\n    status = _status(values, delayed)\n    if measured is not None and measured <= now + timedelta(seconds=FUTURE_TOLERANCE):\n        update = "Última medición: " + _age(measured, now)\n    else:\n        update = "Última medición: sin fecha válida" if latest else "Aún no recibimos mediciones"\n    reception = "Mensaje recibido " + _age(received, now) if received else "Sin mensajes disponibles"\n    css_class = "dark" if theme == "dark" else "light"\n    hero = (\n        \'<section class="hero \' + status["tone"] + \'" aria-label="Resumen del ambiente">\'\n        \'<h2>\' + _escape(status["title"]) + \'</h2><p>\' + _escape(status["detail"]) + \'</p>\'\n        \'<p class="action"><strong>Qué hacer:</strong> \' + _escape(status["action"]) + \'</p>\'\n        \'<div class="coverage">\' + _escape(status["coverage"]) + \'</div></section>\'\n    )\n    return (\n        STYLE + \'<div class="cwdb-no-default-styles anemo-root \' + css_class + \'" lang="es"><main class="anemo" data-view="anemo-friendly-v1" data-state="\' + status["tone"] + \'">\'\n        \'<header class="page-head"><div><p class="brand">ANEMO</p><h1>Ambiente del aula</h1><p class="place">Aula 01 · Seguimiento del aire interior</p></div>\'\n        \'<div class="updated">\' + _escape(update) + \'<br>Se consideran recientes los últimos 3 minutos.</div></header>\'\n        + hero + \'<section class="cards" aria-label="Lecturas de los sensores">\'\n        + "".join(_card(spec, values) for spec in FIELDS) + \'</section>\'\n        \'<div class="history-head"><h2>Cómo ha cambiado el aire</h2><span>Últimos 30 minutos · Los huecos indican falta de lecturas.</span></div>\'\n        \'<section class="history" aria-label="Historial reciente">\'\n        + "".join(_chart(records, spec, now) for spec in FIELDS[:3]) + \'</section>\'\n        \'<footer class="foot"><p>Los estados se basan en los límites configurados del monitor.</p><p>\'\n        + _escape(reception) + \'</p></footer></main></div>\'\n    )\n\n\ndef fetch_records():\n    # El SDK está disponible en Lambda. Importarlo aquí permite pruebas locales\n    # de render() sin credenciales ni dependencia del SDK.\n    import boto3\n    table = boto3.resource("dynamodb").Table(os.environ.get("TABLE_NAME", "Telemetria_Anemo_equipo4"))\n    response = table.query(\n        KeyConditionExpression="#device = :device",\n        ExpressionAttributeNames={"#device": "device_id"},\n        ExpressionAttributeValues={":device": os.environ.get("DEVICE_ID", "device_equipo4")},\n        ScanIndexForward=False, Limit=181, ConsistentRead=False,\n    )\n    return response.get("Items", [])\n\n\ndef handler(event, context):\n    if isinstance(event, dict) and event.get("describe"):\n        return "# Ambiente del aula\\nResumen de lecturas recientes y recomendaciones según los rangos configurados del monitor. No requiere parámetros."\n    widget_context = event.get("widgetContext", {}) if isinstance(event, dict) else {}\n    theme = widget_context.get("theme", "light") if isinstance(widget_context, dict) else "light"\n    try:\n        return render(fetch_records(), datetime.now(timezone.utc), theme=theme)\n    except Exception as exc:\n        # Solo se registra el tipo del fallo: nunca payloads ni credenciales.\n        LOGGER.error("No se pudieron obtener las lecturas: %s", type(exc).__name__)\n        return (\n            STYLE + \'<div class="cwdb-no-default-styles anemo-root light" lang="es"><main class="anemo" data-view="anemo-friendly-v1" data-state="unavailable">\'\n            \'<section class="unavailable"><p class="brand">ANEMO</p><h1>No pudimos consultar las mediciones</h1>\'\n            \'<p>Intenta actualizar el panel en un momento. Si continúa así, solicita una revisión del monitor.</p>\'\n            \'<p>No hay información suficiente para evaluar el ambiente.</p></section></main></div>\'\n        )\n'


class SetupError(Exception):
    pass


class AwsError(SetupError):
    def __init__(self, message):
        super().__init__(message)
        match = re.search(r"An error occurred \(([^)]+)\)", message)
        self.code = match.group(1) if match else ""


class AwsCLI:
    def __call__(self, service, operation, *args):
        command = [
            "aws", "--region", REGION, "--output", "json", "--no-cli-pager",
            "--cli-connect-timeout", "10", "--cli-read-timeout", "30",
            service, operation, *args,
        ]
        result = subprocess.run(
            command, capture_output=True, text=True,
            env=dict(os.environ, AWS_PAGER="", AWS_CLI_AUTO_PROMPT="off"),
        )
        if result.returncode:
            raise AwsError(result.stderr.strip() or "AWS CLI terminó con un error.")
        return json.loads(result.stdout) if result.stdout.strip() else {}


def optional(api, service, operation, absent_code, *args):
    try:
        return api(service, operation, *args)
    except AwsError as exc:
        if exc.code == absent_code:
            return None
        raise


def dashboard_body():
    return {
        "start": "-PT30M", "periodOverride": "inherit",
        "widgets": [{
            "type": "custom", "x": 0, "y": 0, "width": 24, "height": 36,
            "properties": {
                "endpoint": FUNCTION_ARN, "title": "Anemo · Ambiente del aula",
                "params": {},
                "updateOn": {"refresh": True, "resize": True, "timeRange": True},
            },
        }],
    }


def execution_policy():
    return {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "dynamodb:Query", "Resource": TABLE_ARN,
         "Condition": {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": [DEVICE]}}},
        {"Effect": "Allow", "Action": "logs:CreateLogGroup", "Resource": LOG_ARN},
        {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": LOG_ARN + ":*"},
    ]}


def zip_bytes():
    if not WIDGET_SOURCE:
        raise SetupError("El instalador está incompleto. Descarga el archivo entregado en el chat.")
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("anemo_widget.py", WIDGET_SOURCE)
    return result.getvalue()


def setup(api, backup_dir=Path("."), sleep=time.sleep):
    if api("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise SetupError("Abre CloudShell en la cuenta " + ACCOUNT + ".")
    table = api("dynamodb", "describe-table", "--table-name", TABLE)["Table"]
    expected = {("device_id", "HASH"), ("timestamp", "RANGE")}
    keys = {(k["AttributeName"], k["KeyType"]) for k in table.get("KeySchema", [])}
    types = {a["AttributeName"]: a["AttributeType"] for a in table.get("AttributeDefinitions", [])}
    if keys != expected or types.get("device_id") != "S" or types.get("timestamp") != "N":
        raise SetupError("La tabla tiene otras claves. Comparte este mensaje para adaptar la consulta.")
    if table.get("TableStatus") != "ACTIVE":
        raise SetupError("Espera a que la tabla esté activa y vuelve a ejecutar el archivo.")
    existing_role = optional(api, "iam", "get-role", "NoSuchEntity", "--role-name", ROLE)
    if existing_role and MANAGED not in existing_role["Role"].get("Description", ""):
        raise SetupError("Ya existe otro rol con el nombre " + ROLE + ". Se conservó; comparte este mensaje.")
    existing_function = optional(api, "lambda", "get-function", "ResourceNotFoundException", "--function-name", FUNCTION)
    if existing_function and MANAGED not in existing_function["Configuration"].get("Description", ""):
        raise SetupError("Ya existe otra función con el nombre " + FUNCTION + ". Se conservó; comparte este mensaje.")
    dashboards = api("cloudwatch", "list-dashboards", "--dashboard-name-prefix", DASHBOARD)
    original = None
    if any(d.get("DashboardName") == DASHBOARD for d in dashboards.get("DashboardEntries", [])):
        original = json.loads(api("cloudwatch", "get-dashboard", "--dashboard-name", DASHBOARD)["DashboardBody"])
        recognized = any(
            "**Aula01 · Nodo01 · Equipo04**" in w.get("properties", {}).get("markdown", "")
            or w.get("properties", {}).get("endpoint") == FUNCTION_ARN
            for w in original.get("widgets", [])
        )
        if not recognized:
            raise SetupError("El panel tiene otro diseño. Se conservó; comparte este mensaje.")
    # Verificar la consulta con la sesión actual antes de crear recursos.
    api("dynamodb", "query", "--table-name", TABLE,
        "--key-condition-expression", "#device = :device",
        "--expression-attribute-names", json.dumps({"#device": "device_id"}),
        "--expression-attribute-values", json.dumps({":device": {"S": DEVICE}}),
        "--no-scan-index-forward", "--limit", "1", "--no-paginate")
    archive = zip_bytes()
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6]
    if original is not None:
        backup = backup_dir / ("anemo_antes_de_vista_amigable_" + tag + ".json")
        backup.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Respaldo del panel: " + str(backup.resolve()), flush=True)
    print("Preparando Anemo para mostrar lecturas y recomendaciones claras…", flush=True)
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole",
    }]}
    if existing_role is None:
        created = api("iam", "create-role", "--role-name", ROLE, "--description", DESCRIPTION,
                      "--assume-role-policy-document", json.dumps(trust))
        role_arn = created["Role"]["Arn"]
    else:
        role_arn = existing_role["Role"]["Arn"]
    api("iam", "put-role-policy", "--role-name", ROLE, "--policy-name", "AnemoLecturaDelNodo",
        "--policy-document", json.dumps(execution_policy()))

    with tempfile.TemporaryDirectory(prefix="anemo_instalacion_") as directory:
        directory = Path(directory)
        package = directory / "anemo_widget.zip"
        package.write_bytes(archive)
        environment = {"Variables": {"TABLE_NAME": TABLE, "DEVICE_ID": DEVICE}}
        if existing_function is None:
            print("Creando la vista del panel. Puede tardar unos segundos…", flush=True)
            for attempt in range(9):
                try:
                    api("lambda", "create-function", "--function-name", FUNCTION,
                        "--description", DESCRIPTION, "--runtime", "python3.12",
                        "--role", role_arn, "--handler", "anemo_widget.handler",
                        "--memory-size", "256", "--timeout", "15",
                        "--environment", json.dumps(environment),
                        "--zip-file", "fileb://" + str(package))
                    break
                except AwsError as exc:
                    retry = exc.code == "InvalidParameterValueException" and "cannot be assumed" in str(exc)
                    if not retry or attempt == 8:
                        raise
                    sleep(4)
            api("lambda", "wait", "function-active-v2", "--function-name", FUNCTION)
        else:
            env = dict(existing_function["Configuration"].get("Environment", {}).get("Variables", {}))
            env.update(environment["Variables"])
            api("lambda", "wait", "function-active-v2", "--function-name", FUNCTION)
            api("lambda", "update-function-code", "--function-name", FUNCTION,
                "--zip-file", "fileb://" + str(package))
            api("lambda", "wait", "function-updated-v2", "--function-name", FUNCTION)
            api("lambda", "update-function-configuration", "--function-name", FUNCTION,
                "--description", DESCRIPTION, "--runtime", "python3.12", "--role", role_arn,
                "--handler", "anemo_widget.handler", "--memory-size", "256", "--timeout", "15",
                "--environment", json.dumps({"Variables": env}))
            api("lambda", "wait", "function-updated-v2", "--function-name", FUNCTION)
        event = directory / "evento.json"
        output = directory / "respuesta.json"
        event.write_text(json.dumps({"widgetContext": {"theme": "light"}}), encoding="utf-8")
        for attempt in range(5):
            response = api("lambda", "invoke", "--function-name", FUNCTION,
                           "--payload", "fileb://" + str(event), str(output))
            if response.get("FunctionError"):
                raise SetupError("La función no pudo responder. Comparte este mensaje para revisar la instalación.")
            html = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(html, str) or "anemo-friendly-v1" not in html:
                raise SetupError("La vista no devolvió el contenido esperado. Se conservó el diseño del panel.")
            unavailable = 'data-state="unavailable"' in html or "data-state='unavailable'" in html
            if not unavailable:
                break
            if attempt == 4:
                raise SetupError("La vista no pudo consultar las lecturas. Se conservó el diseño del panel; comparte este mensaje.")
            print("Esperando a que la vista pueda leer las mediciones…", flush=True)
            sleep(3)
        body = dashboard_body()
        if body != original:
            result = api("cloudwatch", "put-dashboard", "--dashboard-name", DASHBOARD,
                         "--dashboard-body", json.dumps(body, ensure_ascii=False))
            if result.get("DashboardValidationMessages"):
                raise SetupError("CloudWatch devolvió avisos: " + json.dumps(result["DashboardValidationMessages"], ensure_ascii=False))
    print("LISTO. Panel amigable preparado:")
    print(PANEL_URL)
    print("Al abrirlo, elige Permitir siempre / Allow always para que se muestre la vista.")
    print("Activa actualización automática cada minuto. El panel usará tus lecturas reales.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export-widget", type=Path, help="Exportar el código del widget sin acceder a AWS.")
    args = parser.parse_args()
    if args.export_widget:
        args.export_widget.write_text(WIDGET_SOURCE, encoding="utf-8")
        print("Código exportado: " + str(args.export_widget))
        return 0
    try:
        setup(AwsCLI())
    except (SetupError, OSError, ValueError, KeyError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        print("Comparte el mensaje completo; no publiques tus claves de acceso.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
