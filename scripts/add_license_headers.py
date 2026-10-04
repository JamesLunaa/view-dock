# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Puts the license + copyright notice at the top of every source file.

    python scripts/add_license_headers.py           # add any that are missing
    python scripts/add_license_headers.py --check   # just report; exit 1 if any are missing

It only touches .py / .kt / .kts / .swift / .sh files known to git (tracked or new, not ignored) and is safe to re-run
(files that already have the notice are left alone). Run it after adding a source file;
a host test (`host/tests/test_license_headers.py`) fails if one is missing.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

SPDX = "SPDX-License-Identifier: GPL-3.0-or-later"
COPYRIGHT = "Copyright (C) 2026 James Luna"

COMMENT_PREFIX = {".py": "#", ".sh": "#", ".kt": "//", ".kts": "//", ".swift": "//"}


def source_files() -> list[pathlib.Path]:
    names = subprocess.run(
        # tracked files plus new ones that aren't ignored, so a file is covered before it is committed
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [ROOT / n for n in names if pathlib.Path(n).suffix in COMMENT_PREFIX and (ROOT / n).is_file()]


def has_header(text: str) -> bool:
    return SPDX in "\n".join(text.splitlines()[:6])


def keep_first(lines: list[str]) -> int:
    """How many leading lines must stay above the notice: a shebang, or Swift's
    `// swift-tools-version` line, which the compiler requires to be first."""
    if lines and (lines[0].startswith("#!") or lines[0].startswith("// swift-tools-version")):
        return 1
    return 0


def with_header(path: pathlib.Path, text: str) -> str:
    prefix = COMMENT_PREFIX[path.suffix]
    header = [f"{prefix} {SPDX}", f"{prefix} {COPYRIGHT}"]
    lines = text.split("\n")
    n = keep_first(lines)
    rest = lines[n:]
    if rest and rest[0].strip() == "":  # don't stack blank lines on re-formatting
        rest = rest[1:]
    body = lines[:n] + header + ([""] + rest if any(line.strip() for line in rest) else [""])
    return "\n".join(body)


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    missing = []
    for path in source_files():
        text = path.read_text()
        if has_header(text):
            continue
        missing.append(path)
        if not check_only:
            path.write_text(with_header(path, text))
    rel = [str(p.relative_to(ROOT)) for p in missing]
    if check_only:
        print("\n".join(rel) or "all source files have the notice")
        return 1 if rel else 0
    print(f"added the notice to {len(rel)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
