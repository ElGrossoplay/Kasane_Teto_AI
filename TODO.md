# TODO — Kasane Teto AI Lite

Última actualización: 2026-11-01 · **Fase 3 completada · Búsqueda en VocaDB hecha, pendiente de la prueba manual de Diego · Siguiente: Fase 4 (memoria)**

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

## Fase 3 — Voz (completada)

- [x] 3.1 Piper 1.8.0 en `models/piper/venv` y 3 voces con hash verificado
- [x] 3.2 faster-whisper 1.2.1 en `models/whisper/venv` y modelo `base` con hash verificado
- [x] 3.3 Procesos aparte en `workers/`: cargan una vez, atienden por tuberías y mueren con la app
- [x] 3.4 `SpeechService`: voz por frases, sin bloquear, cortable y con volumen
- [x] 3.5 `ListenService`: grabar, descartar silencio, transcribir; vocabulario sacado de las fichas
- [x] 3.6 Atajo global `Ctrl+Alt+T` con `RegisterHotKey` (pulsar para empezar y para terminar) y
      botón "Hablar" en el chat (mantener pulsado)
- [x] 3.7 Configuración: voz, volumen, micrófono (apagado por defecto)
- [x] 3.8 **Diego:** eligió la voz Daniela. Primera prueba: había que hablar por sílabas y la
      personalidad resultaba forzada; corregido, y cierre de la fase aprobado (2026-11-01)
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

## Búsqueda en Internet (adelantada de la Fase 5, aprobada por Diego antes que la memoria)

- [x] W.1 `tools/vocadb.py`: API pública con user agent propio, caché SQLite de 7 días en
      `%LOCALAPPDATA%\KasaneTetoAI\vocadb_cache.sqlite3` y máximo de 200 consultas al día
- [x] W.2 `tools/web_lookup.py`: reconoce preguntas por artistas y canciones y envía solo el nombre.
      Lo personal, los correos, los números largos y las frases largas no salen del equipo
- [x] W.3 Integrado en `ConversationService` en hilo aparte. Las fichas locales mandan salvo en
      listas de canciones, y las preguntas de seguimiento reutilizan los datos sin otra consulta
- [x] W.4 Interruptor en Configuración, apagado por defecto. Cada respuesta enlaza su fuente en el
      chat; ese enlace no se lee en voz alta
- [x] W.5 Ficha de Senbonzakura completada con autor y fecha confirmados en VocaDB
- [x] W.6 **Diego:** primera prueba manual con voz: funcionó la lista de 20 canciones, y falló con
      preguntas mal transcritas. Corregido (W.7 a W.11)
- [x] W.7 Reconoce "quién es" deformado por la voz ("Kienes", "Quienes", "Gen es") y "preguntando por
      X"; decide por el nombre preguntado, no por cualquier palabra de la frase
- [x] W.8 Nombres mal transcritos: se comparan en el equipo con fichas y con los 100 artistas, voces
      y canciones más populares de VocaDB, y el chat avisa de qué entendió y qué buscó
- [x] W.9 "Quién es X" solo busca artistas; "búscalo" repite la búsqueda del mensaje anterior
- [x] W.10 Si no hay resultados, se le avisa al modelo sin estropear la cultura general
- [x] W.11 La gramática exige texto: ya no puede responder solo con la emoción. Si llegara vacía, se
      avisa. No se pudo reproducir el caso original en 8 intentos
- [x] W.12 **Diego:** grabó las 12 frases: 69 % con voz real, con "Kienes" en vez de "¿Quién es?".
      En esa prueba la búsqueda estaba apagada en sus ajustes, por eso no conocía a varios artistas
- [x] W.13 `voice/transcript.py` corrige "Kienes", "Quienes" y "Gen es", y nombres casi exactos
      ("Katsune Miku"): sube a 80 % con esas 12 grabaciones
- [x] W.14 Con la búsqueda apagada, el chat avisa cuando buscar habría ayudado
- [ ] W.15 **Diego:** repetir la prueba por voz con la búsqueda activada
- [x] W.16 Modelo `small` descargado con hash verificado y comparado: no mejora a `base`
- [x] W.17 **Diego:** volvió a grabar las 12 frases con las mejoras de audio revisadas: `small` 88 %,
      `base` 59 %, en las mismas tomas. Con 6 hilos `small` da lo mismo y no va más rápido: siguen 4
- [ ] W.18 **Diego:** aprobar el cambio de `base` a `small` (decisión vigente de CLAUDE.md)

Comparativa de ajustes del reconocedor con las 12 grabaciones (modelo `base`): sin vocabulario 54 %,
sin refuerzo de agudos 59 %, ajuste actual 69 %, ejemplos genéricos en el prompt 69–74 %, y actual
con corrección posterior 80 %. Se descartan los ejemplos en el prompt: el reconocedor los repite como
si se hubieran dicho ("¿Quién es? ¿Quién es?") y deforman otras frases. Las mismas 12 frases sirvieron
para elegir y para medir, así que el 80 % puede ser algo optimista.

