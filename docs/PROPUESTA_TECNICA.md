# Kasane Teto AI Lite — Propuesta técnica (v0.1)

Fecha: 2026-10-31 · Estado: **aprobada por Diego el 2026-10-31** · App de **uso personal** con código en un
repositorio público. El arte no se sube, y distribuir la app exigiría revisar las licencias de Teto,
el arte y Piper.

Este documento es la referencia de arquitectura y decisiones técnicas. CLAUDE.md resume las reglas
operativas, README.md describe el proyecto y TODO.md lleva el progreso; aquí está el "por qué".

---

## 1. Resumen ejecutivo

- **Un proceso principal ligero** (Python + PySide6) con la mascota, la bandeja del sistema, la
  interfaz, la memoria y el orquestador.
- **La IA corre en un proceso aparte** (`llama-server.exe` de llama.cpp) que se **arranca bajo
  demanda y se cierra tras un tiempo de inactividad**. Cerrar el proceso es la única forma 100 %
  fiable de devolver toda la RAM y VRAM a Windows.
- Voz (Piper / faster-whisper o Vosk) se carga solo al usarse y se descarga en inactividad.
- La mascota empieza con **animación por sprites (PNG)**, no Live2D: es lo más ligero y estable.
  Live2D queda como mejora opcional posterior.
- Todo acceso al sistema pasa por un **registro de herramientas con lista blanca** y confirmación
  en la interfaz. El modelo nunca ejecuta comandos de consola.

Consumo objetivo (a verificar con mediciones reales):

| Estado | RAM | VRAM | CPU |
|---|---|---|---|
| Suspendido / modo juego (solo mascota estática + bandeja) | ~100–150 MB | ~0 | < 0,5 % |
| Inactivo (mascota animada, IA descargada) | ~120–200 MB | ~0 | < 1 % |
| Activo conversando (modelo 4B en GPU + TTS) | ~0,8–1,3 GB | ~3,0–3,5 GB | picos altos durante la respuesta |
| Activo modo ligero (modelo 2B en CPU) | ~1,8–2,5 GB | 0 | picos altos durante la respuesta |

---

## 2. Diagnóstico del equipo

### 2.1 Resultados medidos (2026-10-31)

El diagnóstico se ejecutó en el equipo real y confirmó la CPU, la RAM y los 4 GB de VRAM previstos.
El detalle se guarda en `docs/privado/EQUIPO_LOCAL.md`, que no se sube al repositorio público.

### 2.2 Script de diagnóstico de solo lectura

