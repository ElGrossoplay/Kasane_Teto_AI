# TODO — Kasane Teto AI Lite

Última actualización: 2026-10-31 · **Fase actual: 1 (base y mascota) — aprobada, en pausa hasta conectar GitHub**

Leyenda: `[ ]` pendiente · `[~]` en curso · `[x]` hecho y probado · `[!]` bloqueado

## Fase 0 — Análisis y planificación

- [x] Analizar requisitos
- [x] Investigar herramientas y licencias (llama.cpp, modelos, Piper, Whisper/Vosk, Live2D, Teto)
- [x] Diseñar arquitectura y plan por fases → `docs/PROPUESTA_TECNICA.md`
- [x] Crear CLAUDE.md, README.md, TODO.md
- [x] Crear script de diagnóstico de solo lectura → `scripts/diagnostico.ps1`
- [x] Ejecutar `scripts/diagnostico.ps1` en el equipo real → resultados en `docs/PROPUESTA_TECNICA.md` §2.1
- [x] **Diego:** decidir si la app será pública o personal → **personal** (2026-10-31)
- [x] **Diego:** aprobar la propuesta técnica (2026-10-31)
- [x] **Diego:** aprobar el inicio de la Fase 1 y la instalación de Python 3.12 (2026-10-31)

## Fase 1 — Base y mascota (en curso)

- [ ] 1.1 Instalar Python 3.12 (aprobado)
- [ ] 1.2 Crear estructura de carpetas, `.gitignore`, `pyproject.toml`, `requirements.txt`, repo Git
- [ ] 1.3 Crear `.venv` e instalar PySide6, psutil, pytest (con aprobación)
- [ ] 1.4 Punto de entrada + bloqueo de instancia única + logging a `logs/`
- [ ] 1.5 Carga de configuración (`config/default.toml` + configuración de usuario en `%LOCALAPPDATA%`)
- [ ] 1.6 `PetWindow`: ventana transparente, sin marco, arrastrable, siempre encima opcional
- [ ] 1.7 Redimensionar la mascota (rueda del ratón / menú) y recordar posición y tamaño
- [ ] 1.8 `SpriteAnimator` + formato de paquete de personaje + sprites provisionales genéricos
- [ ] 1.9 Estados visuales: idle, listening, thinking, speaking, happy, surprised, confused, angry, bored
- [ ] 1.10 `TrayIcon`: mostrar/ocultar, siempre encima, salir
- [ ] 1.11 Ventana de configuración mínima
- [ ] 1.12 `scripts/medir_recursos.py` y medición (objetivo: < 200 MB RAM, < 1 % CPU en reposo)
- [ ] 1.13 Pruebas: unitarias + lista manual (DPI 100/125/150 %, multi-monitor)
- [ ] 1.14 `docs/LICENCIAS.md`

## Fases siguientes (detalle al aprobar cada una)

- [ ] Fase 2 — IA local: `LLMProcess`, `LLMClient`, personalidad, emociones, carga/descarga, pruebas de modelos
- [ ] Fase 3 — Voz: Piper, faster-whisper/Vosk, push-to-talk, volumen
- [ ] Fase 4 — Memoria: SQLite + FTS5, confirmaciones, panel, historial
- [ ] Fase 5 — Herramientas: lista blanca, confirmaciones, registro, búsqueda web opcional
- [ ] Fase 6 — Optimización: modo juego, estados, prueba de estabilidad de 8 h
- [ ] Fase 7 — Final: corrección de errores, PyInstaller, instalador

## Ideas para el futuro (fuera del alcance actual)

- Palabra de activación "Teto" y reconocimiento continuo
- Modelo Live2D (con arte licenciado)
- Búsqueda semántica en memoria (embeddings)
- Comentarios espontáneos

## Problemas conocidos / pendientes de verificar

- Detalles del equipo y pruebas específicas: `docs/privado/EQUIPO_LOCAL.md` (local, no se sube).
- Comprobar en la Fase 2 con `--list-devices` que el build CUDA 12 detecta la GPU.
- La VRAM libre puede bajar con otras apps activas: medirla antes de cargar el modelo.
- Repositorio público: `https://github.com/ElGrossoplay/Kasane_Teto_AI`. Sin archivo de licencia,
  el código queda con todos los derechos reservados.
- Directrices oficiales de uso de Kasane Teto: leerlas en kasaneteto.jp antes de publicar.
- Cifras de consumo y velocidad en la propuesta son **estimaciones** hasta medirlas.

## Registro de sesiones

- **2026-10-31:** análisis inicial, investigación, propuesta técnica, documentos base y script de
  diagnóstico. Sin código de la app, sin instalaciones, sin descargas.
- **2026-10-31:** diagnóstico ejecutado en el equipo real; propuesta ajustada con los resultados;
  corregida la línea de CUDA del script (nvidia-smi ahora muestra "CUDA UMD Version").
