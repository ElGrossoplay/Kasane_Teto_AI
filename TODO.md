# TODO — Kasane Teto AI Lite

Última actualización: 2026-10-31 · **Fase 1 completada · Siguiente: Fase 2 (IA local), pendiente de aprobación**

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

## Fase 1 — Base y mascota (completada)

- [x] 1.1 Instalar Python 3.12 (3.12.10, junto a 3.14; 3.14 sigue por defecto)
- [x] 1.2 Crear estructura de carpetas, `.gitignore`, `pyproject.toml`, `requirements.txt`, repo Git
- [x] 1.3 Crear `.venv` e instalar PySide6-Essentials, psutil, pytest (239 MB)
- [x] 1.4 Punto de entrada + bloqueo de instancia única + logging (en `%LOCALAPPDATA%\KasaneTetoAI\logs`)
- [x] 1.5 Carga de configuración (`config/default.toml` + `settings.json` en `%LOCALAPPDATA%`)
- [x] 1.6 `PetWindow`: ventana transparente, sin marco, arrastrable, siempre encima opcional
- [x] 1.7 Cambiar tamaño (rueda del ratón / configuración) y recordar posición y tamaño
- [x] 1.8 `SpriteAnimator` + formato de paquete de personaje + sprites provisionales genéricos
- [x] 1.9 Estados visuales: idle, listening, thinking, speaking, happy, surprised, confused, angry, bored
- [x] 1.10 `TrayIcon`: mostrar/ocultar, siempre encima, salir
- [x] 1.11 Ventana de configuración mínima
- [x] 1.12 `scripts/medir_recursos.py` y medición (ver abajo)
- [x] 1.13 Pruebas: 27 unitarias, prueba automática en el escritorio real y prueba manual de Diego
      superadas. Limitación aceptada: la mascota no se superpone a juegos con anticheat
- [x] 1.14 `docs/LICENCIAS.md`

Medido en reposo (2026-10-31): RAM ~66 MB, máximo 67,5 MB (objetivo < 200 MB, cumplido). CPU: 0,10 a
0,33 % con la mascota quieta (objetivo < 1 %, cumplido), con mediana 0 %. En otras dos tomas salió
0,87 y 1,21 % por ráfagas de 3–7 % de varios segundos. En la única ráfaga rastreada, la ventana se
estaba arrastrando; la causa de las demás no está confirmada.

Marcadores de posición declarados: los sprites son provisionales y el menú "Probar estado" es la
única forma de cambiar de estado hasta la Fase 2.

## Fases siguientes (detalle al aprobar cada una)

- [ ] Fase 2 — IA local: `LLMProcess`, `LLMClient`, personalidad, emociones, carga/descarga, pruebas de modelos
- [ ] Fase 3 — Voz: Piper, faster-whisper/Vosk, push-to-talk, volumen
- [ ] Fase 4 — Memoria: SQLite + FTS5, confirmaciones, panel, historial
- [ ] Fase 5 — Herramientas: lista blanca, confirmaciones, registro, búsqueda web opcional
- [ ] Fase 6 — Optimización: modo juego (sin interactuar con juegos ni anticheat), estados, prueba de
      estabilidad de 8 h
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
- **2026-10-31:** repositorio conectado a GitHub (público). Fase 1 implementada: Python 3.12, `.venv`,
  mascota, bandeja, configuración, pruebas y medición.
- **2026-10-31:** prueba manual de Diego superada; Fase 1 cerrada. Añadida la regla de no interactuar
  con juegos ni anticheat.
