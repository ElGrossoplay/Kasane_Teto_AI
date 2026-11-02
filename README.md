# Kasane Teto AI Lite

Asistente virtual de escritorio para Windows 11, inspirada en Kasane Teto: una mascota animada
que vive en tu escritorio, conversa en español con una IA que corre **en tu propio equipo**, puede
hablar y escucharte, recuerda lo que tú le autorices y realiza acciones sencillas de Windows bajo
tu control.

> **Estado:** Fases 1 a 5 completadas. Funcionan la mascota con sprites provisionales, el chat con IA
> local, la voz, los recuerdos, la búsqueda de música y las acciones de Windows. El progreso está en [`TODO.md`](TODO.md) y el diseño en
> [`docs/PROPUESTA_TECNICA.md`](docs/PROPUESTA_TECNICA.md).

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
| Búsqueda opcional de artistas y canciones en VocaDB | 5 | Hecho |
| Acciones de Windows controladas | 5 | Hecho |
| Modo juego y estados de consumo | 6 | Pendiente |
| Instalador para Windows | 7 | Pendiente |

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
derecho (o el icono de la bandeja) para el menú.

La búsqueda en Internet viene apagada y se activa en Configuración. Consulta
[VocaDB](https://vocadb.net), envía solo el nombre del artista o la canción y cita la fuente en el
chat. Sus datos están bajo licencia Creative Commons Attribution.

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

Discord: con "Conectar Discord…" en Configuración y una aplicación propia del portal de Discord,
puedes decir "entra al canal General de Minecraft" o "sal del canal". Usa su sistema oficial y las
claves quedan cifradas en tu equipo.

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
