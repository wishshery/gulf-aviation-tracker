#!/usr/bin/env python3
"""
Gulf Aviation Route Tracker — Automated Update Engine
======================================================
Searches trusted aviation sources for route changes, disruptions,
and operational updates affecting Gulf country airports, then
updates the site's JSON data files and (optionally) git-commits
and pushes the changes.

Usage:
    python scripts/update.py                 # run update
    python scripts/update.py --dry-run       # preview without saving
    python scripts/update.py --force-commit  # always commit even if no changes

Environment variables (set in .env or CI secrets):
    ANTHROPIC_API_KEY   — required for LLM-powered extraction
    GITHUB_TOKEN        — required for authenticated git push (optional)
    GIT_REPO_PATH       — path to repo root (defaults to parent of scripts/)
    MAX_AGE_DAYS        — how many days of history to keep (default: 45)
    OPENROUTER_KEY      — alternative: use OpenRouter instead of Anthropic API
"""

import os
import sys
import json
import time
import uuid
import logging
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Optional dependencies ──────────────────────────────────────────────────
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("⚠  'requests' not installed. Run: pip install requests")

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    print("⚠  'anthropic' not installed. Run: pip install anthropic")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gulf-tracker")

# ── Config ─────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(os.getenv("GIT_REPO_PATH", Path(__file__).parent.parent)).resolve()
DATA_DIR    = REPO_ROOT / "data"
MAX_AGE     = int(os.getenv("MAX_AGE_DAYS", 45))
NOW_UTC     = datetime.now(timezone.utc)
TODAY_STR   = NOW_UTC.strftime("%Y-%m-%d")

# Gulf airports to focus on
GULF_AIRPORTS = [
    "Dubai", "DXB", "Abu Dhabi", "AUH", "Doha", "DOH",
    "Jeddah", "JED", "Riyadh", "RUH", "Muscat", "MCT",
    "Kuwait", "KWI", "Bahrain", "BAH", "Manama", "Sharjah",
]

# Tracked airlines
TRACKED_AIRLINES = [
    "Emirates", "Qatar Airways", "Etihad", "Flydubai", "fly dubai",
    "Air Arabia", "Saudia", "Saudi Arabian Airlines", "Gulf Air",
    "Oman Air", "Kuwait Airways", "SalamAir", "Jazeera Airways",
    "flyadeal", "Flynas",
]

# Aviation news search queries
SEARCH_QUERIES = [
    "Gulf airline new route 2026",
    "Emirates Qatar Airways Etihad route announcement 2026",
    "Dubai Abu Dhabi Doha airline route suspended resumed",
    "Gulf aviation disruption airspace restriction 2026",
    "Saudia Flydubai Air Arabia route launch 2026",
    "Gulf airport operational notice advisory",
    "airline route change Gulf countries March 2026",
]

# Trusted sources
TRUSTED_DOMAINS = [
    "simpleflying.com",
    "airlineroute.net",
    "ch-aviation.com",
    "aviationweek.com",
    "flightglobal.com",
    "theloadstar.com",
    "aviationbusiness.aero",
    "airport-technology.com",
    "emirates.com",
    "qatarairways.com",
    "etihad.com",
    "flydubai.com",
    "airarabia.com",
    "saudia.com",
    "gcaa.gov.ae",
    "qatarairports.com",
    "dubaiairports.ae",
]

# ─────────────────────────────────────────────────────────────────────────
# 1. WEB SEARCH
# ─────────────────────────────────────────────────────────────────────────

