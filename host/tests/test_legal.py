# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""The apps' About / Licenses screens show text generated from LICENSE and
legal/components.json. These checks keep the bundled copies in step with their sources
and the two apps' hard-coded credit identical. Fix drift with
`python scripts/generate_legal.py`.
"""

import importlib.util
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _script():
    spec = importlib.util.spec_from_file_location("generate_legal", ROOT / "scripts/generate_legal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundled_legal_files_are_up_to_date():
    stale = [str(p.relative_to(ROOT)) for p, text in _script().build_outputs().items() if not p.exists() or p.read_text() != text]
    assert not stale, "run `python scripts/generate_legal.py`:\n" + "\n".join(stale)


def test_every_component_has_its_license_text_and_a_known_platform():
    data = json.loads((ROOT / "legal/components.json").read_text())
    for component in data["components"]:
        assert (ROOT / "legal/licenses" / component["text"]).is_file(), component["name"]
        assert component["platforms"] and set(component["platforms"]) <= {"android", "ipad"}, component["name"]


def test_the_gpl_copy_in_each_app_is_the_repo_license():
    gpl = (ROOT / "LICENSE").read_text()
    for path in _script().OUTPUT_DIRS.values():
        assert (path / "gpl-3.0.txt").read_text() == gpl


def test_each_apps_notices_list_only_its_own_libraries():
    script = _script()
    android, ipad = script.notices("android"), script.notices("ipad")
    assert "Java-WebSocket" in android and "Java-WebSocket" not in ipad
    assert "stasel/WebRTC" in ipad and "stasel/WebRTC" not in android
    for notices in (android, ipad):
        assert "ABSOLUTELY NO WARRANTY" in notices and "Copyright (C) 2026 James Luna" in notices


def test_mit_and_bsd_licenses_keep_their_copyright_lines():
    for text_file in ("Java-WebSocket-MIT.txt", "SLF4J-MIT.txt", "WebRTC-BSD-3-Clause.txt"):
        assert re.search(r"^Copyright \(c\)", (ROOT / "legal/licenses" / text_file).read_text(), re.MULTILINE), text_file


def test_both_apps_hard_code_the_same_credit_and_source_link():
    kotlin = (ROOT / "android/app/src/main/java/dev/viewdock/android/ui/LegalInfo.kt").read_text()
    swift = (ROOT / "ipad/Sources/Legal/AppInfo.swift").read_text()
    script = _script()
    for source in (kotlin, swift):
        assert script.COPYRIGHT in source
        assert script.SOURCE_URL in source
