# Licencias de recursos de terceros

Registro de cada componente y recurso externo. La app es de uso personal; distribuirla exigiría
revisar esta lista completa. Versiones activas en `requirements.txt`.

| Recurso | Uso | Licencia | Fase |
|---|---|---|---|
| Python 3.12 | Lenguaje | PSF-2.0 | 1 |
| PySide6-Essentials y shiboken6 (Qt) | Interfaz | LGPL-3.0 | 1 |
| psutil | Medición de recursos | BSD-3-Clause | 1 |
| pytest | Pruebas (solo desarrollo) | MIT | 1 |
| llama.cpp (`llama-server`, build b12024) | Ejecutar la IA | MIT | 2 |
| Librerías CUDA 12.4 de NVIDIA (incluidas en el paquete de llama.cpp) | Aceleración por GPU | Licencia de NVIDIA: revisar antes de distribuir | 2 |
| Qwen3.5-4B y Qwen3.5-2B (GGUF de unsloth) | Modelos de lenguaje | Apache-2.0 | 2 |
| Qwen3-4B-Instruct-2507 (GGUF de unsloth) | Modelo de respaldo | Apache-2.0 | 2 |
| httpx, httpcore, idna | Conexión local con la IA | BSD-3-Clause | 2 |
| anyio, h11 | Dependencias de httpx | MIT | 2 |
| certifi | Dependencia de httpx | MPL-2.0 | 2 |

## Recursos propios

- `assets/character/provisional/`: formas genéricas creadas por el proyecto con
  `scripts/generar_sprites_provisionales.py`. No representan al personaje.

## Personaje

Kasane Teto pertenece a TWINDRILL. El repositorio no incluye arte, voz ni modelos del personaje.
Cualquier paquete de personaje con arte de terceros se guarda solo en local y requiere el permiso de
su autor.