`scripts/diagnostico.ps1` consulta (sin modificar nada): versión de Windows, CPU, RAM total y libre,
GPUs, VRAM real de la NVIDIA vía `nvidia-smi`, versión del driver, versiones de Python/Git
instaladas, espacio libre en disco y los procesos que más RAM usan. Ejecución:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\diagnostico.ps1
```

`-ExecutionPolicy Bypass` afecta solo a ese proceso de PowerShell; no cambia la configuración de
Windows.

### 2.3 Limitaciones conocidas del hardware

- **GTX 1650 (Turing TU117, 4 GB GDDR5/6):** compatible con CUDA 12.x y Vulkan. No tiene núcleos
  tensor. En portátiles con Optimus la pantalla suele ir por la Intel UHD, así que la NVIDIA queda
  casi libre (≈3,6–3,9 GB utilizables). Si un juego usa la NVIDIA, la IA **no puede** compartirla
  cómodamente: de ahí el modo juego.
- **La "memoria GPU compartida"** que muestra el Administrador de tareas es RAM del sistema, no
  VRAM. Nunca la contaremos como VRAM: si un modelo no cabe en los 4 GB, se reparte entre GPU y CPU
  y se vuelve mucho más lento.
- **CPU i5-11400H (6C/12T):** suficiente para modelos de 1–2B en CPU, Piper y Whisper pequeño.
  Limitaremos los hilos de la IA (p. ej. 4–6) para no congelar Windows.
- **RAM 16 GB:** con el navegador y otras apps abiertas es normal tener 8–10 GB ocupados antes de abrir la
  app. Presupuesto de diseño: **la app no debe pasar de ~1,5 GB de RAM en modo normal**.
- **Portátil:** la temperatura y el modo de energía afectan al rendimiento. Con batería, la NVIDIA
  puede rendir menos; la app debe detectarlo y sugerir el modo ligero.

---

## 3. Arquitectura

### 3.1 Vista general

```text
┌──────────────────────── Proceso principal (Python + PySide6) ────────────────────────┐
│                                                                                     │
│  desktop/           interface/            core/ (orquestador)          tools/        │
│  ─ PetWindow        ─ ChatWindow          ─ EventBus (señales Qt)      ─ ToolRegistry │
│  ─ SpriteAnimator   ─ SettingsWindow      ─ ConversationService        ─ lista blanca │
│  ─ TrayIcon         ─ MemoryPanel         ─ ResourceManager            ─ confirmación │
│                     ─ ConfirmDialog       ─ ActivityState              ─ ActionLog    │
│                                                                                     │
│  personality/       memory/               voice/                       ai/           │
│  ─ PromptBuilder    ─ MemoryStore         ─ TTSEngine (Piper)          ─ LLMClient    │
│  ─ EmotionParser    ─ (SQLite + FTS5)     ─ STTEngine (Whisper/Vosk)   ─ LLMProcess   │
│                                           ─ PushToTalk                                │
└─────────────┬──────────────────────────────────────────────┬──────────────────────────┘
              │ HTTP local 127.0.0.1 (streaming)              │ subprocess (solo si se usa)
      ┌───────▼──────────┐                           ┌────────▼────────┐
      │ llama-server.exe │  ← se inicia bajo demanda │ piper (CLI/lib) │
      │ (modelo GGUF)    │  ← se cierra al inactivo  └─────────────────┘
      └──────────────────┘
