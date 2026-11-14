"""Movimiento corporal de la mascota, sin depender del modelo ni de Qt.

Calcula en cada fotograma cuánto gira la cabeza, se inclina el cuerpo o se abren los brazos, en
canales normalizados de -1 a 1. Quien dibuja (Live2D) traduce esos canales a los parámetros del
modelo; el pelo, la ropa y el resto del cuerpo los mueve después la física del propio modelo.

Capas, de abajo arriba: postura del estado, balanceo continuo, mirada al ratón, gestos de una vez
(saltito, negar, estirarse…), ritmo al hablar e inercia al arrastrarla.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from kasane_teto.character.states import PetState

CHANNELS = (
    "head_x",  # girar la cabeza: + hacia la derecha de la pantalla
    "head_y",  # + hacia arriba
    "head_z",  # ladear: arrastra hombros y caderas
    "lean",  # 0 a 1, acercarse a la pantalla agachándose un poco
    "shift",  # desplazar el peso a un lado
    "eye_x",
    "eye_y",
    "smile",  # -1 triste, + sonrisa
    "brows",  # - fruncidas, + levantadas
    "eyes_closed",  # 0 a 1
    "arm_r",
    "forearm_r",
    "arm_l",
    "forearm_l",
    "foot",  # sacar un pie
    "rise",  # ponerse de puntillas
)

Pose = dict[str, float]
Keyframes = tuple[tuple[float, Pose], ...]


@dataclass(frozen=True)
class Posture:
    """Cómo se planta en un estado: pose base y carácter del balanceo."""

    pose: Pose = field(default_factory=dict)
    sway: float = 1.0  # amplitud del balanceo
    tempo: float = 1.0  # velocidad del balanceo
    look: float = 1.0  # cuánto sigue al ratón


POSTURES: dict[PetState, Posture] = {
    PetState.IDLE: Posture(),
    PetState.LISTENING: Posture({"lean": 0.35, "head_z": 0.3, "brows": 0.4}, sway=0.5),
    PetState.THINKING: Posture(
        {"head_x": 0.3, "head_y": 0.35, "head_z": -0.35, "eye_x": 0.6, "eye_y": 0.7, "forearm_r": 0.6},
        sway=0.6,
        tempo=0.7,
        look=0.0,
    ),
    PetState.SPEAKING: Posture({"smile": 0.3}, sway=1.2, tempo=1.5, look=0.6),
    PetState.HAPPY: Posture(
        {"smile": 1.0, "brows": 0.4, "arm_r": 0.5, "arm_l": 0.5, "rise": 0.3}, sway=2.0, tempo=2.4
    ),
    PetState.SURPRISED: Posture(
        {"head_y": 0.4, "brows": 1.0, "rise": 0.6, "arm_r": 0.7, "arm_l": 0.7}, sway=0.4
    ),
    PetState.CONFUSED: Posture(
        {"head_z": 0.7, "head_x": -0.2, "brows": -0.3, "smile": -0.3}, sway=0.8, tempo=0.6, look=0.3
    ),
    PetState.ANGRY: Posture(
        {"head_y": -0.3, "brows": -1.0, "smile": -0.8, "lean": 0.2, "forearm_r": 0.5, "forearm_l": 0.5},
        sway=0.5,
        tempo=2.6,
    ),
    PetState.BORED: Posture(
        {"head_y": -0.4, "head_z": -0.35, "smile": -0.2}, sway=0.7, tempo=0.45, look=0.2
    ),
}

# Dormitando cuando nadie la usa: cabeza caída, ojos cerrados y respiración lenta.
DROWSY = Posture({"head_y": -0.55, "head_z": 0.25, "eyes_closed": 1.0}, sway=0.5, tempo=0.35, look=0.0)

_ARMS_OUT: Pose = {"arm_r": 1.0, "arm_l": 1.0, "forearm_r": 0.8, "forearm_l": 0.8}

# Gestos: fotogramas clave (segundos, pose) que se suman a la postura y acaban en cero.
GESTURES: dict[str, Keyframes] = {
    "nod": (
        (0.0, {}),
        (0.16, {"head_y": -0.55}),
        (0.34, {"head_y": 0.1}),
        (0.52, {"head_y": -0.45}),
        (0.75, {}),
    ),
    "shake": (
        (0.0, {}),
        (0.13, {"head_x": -0.55}),
        (0.32, {"head_x": 0.55}),
        (0.51, {"head_x": -0.45}),
        (0.7, {"head_x": 0.3}),
        (0.9, {}),
    ),
    "hop": (
        (0.0, {}),
        (0.14, {"lean": 0.5, "head_y": -0.3}),
        (0.32, {"rise": 1.0, "head_y": 0.45, **_ARMS_OUT}),
        (0.5, {"lean": 0.35, "head_y": -0.15}),
        (0.68, {"rise": 0.6, "head_y": 0.2, "arm_r": 0.5, "arm_l": 0.5}),
        (0.9, {}),
    ),
    "startle": (
        (0.0, {}),
        (0.09, {"rise": 1.0, "head_y": 0.6, "brows": 1.0, **_ARMS_OUT}),
        (0.4, {"rise": 0.5, "head_y": 0.3, "brows": 0.8, "arm_r": 0.5, "arm_l": 0.5}),
        (0.8, {}),
    ),
    "tilt": (
        (0.0, {}),
        (0.35, {"head_z": 0.8, "brows": 0.3}),
        (1.3, {"head_z": 0.8, "brows": 0.3}),
        (1.7, {}),
    ),
    "stretch": (
        (0.0, {}),
        (0.7, {"rise": 1.0, "head_y": 0.6, "eyes_closed": 1.0, "smile": 0.5, **_ARMS_OUT}),
        (1.7, {"rise": 1.0, "head_y": 0.5, "head_z": 0.25, "eyes_closed": 1.0, "smile": 0.5, **_ARMS_OUT}),
        (2.4, {}),
    ),
    "look_around": (
        (0.0, {}),
        (0.5, {"head_x": -0.75, "eye_x": -0.8, "head_z": -0.15}),
        (1.3, {"head_x": -0.75, "eye_x": -0.8, "head_z": -0.15}),
        (1.9, {"head_x": 0.75, "eye_x": 0.8, "head_z": 0.15}),
        (2.7, {"head_x": 0.75, "eye_x": 0.8, "head_z": 0.15}),
        (3.2, {}),
    ),
    "tap": (
        (0.0, {}),
        (0.2, {"foot": 1.0, "head_z": 0.25}),
        (0.4, {"foot": 0.2, "head_z": 0.25}),
        (0.6, {"foot": 1.0, "head_z": 0.25}),
        (0.8, {"foot": 0.2, "head_z": 0.25}),
        (1.0, {"foot": 1.0, "head_z": 0.25}),
        (1.3, {}),
    ),
    "peek": (
        (0.0, {}),
        (0.35, {"lean": 1.0, "brows": 0.5}),
        (1.2, {"lean": 1.0, "head_z": 0.3, "brows": 0.5}),
        (1.6, {}),
    ),
    "wave": (
        (0.0, {}),
        (0.25, {"arm_r": 1.0, "forearm_r": 1.0, "head_z": 0.3, "smile": 1.0, "rise": 0.4}),
        (0.45, {"arm_r": 1.0, "forearm_r": 0.1, "head_z": 0.3, "smile": 1.0, "rise": 0.4}),
        (0.65, {"arm_r": 1.0, "forearm_r": 1.0, "head_z": 0.3, "smile": 1.0, "rise": 0.4}),
        (0.85, {"arm_r": 1.0, "forearm_r": 0.1, "head_z": 0.3, "smile": 1.0, "rise": 0.4}),
        (1.05, {"arm_r": 1.0, "forearm_r": 1.0, "head_z": 0.3, "smile": 1.0, "rise": 0.4}),
        (1.45, {}),
    ),
    "stomp": (
        (0.0, {}),
        (0.12, {"foot": 1.0, "head_x": -0.4}),
        (0.26, {"lean": 0.4, "head_x": 0.4}),
        (0.4, {"foot": 1.0, "head_x": -0.3}),
        (0.54, {"lean": 0.4, "head_x": 0.3}),
        (0.8, {}),
    ),
}

# Gesto al entrar en un estado.
ENTRY_GESTURES: dict[PetState, str] = {
    PetState.HAPPY: "hop",
    PetState.SURPRISED: "startle",
    PetState.ANGRY: "stomp",
    PetState.LISTENING: "peek",
}
# Lo que hace por su cuenta cuando está tranquila.
IDLE_FIDGETS = ("look_around", "stretch", "tap", "tilt", "peek", "hop")
BORED_FIDGETS = ("stretch", "tap", "look_around")
POKE_GESTURES = ("startle", "hop", "tilt")
FIDGET_SECONDS = (9.0, 22.0)

CURSOR_REST_SECONDS = 4.0  # ratón quieto este tiempo: deja de mirarlo
DRAG_TILT = 0.9  # cuánto se ladea al arrastrarla, por alto de ventana y segundo
_SMOOTH_RATE = 7.0  # 1/s: rapidez con la que la postura alcanza su objetivo
_TWO_PI = 2 * math.pi


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def gesture_duration(name: str) -> float:
    return GESTURES[name][-1][0]


def gesture_pose(name: str, seconds: float) -> Pose:
    """Pose de un gesto en un instante, interpolando con suavidad entre fotogramas clave."""
    frames = GESTURES[name]
    if seconds <= frames[0][0] or seconds >= frames[-1][0]:
        return {}
    for (start, before), (end, after) in zip(frames, frames[1:], strict=False):
        if seconds <= end:
            mix = _ease((seconds - start) / (end - start))
            return {
                key: before.get(key, 0.0) * (1 - mix) + after.get(key, 0.0) * mix
                for key in before.keys() | after.keys()
            }
    return {}


class MotionDirector:
    """Decide la pose de cada fotograma. No dibuja ni lee nada del sistema: se le pasa todo."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._state = PetState.IDLE
        self._drowsy = False
        self._current: Pose = dict.fromkeys(CHANNELS, 0.0)
        self._phase = self._rng.uniform(0.0, 100.0)
        self._gesture: str | None = None
        self._gesture_time = 0.0
        self._next_fidget = self._rng.uniform(*FIDGET_SECONDS)
        self._cursor: tuple[float, float] | None = None
        self._cursor_still = CURSOR_REST_SECONDS
        self._look = 0.0
        self._drag = 0.0
        self._dragging = False

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def gesture(self) -> str | None:
        return self._gesture

    @property
    def lively(self) -> bool:
        """Hay movimiento rápido: conviene dibujar a toda velocidad."""
        return (
            self._gesture is not None
            or self._dragging
            or self._look > 0.05
            or self._state not in (PetState.IDLE, PetState.BORED, PetState.THINKING)
        )

    def set_state(self, state: PetState) -> None:
        if state is self._state:
            return
        self._state = state
        entry = ENTRY_GESTURES.get(state)
        if entry is not None:
            self.play(entry)

    def set_drowsy(self, drowsy: bool) -> None:
        """Dormita cuando nadie la usa; al despertar se estira."""
        if drowsy == self._drowsy:
            return
        self._drowsy = drowsy
        if not drowsy:
            self.play("stretch")

    def play(self, name: str) -> None:
        if name not in GESTURES:
            raise KeyError(name)
        self._gesture = name
        self._gesture_time = 0.0

    def poke(self) -> str:
        """Reacción a un clic."""
        name = self._rng.choice(POKE_GESTURES)
        self.play(name)
        return name

    def update(
        self,
        delta: float,
        cursor: tuple[float, float] | None = None,
        mouth: float = 0.0,
        drag_speed: float = 0.0,
    ) -> Pose:
        """Avanza `delta` segundos y devuelve la pose.

        `cursor` es la dirección al ratón desde la cabeza (-1 a 1 en cada eje, + derecha y arriba);
        `mouth`, la apertura de la boca al hablar; `drag_speed`, la velocidad horizontal al
        arrastrarla, en altos de ventana por segundo.
        """
        delta = max(0.0, min(delta, 0.25))
        posture = DROWSY if self._drowsy else POSTURES[self._state]
        self._phase += delta * posture.tempo
        target = dict.fromkeys(CHANNELS, 0.0)
        target.update(posture.pose)
        self._add_look(target, cursor, posture.look, delta)

        mix = 1 - math.exp(-delta * _SMOOTH_RATE)
        for key in CHANNELS:
            self._current[key] += (target[key] - self._current[key]) * mix
        pose = dict(self._current)

        self._add_sway(pose, posture.sway)
        if mouth > 0:
            pose["head_y"] += 0.16 * mouth - 0.05
            pose["head_z"] += 0.08 * math.sin(self._phase * 2.3)
        self._add_drag(pose, drag_speed, delta)
        self._add_gesture(pose, delta)
        for key in ("lean", "eyes_closed"):
            pose[key] = max(0.0, pose[key])
        return {key: max(-1.0, min(1.0, value)) for key, value in pose.items()}

    def _add_look(
        self, target: Pose, cursor: tuple[float, float] | None, weight: float, delta: float
    ) -> None:
        """Sigue al ratón mientras se mueve; si lleva un rato quieto, vuelve a lo suyo."""
        if cursor is None:
            self._cursor_still = CURSOR_REST_SECONDS
        elif self._cursor is None or math.dist(cursor, self._cursor) > 0.02:
            self._cursor_still = 0.0
        else:
            self._cursor_still += delta
        self._cursor = cursor
        wanted = weight if self._cursor_still < CURSOR_REST_SECONDS else 0.0
        self._look += (wanted - self._look) * (1 - math.exp(-delta * 3.0))
        if cursor is None or self._look < 0.01:
            return
        x, y = (max(-1.0, min(1.0, value)) for value in cursor)
        target["head_x"] += 0.6 * x * self._look
        target["head_y"] += 0.5 * y * self._look
        target["eye_x"] += x * self._look
        target["eye_y"] += y * self._look
        target["head_z"] += 0.2 * x * self._look

    def _add_sway(self, pose: Pose, amount: float) -> None:
        """Balanceo: senos de periodos que no encajan entre sí, para que no se note el bucle."""
        phase = self._phase
        pose["head_x"] += amount * (
            0.10 * math.sin(_TWO_PI * phase / 7.3) + 0.04 * math.sin(_TWO_PI * phase / 3.1 + 1.0)
        )
        pose["head_y"] += amount * 0.07 * math.sin(_TWO_PI * phase / 5.3 + 2.0)
        pose["head_z"] += amount * (
            0.15 * math.sin(_TWO_PI * phase / 4.1) + 0.06 * math.sin(_TWO_PI * phase / 9.7 + 0.5)
        )
        pose["shift"] += amount * 0.3 * math.sin(_TWO_PI * phase / 8.2)

    def _add_drag(self, pose: Pose, speed: float, delta: float) -> None:
        """Al arrastrarla cuelga hacia atrás del movimiento, con brazos y pie sueltos."""
        self._dragging = abs(speed) > 0.05
        wanted = max(-1.0, min(1.0, -speed * DRAG_TILT))
        self._drag += (wanted - self._drag) * (1 - math.exp(-delta * 9.0))
        if abs(self._drag) < 0.01:
            return
        strength = abs(self._drag)
        pose["head_z"] += self._drag
        pose["shift"] += self._drag
        pose["arm_r"] += 0.8 * strength
        pose["arm_l"] += 0.8 * strength
        pose["foot"] += 0.7 * strength

    def _add_gesture(self, pose: Pose, delta: float) -> None:
        if self._gesture is None:
            self._schedule_fidget(delta)
            return
        self._gesture_time += delta
        if self._gesture_time >= gesture_duration(self._gesture):
            self._gesture = None
            return
        for key, value in gesture_pose(self._gesture, self._gesture_time).items():
            pose[key] += value

    def _schedule_fidget(self, delta: float) -> None:
        if self._drowsy or self._state not in (PetState.IDLE, PetState.BORED):
            self._next_fidget = self._rng.uniform(*FIDGET_SECONDS)
            return
        self._next_fidget -= delta
        if self._next_fidget <= 0:
            options = BORED_FIDGETS if self._state is PetState.BORED else IDLE_FIDGETS
            self.play(self._rng.choice(options))
            self._next_fidget = self._rng.uniform(*FIDGET_SECONDS)