def search_aviation_news(query: str, num_results: int = 5) -> list[dict]:
    """
    Search for aviation news using DuckDuckGo Instant Answer API (no key needed)
    or SerpAPI / Serper if key available.
    Returns list of {title, url, snippet} dicts.
    """
    if not HAS_REQUESTS:
        return []

    results = []

    # --- Try Serper.dev (free tier available) ---
    serper_key = os.getenv("SERPER_API_KEY")
    if serper_key:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": num_results},
                headers={"X-API-KEY": serper_key},
                timeout=10,
            )
            if r.ok:
                for item in r.json().get("organic", [])[:num_results]:
                    results.append({
                        "title":   item.get("title", ""),
                        "url":     item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })
                return results
        except Exception as e:
            log.warning("Serper search failed: %s", e)

    # --- Fallback: DuckDuckGo JSON API ---
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10,
            headers={"User-Agent": "GulfAviationTracker/1.0"},
        )
        if r.ok:
            data = r.json()
            for topic in (data.get("RelatedTopics") or [])[:num_results]:
                if isinstance(topic, dict) and topic.get("FirstURL"):
                    results.append({
                        "title":   topic.get("Text", "")[:80],
                        "url":     topic["FirstURL"],
                        "snippet": topic.get("Text", ""),
                    })
    except Exception as e:
        log.warning("DuckDuckGo search failed: %s", e)

    return results


def fetch_article(url: str, max_chars: int = 4000) -> str:
    """Fetch and return plain text from a URL using Jina Reader (free)."""
    if not HAS_REQUESTS:
        return ""
    try:
        jina_url = f"https://r.jina.ai/{url}"
        r = requests.get(
            jina_url,
            timeout=15,
            headers={"User-Agent": "GulfAviationTracker/1.0"},
        )
        return r.text[:max_chars] if r.ok else ""
    except Exception as e:
        log.warning("Fetch failed for %s: %s", url, e)
        return ""


# ─────────────────────────────────────────────────────────────────────────
# 2. LLM EXTRACTION (Anthropic Claude)
# ─────────────────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM = """You are an aviation data extraction assistant.
Your job is to read aviation news articles and extract structured data
about airline route changes and operational updates affecting Gulf airports.

Gulf airports: Dubai (DXB), Abu Dhabi (AUH), Doha (DOH), Jeddah (JED),
Riyadh (RUH), Muscat (MCT), Kuwait (KWI), Bahrain (BAH), Sharjah (SHJ).

Tracked airlines: Emirates, Qatar Airways, Etihad Airways, Flydubai,
Air Arabia, Saudia, Gulf Air, Oman Air, Kuwait Airways, SalamAir,
Jazeera Airways, flyadeal, Flynas.

Return ONLY valid JSON. No markdown, no explanation. If no relevant updates, return {"entries": []}.
"""

EXTRACTION_PROMPT = """Extract all Gulf aviation route changes and disruptions from the article below.

Article URL: {url}
Article content:
{content}

Return a JSON object with an "entries" array. Each entry must have these fields:
{{
  "type": "disruption" | "new_route" | "suspended_route" | "resumed_route" | "advisory",
  "airline": "airline name or null",
  "origin": "origin city/airport or null",
  "destination": "destination city/airport or null",
  "route": "origin → destination string or null",
  "status": "new|suspended|resumed|rerouted|delayed|cancelled|diverted|operating|warning|info|critical",
  "effective_date": "YYYY-MM-DD or null",
  "start_date": "YYYY-MM-DD or null",
  "frequency": "e.g. Daily or 4x weekly or null",
  "aircraft": "aircraft type or null",
  "description": "one concise sentence max 150 chars",
  "title": "advisory title if type==advisory else null",
  "body": "advisory full text if type==advisory else null",
  "airports": "relevant airport IATA codes comma-separated or null",
  "source": "{url}"
}}

