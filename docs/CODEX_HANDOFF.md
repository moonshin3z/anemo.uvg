# Traspaso para Codex: informe Fase 03 de Anemo

Contexto: proyecto IoT CC3108 (UVG). Enunciado de la fase: 9 secciones (descripción, E/S, diagramas, configuración, frecuencias, catálogo MQTT, procesamiento, pruebas, evidencias y conclusiones). Entrega: PDF + presentación. Estilo pedido: español de Guatemala, primera persona plural, sencillo, como de estudiantes, sin guiones largos.

## Estado
- Borrador completo: `docs/informe_fase03.md` (secciones 1 a 9). Revisar las marcas [PENDIENTE].
- Diagramas listos: `docs/esquema_final_anemo.png`, `docs/esquema_ventilador.png`.
- Catálogo MQTT detallado: `docs/catalogo_mqtt.md`.
- Hardware validado el 24-oct: CO2, PM, LED, puerta MC-38, ventilador 2N2222A (encendió a 1079 ppm y se apagó bajo 900). Sin broker todavía (rc=-2, mensajes diferidos).
- Faltan: BME280 y SGP40 de reemplazo (llegan lunes/martes), Raspberry Pi (prestada), Firebase.

## Tareas pendientes
1. Dibujar el diagrama de comunicación (sección 3): ESP32 `anemo-nodo01` → Wi-Fi → Mosquitto :1883 en la Pi → suscriptor.py → SQLite + Firestore. Guardar como `docs/diagrama_comunicacion.png`.
2. Completar pruebas 9 a 12 de la sección 8 cuando haya broker (laptop con `raspberry/mosquitto/anemo_laptop.conf` o la Pi) y sensores nuevos.
3. Insertar fotos y capturas en `evidencias/` y referenciarlas en la sección 9.
4. Convertir a PDF (pandoc o Word) con portada, índice e imágenes.
5. Hacer la presentación (10 a 12 diapositivas): problema, hardware, diagramas, MQTT, procesamiento, pruebas, dificultades, demo.
