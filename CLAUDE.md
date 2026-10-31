# CLAUDE.md — Contexto permanente para Claude

Leer al inicio de cada sesión, junto con `TODO.md` (estado actual). La justificación de cada
decisión está en `docs/PROPUESTA_TECNICA.md`; no repetirla aquí.

## Proyecto

Kasane Teto AI Lite: asistente de escritorio para Windows 11 con mascota animada, IA local en
español, voz, memoria SQLite, herramientas controladas de Windows y modo juego.
Desarrollador: Diego. Idioma de trabajo y de la app: **español**.

## Hardware objetivo (no olvidar)

- i5-11400H (6C/12T), 16 GB RAM (a menudo ya muy ocupada), **GTX 1650 con 4 GB de VRAM dedicada**,
  Intel UHD. La "memoria GPU compartida" es RAM, **no** VRAM.
- Proyecto, `.venv`, modelos y cachés siempre en D:. Datos medidos: `docs/privado/EQUIPO_LOCAL.md`
  (local, no se sube).
- Presupuestos: app en reposo < 200 MB RAM y < 1 % CPU; modo normal < ~1,5 GB RAM;
  VRAM total de la IA ≤ ~3,5 GB.

## Decisiones vigentes (cambiarlas requiere aprobación de Diego)

| Área | Decisión |
|---|---|
| Lenguaje / UI | Python 3.12 en `.venv`, PySide6. Sin QtWebEngine ni Electron |
| IA | `llama-server.exe` (llama.cpp, build CUDA 12; plan B Vulkan, plan C CPU) como **subproceso** bajo demanda, HTTP en 127.0.0.1, una sola instancia, se cierra tras inactividad |
| Modelo | Por decidir en Fase 2 con pruebas. Candidatos: Qwen3.5-4B / 2B Q4_K_M, Qwen3-4B-Instruct-2507. Contexto 4096 por defecto |
| TTS | Piper como programa externo (licencia GPL-3.0 en la versión activa), voz candidata `es_MX-claude-high` |
| STT | faster-whisper `base` int8 en CPU (alternativas: `tiny`, Vosk). Push-to-talk |
| Memoria | SQLite + FTS5, sin embeddings por ahora. Datos en `%LOCALAPPDATA%\KasaneTetoAI\` |
| Mascota | Sprites PNG por estado con "paquetes de personaje"; Live2D solo como mejora futura |
| Herramientas | Lista blanca + validación + confirmación. Control de Windows **desactivado por defecto** |
| Web | Opcional y desactivada por defecto (Wikipedia API, DuckDuckGo vía `ddgs`) |
| Empaquetado | PyInstaller `--onedir`; modelos y llama.cpp fuera del ejecutable |
| Distribución | App de uso personal; código en repositorio **público** de GitHub. Nunca subir datos del equipo, recuerdos, configuración de usuario ni arte de terceros. Distribuir la app exigiría revisar las licencias |

## Reglas de trabajo

1. **No empezar una fase sin aprobación explícita.** Fase actual: ver `TODO.md`.
2. **No instalar, descargar ni cambiar configuración del sistema sin preguntar**, explicando qué es,
   para qué, tamaño, licencia, compatibilidad y alternativa más ligera.
3. Antes de un cambio importante: revisar archivos, explicar el plan, archivos afectados y riesgos.
4. Después de cada tarea: resumen, archivos modificados, pruebas hechas, errores pendientes,
   actualizar `TODO.md`, siguiente paso.
5. No simular funciones. Un marcador de posición se declara como tal en `TODO.md`.
6. No declarar nada terminado sin haberlo probado. Reportar cifras de consumo reales.
7. Editar archivos por partes; no regenerar archivos completos que funcionan.
8. No borrar funcionalidades ni archivos importantes sin permiso.
9. Commit de Git al cerrar cada tarea verificada (mensajes en español, formato `fase N: …`).

## Reglas de código

- Paquete `src/kasane_teto/`; módulos: `core`, `ai`, `voice`, `memory`, `character`, `desktop`,
  `tools`, `interface`, `personality`. La UI no llama a la IA directamente: usa el `EventBus`.
- Nada pesado en el hilo de la UI (IA, TTS, STT, red → `QThread`/`QThreadPool`).
- Componentes pesados con carga perezosa y método `unload()`; el `ResourceManager` decide.
- `subprocess` siempre con lista de argumentos y **nunca** `shell=True`. El texto del modelo nunca
  se ejecuta.
- Errores: capturar en los bordes, registrar en `logs/`, mostrar mensaje amable; la app no debe caer
  porque falle la IA o la voz.
- Tipado con anotaciones, `logging` en vez de `print`, configuración en `config/default.toml`.
- Pruebas con pytest en `tests/`; las que necesitan modelos reales llevan `@pytest.mark.slow`.

## Seguridad, privacidad y licencias

- Confirmación obligatoria para: borrar, modificar archivos o configuración, instalar, acciones
  administrativas, enviar mensajes.
- Nada se guarda en memoria sin confirmación del usuario. Nada sale a Internet sin consentimiento,
  y nunca recuerdos personales en consultas web.
- La IA no modifica su propio código.
- Juegos y anticheat: nunca forzar la superposición sobre un juego. Sin inyección, ganchos de teclado
  o ratón, overlays de GPU, capturas de pantalla del juego, lectura de su memoria ni apertura de su
  proceso. Atajos solo con `RegisterHotKey`. Si el juego no deja ver la mascota, se acepta.
- Arte y voz de Kasane Teto: derechos de TWINDRILL (directrices en kasaneteto.jp). Claude no dibuja
  al personaje; el arte lo aporta Diego con permiso del autor. No clonar la voz oficial.
- Registrar la licencia de cada recurso de terceros en `docs/LICENCIAS.md`.
