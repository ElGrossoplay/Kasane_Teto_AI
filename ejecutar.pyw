"""Lanzador sin consola: .venv\\Scripts\\pythonw.exe ejecutar.pyw"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kasane_teto.main import main  # noqa: E402

sys.exit(main())
