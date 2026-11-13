# AGENTS.md Tracker — `agentsmd.formachines.ai`

Daily tracker of agent-instruction files in top GitHub repositories: which of the sampled public repos have
`AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.cursor/rules/`, `.github/copilot-instructions.md`, `llms.txt`,
`GEMINI.md`, `.windsurfrules`; headline shares, a by-language table, an "added today" feed, per-repo cards,
JSON endpoints and an RSS feed of new `AGENTS.md` files.

Built and maintained by AI agents (agent-team) without human editing. Responsible person: Dmitry, formachines.ai.

## Layout

```
build.py                 scan + render (Python 3.12 standard library only, no third-party packages)
scripts/seed_repos.py    one-off: collect the repository sample through the GitHub Search API
static/style.css         the only stylesheet; copied into public/ by build.py
data/repos.json          the sample: id, owner, name, language, stars, default_branch   (committed)
data/scan/<owner>__<name>.json   per-repo cache: {checked, status, default_branch, files: {path: {present, size}}}   (committed)
data/history/<YYYY-MM-DD>.json   per-day counts by type and language, "added" / "removed" since the previous scan   (committed)
data/go.json             stable ids for outbound links /go/<id>/ (append-only)   (committed)
public/                  the whole site, prebuilt   (committed — the server only publishes it)
```

## Build

```bash
python3 scripts/seed_repos.py         # once; re-run to extend the sample (existing entries are kept)
python3 build.py                      # scan what is due, then render public/
python3 build.py --no-scan            # re-render from data/ without touching the network
python3 build.py --limit 200          # scan at most 200 repos this run; the rest stays "pending"
python3 build.py --max-seconds 1500   # stop scanning after 25 min, render whatever is there
python3 build.py --force              # rescan even repos checked in the last 20 h
```

`build.py` is idempotent and resumable: every repo result is written to `data/scan/` immediately, so an
interrupted run (Ctrl-C, SIGTERM, time budget) loses nothing and the next run continues with the never-scanned and
oldest repos first. A run always ends by rendering `public/` from whatever the caches hold.

Daily schedule on the server: `04:00 UTC` — `python3 build.py && git add -A && git commit -m "scan YYYY-MM-DD" && git push`.
The droplet pulls `main` every 5 minutes and publishes `public/` as-is (see agent-team `deploy/droplet/`). It never
runs `build.py`.

## Tests

```bash
python3 -B -m unittest discover -s tests -t .
```

Runs every `tests/test_*.py` (14 files) from the repository root. Offline and read-only: no network, nothing is
written to the checkout (tests that build use a temp copy), so it also passes after `chmod -R a-w .`. Python 3.12
standard library only.

## What to commit

Everything: code, `data/` and `public/`. The site is the committed `public/` directory; the caches in `data/` are the
memory that makes "added today" and the sparklines possible. Do not add a build step the server would have to run,
do not add dependencies outside the Python 3.12 standard library, no JavaScript on the pages.

## Rules (promises kept on every page)

- **Presence, size and a link only.** The tracker records whether a tracked path exists on the default branch and how
  many bytes it has. File contents are never downloaded, stored, quoted or republished. "Examples of good files" =
  links to GitHub, nothing else.
- **Addresses never change.** `/`, `/repo/<owner>/<name>/` (+ `index.json`), `/go/<id>/`, `/stats.json`, `/today.json`,
  `/feed.xml`, `/llms.txt`, `/legal/`, `/build.json`, `/robots.txt`, `/sitemap.xml`, `/404.html`. A repo card stays even
  if the repo becomes unreachable (status is shown). `/go/<id>` ids come from `data/go.json` and are never reused.
- **AI disclosure in the footer of every page**: "Built by AI agents (agent-team) without human editing · responsible:
  Dmitry, formachines.ai · updated <UTC>". Keep it in `layout()`.
- **No tracking.** No cookies, no JavaScript, no analytics, no forms. Outbound clicks are counted from the server's
  standard access log through the `/go/<id>/` redirect pages (meta refresh) — that is the whole mechanism.
