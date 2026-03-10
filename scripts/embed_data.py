#!/usr/bin/env python3
"""
embed_data.py — Bake live JSON data files into index.html inline constants.

Run after update.py so the static site always serves the latest data.
Usage:
    python scripts/embed_data.py
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR  = REPO_ROOT / "data"
HTML_FILE = REPO_ROOT / "index.html"


def load(name: str) -> str:
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        print(f"  ⚠ Missing {path.name} — skipping")
        return None
    with open(path, encoding="utf-8") as f:
        return json.dumps(json.load(f), separators=(",", ":"), ensure_ascii=False)


def embed():
    print("📦 embed_data.py — baking JSON into index.html")

    if not HTML_FILE.exists():
        print(f"❌ index.html not found at {HTML_FILE}")
        sys.exit(1)

    html = HTML_FILE.read_text(encoding="utf-8")

    replacements = {
        "DISRUPTIONS": load("disruptions"),
        "ROUTES":      load("routes"),
        "ADVISORIES":  load("advisories"),
        "AIRPORTS":    load("airports"),
        "UK_PAKISTAN": load("uk_pakistan"),
    }

    changed = 0
    for const, data in replacements.items():
        if data is None:
            continue
        pattern = rf"const {const}=\{{.*?\}};"
        new_val  = f"const {const}={data};"
        new_html, n = re.subn(pattern, new_val, html, flags=re.DOTALL)
        if n:
            html = new_html
            changed += 1
            print(f"  ✅ {const} embedded ({len(data):,} chars)")
        else:
            print(f"  ⚠ {const} — pattern not found in index.html (skipped)")

    if changed:
        HTML_FILE.write_text(html, encoding="utf-8")
        print(f"✅ index.html updated with {changed} data constants")
    else:
        print("ℹ No constants updated")

    return changed


if __name__ == "__main__":
    embed()
