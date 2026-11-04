#!/usr/bin/env python3
"""build.py — scan the repository sample for agent-instruction files and render the static site.

    python3 build.py                 # scan what is due (never-scanned first, then oldest), then render public/
    python3 build.py --no-scan       # render only, from data/ caches
    python3 build.py --limit 200     # scan at most 200 repos this run (the rest stays "pending")
    python3 build.py --max-seconds 1500

Python 3.12 standard library only. No GitHub token is needed for the scan: file presence and size
come from HEAD requests to raw.githubusercontent.com (``Content-Length``), directory presence from a
HEAD request to the github.com tree URL. Neither counts against the REST API quota. ``GITHUB_TOKEN``
(env) is only used, when present, for the one REST call that confirms a repository still exists
after every path came back 404 (without it the github.com HTML HEAD is used instead).

Data files (all committed):
  data/repos.json               sample (scripts/seed_repos.py)
  data/scan/<owner>__<name>.json {"checked", "status", "default_branch", "files": {path: {"present", "size"}}}
  data/history/<YYYY-MM-DD>.json  counts per type and language, "added"/"removed" versus the previous scan
  data/go.json                  stable /go/<id>/ ids for outbound links (append-only)
"""
from __future__ import annotations

import argparse
import html
import http.client
import json
import logging
import os
import re
import shutil
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# ----------------------------------------------------------------------------- settings
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SCAN_DIR = DATA_DIR / "scan"
HISTORY_DIR = DATA_DIR / "history"
REPOS_FILE = DATA_DIR / "repos.json"
GO_FILE = DATA_DIR / "go.json"
PUBLIC_DIR = ROOT / "public"
STATIC_DIR = ROOT / "static"                       # files copied verbatim into public/ (style.css)

SITE_NAME = "AGENTS.md Tracker"
TITLE_MAX = 70
DESC_MAX = 160
DEFAULT_DESCRIPTION = (f"{SITE_NAME}: daily count of AGENTS.md, CLAUDE.md, .cursorrules, copilot-instructions.md, "
                       "llms.txt and other agent-instruction files in top GitHub repos.")
METHOD = ("Top-by-stars sample of public repositories per language; one HEAD request per tracked path on the default branch; "
          "only presence and size are recorded, never file contents.")
SITE_HOST = "agentsmd.formachines.ai"
FEEDBACK_ISSUES_URL = "https://github.com/formachines-ai/agentsmd-tracker/issues/new"
SITE_BASE = f"https://{SITE_HOST}"
RESPONSIBLE = "Dmitry, formachines.ai"
LEGAL_UPSTREAM = "https://formachines.ai/legal/"
USER_AGENT = "agentsmd-tracker/0.1 (+https://agentsmd.formachines.ai)"

# Tracked paths. kind: "file" (raw HEAD) or "dir" (github.com tree HEAD). Order = display order.
PATHS: list[dict] = [
    {"path": "AGENTS.md", "kind": "file", "label": "AGENTS.md", "note": "cross-tool agent instructions (agents.md spec)"},
    {"path": "CLAUDE.md", "kind": "file", "label": "CLAUDE.md", "note": "Claude Code"},
    {"path": ".cursorrules", "kind": "file", "label": ".cursorrules", "note": "Cursor (legacy single file)"},
    {"path": ".cursor/rules", "kind": "dir", "label": ".cursor/rules/", "note": "Cursor (rules directory)"},
    {"path": ".github/copilot-instructions.md", "kind": "file", "label": "copilot-instructions.md", "note": "GitHub Copilot"},
    {"path": "llms.txt", "kind": "file", "label": "llms.txt", "note": "llms.txt proposal"},
    {"path": "GEMINI.md", "kind": "file", "label": "GEMINI.md", "note": "Gemini CLI"},
    {"path": ".windsurfrules", "kind": "file", "label": ".windsurfrules", "note": "Windsurf"},
]
PRIMARY_PATH = "AGENTS.md"

RAW_BASE = "https://raw.githubusercontent.com"
GH_BASE = "https://github.com"
API_BASE = "https://api.github.com"
PAUSE_S = 0.08                   # between HTTP requests (single thread)
TIMEOUT_S = 20
MAX_429_IN_A_ROW = 5             # then the scan stops and the rest stays pending
BACKOFF_429_S = 60
RESCAN_HOURS = 20                # a repo checked less than this many hours ago is not rescanned
STALE_HOURS = 36                 # no successful scan for this long => "data delayed" banner
FEED_DAYS = 30                   # history window for feed.xml
SPARK_MIN_SPAN_PP = 5.0          # sparkline y-axis never spans less than this many percentage points
BASELINE_DAYS = 14               # show the "baseline" label while history is shorter than this
SPARK_DAYS = 60                  # history window for the sparklines
MAX_TODAY_ITEMS = 200            # feed on the front page

log = logging.getLogger("build")
_stop = {"flag": False}


# ----------------------------------------------------------------------------- small helpers
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        log.error("corrupt JSON %s: %s — ignored", p, e)
        return default


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False), encoding="utf-8")
    tmp.replace(p)


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def scan_file_for(repo: dict) -> Path:
    return SCAN_DIR / f"{repo['owner']}__{repo['name']}.json"


def lang_slug(lang: str) -> str:
    s = lang.lower().replace("++", "-plus-plus").replace("#", "-sharp")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "other"

def pct(n: int, m: int) -> float:
    return round(100.0 * n / m, 1) if m else 0.0


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _handle_sigterm(signum, frame):   # graceful stop: finish current repo, write caches, render
    log.warning("signal %s received — stopping the scan after the current repo", signum)
    _stop["flag"] = True


# ----------------------------------------------------------------------------- HTTP
class RateLimited(Exception):
    pass


_conns: dict[str, "http.client.HTTPSConnection"] = {}


def _conn(host: str, fresh: bool = False):
    c = _conns.get(host)
    if c is None or fresh:
        if c is not None:
            try:
                c.close()
            except OSError:
                pass
        c = http.client.HTTPSConnection(host, timeout=TIMEOUT_S)
        _conns[host] = c
    return c


def head(url: str, token: str | None = None) -> tuple[int, dict]:
    """HEAD request over a kept-alive connection per host. Returns (status, headers).
    Network failure -> (0, {}). 429 (or 403 with Retry-After) -> RateLimited."""
    u = urllib.parse.urlsplit(url)
    path = u.path + (f"?{u.query}" if u.query else "")
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if token and u.netloc == urllib.parse.urlsplit(API_BASE).netloc:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in (1, 2):
        c = _conn(u.netloc, fresh=(attempt == 2))
        try:
            c.request("HEAD", path, headers=headers)
            resp = c.getresponse()
            resp.read()          # HEAD has no body; this releases the connection for reuse
            hdrs = {k: v for k, v in resp.getheaders()}
            if resp.status == 429 or (resp.status == 403 and hdrs.get("Retry-After")):
                raise RateLimited(f"{resp.status} {url} retry-after={hdrs.get('Retry-After')}")
            return resp.status, hdrs
        except RateLimited:
            raise
        except (http.client.HTTPException, TimeoutError, OSError) as e:
            log.debug("HEAD %s attempt %d failed: %s", url, attempt, e)
            if attempt == 2:
                return 0, {}
    return 0, {}


