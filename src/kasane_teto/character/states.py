"""Estados visuales de la mascota."""

from __future__ import annotations

from enum import Enum


class PetState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    HAPPY = "happy"
    SURPRISED = "surprised"
    CONFUSED = "confused"
    ANGRY = "angry"
    BORED = "bored"


STATE_LABELS: dict[PetState, str] = {
    PetState.IDLE: "Reposo",
    PetState.LISTENING: "Escuchando",
    PetState.THINKING: "Pensando",
    PetState.SPEAKING: "Hablando",
    PetState.HAPPY: "Feliz",
    PetState.SURPRISED: "Sorprendida",
    PetState.CONFUSED: "Confundida",
    PetState.ANGRY: "Enfadada",
    PetState.BORED: "Aburrida",
}
