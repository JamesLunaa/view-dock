# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Builds the legal text the Android and iPad apps show on their About / Licenses screens.

    python scripts/generate_legal.py           # (re)write the bundled files
    python scripts/generate_legal.py --check   # exit 1 if they are out of date

Inputs:  LICENSE (the GPL), legal/components.json, legal/licenses/*.txt
Outputs: for each app, `gpl-3.0.txt` (the full license) and `notices.txt` (copyright,
         no-warranty statement and the third-party licenses):
           android/app/src/main/assets/legal/
           ipad/Resources/Legal/

The output is deterministic (no dates), so it is committed and a host test fails if it
drifts from the inputs. Re-run after changing a dependency's row in components.json.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEGAL = ROOT / "legal"

COPYRIGHT = "Copyright (C) 2026 James Luna"
SOURCE_URL = "https://github.com/JamesLunaa/view-dock"

OUTPUT_DIRS = {
    "android": ROOT / "android/app/src/main/assets/legal",
    "ipad": ROOT / "ipad/Resources/Legal",
}

RULE = "=" * 64


def components_for(platform: str) -> list[dict]:
    data = json.loads((LEGAL / "components.json").read_text())
    return [c for c in data["components"] if platform in c["platforms"]]


def notices(platform: str) -> str:
    items = components_for(platform)
    lines = [
        "view-dock",
        COPYRIGHT,
        "",
        "view-dock is free software, licensed under the GNU General Public License,",
        "version 3 or (at your option) any later version.",
        "",
        "This program comes with ABSOLUTELY NO WARRANTY. You are welcome to",
        "redistribute it under the conditions of that license; the full text is",
        "available from the License screen.",
        "",
        f"Source code: {SOURCE_URL}",
        "",
        RULE,
        "THIRD-PARTY SOFTWARE",
        RULE,
        "",
        "view-dock includes the open-source software listed below. Each part is used",
        "under its own license, reproduced after the list.",
        "",
    ]

    for number, item in enumerate(items, start=1):
        lines += [f"[{number}] {item['name']}", f"    by {item['by']}", f"    {item['url']}", f"    License: {item['license']}"]
        if item.get("note"):
            lines += [f"    Note: {item['note']}"]
        lines.append("")

    # Group by license text: libraries that share a text (Apache-2.0) print it once.
    groups: dict[str, list[int]] = {}
    for number, item in enumerate(items, start=1):
        groups.setdefault(item["text"], []).append(number)

    for text_file, numbers in groups.items():
        first = items[numbers[0] - 1]
        used_by = ", ".join(f"[{n}]" for n in numbers)
        lines += [RULE, f"{first['license']} — applies to {used_by}", RULE, ""]
        lines += [(LEGAL / "licenses" / text_file).read_text().rstrip(), ""]

    return "\n".join(lines).rstrip() + "\n"


def build_outputs() -> dict[pathlib.Path, str]:
    gpl = (ROOT / "LICENSE").read_text()
    outputs: dict[pathlib.Path, str] = {}
    for platform, directory in OUTPUT_DIRS.items():
        outputs[directory / "gpl-3.0.txt"] = gpl
        outputs[directory / "notices.txt"] = notices(platform)
    return outputs


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    stale = []
    for path, text in build_outputs().items():
        if not path.exists() or path.read_text() != text:
            stale.append(path)
            if not check_only:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
    names = [str(p.relative_to(ROOT)) for p in stale]
    if check_only:
        print("\n".join(names) or "legal files are up to date")
        return 1 if names else 0
    print(f"wrote {len(names)} file(s)" if names else "nothing to change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
