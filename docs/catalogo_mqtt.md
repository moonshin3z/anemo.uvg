# Anemo: catalogo de mensajes MQTT

Broker: Mosquitto en la Raspberry Pi, puerto 1883, con usuario y clave (sin anonimos) y ACL por usuario.
Formato de topicos: `anemo/<aula>/<nodo>/<tipo>`. Payloads en JSON UTF-8.

| Cliente | Client ID | Usuario MQTT | Rol |
|---|---|---|---|
| Nodo ESP32 | `anemo-nodo01` | `nodo01` | Publica telemetria, eventos y estado; recibe comandos |
| Suscriptor de la Pi | `anemo-pi-suscriptor` | `pi_sub` | Recibe todo, guarda, procesa, sube a Firebase |
| CLI de comandos | `anemo-cli-<pid>` | `pi_sub` | Envia aforo, modo y ventilador |

> Cada cliente debe tener un Client ID unico: si dos clientes usan el mismo, el broker desconecta al anterior y se pierden mensajes.

## Resumen

| # | Topico | Emisor -> Receptor | QoS | Retenido | Condicion de envio |
|---|---|---|---|---|---|
| 1 | `.../telemetria` | Nodo -> Pi | 0 | No | Periodico: 10 s (normal), 60 s (ahorro) |
| 2 | `.../evento` | Nodo -> Pi | 0 | No | Cambio de estado (puerta, ventana, aire, ventilador), conexion, respuesta a comando |
| 3 | `.../estado` | Nodo (o broker por LWT) -> Pi | 1 | Si | Al conectar ("online"); el broker publica "offline" si el nodo se cae |
| 4 | `.../cmd/aforo` | Pi -> Nodo | 1 | No | El docente o el CLI ingresa la ocupacion |
| 5 | `.../cmd/modo` | Pi -> Nodo | 1 | No | Cambio a modo normal o ahorro |
| 6 | `.../cmd/ventilador` | Pi -> Nodo | 1 | No | Forzar ventilador on/off o volver a auto |
| 7 | `.../procesado` | Pi -> cualquier suscriptor | 0 | No | Cada telemetria recibida (ACH, tendencia, CO2 por persona) |

## 1. Telemetria

Proposito: reportar todas las variables medidas y el estado de las salidas.

```json
{"nodo":"nodo01","aula":"aula01","seq":152,"ts":"2026-10-20T09:15:40-06:00","uptime_s":1520,
 "modo":"normal","co2_ppm":1043,"pm1_ugm3":8.1,"pm25_ugm3":12.4,"pm10_ugm3":15.0,"voc_index":118,"n_pm25":10,"n_voc":10,
 "temp_c":24.6,"hum_pct":58.1,"pres_hpa":845.2,"ocupacion":28,"puerta":"cerrada",
 "ventana":"abierta","ventilador":true,"vent_modo":"auto","aire":"malo","errores":0,"diferido":false}
```

| Campo | Tipo | Descripcion |
|---|---|---|
| `seq` | entero | Contador del nodo, compartido con eventos; la Pi detecta huecos (perdidas) y reinicios |
| `ts` | texto o null | Hora del nodo en ISO 8601 con zona (UTC-6), sincronizada por NTP con la Pi. `null` si aun no hay hora: la Pi usa su hora de recepcion |
| `uptime_s` | entero | Segundos desde que arranco el nodo (respaldo si no hay `ts`) |
| `co2_ppm` | entero o null | Ultima lectura valida del MH-Z19C (null en el precalentamiento de 1 min o si falla) |
| `pm1_ugm3`, `pm25_ugm3`, `pm10_ugm3`, `voc_index` | numero o null | Promedio de las lecturas de 1 s de la ventana de envio |
| `n_pm25`, `n_voc` | entero | Cantidad de lecturas promediadas (control de calidad) |
| `temp_c`, `hum_pct`, `pres_hpa` | numero o null | BME280 |
| `ocupacion` | entero o null | Ultimo aforo recibido por comando |
| `puerta`, `ventana` | texto | `abierta`, `cerrada` o `desconocido` (sensores 433 MHz) |
| `ventilador`, `vent_modo` | bool, texto | Estado de la salida y su modo (`auto`, `on`, `off`) |
| `aire` | texto | `bueno`, `moderado`, `malo` o `sin_dato` (peor de CO2, PM2.5 y COV) |
| `errores` | entero | Lecturas descartadas por fuera de rango o falla de sensor |
| `diferido` | bool | `true` si el mensaje se guardo en el buffer porque no habia broker y se envio despues |

