# ECI Electoral Roll — Technical Reconnaissance

Public-only analysis of [voters.eci.gov.in/download-eroll](https://voters.eci.gov.in/download-eroll).

**This is not a production scraper.** It does not mass-download PDFs, reverse request-signing, or bypass CAPTCHA/anti-bot controls.

## What it produces

1. Python recon toolkit (`analyzer/`, `network/`, `browser/`, `parser/`, `report/`)
2. Excel workbook → `excel/eci_eroll_reconnaissance.xlsx`
3. Markdown docs → `docs/`
4. Machine-readable master JSON → `output/recon_master.json`

## Quick start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
# if browsers are missing after a Playwright upgrade:
python -m playwright install chromium

# Full public recon (polite geo inventory + browser observation + reports)
python -m analyzer.cli run

# Faster: reuse a prior inventory JSON
python -m analyzer.cli run --use-cached-inventory output/raw/state_inventory.json --skip-browser
```

## Downloader (new)

Downloads public electoral-roll PDFs for one state using the **live website workflow**.

**Compliance:** CAPTCHA is entered by a human in a headed browser. Request signing stays inside the SPA (Playwright drives the page — nothing is reverse-engineered or bypassed).

```bash
# List state short codes
python download_eroll.py --list-states

# Discover only (no PDFs) — auto-selects newest year with roll types
python download_eroll.py --state AP --dry-run --headless --delay 1.0

# Limit scan while testing
python download_eroll.py -s AP --dry-run --headless --max-districts 1 --max-assemblies 1

# Download (headed browser; type captcha when prompted)
python download_eroll.py --state TN --language ENG --delay 1.5 --output ./downloads

# Force re-download / resume controls
python download_eroll.py -s KA --force
python download_eroll.py -s KA --no-resume
```

Output layout:

```
downloads/
  AP/
    2025/
      District_Name/
        Assembly_Name/
          ENG/
            Part_0001_….pdf
  downloads.sqlite
  AP_manifest.json
```

See `config/downloader.yaml` and `downloader/` for architecture.

## Compliance

- Public endpoints only
- Polite delays (`config/settings.yaml`)
- Signed PDF endpoints documented but not exploited
- CAPTCHA/Akamai/signing: **identify only**

## Key findings (high level)

| Topic | Finding |
|-------|---------|
| Stack | React CSR SPA + Akamai CDN + `gateway-voters.eci.gov.in` |
| Hierarchy | State → District → AC → Year/Type → Language → Part → PDF |
| Public APIs | states, districts, constituencies, get-ac-languages |
| Gated APIs | printing-publish roll/PDF calls require client request signing |
| PDFs | Temporary `preSignedUrl` from object storage — not permanent public URLs |

See `docs/` after running the analyzer for diagrams and full inventories.

## CLI

```bash
python -m analyzer.cli run --help
python -m analyzer.cli inventory
python -m analyzer.cli observe
```

---

## Setup & configuration (detailed)

### Prerequisites

| Requirement | Notes |
|-------------|--------|
| Python | **3.12+** recommended |
| Network | Access to `voters.eci.gov.in` and `gateway-voters.eci.gov.in` |
| Playwright browsers | Chromium must be installed into **your** user cache (see below) |
| Disk | PDF downloads can be large; plan space before a full-state run |

### One-time environment setup

```bash
cd /path/to/voter-list-scraper

# 1) Virtualenv
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2) Python packages
pip install -r requirements.txt
# optional (editable install):
# pip install -e .

# 3) Playwright Chromium (required for SPA discovery / downloads)
python -m playwright install chromium

# 4) Confirm browser launches
python -c "from playwright.sync_api import sync_playwright; \
p=sync_playwright().start(); b=p.chromium.launch(headless=True); print(b.version); b.close(); p.stop()"
```

If you see `Executable doesn't exist` / `playwright install`, re-run step 3 in the **same** terminal/venv you use to run scripts. Cursor/sandbox installs can land in a different cache than your interactive shell (`~/Library/Caches/ms-playwright` on macOS).

### Project layout (what each area is for)

