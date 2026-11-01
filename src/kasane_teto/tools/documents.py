"""Crea archivos nuevos con lo que redacta Teto. Nunca escribe sobre un archivo que ya exista."""

from __future__ import annotations

import re
import time
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

FORMAT_TEXT = "txt"
FORMAT_WORD = "docx"
FORMAT_SLIDES = "pptx"
MAX_SLIDE_LINES = 7
_TITLE_LABEL = re.compile(r"^t[ií]tulo\s*:\s*", re.IGNORECASE)

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/></Types>'
)
_RELATIONSHIPS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)


def strip_preamble(text: str) -> str:
    """El modelo a veces presenta el texto ("Aquí tienes el poema:"); eso no va en el archivo."""
    first, _, rest = text.strip().partition("\n")
    return rest.strip() if first.rstrip().endswith(":") and rest.strip() else text.strip()


def _new_path(folder: Path, extension: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H%M%S")
    for number in range(1, 1000):
        suffix = f" {number}" if number > 1 else ""
        path = folder / f"Teto {stamp}{suffix}.{extension}"
        if not path.exists():
            return path
    raise FileExistsError(folder)


def _write_word(path: Path, text: str) -> None:
    paragraphs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'
        for line in text.splitlines()
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELATIONSHIPS)
        archive.writestr("word/document.xml", body)


def split_slides(text: str) -> list[tuple[str, list[str]]]:
    """Cada bloque separado por una línea en blanco es una diapositiva; la primera línea, su título."""
    slides = []
    for block in text.split("\n\n"):
        lines = [line.strip(" -•*\t") for line in block.splitlines()]
        lines = [line for line in lines if line]
        if lines:
            slides.append((_TITLE_LABEL.sub("", lines[0]), lines[1:MAX_SLIDE_LINES]))
    return slides


def _write_slides(path: Path, text: str) -> None:
    from pptx import Presentation  # Carga perezosa: solo hace falta al crear presentaciones.

    presentation = Presentation()
    layout = presentation.slide_layouts[1]
    for title, lines in split_slides(text):
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = title
        slide.placeholders[1].text = "\n".join(lines)
    presentation.save(path)


def create_document(kind: str, text: str, folder: Path) -> Path:
    path = _new_path(folder, kind)
    if kind == FORMAT_WORD:
        _write_word(path, text)
    elif kind == FORMAT_SLIDES:
        _write_slides(path, text)
    else:
        with path.open("x", encoding="utf-8") as file:
            file.write(text)
    return path
