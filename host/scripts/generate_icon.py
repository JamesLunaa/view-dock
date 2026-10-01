"""One-off generator for host/gui/assets/icon.png — the app icon used by the
window, the .desktop launcher, and (as a fallback at idle) the tray. Not run
automatically; the output is committed to the repo like any other asset.
Re-run manually (`python host/scripts/generate_icon.py`) if the design ever
needs to change.
"""

import pathlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap


def main() -> None:
    app = QGuiApplication([])  # a QGuiApplication is required to render offscreen

    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Background: rounded square.
    painter.setBrush(QColor("#1f6feb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(8, 8, size - 16, size - 16, 40, 40)

    # Pictogram: a monitor (the real desktop) and a smaller tablet (the
    # iPad) overlapping it, both as simple white rounded rectangles —
    # literally "extend this desktop onto that tablet".
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(40, 64, 130, 96, 10, 10)
    painter.setBrush(QColor("#1f6feb"))
    painter.drawRoundedRect(54, 78, 102, 68, 6, 6)

    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(140, 120, 76, 104, 14, 14)
    painter.setBrush(QColor("#1f6feb"))
    painter.drawRoundedRect(150, 132, 56, 80, 6, 6)

    painter.end()

    out_path = pathlib.Path(__file__).resolve().parent.parent / "gui" / "assets" / "icon.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(out_path), "PNG")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