def check_path(repo: dict, spec: dict) -> dict | None:
    """Presence + size of one tracked path. None = network failure (unknown)."""
    full, branch = repo["full_name"], repo.get("default_branch") or "main"
    if spec["kind"] == "file":
        url = f"{RAW_BASE}/{full}/{urllib.parse.quote(branch)}/{spec['path']}"
        status, hdrs = head(url)
        if status == 200:
            size = hdrs.get("Content-Length")
            return {"present": True, "size": int(size) if size and size.isdigit() else None}
        if status in (404, 400):
            return {"present": False, "size": None}
        return None
    url = f"{GH_BASE}/{full}/tree/{urllib.parse.quote(branch)}/{spec['path']}"
    status, _ = head(url)
    if 200 <= status < 400:
        return {"present": True, "size": None}
    if status == 404:
        return {"present": False, "size": None}
    return None


def repo_exists(repo: dict, token: str | None) -> bool | None:
    """True/False, None = unknown. Used only when every path came back absent."""
    if token:
        status, _ = head(f"{API_BASE}/repos/{repo['full_name']}", token)
    else:
        status, _ = head(f"{GH_BASE}/{repo['full_name']}")
    if status == 200:
        return True
    if status in (301, 302, 404, 451):
        return False
    return None


def scan_repo(repo: dict, token: str | None) -> dict:
    files: dict[str, dict] = {}
    unknown = 0
    for spec in PATHS:
        r = check_path(repo, spec)
        time.sleep(PAUSE_S)
        if r is None:
            unknown += 1
            files[spec["path"]] = {"present": None, "size": None}
        else:
            files[spec["path"]] = r
    status = "ok"
    if unknown:
        status = "partial" if unknown < len(PATHS) else "error"
    elif not any(f["present"] for f in files.values()):
        ex = repo_exists(repo, token)
        time.sleep(PAUSE_S)
        if ex is False:
            status = "unreachable"       # moved / deleted / taken down: excluded from the denominators
        elif ex is None:
            status = "error"
    return {"checked": iso(now_utc()), "status": status, "default_branch": repo.get("default_branch") or "main",
            "files": files}


# ----------------------------------------------------------------------------- scan orchestration
def due_repos(repos: list[dict], force: bool) -> list[dict]:
    """Never-scanned and failed first, then by oldest check; skip fresh 'ok' scans unless --force."""
    cutoff = now_utc() - timedelta(hours=RESCAN_HOURS)
    ranked = []
    for r in repos:
        sc = read_json(scan_file_for(r), None)
        if sc is None:
            ranked.append((0, "", r))
            continue
        checked = sc.get("checked") or ""
        try:
            dt = datetime.fromisoformat(checked.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.min.replace(tzinfo=timezone.utc)
        if sc.get("status") in ("error", "partial"):
            ranked.append((1, checked, r))
        elif force or dt < cutoff:
            ranked.append((2, checked, r))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in ranked]


def run_scan(repos: list[dict], limit: int | None, max_seconds: float | None, force: bool) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or None
    todo = due_repos(repos, force)
    log.info("scan: %d repos in sample, %d due (limit=%s, max_seconds=%s, token=%s)", len(repos), len(todo), limit, max_seconds, "yes" if token else "no")
    t0 = time.time()
    stats = {"scanned": 0, "ok": 0, "unreachable": 0, "error": 0, "partial": 0, "rate_limited": False, "stopped": False,
             "added": [], "removed": []}
    consecutive_429 = 0
    for i, repo in enumerate(todo, 1):
        if limit is not None and stats["scanned"] >= limit:
            break
        if max_seconds is not None and time.time() - t0 > max_seconds:
            log.warning("time budget %.0fs exhausted after %d repos", max_seconds, stats["scanned"])
            stats["stopped"] = True
            break
        if _stop["flag"]:
            stats["stopped"] = True
            break
        try:
            new = scan_repo(repo, token)
            consecutive_429 = 0
        except RateLimited as e:
            consecutive_429 += 1
            log.warning("rate limited (%d in a row): %s — sleeping %ds", consecutive_429, e, BACKOFF_429_S)
            if consecutive_429 >= MAX_429_IN_A_ROW:
                log.error("rate limited %d times in a row — stopping the scan, remaining repos stay pending", consecutive_429)
                stats["rate_limited"] = True
                break
            time.sleep(BACKOFF_429_S)
            continue
        prev = read_json(scan_file_for(repo), None)
        if prev and prev.get("status") == "ok" and new["status"] == "ok":
            for spec in PATHS:
                p = spec["path"]
                was = (prev.get("files") or {}).get(p, {}).get("present")
                is_ = new["files"][p]["present"]
                if is_ and was is False:
                    stats["added"].append(_change(repo, p, new))
                elif was and is_ is False:
                    stats["removed"].append(_change(repo, p, new))
        elif prev and prev.get("status") == "ok" and new["status"] in ("error", "partial"):
            # keep the good snapshot, only note the failed attempt
            prev["last_error"] = new["checked"]
            new = prev
        write_json(scan_file_for(repo), new)
        stats["scanned"] += 1
        stats[new["status"]] = stats.get(new["status"], 0) + 1
        present = [p for p, f in new["files"].items() if f["present"]]
        log.info("[%d/%d] %s (%s, %d★) %s %s", i, len(todo), repo["full_name"], repo["language"], repo["stars"], new["status"], present or "-")
    log.info("scan done: %s in %.0fs", {k: v for k, v in stats.items() if k not in ("added", "removed")}, time.time() - t0)
    log.info("added since previous scan: %d, removed: %d", len(stats["added"]), len(stats["removed"]))
    return stats


def _change(repo: dict, path: str, sc: dict) -> dict:
    return {"full_name": repo["full_name"], "owner": repo["owner"], "name": repo["name"], "language": repo["language"],
            "stars": repo["stars"], "path": path, "size": sc["files"][path]["size"],
            "url": file_url(repo, path, sc.get("default_branch"))}


def file_url(repo: dict, path: str, branch: str | None = None) -> str:
    branch = branch or repo.get("default_branch") or "main"
    kind = next((s["kind"] for s in PATHS if s["path"] == path), "file")
    return f"{GH_BASE}/{repo['full_name']}/{'tree' if kind == 'dir' else 'blob'}/{urllib.parse.quote(branch)}/{path}"


# ----------------------------------------------------------------------------- aggregation
def aggregate(repos: list[dict]) -> dict:
    scans = {r["full_name"]: read_json(scan_file_for(r), None) for r in repos}
    ok = [r for r in repos if (scans[r["full_name"]] or {}).get("status") == "ok"]
    pending = [r for r in repos if scans[r["full_name"]] is None or scans[r["full_name"]].get("status") in ("error", "partial")]
    unreachable = [r for r in repos if (scans[r["full_name"]] or {}).get("status") == "unreachable"]
    counts = {s["path"]: 0 for s in PATHS}
    any_count = 0
    by_lang: dict[str, dict] = {}
    for r in ok:
        files = scans[r["full_name"]]["files"]
        lang = r["language"]
        bl = by_lang.setdefault(lang, {"repos": 0, "any": 0, **{s["path"]: 0 for s in PATHS}})
        bl["repos"] += 1
        has_any = False
        for s in PATHS:
            if files.get(s["path"], {}).get("present"):
                counts[s["path"]] += 1
                bl[s["path"]] += 1
                has_any = True
        if has_any:
            any_count += 1
            bl["any"] += 1
    last_checked = max((scans[r["full_name"]]["checked"] for r in ok), default=None)
    return {"scans": scans, "ok": ok, "pending": pending, "unreachable": unreachable, "counts": counts,
            "any": any_count, "by_lang": by_lang, "last_checked": last_checked}


