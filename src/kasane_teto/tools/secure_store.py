"""Guarda secretos cifrados con la sesión de Windows (DPAPI): otro usuario no puede leerlos."""

from __future__ import annotations

import ctypes
import json
import logging
from ctypes import wintypes
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.LocalFree.argtypes = (ctypes.c_void_p,)


def _blob(data: bytes) -> _Blob:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))


def _result(blob: _Blob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(blob.pbData)


def protect(data: bytes) -> bytes:
    source, target = _blob(data), _Blob()
    if not _crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return _result(target)


def unprotect(data: bytes) -> bytes:
    source, target = _blob(data), _Blob()
    if not _crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return _result(target)


class SecureStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(unprotect(self._path.read_bytes()))
        except (OSError, ValueError):
            log.exception("No se pudo leer el archivo cifrado; se ignora")
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        self._path.write_bytes(protect(json.dumps(data).encode("utf-8")))

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
