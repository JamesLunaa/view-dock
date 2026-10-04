# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""The release version must read the same everywhere: the latest dated section of
CHANGELOG.md, the Android app's versionName/versionCode, and the iPad project's
MARKETING_VERSION. They're bumped together at release time (see CONTRIBUTING.md);
this fails if one is forgotten.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _changelog_version() -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    # First *released* heading, i.e. skipping `## [Unreleased]`.
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}", text, re.MULTILINE)
    assert match, "CHANGELOG.md has no dated `## [X.Y.Z] - YYYY-MM-DD` section"
    return match.group(1)


def test_android_version_matches_the_latest_release():
    gradle = (ROOT / "android/app/build.gradle.kts").read_text()
    name = re.search(r'versionName = "([^"]+)"', gradle).group(1)
    code = int(re.search(r"versionCode = (\d+)", gradle).group(1))

    assert name == _changelog_version()
    major, minor, patch = (int(part) for part in name.split("."))
    # Must only ever increase for an update to install over an older build.
    assert code == major * 10000 + minor * 100 + patch


def test_ipad_version_matches_the_latest_release():
    spec = (ROOT / "ipad/project.yml").read_text()
    assert re.search(r'MARKETING_VERSION: "([^"]+)"', spec).group(1) == _changelog_version()
    # Without these the generated Info.plist would keep XcodeGen's hard-coded "1.0".
    assert 'CFBundleShortVersionString: "$(MARKETING_VERSION)"' in spec
    assert 'CFBundleVersion: "$(CURRENT_PROJECT_VERSION)"' in spec
    assert re.search(r'CURRENT_PROJECT_VERSION: "\d+"', spec)


def test_changelog_has_compare_links_for_unreleased_and_the_latest_release():
    text = (ROOT / "CHANGELOG.md").read_text()
    version = _changelog_version()
    assert re.search(rf"^\[Unreleased\]: .*compare/v{re.escape(version)}\.\.\.HEAD$", text, re.MULTILINE)
    assert re.search(rf"^\[{re.escape(version)}\]: ", text, re.MULTILINE)
