"""Reconoce órdenes del usuario con reglas fijas. El texto del modelo nunca pasa por aquí."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

from kasane_teto.memory.knowledge import MIN_NAME_SIMILARITY, name_key, name_similarity

OPEN_APP = "app"
OPEN_FOLDER = "folder"
OPEN_FILE = "file"
OPEN_URL = "url"
CLOSE_APP = "close"
MINIMIZE_APP = "minimize"
RESTORE_APP = "restore"
MAXIMIZE_APP = "maximize"
WINDOW_KINDS = frozenset((CLOSE_APP, MINIMIZE_APP, RESTORE_APP, MAXIMIZE_APP))
THIS_WINDOW = "esta ventana"
LOOK_AT_SCREEN = "look"
WRITE_DOCUMENT = "write"
WEB_SEARCH = "search"
INFO = "info"

INFO_TIME = "hora"
INFO_DATE = "fecha"
INFO_MEMORY = "memoria"
INFO_CPU = "cpu"
INFO_DISK = "disco"
INFO_BATTERY = "bateria"

SAFE_FILE_TYPES = frozenset(
    ".txt .md .pdf .rtf .csv .doc .docx .xlsx .pptx .odt .ods .odp "
    ".png .jpg .jpeg .gif .webp .bmp .mp3 .wav".split()
)
# Tipos que ejecutan algo: se reconocen para poder rechazarlos, nunca para abrirlos.
UNSAFE_FILE_TYPES = frozenset(
    ".exe .bat .cmd .msi .ps1 .psm1 .vbs .vbe .js .jse .wsf .wsh .lnk .url .scr .pif .hta "
    ".reg .cpl .jar .py .pyw .dll .sys .docm .xlsm .pptm".split()
)
FOLDER_NAMES = {
    "documentos": "documentos",
    "descargas": "descargas",
    "imagenes": "imagenes",
    "imágenes": "imagenes",
    "fotos": "imagenes",
    "musica": "musica",
    "música": "musica",
    "videos": "videos",
    "vídeos": "videos",
    "escritorio": "escritorio",
}

_PREFIX = (
    r"^\W*(?:oye\W+)?(?:teto\W+)?(?:por\s+favor\W+)?"
    r"(?:puedes\s+|podr[ií]as\s+|quiero\s+que\s+|me\s+puedes\s+)?"
)
# Incluye lo que la voz deforma: "abré", "abra" y "sierra" por "cierra".
_OPEN = re.compile(
    _PREFIX + r"(?:[aá]br[eéa](?:me)?|abr[ií]r?|abras|inicia|iniciar|lanza|lanzar|ejecuta|ejecutar)"
    r"\W+(?P<target>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_WINDOW_ORDERS = (
    (CLOSE_APP, r"[cs]i[eé]rra(?:me)?|[cs]errar|[cs]ierres|apaga"),
    (MINIMIZE_APP, r"minimi[zs]a(?:me|r)?|minimices|esconde|oculta"),
    (RESTORE_APP, r"restaura(?:r|me)?|recupera(?:r|me)?|muestra(?:me)?"),
    (MAXIMIZE_APP, r"maximi[zs]a(?:me|r)?|maximices"),
)
_WINDOW = tuple(
    (kind, re.compile(_PREFIX + rf"(?:{verbs})(?:\W+(?P<target>.+))?$", re.IGNORECASE | re.DOTALL))
    for kind, verbs in _WINDOW_ORDERS
)
_LOOK = re.compile(
    r"\b(?:mira|m[ií]rame|ve|observa|analiza|revisa|describe|lee)\s+(?:a\s+)?(?:mi|la|esta)\s+pantalla\b"
    r"|\bqu[eé]\s+(?:ves|hay|sale|aparece)\s+en\s+(?:mi|la|esta)\s+pantalla\b"
    r"|\bqu[eé]\s+ves\b",
    re.IGNORECASE,
)
_ASKS_OPEN_THINGS = re.compile(
    r"\bqu[eé]\s+(?:tengo|hay)\s+abiert[oa]s?\b"
    r"|\bqu[eé]\s+(?:ventanas|programas|aplicaciones|apps)\s+(?:tengo|hay)\b"
    r"|\bqu[eé]\s+estoy\s+(?:viendo|haciendo|jugando|usando)\b"
    r"|\bqu[eé]\s+tengo\s+delante\b",
    re.IGNORECASE,
)
_DOCUMENT_WORDS = (
    (r"bloc\s+de\s+notas|notepad|archivo\s+de\s+texto|txt", "txt"),
    (r"(?:documento\s+de\s+)?word|documento", "docx"),
    (r"power\s*point|presentaci[oó]n|diapositivas", "pptx"),
)
_WRITE_IN = tuple(
    (
        kind,
        re.compile(
            _PREFIX + r"(?:escr[ií]b[ea]|escribir|redacta|anota|apunta|pon|crea|haz)(?:me)?\s+"
            rf"(?P<what>.+?)\s+en\s+(?:(?:un|una|el|la|mi)\s+)?(?:nuevo\s+)?(?:{words})\W*$",
            re.IGNORECASE | re.DOTALL,
        ),
    )
    for words, kind in _DOCUMENT_WORDS
)
_MAKE_DOCUMENT = tuple(
    (
        kind,
        re.compile(
            _PREFIX + r"(?:crea|haz|hazme|prepara|escribe|redacta)(?:me)?\s+(?:un|una)\s+(?:nuev[oa]\s+)?"
            rf"(?:{words})\s+(?:sobre|de|con|acerca\s+de)\s+(?P<what>.+?)\W*$",
            re.IGNORECASE | re.DOTALL,
        ),
    )
    for words, kind in _DOCUMENT_WORDS
)
_THIS_WINDOW = re.compile(
    r"^(?:(?:est[ae]|es[ae]|la|el)\s+)?(?:ventana|programa|aplicaci[oó]n|app)?(?:\s+actual)?$"
    r"|^esto$|^eso$",
    re.IGNORECASE,
)
_SEARCH = re.compile(
    _PREFIX + r"b[uú]sca(?:r|me)?\s+(?!en\b)(?P<target>.+?)"
    r"\s+en\s+(?:internet|google|el\s+navegador|la\s+web)\W*$",
    re.IGNORECASE | re.DOTALL,
)
_INFO = (
    (INFO_TIME, re.compile(r"\bqu[eé]\s+hora\s+es\b", re.IGNORECASE)),
    (INFO_DATE, re.compile(r"\bqu[eé]\s+(?:d[ií]a|fecha)\s+es(?:\s+hoy)?\b", re.IGNORECASE)),
    (
        INFO_MEMORY,
        re.compile(
            r"\bcu[aá]nta\s+(?:ram|memoria)\b|\buso\s+de\s+(?:la\s+)?(?:ram|memoria)\b"
            r"|\bc[oó]mo\s+va\s+la\s+(?:ram|memoria)\b",
            re.IGNORECASE,
        ),
    ),
    (
        INFO_CPU,
        re.compile(
            r"\buso\s+de\s+(?:la\s+|el\s+)?(?:cpu|procesador)\b"
            r"|\bc[oó]mo\s+va\s+(?:la\s+|el\s+)(?:cpu|procesador)\b",
            re.IGNORECASE,
        ),
    ),
    (
        INFO_DISK,
        re.compile(
            r"\bcu[aá]nto\s+(?:espacio|disco)\b|\bespacio\s+(?:libre|en\s+(?:el\s+)?disco)\b",
            re.IGNORECASE,
        ),
    ),
    (
        INFO_BATTERY,
        re.compile(
            r"\bcu[aá]nta\s+bater[ií]a\b|\bnivel\s+de\s+(?:la\s+)?bater[ií]a\b"
            r"|\bqu[eé]\s+tal\s+(?:va\s+)?la\s+bater[ií]a\b",
            re.IGNORECASE,
        ),
    ),
)
_FILE_WORDS = re.compile(
    r"^(?:(?:el|la|mi)\s+)?(?:archivo|fichero|documento|foto|imagen|pdf)\W+(?P<name>.+)$",
    re.IGNORECASE,
)
_FOLDER = re.compile(
    r"^(?:(?:la|mi|mis)\s+)?(?P<word>carpeta\s+)?(?:(?:de|del|mis)\s+)?(?:(?:el|la|las|los)\s+)?"
    r"(?P<name>\w+)$",
    re.IGNORECASE,
)
_IN_FOLDER = re.compile(
    r"\s+(?:en|de|dentro\s+de)\s+(?:(?:la\s+)?carpeta\s+(?:de\s+)?)?(?:(?:mis|el|la|las)\s+)?"
    r"(?P<folder>\w+)$",
    re.IGNORECASE,
)
_LEADING = re.compile(
    r"^(?:(?:el|la|los|las|mi|mis|un|una|esa|ese|programa|ventana|aplicaci[oó]n|app|de|del)\s+)+",
    re.IGNORECASE,
)
_TRAILING = re.compile(r"\s*,?\s*(?:por\s+favor|porfa)$", re.IGNORECASE)
# "Abre Discord y dime un chiste": la segunda parte no es el nombre de la aplicación.
_SECOND_ORDER = re.compile(
    r"\s*(?:,|\s+y)\s+(?:(?:luego|despu[eé]s)\s+)?"
    r"(?:dime|cu[eé]ntame|h[aá]blame|hazme|haz|pon|ponme|busca|escribe|minimiza|cierra|abre)\b.*$",
    re.IGNORECASE | re.DOTALL,
)
_SPOKEN_DOT = re.compile(r"\s+punto\s+", re.IGNORECASE)
_URL = re.compile(r"^(?:https?://)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:[/?#]\S*)?$", re.IGNORECASE)


@dataclass(frozen=True)
class Command:
    kind: str
    target: str = ""
    folder: str = ""


def _clean_target(raw: str) -> str:
    target = _SECOND_ORDER.sub("", raw.strip()).rstrip(".,;:!?¡¿ ").strip("\"'“”«»")
    return _TRAILING.sub("", target).strip()


def _folder_name(word: str, tolerant: bool = False) -> str:
    """La voz come letras ("escargas"): si dijo "carpeta", se admite un nombre parecido."""
    name = FOLDER_NAMES.get(word.casefold(), "")
    if name or not tolerant:
        return name
    key = name_key(word)
    best = max(FOLDER_NAMES, key=lambda known: name_similarity(key, name_key(known)))
    return FOLDER_NAMES[best] if name_similarity(key, name_key(best)) >= MIN_NAME_SIMILARITY else ""


def _file_command(raw: str) -> Command:
    name = _clean_target(raw.split(",")[0])
    place = _IN_FOLDER.search(name)
    folder = _folder_name(place.group("folder"), tolerant=True) if place else ""
    return Command(OPEN_FILE, name[: place.start()].strip() if folder and place else name, folder)


def _classify_open(raw: str) -> Command | None:
    target = _clean_target(raw)
    if not target:
        return None
    named_file = _FILE_WORDS.match(target)
    if named_file is not None:
        return _file_command(named_file.group("name"))
    if PurePath(target).suffix.casefold() in SAFE_FILE_TYPES | UNSAFE_FILE_TYPES:
        return Command(OPEN_FILE, target)
    spoken = _SPOKEN_DOT.sub(".", target)
    if _URL.match(spoken):
        return Command(OPEN_URL, spoken)
    folder = _FOLDER.match(target)
    if folder is not None:
        name = _folder_name(folder.group("name"), tolerant=bool(folder.group("word")))
        if name:
            return Command(OPEN_FOLDER, name)
    place = _IN_FOLDER.search(target)
    if place is not None and _folder_name(place.group("folder"), tolerant=True):
        return _file_command(target)
    return Command(OPEN_APP, _LEADING.sub("", target))


def asks_open_things(text: str) -> bool:
    return _ASKS_OPEN_THINGS.search(text) is not None


def _document_command(text: str) -> Command | None:
    for kind, pattern in (*_MAKE_DOCUMENT, *_WRITE_IN):
        match = pattern.match(text.strip())
        if match is not None:
            what = _clean_target(match.group("what"))
            return Command(WRITE_DOCUMENT, what, kind) if what else None
    return None


def parse_command(text: str) -> Command | None:
    """Convierte una orden clara en un comando. Cualquier otra frase es conversación."""
    if _LOOK.search(text):
        return Command(LOOK_AT_SCREEN)
    document = _document_command(text)
    if document is not None:
        return document
    search = _SEARCH.match(text)
    if search is not None:
        target = _clean_target(search.group("target"))
        return Command(WEB_SEARCH, target) if target else None
    opened = _OPEN.match(text.strip())
    if opened is not None:
        return _classify_open(opened.group("target"))
    for kind, pattern in _WINDOW:
        order = pattern.match(text.strip())
        if order is None:
            continue
        target = _clean_target(order.group("target") or "")
        if _THIS_WINDOW.match(target):
            return Command(kind, THIS_WINDOW)
        return Command(kind, _LEADING.sub("", target))
    for name, pattern in _INFO:
        if pattern.search(text):
            return Command(INFO, name)
    return None
