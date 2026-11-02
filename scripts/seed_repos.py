#!/usr/bin/env python3
"""seed_repos.py — build the repository sample for AGENTS.md Tracker (run once, re-run to extend).

Collects top repositories by stars per language through the GitHub Search API and writes
``data/repos.json``. Only the Python 3.12 standard library is used.

    python3 scripts/seed_repos.py                      # defaults: 10 languages x 200 repos
    python3 scripts/seed_repos.py --per-language 300   # bigger sample (needs more search requests)
    GITHUB_TOKEN=... python3 scripts/seed_repos.py     # 30 search req/min instead of 10

GitHub limits: Search API returns at most 1 000 results per query (10 pages x 100) and allows
10 requests/min without a token, 30 requests/min with one. Rate-limit headers are honoured
(``X-RateLimit-Remaining`` / ``X-RateLimit-Reset`` / ``Retry-After``). Forks and archived repos
are excluded. Existing entries in ``data/repos.json`` are kept (the sample only grows; stars and
default_branch of existing entries are refreshed).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------------------- settings
ROOT = Path(__file__).resolve().parent.parent
REPOS_FILE = ROOT / "data" / "repos.json"
API = "https://api.github.com/search/repositories"
USER_AGENT = "agentsmd-tracker/0.1 (+https://agentsmd.formachines.ai)"
DEFAULT_LANGUAGES = ["Python", "TypeScript", "JavaScript", "Go", "Rust", "Java", "C++", "C#", "Ruby", "PHP"]
DEFAULT_PER_LANGUAGE = 200          # repos per language (<= 1000: Search API hard cap per query)
DEFAULT_MIN_STARS = 1000            # stars:>N in the query
PER_PAGE = 100                      # Search API maximum
PAUSE_NO_TOKEN_S = 6.5              # 10 req/min without a token
PAUSE_TOKEN_S = 2.1                 # 30 req/min with a token
MAX_RETRIES = 5
TIMEOUT_S = 30

log = logging.getLogger("seed")


def _request(url: str, token: str | None) -> tuple[dict, dict]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8")), dict(resp.headers)


def search_page(language: str, min_stars: int, page: int, token: str | None) -> tuple[list[dict], dict]:
    q = f"stars:>{min_stars} language:{language}"
    url = API + "?" + urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": PER_PAGE, "page": page})
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            body, hdrs = _request(url, token)
            return body.get("items", []), hdrs
        except urllib.error.HTTPError as e:
            hdrs = dict(e.headers)
            if e.code in (403, 429):
                wait = _wait_seconds(hdrs)
                log.warning("HTTP %s on %s page %d (attempt %d) — rate limited, sleeping %.0fs", e.code, language, page, attempt, wait)
                time.sleep(wait)
                continue
            if e.code == 422:   # beyond the 1 000-result window
                log.warning("HTTP 422 on %s page %d — result window exhausted", language, page)
                return [], hdrs
            log.error("HTTP %s on %s page %d: %s", e.code, language, page, e.read()[:200])
            time.sleep(5 * attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.error("network error on %s page %d (attempt %d): %s", language, page, attempt, e)
            time.sleep(10 * attempt)
    log.error("giving up on %s page %d", language, page)
    return [], {}


def _wait_seconds(hdrs: dict) -> float:
    ra = hdrs.get("Retry-After") or hdrs.get("retry-after")
    if ra and str(ra).isdigit():
        return float(ra) + 1
    reset = hdrs.get("X-RateLimit-Reset") or hdrs.get("x-ratelimit-reset")
    if reset and str(reset).isdigit():
        return max(5.0, float(reset) - time.time() + 2)
    return 65.0


def _entry(item: dict) -> dict:
    return {
        "id": item["id"],
        "owner": item["owner"]["login"],
        "name": item["name"],
        "full_name": item["full_name"],
        "language": item.get("language") or "Other",
        "stars": item.get("stargazers_count", 0),
        "default_branch": item.get("default_branch") or "main",
        "html_url": item.get("html_url"),
        "pushed_at": item.get("pushed_at"),
        "fork": bool(item.get("fork")),
        "archived": bool(item.get("archived")),
    }


def load_existing() -> dict:
    if REPOS_FILE.exists():
        return json.loads(REPOS_FILE.read_text(encoding="utf-8"))
    return {"generated": None, "query": {}, "repos": []}


def save(doc: dict) -> None:
    REPOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPOS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(REPOS_FILE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--languages", nargs="*", default=DEFAULT_LANGUAGES)
    ap.add_argument("--per-language", type=int, default=DEFAULT_PER_LANGUAGE)
    ap.add_argument("--min-stars", type=int, default=DEFAULT_MIN_STARS)
    ap.add_argument("--pause", type=float, default=None, help="seconds between search requests (default by token)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    token = os.environ.get("GITHUB_TOKEN") or None
    pause = a.pause if a.pause is not None else (PAUSE_TOKEN_S if token else PAUSE_NO_TOKEN_S)
    log.info("seed start: languages=%s per_language=%d min_stars=%d token=%s pause=%.1fs",
             a.languages, a.per_language, a.min_stars, "yes" if token else "no", pause)

    doc = load_existing()
    repos: dict[int, dict] = {r["id"]: r for r in doc.get("repos", [])}
    log.info("existing sample: %d repos", len(repos))

    for lang in a.languages:
        got = 0
        pages = (min(a.per_language, 1000) + PER_PAGE - 1) // PER_PAGE
        for page in range(1, pages + 1):
            items, hdrs = search_page(lang, a.min_stars, page, token)
            remaining = hdrs.get("X-RateLimit-Remaining") or hdrs.get("x-ratelimit-remaining")
            kept = 0
            for it in items:
                e = _entry(it)
                if e["fork"] or e["archived"]:
                    continue
                if got >= a.per_language:
                    break
                old = repos.get(e["id"])
                if old:
                    old.update({k: e[k] for k in ("stars", "default_branch", "pushed_at", "language", "owner", "name", "full_name", "html_url")})
                else:
                    repos[e["id"]] = e
                got += 1
                kept += 1
            log.info("%s page %d: %d items, kept %d, total for language %d, ratelimit remaining %s", lang, page, len(items), kept, got, remaining)
            save({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "query": {"languages": a.languages, "per_language": a.per_language, "min_stars": a.min_stars},
                  "repos": sorted(repos.values(), key=lambda r: -r["stars"])})   # checkpoint after every page
            if not items or got >= a.per_language or len(items) < PER_PAGE:
                break
            time.sleep(pause)
        time.sleep(pause)

    doc = load_existing()
    by_lang: dict[str, int] = {}
    for r in doc["repos"]:
        by_lang[r["language"]] = by_lang.get(r["language"], 0) + 1
    log.info("seed done: %d repos -> %s; by language: %s", len(doc["repos"]), REPOS_FILE, by_lang)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.warning("interrupted — data/repos.json holds everything fetched so far")
        sys.exit(130)
