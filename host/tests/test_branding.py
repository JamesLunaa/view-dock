"""Keeps the app icons consistent: `branding/icon.svg` is the single source, and
`branding/generate_icons.py` derives the host, iPad and Android icons from it.
These checks fail if someone edits the master (or a generated file) without
regenerating, so the three platforms can't quietly drift apart again.

They read the committed files only — no PySide6 or image library needed.
"""

import json
import pathlib
import struct
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SVG = "{http://www.w3.org/2000/svg}"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def _master() -> dict[str, dict[str, str]]:
    return {e.get("id"): dict(e.attrib) for e in ET.parse(ROOT / "branding/icon.svg").getroot() if e.get("id")}


def _png_header(path: pathlib.Path) -> tuple[int, int, int]:
    """(width, height, color type) from the IHDR chunk; color type 2 = RGB, 6 = RGBA."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height, data[25]


def test_android_foreground_matches_the_master():
    master = _master()
    paths = ET.parse(ROOT / "android/app/src/main/res/drawable/ic_launcher_foreground.xml").getroot().findall("path")
    drawn = [(p.get(f"{ANDROID}fillColor"), p.get(f"{ANDROID}pathData")) for p in paths]
    assert drawn == [
        (master["screen-back"]["fill"], master["screen-back"]["d"]),
        (master["screen-front"]["fill"], master["screen-front"]["d"]),
    ], "run `python branding/generate_icons.py`"


def test_android_background_color_matches_the_master():
    colors = ET.parse(ROOT / "android/app/src/main/res/values/colors.xml").getroot()
    background = next(c for c in colors if c.get("name") == "ic_launcher_background")
    assert background.text == _master()["background"]["fill"], "run `python branding/generate_icons.py`"


def test_ipad_app_icon_is_a_1024_opaque_png_the_catalog_points_at():
    appiconset = ROOT / "ipad/Resources/Assets.xcassets/AppIcon.appiconset"
    contents = json.loads((appiconset / "Contents.json").read_text())
    (image,) = contents["images"]
    assert (image["idiom"], image["size"]) == ("universal", "1024x1024")

    width, height, color_type = _png_header(appiconset / image["filename"])
    assert (width, height) == (1024, 1024)
    assert color_type == 2, "iOS app icons must have no alpha channel (RGB, not RGBA)"


def test_xcode_project_uses_the_app_icon_set():
    assert "ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon" in (ROOT / "ipad/project.yml").read_text()


def test_host_icon_is_the_256px_png_the_gui_and_launcher_load():
    width, height, _ = _png_header(ROOT / "host/gui/assets/icon.png")
    assert (width, height) == (256, 256)


def test_xcode_project_actually_includes_the_asset_catalog():
    """XcodeGen ignores unknown keys silently: the catalog used to sit under a
    `resources:` key that doesn't exist, so the icon was never packaged into the
    app. Asset catalogs must be listed under `sources`."""
    spec = (ROOT / "ipad/project.yml").read_text()
    assert "- path: Resources/Assets.xcassets" in spec
    assert "\n    resources:" not in spec, "`resources:` is not an XcodeGen target key"