def update_history(agg: dict, scan_stats: dict | None, write: bool = True) -> dict:
    if not write:   # nothing was scanned: never create or move a dated row; report the last real scan as-is
        last = load_history()
        if last:
            return last[-1]
    scan_time = iso(now_utc())   # the one clock reading of a real scan; the date is derived from it
    today = scan_time[:10]
    hfile = HISTORY_DIR / f"{today}.json"
    doc = read_json(hfile, {"date": today, "added": [], "removed": []})
    if scan_stats:   # union with earlier runs of the same day
        for key in ("added", "removed"):
            seen = {(x["full_name"], x["path"]) for x in doc.get(key, [])}
            for x in scan_stats[key]:
                if (x["full_name"], x["path"]) not in seen:
                    doc.setdefault(key, []).append(x)
                    seen.add((x["full_name"], x["path"]))
    doc.update({
        "date": today,
        "generated": scan_time,
        "sample": len(agg["ok"]) + len(agg["pending"]) + len(agg["unreachable"]),
        "scanned": len(agg["ok"]),
        "pending": len(agg["pending"]),
        "unreachable": len(agg["unreachable"]),
        "counts": agg["counts"],
        "any": agg["any"],
        "by_language": {k: {"repos": v["repos"], **{s["path"]: v[s["path"]] for s in PATHS}} for k, v in sorted(agg["by_lang"].items())},
    })
    if write:
        write_json(hfile, doc)
    log.info("history %s: scanned=%d pending=%d counts=%s added=%d removed=%d", today, doc["scanned"], doc["pending"], doc["counts"], len(doc["added"]), len(doc["removed"]))
    return doc


def load_history() -> list[dict]:
    days = []
    for p in sorted(HISTORY_DIR.glob("*.json")):
        d = read_json(p, None)
        if d and d.get("scanned"):
            days.append(d)
    return days


# ----------------------------------------------------------------------------- go links
class GoLinks:
    def __init__(self):
        self.doc = read_json(GO_FILE, {"next_id": 1, "links": {}})
        self.doc.setdefault("next_id", 1)
        self.doc.setdefault("links", {})

    def id_for(self, repo: dict, path: str, url: str) -> int:
        key = f"{repo['full_name']}/{path}"
        entry = self.doc["links"].get(key)
        if entry is None:
            entry = {"id": self.doc["next_id"], "url": url, "repo": repo["full_name"], "path": path}
            self.doc["links"][key] = entry
            self.doc["next_id"] += 1
        elif entry["url"] != url:      # default branch renamed etc. — same id, new target
            entry["url"] = url
        return entry["id"]

    def href(self, repo: dict, path: str, url: str) -> str:
        return f"/go/{self.id_for(repo, path, url)}/"

    def save(self) -> None:
        write_json(GO_FILE, self.doc)

    def render(self, out: Path) -> int:
        n = 0
        for key, e in self.doc["links"].items():
            write_text(out / "go" / str(e["id"]) / "index.html", page_go(e))
            n += 1
        return n


# ----------------------------------------------------------------------------- rendering
def clamp(text: str, limit: int) -> str:
    """Shorten text to at most `limit` chars, cutting at a word boundary and ending with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-—·")
    return cut + "…"


def jsonld_block(data: dict) -> str:
    """JSON-LD script; '<' is escaped so the payload can never close the tag."""
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + "</script>"


def layout(title: str, body: str, updated: str, *, description: str = "", canonical: str = "", extra_head: str = "",
           jsonld: dict | None = None) -> str:
    title = clamp(title, TITLE_MAX)
    desc = clamp(description or DEFAULT_DESCRIPTION, DESC_MAX)
    canon = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ""
    og = (f'<meta property="og:title" content="{esc(title)}">\n<meta property="og:description" content="{esc(desc)}">\n'
          f'<meta property="og:type" content="website">\n<meta property="og:site_name" content="{esc(SITE_NAME)}">\n')
    og += f'<meta property="og:url" content="{esc(canonical or SITE_BASE + "/")}">\n'
    if jsonld:
        og += jsonld_block(jsonld) + "\n"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="color-scheme" content="light dark">
<meta name="generator" content="agentsmd-tracker build.py (AI agents, no human editing)">
{canon}
{og}<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/style.css">
<link rel="alternate" type="application/rss+xml" title="New AGENTS.md files" href="/feed.xml">
{extra_head}
</head>
<body>
<header class="top">
<a class="brand" href="/">{esc(SITE_NAME)}</a>
<nav><a href="/#languages">Languages</a> <a href="/#today">Added today</a> <a href="/stats.json">stats.json</a> <a href="/feed.xml">RSS</a> <a href="/llms.txt">llms.txt</a> <a href="/legal/">Legal</a></nav>
</header>
<main>
{body}
</main>
<footer>
<p>Built by AI agents (agent-team) without human editing · responsible: {esc(RESPONSIBLE)} · updated {esc(updated)}</p>
<p>Data: public GitHub API and raw file HEAD requests; only presence, size and links are published — file contents are never republished. Stats are CC BY 4.0. No tracking, no cookies, no JavaScript. <a href="/legal/">Legal</a> · <a href="https://github.com/formachines-ai/agentsmd-tracker">Source</a></p>
</footer>
</body>
</html>
"""


def webpage_ld(name: str, url: str, modified: str) -> dict:
    return {"@context": "https://schema.org", "@type": "WebPage", "name": clamp(name, TITLE_MAX), "url": url,
            "dateModified": modified, "inLanguage": "en", "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": SITE_BASE + "/"}}


def sparkline(values: list[float], width: int = 260, height: int = 48, label: str = "") -> str:
    """Inline SVG line of daily values (percent). No JS."""
    if not values:
        return ""
    # fixed minimum span (SPARK_MIN_SPAN_PP percentage points): tiny changes stay tiny
    vmax = max(values)
    span = max(vmax - min(values), SPARK_MIN_SPAN_PP)
    vmin = max(0.0, (vmax + min(values)) / 2 - span / 2)
    pad = 4
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad + (width - 2 * pad) * (i / (n - 1) if n > 1 else 0.5)
        y = height - pad - (height - 2 * pad) * ((v - vmin) / span)
        pts.append((round(x, 1), round(y, 1)))
    poly = " ".join(f"{x},{y}" for x, y in pts)
    circles = "".join(f'<circle cx="{x}" cy="{y}" r="2.5" class="dot"/>' for x, y in pts) if n <= 90 else ""
    title = esc(label or "daily share")
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{title}">'
            f'<title>{title}</title><polyline points="{poly}" fill="none" class="line"/>{circles}</svg>')