- **Every number is dated and sourced**: `generated` / `built_at` in every JSON, the method section on the home page.
- **Stats are CC BY 4.0**; linked files keep their repositories' licences. `/legal/` names the responsible person and
  links to https://formachines.ai/legal/.

## How the scan works

- One HTTP `HEAD` per tracked path, single thread, `PAUSE_S` between requests:
  - files → `https://raw.githubusercontent.com/<owner>/<name>/<default_branch>/<path>`: `200` = present,
    `Content-Length` = size; `404` = absent. Case-sensitive, exact spelling of the convention.
  - `.cursor/rules` (directory) → `https://github.com/<owner>/<name>/tree/<default_branch>/.cursor/rules`:
    2xx/3xx = present, `404` = absent.
  - when all paths are absent, one `HEAD https://github.com/<owner>/<name>` confirms the repo still exists;
    301/404/451 → status `unreachable` (excluded from all denominators, card kept).
- Neither host counts against the REST API quota, so **the daily scan needs no token**. Throughput is ~2–3 s per repo
  (9 requests), i.e. about 1.5 h for 2 000 repos; `--max-seconds` keeps a cron run bounded.
- `429` / `403 + Retry-After` → sleep 60 s; after 5 in a row the scan stops, remaining repos stay `pending`, the site
  is rendered with a "partial scan" banner. `data_delayed` in `build.json` (and a yellow banner) is set when no repo
  has a successful check within 36 h.
- A repo checked `ok` less than 20 h ago is skipped (`RESCAN_HOURS`); `error`/`partial` results are retried first
  and never overwrite an older good snapshot.
- **Added today** = path present in this scan and `present: false` in the previous snapshot of the same repo
  (`data/history/<date>.json` → `added`; several runs on one day are merged). The very first scan of a repo is a
  baseline and produces no "added" entries. "Removed" is recorded symmetrically.

## GitHub API limits (seed only)

`scripts/seed_repos.py` uses the Search API: 10 requests/min without a token, 30/min with `GITHUB_TOKEN` in the
environment (read-only, public data); at most 1 000 results per query, 100 per page; forks and archived repos are
dropped. Rate-limit headers (`X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`) are honoured and every
page is checkpointed into `data/repos.json`.

The REST Core API (60 req/h without a token, 5 000/h with one) is only touched by `build.py` when `GITHUB_TOKEN` is
set *and* a repo needs the existence check; without a token the github.com HTML `HEAD` is used instead. The site
therefore builds fully on the cache without any token, and marks data as delayed rather than showing zeros.

### Sample as of 2026-11-02

Seeded without a token: 10 languages × top 200 by stars, `stars:>1000`, forks/archived excluded → **1 922 repos**
(Python 197 · Rust 198 · TypeScript 195 · Go 193 · Java 193 · JavaScript 191 · C++ 191 · PHP 191 · Ruby 189 · C# 184).

**To grow to ≥ 2 000 (or beyond):** `python3 scripts/seed_repos.py --per-language 300` (adds the next 100 per
language, 30 requests ≈ 3 min without a token, 1 min with `GITHUB_TOKEN`), or add languages:
`python3 scripts/seed_repos.py --languages Kotlin Swift Shell Dart Scala --per-language 100`. New repos appear as
`pending` until the next `build.py` scan picks them up (never-scanned first). To widen beyond "most stars" (the PO's
lever when the "added today" feed stays empty), add a query mode — e.g. `pushed:>YYYY-MM-DD` with `--min-stars 300` —
in `seed_repos.py`; keep the per-query cap of 1 000 results in mind.

## Conventions for the developer role

- Keep all tunables in the constants block at the top of `build.py` / `seed_repos.py`; no magic numbers in functions.
- Log at INFO what was scanned and rendered; DEBUG for per-request detail (`-v`).
- New tracked path = one entry in `PATHS` (kind `file` or `dir`); everything else (cards, tables, JSON, cards, history)
  follows. Old history files without the new key count it as 0.
- Changing a template: check the result on a 375 px viewport (tables are wrapped in `.scroll`), in light and dark.
- Never put secrets in the repo; the only optional secret is `GITHUB_TOKEN` in the server environment.
- Verify before reporting: run `python3 build.py --no-scan`, open `public/index.html`, check `public/build.json`.
