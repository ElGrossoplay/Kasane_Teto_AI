# Kasane Teto AI Lite

Asistente virtual de escritorio para Windows 11, inspirada en Kasane Teto: una mascota animada
que vive en tu escritorio, conversa en español con una IA que corre **en tu propio equipo**, puede
hablar y escucharte, recuerda lo que tú le autorices y realiza acciones sencillas de Windows bajo
tu control.

> **Estado:** Fases 1 a 7 implementadas, a falta de la prueba manual de Diego. Funcionan la mascota
> (sprites o Live2D), el chat con IA local, la voz, los recuerdos, la búsqueda en Internet, las
> acciones de Windows, el modo juego y el ejecutable. El progreso está en [`TODO.md`](TODO.md) y el
> diseño en [`docs/PROPUESTA_TECNICA.md`](docs/PROPUESTA_TECNICA.md).

## Principios

1. Estabilidad. 2. Bajo consumo. 3. Funcionamiento real. 4. Privacidad y seguridad.
5. Modularidad. 6. Experiencia. 7. Ampliación futura.

- Funciona sin Internet y sin APIs de pago.
- La IA solo ocupa memoria mientras la usas; se descarga sola cuando está inactiva.
- Nunca ejecuta comandos libres: solo acciones de una lista permitida, con confirmación.
- Tus datos se quedan en tu equipo.

## Funciones previstas

| Función | Fase | Estado |
|---|---|---|
| Mascota transparente, arrastrable, bandeja del sistema | 1 | Hecho |
| Chat con IA local y personalidad de Teto | 2 | Hecho |
| Voz (TTS) y push-to-talk (STT) | 3 | Hecho |
| Memoria persistente con panel de administración | 4 | Hecho |
| Búsqueda opcional en VocaDB, Wikipedia y otras fuentes | 5 | Hecho |
| Acciones de Windows controladas | 5 | Hecho |
| Modo juego y estados de consumo | 6 | Hecho |
| Mascota Live2D con un modelo propio | 6 | Hecho |
| Ejecutable y accesos directos | 7 | Hecho |

## Requisitos

- Windows 11 de 64 bits.
- 16 GB de RAM recomendados (funciona en modo ligero con menos).
- GPU NVIDIA con 4 GB de VRAM opcional (sin ella se usa la CPU, más lento).
- ~4–6 GB de disco (sobre todo modelos de IA).

## Instalación para desarrollo

```powershell
git clone https://github.com/ElGrossoplay/Kasane_Teto_AI.git
cd Kasane_Teto_AI
py -V:3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe ejecutar.pyw
```

Para el chat hacen falta, fuera de git, los binarios de llama.cpp en `models/llama/` y los GGUF
indicados en `config/default.toml` en `models/gguf/`. La voz necesita Piper y sus voces en
`models/piper/`, y faster-whisper y su modelo en `models/whisper/`, cada uno con su propio `venv`.

Pruebas: `.\.venv\Scripts\python.exe -m pytest` (con modelos reales, añade `-m slow`). Medir consumo:
`.\.venv\Scripts\python.exe scripts\medir_recursos.py --segundos 60`.

Uso de la mascota: arrastrar con el botón izquierdo, rueda del ratón para cambiar el tamaño y clic
derecho (o el icono de la bandeja) para el menú. Un clic la hace reaccionar, el doble clic abre el
chat y el botón central empieza o termina de escuchar. Atajos desde cualquier ventana: `Ctrl+Alt+C`
abre el chat, `Ctrl+Alt+T` escucha y `Ctrl+Alt+H` muestra u oculta a Teto (en modo juego se sueltan).
Lo que dice aparece en un bocadillo sobre ella, que se puede quitar en Configuración.