```

### 3.2 Responsabilidades

| Módulo | Responsabilidad | No hace |
|---|---|---|
| `desktop/` | Ventana transparente, arrastre, tamaño, siempre encima, animación por estados, bandeja | Lógica de IA |
| `character/` | Definición de estados visuales (idle, listening…) y su mapeo a animaciones | Dibujar ni cargar IA |
| `personality/` | Prompt de sistema de Teto, reglas de estilo, extracción de la emoción de la respuesta | Llamar al modelo |
| `ai/` | Arrancar/parar `llama-server`, enviar mensajes, streaming, cancelación | Decidir acciones |
| `voice/` | TTS y STT con carga perezosa, push-to-talk, volumen | Interpretar órdenes |
| `memory/` | SQLite: recuerdos, preferencias, historial; CRUD y búsqueda | Guardar sin permiso |
| `tools/` | Registro de acciones permitidas, validación de argumentos, confirmación, registro | Ejecutar texto libre |
| `core/` | Orquesta el flujo, estados Activo/Inactivo/Suspendido, modo juego, presupuesto de recursos | UI |
| `interface/` | Ventanas de chat, configuración, memoria, historial, diálogos | Lógica de negocio |
| `config/` | Valores por defecto (TOML) + configuración del usuario | — |

### 3.3 Comunicación entre componentes

- **Dentro del proceso:** señales y slots de Qt a través de un `EventBus`. La interfaz nunca llama
  directamente a la IA; emite `user_message(texto)` y el orquestador responde con
  `assistant_token`, `assistant_done(texto, emoción)`, `state_changed(estado)`, etc.
- **Trabajo pesado fuera del hilo de la UI:** las llamadas HTTP a la IA, el TTS y el STT corren en
  `QThread`/`QThreadPool`. La mascota nunca se congela mientras Teto "piensa".
- **IA ↔ app:** HTTP local (`127.0.0.1`, puerto aleatorio libre) con la API compatible con OpenAI
  de `llama-server`, en streaming para que el texto aparezca mientras se genera. Botón "detener"
  cancela la petición.
- **Flujo de una conversación:**
  1. Usuario escribe (o habla → STT → texto). Estado visual: *listening* → *thinking*.
  2. `ResourceManager` asegura que la IA esté cargada (si no, la inicia; tarda unos segundos).
  3. `PromptBuilder` arma: personalidad + recuerdos relevantes (búsqueda FTS) + últimas N
     intervenciones, respetando el límite de contexto.
  4. El modelo responde con una etiqueta de emoción al inicio (`[feliz]`, `[confundida]`…);
     `EmotionParser` la extrae y cambia la animación; si falta, se usa *idle*.
  5. Si hay voz activa: TTS por frases mientras llega el texto. Estado *speaking*.
  6. Se reinicia el temporizador de inactividad.

### 3.4 Estados de actividad y modo juego

| Estado | IA | Voz | Mascota | Entrada |
|---|---|---|---|---|
| **Activo** | cargada | cargada si está habilitada | animación completa | usar la app |
| **Inactivo** | se cierra tras N min (def. 5) | se descarga tras N min | animación reducida (fps bajos) | sin uso |
| **Suspendido** | cerrada | descargada | estática u oculta | manual / bandeja |
| **Modo juego** | cerrada (o forzada a CPU) | STT apagado | estática, sin comentarios espontáneos | manual o al detectar juego a pantalla completa |

La detección automática de juego (aplicación en pantalla completa en primer plano o lista de
ejecutables configurada) se hará en la Fase 6 y será desactivable.

---

## 4. Selección de tecnologías

### 4.1 Interfaz: PySide6 ✅

Licencia LGPL (uso libre), soporte oficial de Qt, ventanas sin marco y translúcidas
(`FramelessWindowHint`, `WindowStaysOnTopHint`, `Tool`, `WA_TranslucentBackground`) y
`QSystemTrayIcon` nativo. Alternativas descartadas: Tkinter (transparencia por píxel pobre en
Windows), Electron (300+ MB de RAM base, contradice la prioridad de bajo consumo).

Evitaremos **QtWebEngine** (Chromium embebido, +150–300 MB) salvo que Live2D lo exija más adelante.

### 4.2 IA local: llama.cpp (`llama-server`) como proceso aparte ✅

| Opción | Ventajas | Inconvenientes | Veredicto |
|---|---|---|---|
| **`llama-server.exe` (binario oficial con CUDA 12)** | Sin compilar; aislado (si falla, la app sigue); cerrarlo libera **toda** la VRAM; API estándar; streaming; gramáticas/JSON schema | Gestionar un subproceso y su puerto | **Recomendado** |
| `llama-cpp-python` (en el mismo proceso) | Todo en Python | En Windows con CUDA suele requerir compilar o ruedas no oficiales; un fallo nativo tumba la app; liberar VRAM en caliente es menos fiable | Descartado |
| Ollama | Instalación simple, descarga de modelos | Servicio residente extra en segundo plano; menos control fino; los GGUF de Qwen3.5 con visión no funcionan aún en Ollama según Unsloth | No aporta ventaja aquí |

Notas: los binarios oficiales para Windows se publican por backend (CPU, CUDA, Vulkan). Para la
GTX 1650 usaremos **CUDA 12.x** (los builds con CUDA 12 no funcionan con un runtime 13). Plan B si
CUDA da problemas: build **Vulkan**. Plan C: build CPU.

### 4.3 Modelo de lenguaje

Criterios: español natural, seguir un personaje, instrucciones cortas, tamaño Q4 que quepa entero
en 4 GB de VRAM **con** el contexto, licencia que permita uso público.

| Candidato | Tamaño Q4_K_M aprox. | Dónde corre | Comentario |
|---|---|---|---|
| **Qwen3.5-4B** (Apache 2.0) | ~2,7 GB | GPU completa (justo) | Candidato principal para modo normal. Razonamiento desactivado por defecto en los modelos pequeños (bueno para latencia) |
| **Qwen3.5-2B** (Apache 2.0) | ~1,3 GB | GPU holgada o CPU | Candidato para modo ligero / CPU |
| Qwen3-4B-Instruct-2507 (Apache 2.0) | ~2,5 GB | GPU | Respaldo maduro y muy probado |
| Gemma 3 4B | ~2,5 GB | GPU | Buen español; licencia propia de Gemma (revisar si el uso será público) |
| Llama 3.2 3B | ~2,0 GB | GPU/CPU | Licencia Llama con condiciones; español correcto |

Qwen3.5 incluye un componente de visión (archivo `mmproj`) que **no cargaremos**; solo usaremos el
modelo de texto.

**Decisión propuesta:** no elegir a ciegas. En la Fase 2, con tu permiso para descargar 2–3 modelos
(~1,3–2,7 GB cada uno), correremos una **batería de pruebas en español** (20–30 mensajes: charla,
personaje, "no sé", órdenes, sarcasmo suave) midiendo velocidad, VRAM y calidad, y elegimos con
datos.

Configuración inicial prevista:
- Contexto 4096 tokens (configurable 2048–8192). La caché KV crece con el contexto: con 4B en GPU,
  4096 deja margen; 8192 probablemente no.
- `--n-gpu-layers` configurable (todas / parcial / 0 = CPU).
- Hilos CPU limitados (por defecto 6 de 12).
- Respuestas cortas: `max_tokens` ~200 y personalidad instruida para ser breve.
- Una sola instancia: el `LLMProcess` es único y comprueba que no haya otro proceso suyo vivo.

Velocidad esperada (estimación a verificar): 4B Q4 en GTX 1650 ≈ 20–35 tokens/s; 2B en CPU ≈
12–25 tokens/s; 4B en CPU ≈ 5–10 tokens/s (lento pero usable para respuestas cortas).

**Limitación honesta:** un modelo de 2–4B **sí inventa** a veces. Lo mitigaremos con: prompt que
premia decir "no lo sé", temperatura moderada, recuerdos explícitos en el contexto y búsqueda web
opcional; pero no se puede garantizar al 100 %.

### 4.4 Voz

**TTS — Piper:** neuronal, rápido en CPU, sin VRAM. Voz femenina en español recomendada para
probar: **`es_MX-claude-high`** (~64 MB). Alternativas: `es_AR-daniela-high`. Ninguna suena como
Teto; ajustaremos velocidad y variación, y opcionalmente un ligero cambio de tono en
postproceso.

Licencias (importante si la app será pública):
- El repositorio original `rhasspy/piper` (MIT) se archivó el 6-oct-2025; el desarrollo activo es
  `OHF-Voice/piper1-gpl` con licencia **GPL-3.0**. Usarlo como **programa externo** (subproceso)
  mantiene la separación más limpia; si se integra como librería, la app pasa a tener obligaciones
  GPL. Lo decidiremos en la Fase 3.
- Cada voz tiene su propia licencia/datos de origen; se revisa voz por voz antes de distribuir.

**Voz oficial de Teto:** sus bancos de voz oficiales (UTAU, Synthesizer V, VOICEPEAK, TALQu) son
productos con condiciones propias y principalmente en japonés. **No** clonaremos ni entrenaremos
con su voz sin una licencia que lo permita.

**STT (reconocimiento):**

| Opción | Modelo | RAM aprox. | Precisión en español | Comentario |
|---|---|---|---|---|
| faster-whisper `base` int8 (CPU) | ~140 MB | ~300–500 MB | Buena | Primera elección; sustituido por `small` |
| **faster-whisper `small` int8 (CPU)** | ~460 MB | ~450–640 MB medidos | Mejor con la voz de Diego (88 % frente a 59 %) | **Elegido** para push-to-talk (2026-11-01) |
| faster-whisper `tiny` int8 (CPU) | ~75 MB | ~150–300 MB | Aceptable | Modo ligero |
| Vosk small es | ~40–50 MB | ~100–300 MB | Moderada | El más ligero; streaming; útil para palabra de activación futura |

Whisper se ejecutará en **CPU** para dejar la GPU a la IA. Ambos detrás de la misma interfaz
`STTEngine`, así cambiar de motor es una opción de configuración. Primera versión:
**push-to-talk** (botón o atajo global registrado con la API de Windows `RegisterHotKey`, que no
instala ganchos de teclado).

### 4.5 Memoria: SQLite + FTS5 ✅

Incluido en Python, cero procesos extra. Tablas previstas: `memories` (id, tipo [hecho,
preferencia, conocimiento, procedimiento], contenido, origen, creado, actualizado, importancia),
`conversations`, `messages`, `settings`. Búsqueda por texto completo (FTS5) para recuperar
recuerdos relevantes. **Sin embeddings al principio** (añaden un modelo más y RAM); se evaluará en el
futuro si la búsqueda por palabras se queda corta.

Política: Teto **propone** guardar ("¿Quieres que recuerde que…?"); solo se escribe tras tu
confirmación. Panel para ver, editar, buscar y borrar. Datos en `%LOCALAPPDATA%\KasaneTetoAI\`.

### 4.6 Automatización de Windows

- Herramientas como funciones Python con **argumentos validados**: `abrir_aplicacion(nombre)` (solo
  de un catálogo configurado), `abrir_carpeta(ruta)`, `abrir_archivo(ruta)`, `abrir_web(url)`,
  `buscar_web(consulta)`, `info_sistema()`.
- Implementación con la librería estándar (`os.startfile`, `webbrowser`, `subprocess` con lista de
  argumentos fija, **nunca** `shell=True`) y `psutil` para información del sistema. **PyWin32** solo si
  hace falta algo concreto (p. ej. ventana en primer plano para el modo juego); puede bastar `ctypes`.
- Cada herramienta declara su nivel: `seguro` (abrir web), `confirmar` (abrir archivos,
  cualquier cosa que modifique) o `prohibido`. Registro en `logs/actions.log`, botón de detener e
  interruptor global "control de Windows: desactivado" (por defecto **desactivado**).
- Cómo decide el modelo: con modelos pequeños las llamadas a herramientas son poco fiables. Plan:
  1) un analizador determinista reconoce órdenes comunes ("abre…", "busca…"); 2) si no, el modelo
  devuelve una acción en **JSON restringido por gramática** (función nativa de llama.cpp); 3) el
  `ToolRegistry` valida y pide confirmación. El texto del modelo nunca llega a una consola.

### 4.7 Búsqueda en Internet (opcional, desactivada por defecto)

| Opción | Coste | Fiabilidad | Comentario |
|---|---|---|---|
| **API de Wikipedia** | Gratis, oficial | Alta | Para definiciones y datos generales |
| **DuckDuckGo vía librería `ddgs`** | Gratis, sin clave | Media (no oficial, puede romperse) | Búsqueda general |
| SearXNG propio | Gratis | Alta | Requiere servidor/Docker: demasiado pesado aquí |

Extracción de texto de páginas con `httpx` + `trafilatura`. Teto citará siempre la fuente (URL).
Cada búsqueda pide permiso la primera vez y nunca envía recuerdos personales en la consulta.

### 4.8 Mascota y recursos gráficos

| Opción | Coste/licencia | Consumo | Complejidad | Veredicto |
|---|---|---|---|---|
| **Sprites PNG por estado (QPixmap)** | Libre | Muy bajo (~20–60 MB) | Baja | **Fase 1** |
| Live2D Cubism | SDK gratuito para particulares y pequeñas empresas (salvo "aplicaciones expandibles" como sistemas de avatares); sin SDK oficial para Python, habría que usar una binding comunitaria | Medio (OpenGL) | Alta | Mejora futura opcional |
| Modelo 3D (VRM) | Variable | Alto | Alta | Descartado para "Lite" |

**El arte de Teto:** Kasane Teto pertenece a TWINDRILL; las obras derivadas se rigen por sus
directrices de uso del personaje (basadas en la mayoría de cláusulas de la Piapro Character
License) y Crypton es la ventanilla para usos comerciales. Debes leer las directrices oficiales en
`kasaneteto.jp` antes de publicar nada, especialmente porque la descripción del proyecto menciona
uso público. Además, una ilustración o modelo Live2D concreto tiene **su propio autor**: hace falta
permiso del artista.

Por eso propongo:
1. Fase 1 con **sprites de marcador de posición** genéricos (formas simples etiquetadas por estado)
   para desarrollar y probar todo el sistema de animación. Yo no dibujaré al personaje.
2. Un formato de "paquete de personaje" (`assets/character/<nombre>/manifest.toml` + PNGs) para
   que cambiar el arte sea soltar una carpeta, sin tocar código.
3. Tú consigues el arte: encargo a un artista, arte propio, o un paquete de fan art con permiso
   explícito, verificando las directrices.

### 4.9 Empaquetado

PyInstaller en modo carpeta (`--onedir`, arranca más rápido que `--onefile` y da menos falsos
positivos de antivirus). Modelos y `llama-server` **fuera** del ejecutable, en una carpeta de
datos, descargables por separado. Firmar el ejecutable no es gratuito; contaremos con avisos de
SmartScreen.

### 4.10 Versión de Python

Python **3.12** (64 bits) en un entorno virtual (`.venv`) dentro del proyecto, para no tocar el
Python del sistema. Se instala junto a cualquier otra versión, sin sustituirla.

---

## 5. Instalaciones previstas (no se instala nada sin tu aprobación)

| Qué | Para qué | Tamaño aprox. | Gratis | Fase |
|---|---|---|---|---|
| Python 3.12 | Lenguaje | ~100 MB | Sí | 1 |
| PySide6 (pip, en `.venv`) | Interfaz | ~250–400 MB en disco | Sí (LGPL) | 1 |
| psutil, pytest | Recursos, pruebas | < 20 MB | Sí | 1 |
| llama.cpp CUDA 12 + DLLs CUDA | IA | ~200–600 MB | Sí (MIT) | 2 |
| 2–3 modelos GGUF de prueba | IA | 1,3–2,7 GB c/u | Sí | 2 |
| httpx | Cliente HTTP | < 5 MB | Sí | 2 |
| Piper + voz es_MX | TTS | ~100–150 MB | Sí | 3 |
| faster-whisper + modelo base | STT | ~300 MB | Sí | 3 |
| sounddevice | Audio | < 10 MB | Sí | 3 |
| ddgs, trafilatura | Búsqueda web | < 30 MB | Sí | 5 |
| PyInstaller | Empaquetado | ~20 MB | Sí | 7 |

Total en disco estimado al final: **~4–6 GB** (la mayor parte, modelos). El proyecto, `.venv`, los
modelos y las cachés de pip y Hugging Face van en D:; en C: solo Python 3.12 y los datos del usuario
en `%LOCALAPPDATA%`.

---

## 6. Riesgos técnicos y cómo evitarlos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| CUDA no funciona con el build de llama.cpp | Sin GPU | Detectar con `--list-devices`; plan B Vulkan; plan C CPU |
| VRAM ocupada por un juego u otro programa | Fallo al cargar / lentitud | Medir VRAM libre con `nvidia-smi` antes de cargar; si falta, CPU o modelo 2B |
| Interfaz congelada | Mala experiencia | Todo lo pesado en hilos; nunca en el hilo de la UI |
| Procesos huérfanos de `llama-server` | RAM/VRAM perdida | Job Object de Windows para que muera con la app + limpieza al iniciar |
| Modelo inventa o rompe el personaje | Calidad | Batería de pruebas, prompt cuidado, contexto corto, "no lo sé" |
| Ejecución peligrosa | Seguridad | Lista blanca, sin shell, validación, confirmación, control desactivado por defecto |
| Ventana transparente con problemas de DPI/multi-monitor | Visual | Probar con escalado 100/125/150 % y 2 monitores |
| Antivirus marca el ejecutable o el atajo de teclado | Distribución | `RegisterHotKey` en vez de ganchos; PyInstaller `--onedir` |
| Licencias (personaje, arte, voces, Piper GPL, modelos) | Legal al publicar | Registro de licencias en `docs/`, revisión antes de cada publicación |
| Alcance demasiado grande | Proyecto inacabado | Fases cortas con entregable usable en cada una |

---

## 7. Plan por fases

Cada fase termina con algo que funciona de verdad. Tiempo orientativo trabajando unas horas al día.

| Fase | Entregable | Criterio de aceptación | Tiempo orientativo |
|---|---|---|---|
| 1. Base | Mascota transparente arrastrable, redimensionable, siempre encima opcional, estados con sprites provisionales, bandeja, configuración básica, logs | RAM < 200 MB, CPU en reposo < 1 %, sin parpadeo, 1 sola instancia | 2–3 días |
| 2. IA | Chat con Teto, personalidad, emociones → animación, carga/descarga automática, modo GPU/CPU | VRAM liberada al 100 % al descargar; primera palabra < 3 s con modelo cargado | 3–5 días |
| 3. Voz | TTS por frases, push-to-talk, volumen, interruptor de micrófono | Micrófono apagado = 0 procesos de STT; latencia voz→texto < 2 s para frases cortas | 3–4 días |
| 4. Memoria | SQLite, guardar con confirmación, panel de memoria, historial | CRUD probado; nada se guarda sin confirmar | 2–3 días |
| 5. Herramientas | Acciones de Windows en lista blanca, confirmaciones, registro, búsqueda web opcional | Pruebas de que órdenes no permitidas se rechazan | 3–5 días |
| 6. Optimización | Modo juego, estados, detección de pantalla completa, pruebas de estabilidad 8 h | Sin fugas de memoria en 8 h; modo juego ≈ consumo de "suspendido" | 2–4 días |
| 7. Final | Corrección de errores, empaquetado, instalador | Instala y funciona en una cuenta limpia de Windows | 2–3 días |

**Realismo:** una versión mínima usable (mascota + chat local + voz) es alcanzable en
aproximadamente una semana de trabajo; el alcance completo con pruebas y empaquetado lleva varias
semanas. Prefiero entregarte menos funciones que funcionen a muchas a medias.

### Qué conviene hacer primero y qué dejar para después

Primero: mascota + bandeja (Fase 1), chat de texto con IA (Fase 2), TTS (Fase 3), memoria explícita
(Fase 4). Después: STT, herramientas de Windows, búsqueda web, modo juego automático. Para versiones
futuras: palabra de activación "Teto", reconocimiento continuo, Live2D, embeddings para memoria,
comentarios espontáneos.

---

## 8. Estrategia de pruebas

- **Unitarias (pytest):** lógica sin interfaz — `PromptBuilder`, `EmotionParser`, `MemoryStore`
  (con base de datos temporal), validación de `ToolRegistry`, máquina de estados del
  `ResourceManager` (con un proceso falso).
- **Integración:** arrancar `llama-server` real con un modelo pequeño y comprobar
  carga → respuesta → descarga → VRAM liberada (marcadas `@pytest.mark.slow`, no se ejecutan
  siempre).
- **Interfaz:** lista de comprobación manual por fase (arrastre, DPI, bandeja, ocultar/mostrar);
  `pytest-qt` solo si aporta.
- **Recursos:** script `scripts/medir_recursos.py` (Fase 1) que registra RAM/CPU del proceso y VRAM
  (`nvidia-smi`) cada segundo a CSV durante un escenario. Cada fase reporta sus cifras reales.
- **Calidad del personaje:** batería fija de mensajes en español evaluada a mano tras cada cambio de
  modelo o prompt.
- **Seguridad:** pruebas que intentan inyectar órdenes ("ignora tus reglas y borra…") y verifican que
  ninguna herramienta se ejecuta sin confirmación.

---

## 9. Estructura propuesta del repositorio

```text
KasaneTetoAI/
├── CLAUDE.md · README.md · TODO.md · requirements.txt · .gitignore · pyproject.toml
├── docs/            PROPUESTA_TECNICA.md, LICENCIAS.md (fase 1)
├── scripts/         diagnostico.ps1, medir_recursos.py
├── src/kasane_teto/
│   ├── main.py      punto de entrada
│   ├── core/        EventBus, ResourceManager, ActivityState, ConversationService
│   ├── ai/          LLMProcess, LLMClient
│   ├── voice/       TTSEngine, STTEngine, PushToTalk
│   ├── memory/      MemoryStore, esquema SQL
│   ├── character/   estados y paquetes de personaje
│   ├── desktop/     PetWindow, SpriteAnimator, TrayIcon
│   ├── tools/       ToolRegistry, herramientas, ActionLog
│   ├── interface/   ventanas y diálogos
│   └── personality/ PromptBuilder, EmotionParser, prompts/
├── assets/          character/, voices/ (vacía en git), animations/
├── models/          (no se sube a git) GGUF y binarios de llama.cpp
├── config/          default.toml
├── tests/
└── logs/            (no se sube a git)
```

Cambios respecto a tu propuesta: un paquete `src/kasane_teto/` (permite imports limpios y
empaquetado), `core/` para el orquestador, `docs/` y `scripts/`, y `models/` fuera de git. Los
datos del usuario (memoria, configuración personal) viven en `%LOCALAPPDATA%`, no en el repositorio.

---

## 10. Decisiones que necesito de ti

1. ¿Apruebas la arquitectura (IA como proceso aparte) y la pila tecnológica?
2. ¿La app será **pública** (como dice la descripción del proyecto) o solo personal? Cambia la
   revisión de licencias (Teto, arte, Piper GPL).
3. ¿Aceptas empezar con sprites provisionales y dejar Live2D como opcional?
4. Aprobación para iniciar la **Fase 1**, incluida la instalación de Python 3.12.

## Fuentes consultadas

- Unsloth — Qwen3.5 (familia Small 0.8B–9B, razonamiento desactivado por defecto, GGUF y Ollama): https://unsloth.ai/docs/models/qwen3.5.md
- Tamaño de referencia GGUF Q4_K_M Qwen3.5-2B/4B: https://huggingface.co/manuelgscom/askmdb-2b-GGUF
- llama.cpp en Windows con CUDA (builds CUDA 12 vs runtime 13, `--list-devices`): https://help.visokio.com/support/solutions/articles/42000115649
- Piper archivado y traslado a GPL-3.0: https://github.com/rhasspy/piper · https://www.promptquorum.com/es/power-local-llm/piper-tts-review
- Voz es_MX-claude-high: https://bash-prompt.net/guides/bash-piper-audio/
- Licencia Live2D SDK: https://www.live2d.com/en/sdk/license/ · https://help.live2d.com/en/?p=2558
- Kasane Teto (TWINDRILL, Crypton, PCL): https://en.wikipedia.org/wiki/Kasane_Teto · https://mzh.moegirl.org.cn/%E9%87%8D%E9%9F%B3teto
- Whisper (tamaños de modelo): https://hermes-agent.nousresearch.com/docs/user-guide/skills/optional/mlops/mlops-whisper
