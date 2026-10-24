"""Entry point: ``python3 -m gui.main``."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow

if __name__ == "__main__":
    load_dotenv()  # populates os.environ from a .env file, if one is found; never overrides a var already set

    app = QApplication(sys.argv)

    qss_path = Path(__file__).parent / "styles.qss"
    app.setStyleSheet(qss_path.read_text())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
