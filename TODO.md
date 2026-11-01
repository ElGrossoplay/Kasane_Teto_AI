# TODO — Kasane Teto AI Lite

Última actualización: 2026-10-31 · **Fase actual: 3 (voz) — implementada, falta la prueba manual de Diego (3.8)**

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

## Fase 2 — IA local (completada)

- [x] 2.1 Descargar llama.cpp b12024 (CUDA 12.4) y comprobar que detecta la GTX 1650
- [x] 2.2 Descargar 3 modelos con hash verificado y elegir con la batería → Qwen3.5-4B en GPU
- [x] 2.3 `LLMProcess`: solo en 127.0.0.1, clave aleatoria, Job Object, limpieza de huérfanos
- [x] 2.4 `LLMClient`: streaming, cancelación y errores controlados
- [x] 2.5 Personalidad, gramática y `EmotionParser` (emoción → animación)
- [x] 2.6 `ResourceManager`: GPU/CPU según VRAM libre, descarga por inactividad y manual
- [x] 2.7 `ConversationService` en hilo aparte + `ChatWindow`
- [x] 2.8 Pruebas: 108 automáticas + 1 con modelo real + verificación en el equipo real
- [x] 2.9 **Diego:** prueba manual: listas cortadas y canciones inventadas, corregidas. Cierre de la
      fase aprobado por Diego (2026-10-31)
- [x] 2.10 Base de conocimiento local: fichas en `assets/knowledge/`, búsqueda por nombre y FTS5 en
      `memory/knowledge.py`, con reacciones propias de Teto (pedido por Diego)

Medido (2026-10-31) con conocimiento activo, objetivos entre paréntesis: reposo con IA descargada
77 MB y 0,01 % de CPU; IA activa 1246 MB de RAM, estable en 30 turnos (< ~1,5 GB), y 2933 MiB de
VRAM (≤ ~3,5 GB); 42 tokens/s; primera palabra ~2 s (< 3 s); VRAM liberada al 100 % al descargar;
interfaz sin congelarse (pausa máxima 32 ms). El primer mensaje tarda ~10 s, y uno de cada 10–15
turnos 8–9 s, al recortar el historial. En CPU: 8,4 tokens/s, 1,8 GB de RAM.

`scripts/probar_conocimiento.py`: 58/60 respuestas con el dato clave correcto. Solo comprueba ese
dato: algunas respuestas deforman detalles (llamó "gratuito" a UTAU, que es shareware).

Ajustes del servidor medidos: `--load-mode none` baja la RAM de 3,2 a 1,1 GB; `--cache-ram 0` evita
una caché de hasta 8 GB; con `--ctx-checkpoints 0` la primera palabra sube a 7–10 s, por eso son 2.

Ajustes tras la prueba de Diego: máximo 400 tokens con aviso si se corta, temperatura 0,3,
penalización de repetición 1,05 y ficha con datos verificados de Teto en el prompt (fuente:
Wikipedia, "Kasane Teto"). Batería ampliada a 33 preguntas con preguntas trampa.

Limitaciones conocidas:
- **Inventa fuera de las fichas:** por ejemplo, películas de Ghibli. Ni el prompt ni la temperatura
  lo eliminan; la vía real es la búsqueda web de la Fase 5. Lo que importe debe añadirse como ficha
  en `assets/knowledge/` con datos verificados.
- A veces deforma datos de las fichas, mezcla identidades o cuenta mal (dijo "diez" canciones
  siendo seis, o "yo no puedo cantar porque soy UTAU").
- Las reacciones de las fichas son personalidad inventada, no hechos ni opiniones oficiales.
- Solo cubre lo que hay en las fichas: el resto del mundo Vocaloid sigue siendo desconocido para ella.
- La carga en frío puede tardar 30–80 s si el modelo no está en la caché de disco de Windows.
- Qwen3.5-4B usa mucho `[neutral]`, por lo que la mascota varía poco de expresión, y a veces añade
  frases sin sentido. Puede inventar: es inherente a un modelo de este tamaño.
- Qwen3.5-2B en CPU inventa bastante más (en la batería dijo que el perro se llama Max). Es solo
  un respaldo para cuando no hay VRAM.
- Marcador de posición: la conversación se pierde al cerrar la app hasta la Fase 4 (memoria).

## Fase 3 — Voz (en pruebas)

