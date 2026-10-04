# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Every source file carries the license + copyright notice, so the credit and the
GPL terms travel with a file even if someone copies just part of the project.
Fix a failure with `python scripts/add_license_headers.py`.
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _script():
    spec = importlib.util.spec_from_file_location("add_license_headers", ROOT / "scripts/add_license_headers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_source_file_has_the_license_notice():
    script = _script()
    missing = [str(p.relative_to(ROOT)) for p in script.source_files() if not script.has_header(p.read_text())]
    assert not missing, "missing the license notice (run scripts/add_license_headers.py):\n" + "\n".join(missing)


def test_the_license_file_is_the_gpl_v3():
    text = (ROOT / "LICENSE").read_text()
    assert "GNU GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text


def test_the_credit_is_in_the_notice_and_the_readme():
    assert "Copyright (C) 2026 James Luna" in (ROOT / "NOTICE").read_text()
    assert "James Luna" in (ROOT / "README.md").read_text()


def test_header_insertion_keeps_shebangs_and_the_swift_tools_line_first():
    script = _script()
    sh = script.with_header(pathlib.Path("x.sh"), "#!/usr/bin/env bash\nset -e\n")
    assert sh.split("\n")[0] == "#!/usr/bin/env bash" and script.SPDX in sh.split("\n")[1]
    pkg = script.with_header(pathlib.Path("Package.swift"), "// swift-tools-version:5.9\nimport PackageDescription\n")
    assert pkg.split("\n")[0] == "// swift-tools-version:5.9"
    # idempotent: a file that already has it is recognised
    assert script.has_header(sh) and script.has_header(pkg)