Medido (2026-11-01): 296 pruebas más 4 reales contra VocaDB. Búsqueda 58/60, con las transcripciones
reales de Diego. Conocimiento 87/90, igual que antes, con la gramática nueva. Reposo
78,1 MB frente a 77,9 MB de la versión anterior, y 0,01 % de CPU. Interfaz: pausa máxima 32 ms.
Consulta sin caché 1–2 s; con caché, 0,02 s. Primera palabra con búsqueda sin caché ~4,5 s, con
caché ~2,4 s. La primera corrección de un nombre tarda ~8 s por las listas populares, que luego
quedan en caché.

Limitaciones conocidas:
- El audio pesa tanto como el modelo. Con mejoras de audio activas y 12 frases: `base` 80 % (0,8 s
  por frase, 362 MB) y `small` 78 % (2,2 s, 636 MB). Tras revisarlas y grabar de nuevo: `small` 88 % y
  `base` 59 %. Es una sola toma de cada caso, y la caída de `base` no está explicada
- Antes, las 12 grabaciones paraban en el pico exacto 0,994 (limitador previo a la app). En las
  nuevas el pico varía, así que ese limitador ya no actúa. La energía de 4 a 8 kHz sigue en
  0,01–0,38 %: la falta de agudos no era la causa, y esa hipótesis queda descartada
- En 4 de las 12 grabaciones nuevas el pico llega a 1,000 con algo de recorte: el volumen de entrada
  aún está algo alto
- Sigue sin resolver "Cuéntame un chiste" ("chit de corto") ni "Mitchie M" ("mi tiem"), y "pesado"
  sale "besó"
- Python puede liberar objetos Qt desde un hilo que no es el principal. En las pruebas causó cierres
  (7 de 25 ejecuciones, 0 de 20 al limpiar la memoria en el hilo principal). No se ha visto en la app,
  cuyos objetos Qt viven toda la sesión, pero queda vigilar si se cierra sola mientras Teto habla
- La primera lista de una voz con muchas versiones es lenta: la de Kasane Teto tardó 17,6 s una vez
  y ~6 s otra. Después queda en caché. Si una consulta supera 10 s, Teto avisa y responde sin datos
- **Modelo de respaldo:** con menos de 3100 MiB libres, la app usa el modelo en CPU sin avisar. Con
  otros programas usando la GPU quedó menos memoria, y las respuestas fueron mucho peores y lentas.
  Forzando la GPU cargó bien con 2968 MiB; el umbral sigue sin tocar
- VocaDB falló de forma intermitente en 2 turnos de una repetición y en otra batería; no se repitió
  después y no se registró la causa. El motivo queda ahora en el registro de la app
- VocaDB cubre música: no sirve para cultura general ni para biografías largas. Muchas descripciones
  son notas para editores, así que solo se usan las que parecen biografía
- Solo reconoce frases concretas. Si la pregunta se formula de otra forma, no busca
- Un nombre común que coincida con un artista puede dar datos de otra persona ("Laura" es un
  productor en VocaDB)
- Una deformación muy grande no se corrige: "Sembo segura" (0,61) o "Sembo se ocurre" no llegan al
  mínimo de 0,78. Rebajarlo empezaría a confundir palabras normales con nombres
- Con datos correctos aún añade falsedades: dijo que Kikuo hace canciones "para Kasane Teto" y, sobre
  Senbonzakura, "la hice yo". Sin datos puede inventar (1 de 3 en "sembo segura")
- Las fichas incompletas impiden buscar: si existe ficha, no se consulta VocaDB salvo para listas
- Fandom: Diego prefiere Vocaloid Wiki y SynthV Wiki, pero sus condiciones (19-dic-2025) prohíben
  cualquier acceso automatizado sin permiso escrito, y su robots.txt activa un control de Cloudflare.
  **No conectar Fandom sin ese permiso por escrito.** Nunca esquivar controles antibots
- Condiciones de VocaDB leídas en su wiki: uso gratuito para cualquier fin, pide cachear, identificarse
  y enlazar la fuente; miles de consultas al día sin permiso pueden suponer un bloqueo de la IP.
  La licencia dice "Creative Commons Attribution" sin indicar versión

## Fases siguientes (detalle al aprobar cada una)

- [ ] Fase 4 — Memoria: SQLite + FTS5, confirmaciones, panel, historial
- [ ] Fase 5 — Herramientas: lista blanca, confirmaciones, registro, búsqueda general opcional
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
  forzada. `probar_conocimiento.py` amplió a 30 preguntas (87/90 respuestas correctas). Fase 3
  cerrada y subida a GitHub.
- **2026-11-01:** Fandom descartado por sus condiciones de uso. Búsqueda de música en VocaDB
  implementada y medida, con `scripts/probar_busqueda.py`. Pendiente la prueba manual.
- **2026-11-01:** primera prueba de Diego con voz: corregidas las preguntas mal transcritas, los
  nombres deformados, "búscalo" y la respuesta vacía. Pendiente repetir la prueba manual.
- **2026-11-01:** con las 12 grabaciones de Diego, corrección de texto tras el reconocimiento (de 69
  a 80 %) y aviso cuando la búsqueda está apagada. Corregido un cierre intermitente de las pruebas.
- **2026-11-01:** modelo `small` descargado y comparado: no mejora a `base`. Detectado un posible
  limitador en el audio del micrófono. Pendiente grabar sin mejoras de audio.
- **2026-11-01:** con las mejoras de audio revisadas, `small` llega a 88 % y `base` baja a 59 %.
  Pendiente que Diego apruebe el cambio de modelo.