def page_go(e: dict) -> str:
    url = e["url"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url={esc(url)}">
<meta name="robots" content="noindex">
<title>Redirecting to GitHub — {esc(e['repo'])}/{esc(e['path'])}</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/style.css"></head>
<body><main><p>Redirecting to <a href="{esc(url)}">{esc(url)}</a> …</p>
<p class="muted">Outbound link {e['id']} from <a href="/">{esc(SITE_NAME)}</a>. This page only forwards you to GitHub; it records nothing beyond the server's standard access log.</p></main>
<footer><p>Built by AI agents (agent-team) without human editing · responsible: {esc(RESPONSIBLE)}</p></footer></body></html>
"""


def page_vote(r: dict, direction: str) -> str:
    back = f"/repo/{r['owner']}/{r['name']}/"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url={esc(back)}">
<meta name="robots" content="noindex">
<title>Thanks — {esc(r['full_name'])}</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/style.css"></head>
<body><main><p>Noted ({'useful' if direction == 'up' else 'not useful'}). Returning to <a href="{esc(back)}">{esc(r['full_name'])}</a> …</p>
<p class="muted">This page only forwards you back; it records nothing beyond the server's standard access log.</p></main>
<footer><p>Built by AI agents (agent-team) without human editing · responsible: {esc(RESPONSIBLE)}</p></footer></body></html>
"""


def feedback_links(r: dict) -> str:
    rid = r["id"]
    title = urllib.parse.quote(f"Error on /repo/{r['full_name']}/: ")
    return (f'<p class="feedback muted">Was this useful? <a href="/go/vote/{rid}/up/" rel="nofollow">useful</a> · '
            f'<a href="/go/vote/{rid}/down/" rel="nofollow">not useful</a> · '
            f'<a href="{FEEDBACK_ISSUES_URL}?title={title}" rel="nofollow">Report an error</a></p>')


def render_site(repos: list[dict], agg: dict, history: list[dict], today: dict, build_info: dict) -> None:
    updated = build_info["built_at"]
    go = GoLinks()
    out = PUBLIC_DIR
    # fresh public/: keep nothing stale, but write into place (publish.sh rsyncs the committed directory)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if STATIC_DIR.exists():
        for p in STATIC_DIR.iterdir():
            if p.is_file():
                shutil.copy2(p, out / p.name)
            elif p.is_dir():
                shutil.copytree(p, out / p.name)

    scans = agg["scans"]
    total = len(agg["ok"])
    sample = len(repos)
    delayed = build_info["data_delayed"]

    # ---- index
    banner = ""
    if delayed:
        banner = f'<div class="banner warn"><strong>Data delayed.</strong> {esc(build_info["delay_reason"])} Numbers below are from the last successful scan.</div>'
    elif agg["pending"]:
        banner = f'<div class="banner"><strong>Partial scan:</strong> {len(agg["pending"])} of {sample} repositories are still pending; percentages use the {total} scanned so far.</div>'

    cards = []
    for s in PATHS:
        p = s["path"]
        n = agg["counts"][p]
        series = [pct(d["counts"].get(p, 0), d["scanned"]) for d in history[-SPARK_DAYS:]]
        cards.append(f"""<section class="card">
<h2><code>{esc(s['label'])}</code></h2>
<p class="big">{n:,} <span class="of">of {total:,}</span></p>
<p class="share">{pct(n, total)} % of scanned repos · {esc(s['note'])}</p>
{sparkline(series, label=f"{s['label']} share by day")}
</section>""")
    any_n = agg["any"]
    gen_raw = today.get("generated") or (history[-1].get("generated") if history else None) or updated  # same value as stats.json 'generated'
    gen_txt = gen_raw[:10] + " " + gen_raw[11:16]
    stale_txt = "" if gen_raw[:10] == updated[:10] else f" (not today's: scan dated {gen_raw[:10]})"
    hero = f"""<section class="hero">
<h1>{agg['counts'][PRIMARY_PATH]:,} of {total:,} top GitHub repositories ({pct(agg['counts'][PRIMARY_PATH], total)} %) have an <code>AGENTS.md</code></h1>
<p class="lead">{any_n:,} ({pct(any_n, total)} %) have at least one agent-instruction file of the {len(PATHS)} kinds tracked here. Sample: {sample:,} public repositories, top by stars across {len(agg['by_lang']) or '—'} languages, rescanned daily. Only presence, size and a link are recorded — never the contents.</p>
<p class="asof"><strong>Latest published scan: {esc(gen_txt)} UTC.</strong> A new scan starts daily at 04:00 UTC; results are published when it finishes. Numbers on this page are from the latest published scan{esc(stale_txt)}.</p>
<p class="limit">What this share measures: whether a listed file path exists at one of its fixed conventional locations on the default branch (AGENTS.md, CLAUDE.md, GEMINI.md, llms.txt, .cursorrules and .windsurfrules at the repository root; .github/copilot-instructions.md; .cursor/rules/), in a sample of popular repositories per language. It is file presence only — not the quality or use of a file, and not all of GitHub.</p>
<p class="paths"><a href="#languages">Explore your language</a> · <a href="#method">See the sampling method</a></p>
</section>"""

    # language table
    rows = []
    for lang, v in sorted(agg["by_lang"].items(), key=lambda kv: -kv[1]["repos"]):
        cells = "".join(f'<td>{v[s["path"]]}<span class="pc"> ({pct(v[s["path"]], v["repos"])} %)</span></td>' for s in PATHS)
        rows.append(f"<tr><th scope=\"row\"><a href=\"/lang/{lang_slug(lang)}/\">{esc(lang)}</a></th><td>{v['repos']}</td><td>{v['any']}<span class=\"pc\"> ({pct(v['any'], v['repos'])} %)</span></td>{cells}</tr>")
    heads = "".join(f'<th><code>{esc(s["label"])}</code></th>' for s in PATHS)
    lang_table = f"""<section id="languages">
<h2>By language</h2>
<div class="scroll"><table>
<thead><tr><th>Language</th><th>Repos</th><th>Any file</th>{heads}</tr></thead>
<tbody>{''.join(rows)}</tbody>
<tfoot><tr><th scope="row">All</th><td>{total}</td><td>{any_n}<span class="pc"> ({pct(any_n, total)} %)</span></td>{''.join(f'<td>{agg["counts"][s["path"]]}<span class="pc"> ({pct(agg["counts"][s["path"]], total)} %)</span></td>' for s in PATHS)}</tr></tfoot>
</table></div>
</section>"""

    # today feed
    added = sorted(today.get("added", []), key=lambda x: (-x["stars"], x["full_name"]))
    removed = today.get("removed", [])
    if added:
        items = []
        for x in added[:MAX_TODAY_ITEMS]:
            repo = {"full_name": x["full_name"], "owner": x["owner"], "name": x["name"]}
            size = f", {x['size']:,} bytes" if x.get("size") else ""
            items.append(f'<li><a href="/repo/{esc(x["owner"])}/{esc(x["name"])}/">{esc(x["full_name"])}</a> <span class="muted">({esc(x["language"])}, {x["stars"]:,}★)</span> added <a href="{go.href(repo, x["path"], x["url"])}" rel="nofollow"><code>{esc(x["path"])}</code></a><span class="muted">{size}</span></li>')
        today_html = f"<ul class=\"feed\">{''.join(items)}</ul>"
        if len(added) > MAX_TODAY_ITEMS:
            today_html += f'<p class="muted">… and {len(added) - MAX_TODAY_ITEMS} more — see <a href="/today.json">today.json</a>.</p>'
    else:
        first_day = len(history) <= 1
        today_html = ('<p class="muted">Baseline day: the first scan establishes what exists; additions are counted from the next scan on.</p>'
                      if first_day else '<p class="muted">Nothing new since the previous scan. Additions are detected when a tracked file is present today and was absent in the previous snapshot.</p>')
    removed_html = ""
    if removed:
        removed_html = "<h3>Removed today</h3><ul class=\"feed\">" + "".join(
            f'<li><a href="/repo/{esc(x["owner"])}/{esc(x["name"])}/">{esc(x["full_name"])}</a> removed <code>{esc(x["path"])}</code></li>' for x in removed) + "</ul>"
    today_sec = f"""<section id="today">
<h2>Added today <span class="muted">(scan of {esc(today.get('date', ''))} UTC)</span></h2>
{today_html}
{removed_html}
<p class="muted">Machine-readable: <a href="/today.json">today.json</a> · <a href="/stats.json">stats.json</a> · <a href="/feed.xml">RSS of new AGENTS.md files</a>.</p>
</section>"""

    # history table (last 14 days)
    hist_rows = "".join(
        f"<tr><td>{esc(d['date'])}</td><td>{d['scanned']}</td>" + "".join(f"<td>{d['counts'].get(s['path'], 0)}</td>" for s in PATHS) + "</tr>"
        for d in reversed(history[-14:]))
    hist_sec = f"""<section id="history">
<h2>By day</h2>
<div class="scroll"><table><thead><tr><th>Date (UTC)</th><th>Scanned</th>{heads}</tr></thead><tbody>{hist_rows}</tbody></table></div>
<p class="muted">Counts are absolute; the sample can grow, so compare shares (see the sparklines above) rather than raw counts across days. Full history: <a href="/stats.json">stats.json</a>.</p>
</section>"""

    method = f"""<section id="method">
<h2>How it works</h2>
<ul>
<li><strong>Sample.</strong> {sample:,} public, non-fork, non-archived repositories with the most stars per language (GitHub Search API, collected once and extended over time). {len(agg['unreachable'])} are currently unreachable (moved or removed) and excluded.</li>
<li><strong>Check.</strong> Once a day a HEAD request per path against the default branch: a <code>200</code> means the file exists, <code>Content-Length</code> is its size. <code>.cursor/rules/</code> is checked as a directory. Names are matched case-sensitively, exactly as the conventions spell them.</li>
<li><strong>Paths checked.</strong> Only these fixed locations on the default branch: AGENTS.md, CLAUDE.md, GEMINI.md, llms.txt, .cursorrules and .windsurfrules at the repository root, plus .github/copilot-instructions.md and .cursor/rules/ ({', '.join(esc(x['label']) for x in PATHS)}). Nested files, for example in subdirectories or packages, are not checked.</li>
<li><strong>Added today.</strong> A path present in today's scan and absent in the previous snapshot of the same repository. Links go to the file on GitHub via <code>/go/&lt;id&gt;/</code>, a plain redirect page.</li>
<li><strong>Languages.</strong> Each language in the table above has a full list of its sampled repositories (every sampled repository is listed) at <code>/lang/&lt;slug&gt;/</code>, for example <a href="/lang/python/">/lang/python/</a>.</li>
<li><strong>Baseline.</strong> A repository seen for the first time is baseline: files it already has are counted, but not shown as added.</li>
<li><strong>Not done.</strong> No file contents are stored or shown. No accounts, no cookies, no JavaScript, no tracking of visitors.</li>
</ul>
</section>"""
    day = updated[:10]
    scan_day = gen_raw[:10]
    cite = (f'<p class="cite muted">Cite as: {esc(SITE_NAME)}, {esc(SITE_HOST)}, scan of {esc(scan_day)}, CC BY 4.0. '
            f'Values for each date stay in <a href="/stats.json">{esc(SITE_BASE)}/stats.json</a> history[].</p>')
    base_note = ""
    if history and len(history) < BASELINE_DAYS:
        base_note = (f'<p class="muted baseline">baseline: {len(history)} days since {esc(history[0]["date"])}. '
                     f'Sparkline axes span at least {SPARK_MIN_SPAN_PP:g} percentage points, so small day-to-day changes look small.</p>')

    home_desc = (f"{agg['counts'][PRIMARY_PATH]:,} of {total:,} top GitHub repos have AGENTS.md ({pct(agg['counts'][PRIMARY_PATH], total)} %). "
                 "Daily tracker of CLAUDE.md, .cursorrules, llms.txt and more.")
    home_ld = {"@context": "https://schema.org", "@type": "Dataset", "name": f"{SITE_NAME}: agent-instruction files in top GitHub repositories",
               "description": home_desc, "url": SITE_BASE + "/", "license": "https://creativecommons.org/licenses/by/4.0/",
               "dateModified": updated, "isAccessibleForFree": True, "inLanguage": "en",
               "creator": {"@type": "Organization", "name": "formachines.ai", "url": "https://formachines.ai/"},
               "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": SITE_BASE + "/stats.json"},
                                {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": SITE_BASE + "/today.json"}]}
    write_text(out / "index.html", layout(f"{SITE_NAME} — AGENTS.md adoption in top GitHub repos",
                                           banner + hero + cite + base_note + '<div class="cards">' + "".join(cards) + '</div>' + today_sec + lang_table + hist_sec + method,
                                           updated, canonical=SITE_BASE + "/", description=home_desc, jsonld=home_ld))

    # ---- repo pages
    urls = [SITE_BASE + "/", SITE_BASE + "/legal/", SITE_BASE + "/brand/"]
    scan_date = (today.get("generated") or (history[-1].get("generated") if history else None) or updated)[:10]   # date part of stats.json 'generated'
    first_scan_day = history[0]["date"] if history else None
    added_on: dict[tuple[str, str], str] = {}   # (repo, path) -> earliest scan day it was recorded as added
    for d in history:
        for x in d.get("added", []):
            added_on.setdefault((x["full_name"], x["path"]), d["date"])
    for r in sorted(repos, key=lambda r: r["full_name"].lower()):
        sc = scans.get(r["full_name"])
        rdir = out / "repo" / r["owner"] / r["name"]
        files_json = {}
        rows = []
        lv = agg["by_lang"].get(r.get("language") or "")
        for s in PATHS:
            shown = s["path"] + ("/" if s["kind"] == "dir" else "")
            share = (f'<br><span class="muted">{lv[s["path"]]:,} of {lv["repos"]:,} sampled {esc(r["language"])} repos ({pct(lv[s["path"]], lv["repos"])} %) on {esc(scan_date)}</span>'
                     if lv and lv["repos"] else "")
            f = (sc or {}).get("files", {}).get(s["path"], {"present": None, "size": None})
            present = f.get("present")
            url = file_url(r, s["path"], (sc or {}).get("default_branch"))
            files_json[s["path"]] = {"present": present, "size": f.get("size"), "url": url if present else None}
            seen_note = ""
            if present:
                fs_day = added_on.get((r["full_name"], s["path"]))
                if fs_day:
                    seen_note = f'<br><span class="muted">first seen in our scans: {esc(fs_day)}</span>'
                    files_json[s["path"]]["first_seen"] = fs_day
                elif first_scan_day:
                    seen_note = f'<br><span class="muted">first seen in our scans: {esc(first_scan_day)} (present at first scan; earlier date unknown)</span>'
                    files_json[s["path"]]["first_seen"] = first_scan_day
                    files_json[s["path"]]["first_seen_at_first_scan"] = True
                share += seen_note
            if present:
                size = f"{f['size']:,} bytes" if f.get("size") else ("directory" if s["kind"] == "dir" else "—")
                rows.append(f'<tr><td><code>{esc(shown)}</code>{share}</td><td class="yes">yes</td><td>{size}</td><td><a href="{go.href(r, s["path"], url)}" rel="nofollow">open on GitHub</a></td></tr>')
            elif present is False:
                rows.append(f'<tr><td><code>{esc(shown)}</code>{share}</td><td class="no">no</td><td>—</td><td></td></tr>')
            else:
                rows.append(f'<tr><td><code>{esc(shown)}</code>{share}</td><td class="muted">not checked yet</td><td>—</td><td></td></tr>')
        status = (sc or {}).get("status", "pending")
        checked = (sc or {}).get("checked", "—")
        lang_line = (f'<p><a href="/lang/{lang_slug(r["language"])}/">Other {esc(r["language"])} repos in the sample →</a></p>\n'
                     if r.get("language") else "")
        body = f"""<section>
<p class="crumb"><a href="/">{esc(SITE_NAME)}</a> › repo</p>
<h1>{esc(r['full_name'])}</h1>
<p class="lead">{esc(r['language'])} · {r['stars']:,} stars · default branch <code>{esc((sc or {}).get('default_branch') or r.get('default_branch') or 'main')}</code> · <a href="{esc(r.get('html_url') or GH_BASE + '/' + r['full_name'])}" rel="nofollow">repository on GitHub</a></p>
<p class="muted">Scan status: {esc(status)} · last checked {esc(checked)} · <a href="/repo/{esc(r['owner'])}/{esc(r['name'])}/index.json">index.json</a></p>
<div class="scroll"><table><thead><tr><th>Path</th><th>Present</th><th>Size</th><th>Link</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{lang_line}{feedback_links(r)}
<p class="muted">Only presence, size and a link are published; the file contents belong to the repository and are not reproduced here.</p>
</section>"""
        write_text(rdir / "index.html", layout(f"{r['full_name']} — {SITE_NAME}", body, updated,
                                              description=f"Does {r['full_name']} have AGENTS.md, CLAUDE.md, .cursorrules, copilot-instructions.md or llms.txt? Daily check by {SITE_NAME}.",
                                              canonical=f"{SITE_BASE}/repo/{r['owner']}/{r['name']}/",
                                              jsonld=webpage_ld(f"{r['full_name']} — {SITE_NAME}", f"{SITE_BASE}/repo/{r['owner']}/{r['name']}/", updated)))
        for d in ("up", "down"):
            write_text(out / "go" / "vote" / str(r["id"]) / d / "index.html", page_vote(r, d))
        write_json(rdir / "index.json", {"repo": r["full_name"], "owner": r["owner"], "name": r["name"], "language": r["language"],
                                          "stars": r["stars"], "default_branch": (sc or {}).get("default_branch") or r.get("default_branch"),
                                          "status": status, "checked": checked if sc else None, "files": files_json,
                                          "page": f"{SITE_BASE}/repo/{r['owner']}/{r['name']}/", "license": "CC BY 4.0"})
        urls.append(f"{SITE_BASE}/repo/{r['owner']}/{r['name']}/")

    # ---- JSON endpoints
    generated = today.get("generated") or (history[-1].get("generated") if history else None) or updated  # time of the last real scan
    stats = {
        "site": SITE_BASE, "generated": generated, "license": "CC BY 4.0", "data_delayed": delayed,
        "method": METHOD, "attribution": f"{SITE_NAME}, {SITE_HOST}, {generated[:10]}, CC BY 4.0",
        "sample": sample, "scanned": total, "pending": len(agg["pending"]), "unreachable": len(agg["unreachable"]),
        "paths": [s["path"] for s in PATHS],
        "counts": agg["counts"], "any": agg["any"],
        "shares": {s["path"]: pct(agg["counts"][s["path"]], total) for s in PATHS},
        "by_language": {k: {"repos": v["repos"], "any": v["any"], **{s["path"]: v[s["path"]] for s in PATHS}} for k, v in sorted(agg["by_lang"].items())},
        "history": [{"date": d["date"], "scanned": d["scanned"], "counts": d["counts"], "any": d.get("any"),
                     "added": len(d.get("added", [])), "removed": len(d.get("removed", []))} for d in history],
    }
    write_json(out / "stats.json", stats)
    write_json(out / "today.json", {"site": SITE_BASE, "date": today.get("date"), "generated": generated, "license": "CC BY 4.0",
                                    "added": added, "removed": removed, "counts": agg["counts"], "scanned": total, "pending": len(agg["pending"])})
    write_json(out / "build.json", build_info)

    # ---- feed.xml (new AGENTS.md)
    items = []
    for d in reversed(history[-FEED_DAYS:]):
        for x in sorted([a for a in d.get("added", []) if a["path"] == PRIMARY_PATH], key=lambda x: -x["stars"]):
            repo = {"full_name": x["full_name"], "owner": x["owner"], "name": x["name"]}
            link = SITE_BASE + go.href(repo, x["path"], x["url"])
            items.append(f"""<item>
<title>{xml_escape(x['full_name'])} added AGENTS.md</title>
<link>{xml_escape(link)}</link>
<guid isPermaLink="false">{xml_escape(d['date'] + ':' + x['full_name'] + ':' + x['path'])}</guid>
<pubDate>{_rfc822(d['date'])}</pubDate>
<description>{xml_escape(f"{x['full_name']} ({x['language']}, {x['stars']:,} stars) now has an AGENTS.md" + (f" ({x['size']:,} bytes)" if x.get('size') else '') + f". Repo card: {SITE_BASE}/repo/{x['owner']}/{x['name']}/")}</description>
</item>""")
    if history:
        d0 = history[0]
        items.append(f"""<item>
<title>Baseline {xml_escape(d0['date'])}: {d0['counts'].get(PRIMARY_PATH, 0)} of {d0['scanned']} top repos have AGENTS.md</title>
<link>{xml_escape(SITE_BASE + '/')}</link>
<guid isPermaLink="false">baseline:{xml_escape(d0['date'])}</guid>
<pubDate>{_rfc822(d0['date'])}</pubDate>
<description>{xml_escape(f"Tracking started. {d0['counts'].get(PRIMARY_PATH, 0)} of {d0['scanned']} scanned repositories ({pct(d0['counts'].get(PRIMARY_PATH, 0), d0['scanned'])} %) had an AGENTS.md on the first day. New files appear here from the second day on.")}</description>
</item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{xml_escape(SITE_NAME)} — new AGENTS.md files</title>
<link>{xml_escape(SITE_BASE + '/')}</link>
<atom:link href="{xml_escape(SITE_BASE + '/feed.xml')}" rel="self" type="application/rss+xml"/>
<description>Top GitHub repositories that added an AGENTS.md since the previous daily scan. Built by AI agents (agent-team), responsible: {xml_escape(RESPONSIBLE)}.</description>
<language>en</language>
<lastBuildDate>{_rfc822_dt(now_utc())}</lastBuildDate>
{''.join(items)}
</channel>
</rss>
"""
    write_text(out / "feed.xml", feed)

    # ---- language pages
    for lang, v in sorted(agg["by_lang"].items()):
        slug = lang_slug(lang)
        lrepos = sorted((r for r in agg["ok"] if r["language"] == lang), key=lambda r: r["full_name"].lower())
        trs = []
        agents_items = []
        for r in lrepos:
            sc = scans[r["full_name"]]
            fl = sc["files"]
            cells = ""
            for sp in PATHS:
                f = fl.get(sp["path"], {})
                if f.get("present"):
                    href = go.href(r, sp["path"], file_url(r, sp["path"], sc.get("default_branch")))
                    cells += f'<td class="yes"><a href="{href}" rel="nofollow">yes</a></td>'
                else:
                    cells += '<td class="no">no</td>'
            trs.append(f'<tr><th scope="row"><a href="/repo/{esc(r["owner"])}/{esc(r["name"])}/">{esc(r["full_name"])}</a></th>{cells}</tr>')
            fa = fl.get(PRIMARY_PATH, {})
            if fa.get("present"):
                href = go.href(r, PRIMARY_PATH, file_url(r, PRIMARY_PATH, sc.get("default_branch")))
                sz = f' <span class="muted">({fa["size"]:,} bytes)</span>' if fa.get("size") else ""
                agents_items.append(f'<li><a href="/repo/{esc(r["owner"])}/{esc(r["name"])}/">{esc(r["full_name"])}</a> · <a href="{href}" rel="nofollow">AGENTS.md on GitHub</a>{sz}</li>')
        agents_sec = (f'<h2>AGENTS.md in {esc(lang)} ({len(agents_items)})</h2>\n'
                      + (f'<ul class="plain">{"".join(agents_items)}</ul>' if agents_items else '<p class="muted">None of the sampled repositories has AGENTS.md yet.</p>')
                      + '\n<h2>All sampled repositories</h2>\n')
        heads = "".join(f'<th><code>{esc(sp["label"])}</code></th>' for sp in PATHS)
        body = f"""<section>
<p class="crumb"><a href="/">{esc(SITE_NAME)}</a> › <a href="/#languages">languages</a> › {esc(lang)}</p>
<h1>{esc(lang)} repositories</h1>
<p class="lead">{v['repos']:,} of {total:,} scanned repositories ({pct(v['repos'], total)} %) are {esc(lang)}; {v[PRIMARY_PATH]} ({pct(v[PRIMARY_PATH], v['repos'])} %) have AGENTS.md. Data as of {esc(updated)}. Source: public GitHub, presence checks only; stats CC BY 4.0, cite as "{esc(SITE_NAME)}, {esc(SITE_HOST)}".</p>
<p class="muted">Sorted alphabetically by owner/name — not a ranking.</p>
{agents_sec}<div class="scroll"><table><thead><tr><th>Repository</th>{heads}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>
</section>"""
        write_text(out / "lang" / slug / "index.html", layout(f"{lang} repos — {SITE_NAME}", body, updated,
                   description=f"Which of the {v['repos']} sampled {lang} repositories have AGENTS.md, CLAUDE.md, .cursorrules and other agent-instruction files.",
                   canonical=f"{SITE_BASE}/lang/{slug}/",
                   jsonld=webpage_ld(f"{lang} repos — {SITE_NAME}", f"{SITE_BASE}/lang/{slug}/", updated)))
        urls.append(f"{SITE_BASE}/lang/{slug}/")

    # ---- llms.txt, robots.txt, sitemap.xml, 404, legal, go pages
    write_text(out / "llms.txt", f"""# {SITE_NAME}

> Daily tracker of agent-instruction files in top GitHub repositories: which of {sample:,} public repositories (top by stars per language) have AGENTS.md, CLAUDE.md, .cursorrules, .cursor/rules/, .github/copilot-instructions.md, llms.txt, GEMINI.md, .windsurfrules. Only presence, size and a link to GitHub are published; file contents are never republished. Built by AI agents (agent-team) without human editing; responsible: {RESPONSIBLE}. Data CC BY 4.0.

Latest ({updated}): {agg['counts'][PRIMARY_PATH]} of {total} scanned repos ({pct(agg['counts'][PRIMARY_PATH], total)} %) have AGENTS.md; {agg['counts']['CLAUDE.md']} CLAUDE.md; {agg['counts']['.cursorrules']} .cursorrules; {agg['counts']['.github/copilot-instructions.md']} copilot-instructions.md; {agg['counts']['llms.txt']} llms.txt.

## Machine-readable
- [stats.json]({SITE_BASE}/stats.json): totals, shares, by-language table, full daily history
- [today.json]({SITE_BASE}/today.json): files added/removed since the previous scan
- [feed.xml]({SITE_BASE}/feed.xml): RSS of repositories that added AGENTS.md
- [build.json]({SITE_BASE}/build.json): build time, scan status, data-delayed flag
- Repo card JSON: {SITE_BASE}/repo/<owner>/<name>/index.json (same fields as the HTML card)

## Pages
- [Home]({SITE_BASE}/): headline numbers, added-today feed, by-language table, by-day table, method
- [Language page]({SITE_BASE}/lang/<slug>/): every sampled repo of one language (e.g. /lang/go/, /lang/c-plus-plus/) with yes/no per tracked path, alphabetical
- [Repo card]({SITE_BASE}/repo/<owner>/<name>/): per-repository presence table with links
- [Legal]({SITE_BASE}/legal/): responsible person, data source, licence

## Rules for reuse
- Cite as "{SITE_NAME}, {SITE_HOST}, <date>". Attribution satisfies CC BY 4.0.
- Do not infer file contents from this site; follow the GitHub link and respect each repository's licence.
""")
    write_text(out / "robots.txt", f"User-agent: *\nAllow: /\nDisallow: /go/\n\nSitemap: {SITE_BASE}/sitemap.xml\n")
    write_text(out / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"<url><loc>{xml_escape(u)}</loc></url>\n" for u in urls) + "</urlset>\n")
    write_text(out / "404.html", layout("Page not found — " + SITE_NAME, f"""<section>
<h1>404 — page not found</h1>
<p>This address does not exist on {esc(SITE_NAME)}. Addresses never change once published, so the link you followed was probably mistyped.</p>
<ul>
<li><a href="/">Home: headline numbers and today's additions</a></li>
<li>Repository cards live at <code>/repo/&lt;owner&gt;/&lt;name&gt;/</code> — the repository must be in the sample ({sample:,} repos).</li>
<li><a href="/stats.json">stats.json</a> · <a href="/today.json">today.json</a> · <a href="/feed.xml">RSS</a> · <a href="/llms.txt">llms.txt</a> · <a href="/legal/">Legal</a></li>
</ul>
</section>""", updated))
    write_text(out / "legal" / "index.html", layout("Legal — " + SITE_NAME, f"""<section>
<h1>Legal</h1>
<h2>Who is responsible</h2>
<p>This website is produced and operated by AI agents (agent-team) without human editing of its pages. The responsible person is <strong>{esc(RESPONSIBLE)}</strong>. Contact and the full legal notice: <a href="{esc(LEGAL_UPSTREAM)}">{esc(LEGAL_UPSTREAM)}</a>.</p>
<h2>What the data is</h2>
<p>All figures are derived from public data of GitHub (REST Search API for the sample; HTTP HEAD requests to public file URLs for presence and size). The site records, for each repository in the sample, whether a handful of well-known file names exist on the default branch and how large they are. It stores and shows <strong>no file contents</strong>. Repository names, languages and star counts are public facts about public repositories.</p>
<h2>Licence</h2>
<p>The statistics and JSON endpoints published here (<code>/stats.json</code>, <code>/today.json</code>, <code>/feed.xml</code>, <code>/repo/*/index.json</code>) are released under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>: reuse freely with attribution to "{esc(SITE_NAME)}, {esc(SITE_HOST)}". The linked files on GitHub keep their own licences.</p>
<h2>Privacy</h2>
<p>No cookies, no JavaScript, no analytics scripts, no forms. The web server keeps a standard access log for operating the site; outbound links go through <code>/go/&lt;id&gt;/</code> redirect pages so that clicks appear in that log as a count — nothing more is collected.</p>
<h2>Removal</h2>
<p>A maintainer who does not want their repository listed can ask via the contact on <a href="{esc(LEGAL_UPSTREAM)}">formachines.ai/legal</a>; the repository is then dropped from the sample at the next build.</p>
<h2>AI disclosure</h2>
<p>Texts, pages and daily social posts of this project are written by AI agents and marked as such (EU AI Act, Article 50).</p>
</section>""", updated, canonical=SITE_BASE + "/legal/",
        description=f"Who is responsible for {SITE_NAME}, where the data comes from, CC BY 4.0 licence, privacy and removal requests.",
        jsonld=webpage_ld("Legal — " + SITE_NAME, SITE_BASE + "/legal/", updated)))
    write_text(out / "brand" / "index.html", layout("Brand — " + SITE_NAME, """<section>
<h1>Brand: avatar</h1>
<p>Two avatar candidates, both plain geometry, no text, readable in a 48 px circle. The image carries no AI mark; the AI disclosure lives in the page footers and post signatures.</p>
<div class="cards">
<div class="card"><h2>A — bars (chosen)</h2><p><img src="/brand/avatar.svg" width="192" height="192" alt="Avatar A: three white bars of growing length on green"> <img src="/brand/avatar.svg" width="48" height="48" style="border-radius:50%" alt=""></p><p>Three bars of growing length: the share of repositories that adopt agent instructions, growing. <a href="/brand/avatar.svg">avatar.svg</a></p></div>
<div class="card"><h2>B — ring</h2><p><img src="/brand/avatar-b.svg" width="192" height="192" alt="Avatar B: ring with one highlighted quarter on dark"> <img src="/brand/avatar-b.svg" width="48" height="48" style="border-radius:50%" alt=""></p><p>A ring with one highlighted segment: a share of the whole. <a href="/brand/avatar-b.svg">avatar-b.svg</a></p></div>
</div>
<h2>Why A</h2>
<p>A fills the circle crop evenly, keeps its contrast at 48 px (white on the site's accent green, the same colour as the site), and reads as growth, which is what the tracker shows. B's thin ring turns muddy when small and looks like a generic pie chart.</p>
<h2>Where it is used</h2>
<ul><li>Site favicon (<a href="/favicon.svg">/favicon.svg</a>) — in use</li><li>Telegram channel <a href="https://t.me/agentsmd_tracker">@agentsmd_tracker</a> — to be uploaded by the owner or the duty session</li></ul>
<p class="muted">Both files are 512×512 SVG, free to reuse with the site's CC BY 4.0 attribution.</p>
</section>""", updated, canonical=SITE_BASE + "/brand/",
        description=f"Avatar candidates and the chosen avatar of {SITE_NAME}, with the channels where it is used.",
        jsonld=webpage_ld("Brand — " + SITE_NAME, SITE_BASE + "/brand/", updated)))
    n_go = go.render(out)
    go.save()
    log.info("rendered: index, %d repo cards, %d go pages, stats/today/build json, feed, llms.txt, robots.txt, sitemap, 404, legal", len(repos), n_go)


def _rfc822(day: str) -> str:
    return _rfc822_dt(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=4))


def _rfc822_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


# ----------------------------------------------------------------------------- main
def main() -> int:
    global PAUSE_S
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-scan", action="store_true", help="render only, from data/ caches")
    ap.add_argument("--limit", type=int, default=None, help="max repos to scan this run")
    ap.add_argument("--max-seconds", type=float, default=None, help="stop scanning after this many seconds, then render")
    ap.add_argument("--force", action="store_true", help="rescan even repos checked within the last %d h" % RESCAN_HOURS)
    ap.add_argument("--pause", type=float, default=None, help="seconds between HTTP requests (default %.2f)" % PAUSE_S)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    if a.pause is not None:
        PAUSE_S = a.pause
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    t0 = now_utc()
    repos_doc = read_json(REPOS_FILE, None)
    if not repos_doc or not repos_doc.get("repos"):
        log.error("%s is missing or empty — run scripts/seed_repos.py first", REPOS_FILE)
        return 2
    repos = [r for r in repos_doc["repos"] if not r.get("fork") and not r.get("archived")]
    log.info("build start: %d repos in sample (generated %s), no_scan=%s", len(repos), repos_doc.get("generated"), a.no_scan)

    scan_stats = None
    if not a.no_scan:
        scan_stats = run_scan(repos, a.limit, a.max_seconds, a.force)

    agg = aggregate(repos)
    # write history only if a scan actually checked something; a run that scanned nothing (--no-scan, or all repos fresh) keeps the scan timestamp
    today = update_history(agg, scan_stats, write=bool(scan_stats and scan_stats.get("ok")))
    history = load_history()

    if not (scan_stats and scan_stats.get("ok")) and history and history[-1].get("generated"):
        today = dict(today, generated=history[-1]["generated"], date=history[-1]["generated"][:10])   # no real scan: keep the last real scan time, never the build clock
    last = agg["last_checked"]
    if today.get("generated") and (not last or today["generated"] > last):
        last = today["generated"]   # the scan finishes (and stamps 'generated') after its last repo check
    delayed, reason = False, ""
    if not agg["ok"]:
        delayed, reason = True, "No repository has been scanned successfully yet."
    else:
        age_h = (now_utc() - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 3600
        if age_h > STALE_HOURS:
            delayed, reason = True, f"The last successful check is {age_h:.0f} hours old (expected daily)."
        elif scan_stats and scan_stats["rate_limited"] and scan_stats["ok"] == 0:
            delayed, reason = True, "GitHub rate-limited today's scan before any repository could be checked."
    build_info = {
        "site": SITE_BASE, "built_at": iso(now_utc()), "build_seconds": round((now_utc() - t0).total_seconds(), 1),
        "sample": len(repos), "scanned_ok": len(agg["ok"]), "pending": len(agg["pending"]), "unreachable": len(agg["unreachable"]),
        "last_checked": last, "data_delayed": delayed, "delay_reason": reason,
        "scan": ({k: v for k, v in scan_stats.items() if k not in ("added", "removed")} | {"added": len(scan_stats["added"]), "removed": len(scan_stats["removed"])}) if scan_stats else None,
        "paths": [s["path"] for s in PATHS], "github_token": bool(os.environ.get("GITHUB_TOKEN")),
    }
    render_site(repos, agg, history, today, build_info)
    log.info("build done in %.0fs: scanned_ok=%d pending=%d unreachable=%d data_delayed=%s", build_info["build_seconds"], len(agg["ok"]), len(agg["pending"]), len(agg["unreachable"]), delayed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