## 2. Evento

Proposito: avisar de inmediato un cambio, sin esperar la siguiente telemetria.

```json
{"nodo":"nodo01","aula":"aula01","seq":153,"ts":"2026-10-20T09:15:42-06:00","uptime_s":1522,
 "tipo":"puerta","detalle":"abierta","co2_ppm":1043,"diferido":false}
```

| `tipo` | `detalle` posibles | Cuando |
|---|---|---|
| `puerta`, `ventana` | `abierta`, `cerrada` | Llega un codigo 433 MHz que cambia el estado |
| `aire` | `bueno`, `moderado`, `malo` | Cambia la clasificacion |
| `ventilador` | `encendido`, `apagado` | Cambia la salida |
| `conexion` | `conectado al broker` | Al (re)conectar |
| `sensor` | `bme280 reinicializado`, `bus i2c recuperado` | El BME280 dio 3 lecturas imposibles seguidas (corte de energia) y se reinicio |
| `cmd_ok` | texto del cambio aplicado | Comando valido |
| `cmd_error` | motivo | Comando invalido o fuera de rango |

## 3. Estado (retenido + Last Will)

```json
{"nodo":"nodo01","estado":"online","ip":"192.168.1.60","buffer":0}
{"nodo":"nodo01","estado":"offline"}
```
El nodo publica `online` al conectar. El broker publica `offline` automaticamente (LWT) si el nodo deja de responder por mas de 1.5 veces el keepalive (15 s, o sea unos 22 s). Al ser retenido, un suscriptor nuevo conoce el estado al instante.

## 4 a 6. Comandos

| Topico | Payload | Validacion en el nodo |
|---|---|---|
| `.../cmd/aforo` | `{"ocupacion":28}` | Entero 0 a 50 |
| `.../cmd/modo` | `{"modo":"ahorro"}` | `normal` o `ahorro` |
| `.../cmd/ventilador` | `{"modo":"on"}` | `auto`, `on` u `off` |

Respuesta: evento `cmd_ok` o `cmd_error`.

## 7. Procesado (Pi)

```json
{"nodo":"nodo01","aula":"aula01","ts":"2026-10-20T09:25:00-06:00","seq_origen":210,"co2_ppm":760,
 "tendencia_ppm_min":-31.5,"ach":4.8,"ventilacion":"buena","co2_por_persona":12.1}
```
`ach` se calcula solo cuando el CO2 baja de forma sostenida durante 10 min:

$$\text{ACH}=\frac{1}{t}\ln\!\left(\frac{C_0-C_{ext}}{C_t-C_{ext}}\right),\quad C_{ext}=420\ \text{ppm},\ t\ \text{en horas}$$

Clasificacion: buena (4 o mas), regular (2 a 4), insuficiente (menos de 2).

## Firebase Firestore (lo escribe la Pi, no el nodo)

| Ruta | Contenido | Frecuencia |
|---|---|---|
| `aulas/{aula}/telemetria/{nodo}-{id}` | Telemetria + `recibido` | 1 documento por minuto por nodo |
| `aulas/{aula}/eventos/{nodo}-{id}` | Eventos | Todos, al instante |
| `aulas/{aula}/estado/{nodo}-{id}` | Historial online/offline | Todos |
| `aulas/{aula}/procesado/{nodo}-{id}` | ACH | 1 por minuto, solo si hay ACH |
| `nodos/{nodo}` | `ultimo` (ultima telemetria) y `estado` | Se sobrescribe |

Sin internet todo queda en SQLite (`sync=0`) y se sube al volver la conexion.