```
voter-list-scraper/
  config/
    settings.yaml          # Recon analyzer defaults (gateway, delays, output dirs)
    downloader.yaml        # Downloader policy notes / preferred roll kinds
  analyzer/                # Website reconnaissance (APIs, inventory, reports)
  network/                 # Shared polite HTTP client + gateway helpers
  browser/                 # Playwright observation for recon
  downloader/              # State PDF discovery + download (SPA-driven)
  download_eroll.py        # Downloader entrypoint
  docs/                    # Generated + hand-written technical docs
  excel/                   # Recon Excel workbook output
  output/                  # Recon JSON / raw captures
  downloads/               # PDF tree + SQLite ledger + manifests
  logs/                    # Rotating log files
```

### Config files

#### `config/settings.yaml` (reconnaissance)

Controls the **analyzer** only. Common knobs:

| Key | Purpose |
|-----|---------|
| `target.site_url` / `gateway_url` | Portal + API base URLs |
| `http.request_delay_seconds` | Polite pause between public API calls |
| `http.timeout_seconds` / `max_retries` | HTTP resilience |
| `browser.*` | Playwright observation timeouts / headless for recon |
| `recon.skip_signed_endpoints` | Keep `true` — do not probe signed PDF APIs directly |
| `output.*` | Where Excel/docs/JSON/logs are written |

Override path when running recon:

```bash
python -m analyzer.cli run --config config/settings.yaml
```

#### `config/downloader.yaml` (downloader policy)

Documents preferred roll kinds (Final / Draft), default delays, and compliance rules. Runtime behaviour is primarily driven by **CLI flags** on `download_eroll.py` (state, revision, language, delay, output, etc.).

---

## Tool A — Reconnaissance analyzer

Goal: understand the site, inventory geography, document APIs, write Excel + Markdown. **Does not download electoral-roll PDFs.**

### Commands

```bash
# Full recon: shell + bundle + geo inventory + browser observe + Excel + docs
python -m analyzer.cli run

# Faster: reuse a prior inventory JSON; skip Playwright observe
python -m analyzer.cli run \
  --use-cached-inventory output/raw/state_inventory.json \
  --skip-browser

# Skip live geo walk entirely (reports still build from catalog + optional cache)
python -m analyzer.cli run --skip-inventory --skip-browser

# Geo inventory only (states / districts / ACs / sample languages)
python -m analyzer.cli inventory

# Browser observation only (DOM + network capture of /download-eroll)
python -m analyzer.cli observe

python -m analyzer.cli run --help
```

### Outputs (recon)

| Desired output | Where it lands |
|----------------|----------------|
| Excel workbook (19 sheets) | `excel/eci_eroll_reconnaissance.xlsx` |
| Master JSON | `output/recon_master.json` |
| Markdown architecture / API / flow docs | `docs/*.md` |
| State inventory summary | `output/raw/state_inventory.json` |
| Per-state district/AC JSON | `output/raw/geo/` |
| Browser capture | `output/raw/browser_observation.json` |
| Hierarchy graph | `output/raw/hierarchy_graph.json` |
| Logs | `logs/recon_YYYYMMDD.log` |

### Typical workflows

**“I want a fresh Excel + docs after a site change”**

```bash
source .venv/bin/activate
python -m analyzer.cli run
```

**“I already have inventory; just refresh docs/Excel quickly”**

```bash
python -m analyzer.cli run \
  --use-cached-inventory output/raw/state_inventory.json \
  --skip-browser
```

**“I only want geo counts for all states”**

```bash
python -m analyzer.cli inventory
# → output/raw/inventory/
```

---

## Tool B — Electoral roll downloader

Goal: for **one state**, discover the newest usable revision and (optionally) download part PDFs via the live portal UI.

```bash
python download_eroll.py --help
python download_eroll.py --list-states
```

### CLI flag reference

| Flag | Short | Default | Effect |
|------|-------|---------|--------|
| `--state` | `-s` | *(required)* | State short code (`AP`, `TN`, `KA`, …) or ECI code (`S22`) |
| `--revision` | `-r` | `auto` | `auto` = newest year with a roll type that shows districts; or pin `2025` / `2026` |
| `--language` | `-l` | first / prefer `ENG` | Language code (`ENG`, `TAM`, `HIN`, `TEL`, …) |
| `--output` | `-o` | `./downloads` | Root folder for PDFs + SQLite + manifests |
| `--delay` | `-d` | `1.0` | Seconds between polite SPA/API actions |
| `--workers` | `-w` | `1` | Reserved; PDF phase stays single-browser (CAPTCHA) |
| `--dry-run` | | off | Discover parts + write manifest/DB **without** downloading PDFs |
| `--headless` / `--headed` | | headed | Headless OK for dry-run; real downloads force headed for CAPTCHA |
| `--resume` / `--no-resume` | | resume on | Skip completed files / DB rows |
| `--force` | | off | Redownload even if file already exists |
| `--verbose` | `-v` | off | Debug logging |
| `--summary` / `--no-summary` | | summary on | Rich end-of-run table |
| `--captcha-timeout` | | `300` | Seconds to wait for human captcha input |
| `--max-districts` | | none | Cap districts scanned (testing) |
| `--max-assemblies` | | none | Cap assemblies scanned overall (testing) |
| `--list-states` | | | Print short code → ECI `stateCd` → name |