Only include entries related to Gulf airports or Gulf carriers. Ignore unrelated routes.
"""


def extract_with_llm(content: str, url: str) -> list[dict]:
    """Use Claude to extract structured route data from article text."""
    if not HAS_ANTHROPIC:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping LLM extraction")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    prompt = EXTRACTION_PROMPT.format(url=url, content=content[:3500])

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
            system=EXTRACTION_SYSTEM,
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return data.get("entries", [])
    except (json.JSONDecodeError, Exception) as e:
        log.warning("LLM extraction failed for %s: %s", url, e)
        return []


# ─────────────────────────────────────────────────────────────────────────
# 3. DATA FILE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info("Saved: %s", path)


def is_recent(date_str: Optional[str], max_days: int = MAX_AGE) -> bool:
    if not date_str:
        return True
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (NOW_UTC - dt).days <= max_days
    except ValueError:
        return True


def purge_old_entries(entries: list[dict], date_key: str = "added_date") -> list[dict]:
    return [e for e in entries if is_recent(e.get(date_key))]


def dedup(entries: list[dict], key_fn) -> list[dict]:
    seen = set()
    out  = []
    for e in entries:
        k = key_fn(e)
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


# ─────────────────────────────────────────────────────────────────────────
# 4. UPDATE LOGIC
# ─────────────────────────────────────────────────────────────────────────

def update_disruptions(new_entries: list[dict]) -> int:
    path = DATA_DIR / "disruptions.json"
    data = load_json(path)
    existing = data.get("disruptions", [])

    added = 0
    for e in new_entries:
        if e.get("type") not in ("disruption",):
            continue
        entry = {
            "id":             "d" + uuid.uuid4().hex[:8],
            "airline":        e.get("airline", ""),
            "origin":         e.get("origin", ""),
            "destination":    e.get("destination", ""),
            "route":          e.get("route", ""),
            "status":         e.get("status", "unknown"),
            "effective_date": e.get("effective_date", TODAY_STR),
            "notes":          e.get("description", ""),
            "source":         e.get("source", ""),
            "added_date":     TODAY_STR,
        }
        existing.insert(0, entry)
        added += 1

    existing = purge_old_entries(existing, "added_date")
    existing = dedup(existing, lambda x: (x.get("airline",""), x.get("route",""), x.get("effective_date","")))

    data["disruptions"]  = existing
    data["last_updated"] = NOW_UTC.isoformat()
    save_json(path, data)
    return added


def update_routes(new_entries: list[dict]) -> int:
    path = DATA_DIR / "routes.json"
    data = load_json(path)
    existing = data.get("routes", [])

    added = 0
    type_to_status = {
        "new_route":      "new",
        "suspended_route":"suspended",
        "resumed_route":  "resumed",
    }
    for e in new_entries:
        t = e.get("type", "")
        if t not in type_to_status:
            continue
        entry = {
            "id":          "r" + uuid.uuid4().hex[:8],
            "airline":     e.get("airline", ""),
            "origin":      e.get("origin", ""),
            "destination": e.get("destination", ""),
            "status":      e.get("status") or type_to_status[t],
            "start_date":  e.get("start_date") or e.get("effective_date"),
            "frequency":   e.get("frequency", ""),
            "aircraft":    e.get("aircraft", ""),
            "description": e.get("description", ""),
            "source":      e.get("source", ""),
            "added_date":  TODAY_STR,
        }
        existing.insert(0, entry)
        added += 1

    existing = purge_old_entries(existing, "added_date")
    existing = dedup(existing, lambda x: (x.get("airline",""), x.get("origin",""), x.get("destination",""), x.get("status","")))

    data["routes"]       = existing
    data["last_updated"] = NOW_UTC.isoformat()
    save_json(path, data)
    return added


def update_advisories(new_entries: list[dict]) -> int:
    path = DATA_DIR / "advisories.json"
    data = load_json(path)
    existing = data.get("advisories", [])

    added = 0
    for e in new_entries:
        if e.get("type") != "advisory":
            continue
        entry = {
            "id":             "adv" + uuid.uuid4().hex[:8],
            "type":           e.get("status", "info"),
            "title":          e.get("title") or e.get("description", "")[:80],
            "body":           e.get("body") or e.get("description", ""),
            "airline":        e.get("airline", ""),
            "airports":       e.get("airports", ""),
            "effective_date": e.get("effective_date", TODAY_STR),
            "expiry_date":    None,
            "source":         e.get("source", ""),
            "added_date":     TODAY_STR,
        }
        existing.insert(0, entry)
        added += 1

    existing = purge_old_entries(existing, "added_date")
    existing = dedup(existing, lambda x: x.get("title",""))

    data["advisories"]   = existing
    data["last_updated"] = NOW_UTC.isoformat()
    save_json(path, data)
    return added


# ─────────────────────────────────────────────────────────────────────────
# 5. GIT OPERATIONS
# ─────────────────────────────────────────────────────────────────────────

def git_commit_and_push(repo_path: Path, message: str) -> bool:
    """Stage data files, commit, and push."""
    try:
        subprocess.run(
            ["git", "-C", str(repo_path), "add",
             "data/disruptions.json", "data/routes.json",
             "data/advisories.json", "data/airports.json"],
            check=True, capture_output=True,
        )
        result = subprocess.run(
            ["git", "-C", str(repo_path), "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if result.returncode == 0:
            log.info("No changes to commit.")
            return False

        subprocess.run(
            ["git", "-C", str(repo_path), "commit", "-m", message],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_path), "push"],
            check=True, capture_output=True,
        )
        log.info("✅ Git commit & push successful: %s", message)
        return True

    except subprocess.CalledProcessError as e:
        log.error("Git operation failed: %s", e.stderr.decode())
        return False


# ─────────────────────────────────────────────────────────────────────────
# 6. MAIN ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────

def run_update(dry_run: bool = False, force_commit: bool = False) -> None:
    log.info("━━━ Gulf Aviation Tracker — Update Run ━━━")
    log.info("Timestamp : %s", NOW_UTC.isoformat())
    log.info("Data dir  : %s", DATA_DIR)
    log.info("Dry run   : %s", dry_run)

    all_entries: list[dict] = []
    sources_checked = 0

    for query in SEARCH_QUERIES:
        log.info("🔍 Searching: %s", query)
        results = search_aviation_news(query, num_results=4)
        log.info("   Found %d results", len(results))

        for item in results:
            url     = item.get("url", "")
            snippet = item.get("snippet", "")
            if not url:
                continue

            # Quick relevance filter before full fetch
            combined = (item.get("title","") + snippet).lower()
            is_relevant = any(a.lower() in combined for a in TRACKED_AIRLINES) or \
                          any(ap.lower() in combined for ap in GULF_AIRPORTS)
            if not is_relevant:
                log.debug("   Skipping irrelevant: %s", url[:60])
                continue

            content = fetch_article(url, max_chars=4000)
            sources_checked += 1
            if not content:
                continue

            entries = extract_with_llm(content, url)
            log.info("   Extracted %d entries from %s", len(entries), url[:60])
            all_entries.extend(entries)
            time.sleep(0.5)  # be kind to rate limits

        time.sleep(1)

    log.info("Total entries extracted: %d from %d sources", len(all_entries), sources_checked)

    if dry_run:
        log.info("DRY RUN — printing extracted entries:")
        print(json.dumps(all_entries, indent=2))
        return

    # Update data files
    d_added   = update_disruptions(all_entries)
    r_added   = update_routes(all_entries)
    adv_added = update_advisories(all_entries)
    total     = d_added + r_added + adv_added

    log.info("✅ Added: %d disruptions, %d routes, %d advisories", d_added, r_added, adv_added)

    # Git commit
    if total > 0 or force_commit:
        msg = f"Daily Gulf aviation update — {TODAY_STR} ({total} new entries)"
        committed = git_commit_and_push(REPO_ROOT, msg)
        if committed:
            log.info("🚀 Deployment triggered via git push")
    else:
        log.info("No new entries — skipping git commit")

    log.info("━━━ Update complete ━━━")


# ─────────────────────────────────────────────────────────────────────────
# 7. CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gulf Aviation Tracker — Update Engine")
    parser.add_argument("--dry-run",      action="store_true", help="Search and extract but do not write files")
    parser.add_argument("--force-commit", action="store_true", help="Commit even if no new entries found")
    args = parser.parse_args()

    run_update(dry_run=args.dry_run, force_commit=args.force_commit)
