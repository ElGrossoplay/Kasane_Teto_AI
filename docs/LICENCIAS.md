# Licencias de recursos de terceros

Registro de cada componente y recurso externo. La app es de uso personal; distribuirla exigiría
revisar esta lista completa. Versiones activas en `requirements.txt`.

| Recurso | Uso | Licencia | Fase |
|---|---|---|---|
| Python 3.12 | Lenguaje | PSF-2.0 | 1 |
| PySide6-Essentials y shiboken6 (Qt) | Interfaz | LGPL-3.0 | 1 |
| psutil | Medición de recursos | BSD-3-Clause | 1 |
| pytest | Pruebas (solo desarrollo) | MIT | 1 |
| PyInstaller 6.22.3 y pyinstaller-hooks-contrib | Empaquetado (solo desarrollo) | GPL-2.0-or-later con excepción que permite empaquetar cualquier programa; hooks-contrib GPL-2.0/Apache-2.0 | 7 |
| altgraph, pefile, pywin32-ctypes | Dependencias de PyInstaller | MIT, MIT, BSD-3-Clause | 7 |
| llama.cpp (`llama-server`, build b12024) | Ejecutar la IA | MIT | 2 |
| Librerías CUDA 12.4 de NVIDIA (incluidas en el paquete de llama.cpp) | Aceleración por GPU | Licencia de NVIDIA: revisar antes de distribuir | 2 |
| Qwen3.5-4B y Qwen3.5-2B (GGUF de unsloth) | Modelos de lenguaje | Apache-2.0 | 2 |
| Qwen3-4B-Instruct-2507 (GGUF de unsloth) | Modelo de respaldo | Apache-2.0 | 2 |
| Qwen3.5-4B mmproj-F16 (GGUF de unsloth) | Visión al mirar la pantalla | Apache-2.0 | 5 |
| python-pptx | Crear presentaciones | MIT | 5 |
| live2d-py 1.0.0 | Dibujar la mascota Live2D | MIT (biblioteca no oficial) | 6 |
| Live2D Cubism Core 5-r.5 (incluido en live2d-py) | Motor de Live2D | Live2D Proprietary Software License: gratuito para particulares; distribuir una app exigiría revisar la Cubism SDK Release License | 6 |
| PyOpenGL 3.1.10, numpy 2.5.4 | Dependencias de live2d-py | BSD-3-Clause y similares | 6 |
| lxml, XlsxWriter, typing-extensions, Pillow | Dependencias de python-pptx | BSD-3-Clause, BSD-2-Clause, PSF-2.0, MIT-CMU | 5 |
| httpx, httpcore, idna | Conexión local con la IA | BSD-3-Clause | 2 |
| anyio, h11 | Dependencias de httpx | MIT | 2 |
| certifi | Dependencia de httpx | MPL-2.0 | 2 |
| Piper 1.8.0 (`piper-tts`), en proceso y entorno propios | Síntesis de voz | GPL-3.0-or-later | 3 |
| `workers/piper_worker.py` | Usa la biblioteca de Piper | GPL-3.0-or-later | 3 |
| Voz es_MX-claude-high | Voz de Teto | Apache-2.0 | 3 |
| Voz es_MX-ald-medium | Voz alternativa | Unlicense | 3 |
| Voz es_AR-daniela-high | Voz alternativa | CC BY-SA 4.0 | 3 |
| faster-whisper 1.2.1, CTranslate2, onnxruntime | Reconocimiento de voz | MIT | 3 |
| Modelo faster-whisper-large-v3-turbo (conversión de mobiuslabsgmbh) | Reconocimiento de voz | MIT | 5 |
| Modelo faster-whisper-small | Respaldo más rápido, la app no lo usa por defecto | MIT | 3 |
| sounddevice | Audio | MIT | 3 |
| Wikipedia en español (API de MediaWiki) | Cultura general | CC BY-SA 4.0, con enlace al artículo en cada respuesta. Se usa un resumen, no el texto entero | 5 |
| Wikcionario en español | Significado de palabras | CC BY-SA 4.0, con enlace | 5 |
| Open-Meteo (geocodificación y previsión) | El tiempo | CC BY 4.0, con enlace a open-meteo.com; API gratuita solo para uso no comercial, menos de 10 000 consultas al día | 5 |
| Frankfurter | Tipos de cambio de bancos centrales | Gratuita y de código abierto, sin clave | 5 |
| AniList (API GraphQL) | Anime y manga | Gratuita para uso no comercial; prohíbe usarla como almacén o acumular datos (caché de un día) | 5 |
| Open Library | Autores de libros | Pide identificar la app en el User-Agent y no descargar en masa | 5 |
| Datos de VocaDB (API pública) | Búsqueda de artistas y canciones | Creative Commons Attribution, con enlace a VocaDB en cada respuesta. Sin letras, imágenes ni audio, que no cubre esa licencia | 5 |

## Recursos propios

- `assets/character/provisional/`: formas genéricas creadas por el proyecto con
  `scripts/generar_sprites_provisionales.py`. No representan al personaje.

- `assets/knowledge/`: fichas redactadas por el proyecto con datos contrastados, sobre todo en los
  artículos de Wikipedia de cada tema. El autor y la fecha de Senbonzakura vienen de
  [VocaDB](https://vocadb.net/S/8394). Contienen hechos, no letras ni textos copiados. Las
  reacciones son invención del proyecto.

## Personaje

Kasane Teto pertenece a TWINDRILL. El repositorio no incluye arte, voz ni modelos del personaje.
Cualquier paquete de personaje con arte de terceros se guarda solo en local y requiere el permiso de
su autor.

Modelo Live2D de Diego (ilustración de NaCl_chica, rigging de Missingperson04, con licencia de
TWINDRILL): gratuito para fans, sin uso comercial, sin revender, copiar ni redistribuir. La app lo
lee desde la carpeta donde lo tiene Diego y nunca lo copia al proyecto ni al repositorio. Solo guarda
texturas reducidas en `%LOCALAPPDATA%\KasaneTetoAI\live2d_cache`, para uso local. La marca de agua
se quita con la expresión que incluye el propio modelo para ello.
