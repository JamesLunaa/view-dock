"""Derives every view-dock app icon from `branding/icon.svg`, so the host, the
iPad app and the Android app can't drift apart.

    python branding/generate_icons.py          # needs PySide6 (QtSvg), as the host GUI does

Outputs (all committed; this is not run by any build):
  host/gui/assets/icon.png                       256px, rounded square, transparent corners
  ipad/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png
                                                 1024px, opaque, square (iOS rounds it itself)
  android/app/src/main/res/drawable/ic_launcher_foreground.xml
  android/app/src/main/res/values/colors.xml     (ic_launcher_background)

Android keeps the artwork at its natural size because its adaptive-icon mask
crops the edges; the host and iPad icons are shown whole, so the artwork is
scaled up a little there to give it the same visual weight.
"""

import os
import pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = ROOT / "branding" / "icon.svg"
SVG_NS = "{http://www.w3.org/2000/svg}"

FULL_BLEED_SCALE = 1.3
HOST_CORNER_RADIUS = 24  # of 108 — roughly the usual app-icon corner


def read_master() -> dict[str, dict[str, str]]:
    elements = {}
    for element in ET.parse(MASTER).getroot():
        element_id = element.get("id")
        if element_id:
            elements[element_id] = dict(element.attrib)
    for required in ("background", "screen-back", "screen-front"):
        if required not in elements:
            raise SystemExit(f"{MASTER} is missing the element with id={required!r}")
    return elements


def full_bleed_svg(master: dict, *, rounded: bool) -> str:
    """The master as a standalone SVG, artwork scaled about the canvas centre."""
    rx = f' rx="{HOST_CORNER_RADIUS}"' if rounded else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 108 108">
  <rect width="108" height="108"{rx} fill="{master['background']['fill']}"/>
  <g transform="translate(54 54) scale({FULL_BLEED_SCALE}) translate(-54 -54)">
    <path fill="{master['screen-back']['fill']}" d="{master['screen-back']['d']}"/>
    <path fill="{master['screen-front']['fill']}" d="{master['screen-front']['d']}"/>
  </g>
</svg>"""


def render_png(svg: str, size: int, out: pathlib.Path, *, opaque: bool) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])  # needed to render offscreen
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    # RGB32 has no alpha channel, so the PNG is written as plain RGB — what iOS wants.
    image = QImage(size, size, QImage.Format.Format_RGB32 if opaque else QImage.Format.Format_ARGB32)
    image.fill(QColor("black") if opaque else Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(out), "PNG"):
        raise SystemExit(f"could not write {out}")
    print(f"wrote {out.relative_to(ROOT)}")
    del app


def write_android(master: dict) -> None:
    drawable = ROOT / "android/app/src/main/res/drawable/ic_launcher_foreground.xml"
    drawable.write_text(f"""<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
    <!-- Generated from branding/icon.svg by branding/generate_icons.py — edit that, not this. -->
    <path
        android:fillColor="{master['screen-back']['fill']}"
        android:pathData="{master['screen-back']['d']}" />
    <path
        android:fillColor="{master['screen-front']['fill']}"
        android:pathData="{master['screen-front']['d']}" />
</vector>
""")
    colors = ROOT / "android/app/src/main/res/values/colors.xml"
    colors.write_text(f"""<resources>
    <!-- Generated from branding/icon.svg by branding/generate_icons.py. -->
    <color name="ic_launcher_background">{master['background']['fill']}</color>
</resources>
""")
    print(f"wrote {drawable.relative_to(ROOT)}\nwrote {colors.relative_to(ROOT)}")


def write_ipad_catalog() -> None:
    catalog = ROOT / "ipad/Resources/Assets.xcassets"
    (catalog / "AppIcon.appiconset").mkdir(parents=True, exist_ok=True)
    (catalog / "Contents.json").write_text('{\n  "info" : {\n    "author" : "xcode",\n    "version" : 1\n  }\n}\n')
    (catalog / "AppIcon.appiconset/Contents.json").write_text(
        '{\n  "images" : [\n    {\n      "filename" : "icon-1024.png",\n      "idiom" : "universal",\n'
        '      "platform" : "ios",\n      "size" : "1024x1024"\n    }\n  ],\n'
        '  "info" : {\n    "author" : "xcode",\n    "version" : 1\n  }\n}\n'
    )


def main() -> None:
    master = read_master()
    render_png(full_bleed_svg(master, rounded=True), 256, ROOT / "host/gui/assets/icon.png", opaque=False)
    write_ipad_catalog()
    render_png(
        full_bleed_svg(master, rounded=False),
        1024,
        ROOT / "ipad/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png",
        opaque=True,
    )
    write_android(master)


if __name__ == "__main__":
    main()
