# Kasane Teto AI Lite

Asistente virtual de escritorio para Windows 11, inspirada en Kasane Teto: una mascota animada
que vive en tu escritorio, conversa en español con una IA que corre **en tu propio equipo**, puede
hablar y escucharte, recuerda lo que tú le autorices y realiza acciones sencillas de Windows bajo
tu control.

> **Estado:** planificación. Todavía no hay código ejecutable. El progreso está en [`TODO.md`](TODO.md)
> y el diseño en [`docs/PROPUESTA_TECNICA.md`](docs/PROPUESTA_TECNICA.md).

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
| Mascota transparente, arrastrable, bandeja del sistema | 1 | Pendiente |
| Chat con IA local y personalidad de Teto | 2 | Pendiente |
| Voz (TTS) y push-to-talk (STT) | 3 | Pendiente |
| Memoria persistente con panel de administración | 4 | Pendiente |
| Acciones de Windows controladas y búsqueda web opcional | 5 | Pendiente |
| Modo juego y estados de consumo | 6 | Pendiente |
| Instalador para Windows | 7 | Pendiente |

## Requisitos

- Windows 11 de 64 bits.
- 16 GB de RAM recomendados (funciona en modo ligero con menos).
- GPU NVIDIA con 4 GB de VRAM opcional (sin ella se usa la CPU, más lento).
- ~4–6 GB de disco (sobre todo modelos de IA).

## Instalación para desarrollo

_Se completará en la Fase 1, cuando haya código que instalar._ Resumen previsto:

```powershell
git clone <repositorio>
cd KasaneTetoAI
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m kasane_teto
```

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

Por decidir (depende de si la app será pública y de las licencias de los componentes, por ejemplo
Piper GPL-3.0).
