"""One-time setup for Memorize.

Run once with the Python environment that has PySide6 + fsrs installed:
    python install.py

What it does:
  1. Detects pythonw.exe (no-console launcher)
  2. Writes .python-path so memorize.vbs knows which Python to use
  3. Creates %APPDATA%\\memorize\\ data directory

After this, double-click memorize.vbs to start.
Re-running is safe (idempotent).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.resolve()
PYTHON_PATH_FILE = REPO_DIR / ".python-path"
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "memorize"


def find_pythonw() -> str:
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if pythonw.exists():
        return str(pythonw)
    # Fallback: plain python.exe (will show a console, but works)
    return sys.executable


def main() -> None:
    print("Memorize setup\n")

    python_path = find_pythonw()
    print(f"  Python : {python_path}")
    print(f"  Repo   : {REPO_DIR}")

    PYTHON_PATH_FILE.write_text(python_path, encoding="utf-8")
    print(f"  Written: {PYTHON_PATH_FILE}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Data   : {DATA_DIR}")

    print("\nDone!")
    print("Next step: python scripts/import_words.py <your_words.txt>")
    print("Then:      double-click memorize.vbs to launch.")


if __name__ == "__main__":
    main()