La búsqueda en Internet viene apagada y se activa en Configuración, con dos interruptores. La de
música consulta [VocaDB](https://vocadb.net). La general responde "¿quién es Messi?" o "¿qué es la
fotosíntesis?" con Wikipedia, "¿qué significa efímero?" con Wikcionario, "¿qué tiempo hace en
Madrid?" con Open-Meteo, "¿cuánto son 20 dólares en euros?" con Frankfurter, "háblame del anime
Frieren" con AniList y "el libro Cien años de soledad" con Open Library. Solo envía lo que buscas,
nunca la conversación ni los recuerdos, y cita la fuente en el chat.

Memoria: di "recuerda que…" y confirma con los botones o diciendo "sí". Nada se guarda sin tu
confirmación. En el menú, "Memoria…" permite ver, editar y borrar lo guardado, todo en tu equipo. El
historial de conversaciones viene apagado y se activa en Configuración.

Control de Windows: viene apagado y se activa en Configuración. Teto encuentra las aplicaciones del
menú Inicio, salvo consolas y herramientas del sistema; las demás se añaden en Configuración. Di
"abre Discord", "minimiza Discord", "cierra el navegador", "maximiza esta ventana",
"abre la carpeta de descargas", "abre YouTube", "busca recetas en Internet" o "¿qué hora es?". Nunca
interactúa con juegos. Si prefieres que pregunte antes de actuar, actívalo en Configuración. Lo que
hace queda en `logs/actions.log`.

Con el control activo también puedes decir "mira mi pantalla" (nunca con un juego abierto; la imagen
no se guarda ni sale del equipo), "¿qué tengo abierto?", "escribe un poema en el bloc de notas" o
"crea una presentación sobre gatos". Los archivos se crean en `Documentos\Teto`. Los comentarios por
su cuenta se activan aparte en Configuración.

Discord: con "Discord y contactos…" en Configuración y una aplicación propia del portal de Discord,
puedes decir "entra al canal General de Minecraft" o "sal del canal". Usa su sistema oficial y las
claves quedan cifradas en tu equipo.

Si apuntas a tus amigos en esa ventana con el ID del canal de su chat, puedes decir "abre el chat de
Pablo" o "dile a Pablo que llego tarde". En el segundo caso Teto redacta el mensaje, abre el chat y lo
copia: tú lo pegas con Ctrl+V y pulsas Enter. Teto nunca envía mensajes por su cuenta.

Modo juego: Teto lo activa sola cuando ve un juego en primer plano (solo lee el título de la
ventana) o a mano desde la bandeja. Libera la GPU, apaga el oído y el atajo, se queda quieta y deja
de estar encima del juego. Desde la bandeja también se puede suspender: descarga todo hasta que le
hables.

Live2D: en Configuración, "Modelo Live2D" elige el archivo `.model3.json` y el personaje "live2d" lo
activa. El modelo se lee desde su carpeta, no se copia ni se sube al repositorio. Cambia de
expresión con las emociones, mueve la boca al hablar y sigue el ratón con la mirada.

## Ejecutable

```powershell
.\.venv\Scripts\python.exe scripts\empaquetar.py      # crea dist\KasaneTetoAI\KasaneTetoAI.exe
.\.venv\Scripts\python.exe scripts\crear_accesos.py   # menú Inicio y escritorio (--quitar los borra)
dist\KasaneTetoAI\KasaneTetoAI.exe --diagnostico      # informe en %LOCALAPPDATA%\KasaneTetoAI
```

Los modelos no van dentro del ejecutable: los busca en la carpeta `models` del proyecto.

## Diagnóstico del equipo

Script de solo lectura que muestra CPU, RAM, GPU/VRAM, Python y disco sin modificar nada:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\diagnostico.ps1
```

## Estructura

```text
src/kasane_teto/   código (core, ai, voice, memory, character, desktop, tools, interface, personality)
assets/            arte y animaciones (paquetes de personaje)
config/            configuración por defecto
docs/              diseño, decisiones y licencias
scripts/           utilidades de diagnóstico y medición
tests/             pruebas automáticas
models/, logs/     no se suben a git
```

## Aviso sobre el personaje

Kasane Teto es un personaje de TWINDRILL. Este es un proyecto de fans no oficial. El uso del
personaje debe seguir sus directrices oficiales (kasaneteto.jp). El arte y las voces de terceros
se usan solo con licencia o permiso de sus autores; ver `docs/LICENCIAS.md`.

## Licencia

Sin licencia por ahora: el código es visible, pero todos los derechos quedan reservados. Las
licencias de los componentes están en [`docs/LICENCIAS.md`](docs/LICENCIAS.md).