- [x] 3.1 Piper 1.8.0 en `models/piper/venv` y 3 voces con hash verificado
- [x] 3.2 faster-whisper 1.2.1 en `models/whisper/venv` y modelo `base` con hash verificado
- [x] 3.3 Procesos aparte en `workers/`: cargan una vez, atienden por tuberías y mueren con la app
- [x] 3.4 `SpeechService`: voz por frases, sin bloquear, cortable y con volumen
- [x] 3.5 `ListenService`: grabar, descartar silencio, transcribir; vocabulario sacado de las fichas
- [x] 3.6 Atajo global `Ctrl+Alt+T` con `RegisterHotKey` (pulsar para empezar y para terminar) y
      botón "Hablar" en el chat (mantener pulsado)
- [x] 3.7 Configuración: voz, volumen, micrófono (apagado por defecto)
- [~] 3.8 **Diego:** eligió la voz Daniela. Primera prueba: había que hablar por sílabas y la
      personalidad resultaba forzada; corregido en parte
- [x] 3.9 **Diego:** medición con su voz: 50 % al principio, 55 % con ajustes de software y 79 % tras
      revisar la configuración de sonido de Windows (8 frases). El reparto de frecuencias apenas
      cambió, así que "faltan agudos" queda sin confirmar; el indicio es que dejó de haber un fondo
      silenciado. Modelo `small` (461 MB) sin descargar: solo si 79 % se queda corto
- [x] 3.10 Captura por WASAPI a calidad nativa (48 kHz) con conversión correcta, normalización,
      filtro de silencio y vocabulario como `hotwords`
- [x] 3.11 Personalidad menos forzada: datos de Teto en una ficha que solo se usa si preguntan por
      ella, reacciones solo si piden su opinión, prompt con ejemplos de tono natural

Medido (2026-10-31): Piper 0,15–0,33 s por frase (carga 4 s), 310 MB de RAM, 0 de VRAM. Whisper
0,9–1,8 s por frase con audio sintético (< 2 s), ~195 MB. Reposo 78 MB y 0,01 % de CPU. Interfaz sin
congelarse en todo el ciclo (pausa máxima 172 ms). RAM con todo activo ~1,74 GB, por encima de
~1,5 GB solo mientras Piper y Whisper siguen cargados.

Limitaciones conocidas:
- El reconocimiento falla en palabras sueltas ("chiste" → "ciste") y Teto puede inventar cuando
  ocurre. El modelo `base` llega a 79 % con la voz de Diego y aún falla en nombres propios.
- Una mala transcripción con un nombre real puede hacerle inventar ("SereReRe").
- La voz es genérica: no suena como Teto. RVC queda como mejora (ver ideas).
- La primera respuesta de voz puede tardar 40 s si el modelo no está en la caché de Windows.
- El atajo global no detecta soltar la tecla: es una limitación de `RegisterHotKey`, que se usa por
  seguridad frente a anticheat.

## Fases siguientes (detalle al aprobar cada una)

- [ ] Fase 4 — Memoria: SQLite + FTS5, confirmaciones, panel, historial
- [ ] Fase 5 — Herramientas: lista blanca, confirmaciones, registro, búsqueda web opcional
- [ ] Fase 6 — Optimización: modo juego (sin interactuar con juegos ni anticheat), estados, prueba de
      estabilidad de 8 h
- [ ] Fase 7 — Final: corrección de errores, PyInstaller, instalador

## Ideas para el futuro (fuera del alcance actual)

- Voz de Teto con RVC (aprobado para después de Piper, 2026-10-31): solo modelo entrenado por Diego
  con la biblioteca oficial de UTAU, para uso personal y sin distribuirlo; nunca modelos ajenos.
  Antes hay que medir CPU y VRAM, y ajustar la regla "No clonar la voz oficial" de CLAUDE.md
- Palabra de activación "Teto" y reconocimiento continuo
- Modelo Live2D (con arte licenciado)
- Búsqueda semántica en memoria (embeddings)
- Comentarios espontáneos

## Problemas conocidos / pendientes de verificar

- Detalles del equipo y pruebas específicas: `docs/privado/EQUIPO_LOCAL.md` (local, no se sube).
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
- **2026-10-31:** Fase 2 implementada: llama.cpp, modelos, batería, chat, emociones y descarga por
  inactividad. Pendiente la prueba manual.
- **2026-10-31:** corregidas listas cortadas y canciones inventadas tras la prueba de Diego. Añadida
  la base de conocimiento de Vocaloid y música virtual. Fase 2 cerrada y subida a GitHub.
- **2026-10-31:** Fase 3 implementada: Piper, faster-whisper, atajo global y botón de hablar.
  Pendiente la prueba con micrófono real y la elección de voz.
- **2026-11-01:** tras la prueba de Diego, corregida la captura del micrófono y la personalidad
  forzada. `probar_conocimiento.py` amplió a 30 preguntas (87/90 respuestas correctas).