### Recipes — pick the output you want

**1) List supported states**

```bash
python download_eroll.py --list-states
```

**2) Discover only (no PDFs) — full state, auto revision**

Writes SQLite ledger + `{STATE}_manifest.json`; prints summary (parts found, revision chosen).

```bash
python download_eroll.py --state TN --dry-run --headless --delay 1.0
```

**3) Fast smoke test (1 district, 1 assembly)**

```bash
python download_eroll.py -s AP --dry-run --headless \
  --max-districts 1 --max-assemblies 1 --delay 0.8
```

**4) Pin a revision year**

```bash
python download_eroll.py -s AP --revision 2025 --dry-run --headless
python download_eroll.py -s GA --revision 2026 --dry-run --headless
```

`auto` tries years newest-first and picks the first roll type that exposes district/part UI (skips empty / bye-election stubs when possible). Prefer **Draft / SIR Draft** over Final when both exist (after SIR Final is published, Draft is the intended download).

**5) Prefer a language**

```bash
python download_eroll.py -s AP --language ENG --dry-run --headless
python download_eroll.py -s TN --language TAM --dry-run --headless
python download_eroll.py -s UP --language HIN --dry-run --headless
```

**6) Download PDFs (human CAPTCHA required)**

Opens a **headed** browser. When prompted, type the captcha in the page (do not click Download yourself — the script clicks after it sees the captcha field filled).

```bash
python download_eroll.py --state TN --language ENG --delay 1.5 --output ./downloads
```

**7) Resume an interrupted run**

```bash
# Same command again — skips existing PDFs / completed DB rows
python download_eroll.py -s TN --language ENG --delay 1.5
```

**8) Force re-download everything already on disk**

```bash
python download_eroll.py -s KA --force --delay 1.5
```

**9) Custom output directory + quieter / louder logs**

```bash
python download_eroll.py -s KL -o ~/data/eroll-kl --dry-run --headless --no-summary
python download_eroll.py -s KL -o ~/data/eroll-kl --verbose --delay 2.0
```

**10) Longer captcha wait (slow typing / distractions)**

```bash
python download_eroll.py -s MH --captcha-timeout 600 --delay 1.5
```

### Downloader outputs

| Desired output | Path |
|----------------|------|
| PDF hierarchy | `downloads/{STATE}/{YEAR}/{District}/{Assembly}/{LANG}/Part_NNNN_….pdf` |
| Resume ledger | `downloads/downloads.sqlite` |
| Per-state manifest | `downloads/{STATE}_manifest.json` |
| Run logs | `logs/recon_YYYYMMDD.log` (shared logger dir) |
| Terminal summary | State, revision, districts/ACs, parts found, downloaded / skipped / failed, elapsed |

Example tree:

```
downloads/
  TN/
    2025/
      Chennai/
        Some_AC_Name/
          TAM/
            Part_0001_….pdf
            Part_0002_….pdf
  downloads.sqlite
  TN_manifest.json
```

---

## Choosing which tool to run

| You want… | Run |
|-----------|-----|
| Architecture / API / Excel inventory of India | `python -m analyzer.cli run` |
| Only state→district→AC counts | `python -m analyzer.cli inventory` |
| Part list for one state **without** PDFs | `python download_eroll.py -s XX --dry-run --headless` |
| Actual PDF files for one state | `python download_eroll.py -s XX` (headed + human captcha) |
| Safe local experiment | add `--max-districts 1 --max-assemblies 1` |

---

## Compliance reminders

- Do **not** bypass CAPTCHA, reverse request signing, or ignore rate limits.
- Prefer `--dry-run` until you confirm the revision/language you need.
- Use a polite `--delay` (≈1.0–2.0s) on real runs.
- Full-state discovery can take a long time (hundreds of assemblies); start with limits, then scale up.
