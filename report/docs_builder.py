"""Markdown documentation generator for recon deliverables."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


def write_docs(docs_dir: Path, payload: dict[str, Any]) -> list[Path]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    arch = docs_dir / "01_website_architecture.md"
    arch.write_text(_architecture_md(payload), encoding="utf-8")
    written.append(arch)

    flow = docs_dir / "02_download_flow.md"
    flow.write_text(_download_flow_md(payload), encoding="utf-8")
    written.append(flow)

    api = docs_dir / "03_api_inventory.md"
    api.write_text(_api_md(payload), encoding="utf-8")
    written.append(api)

    net = docs_dir / "04_network_analysis.md"
    net.write_text(_network_md(payload), encoding="utf-8")
    written.append(net)

    feas = docs_dir / "05_feasibility_and_recommendations.md"
    feas.write_text(_feasibility_md(payload), encoding="utf-8")
    written.append(feas)

    crawler = docs_dir / "06_future_compliant_crawler_design.md"
    crawler.write_text(_crawler_design_md(payload), encoding="utf-8")
    written.append(crawler)

    index = docs_dir / "README.md"
    index.write_text(_index_md(written), encoding="utf-8")
    written.append(index)

    logger.info("Wrote {} markdown docs to {}", len(written), docs_dir)
    return written


def _index_md(paths: list[Path]) -> str:
    lines = [
        "# ECI Download E-Roll — Reconnaissance Documentation",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "This documentation is the output of a **public technical reconnaissance** project.",
        "It does **not** implement a production scraper and does **not** bypass protections.",
        "",
        "## Contents",
        "",
    ]
    for p in paths:
        if p.name == "README.md":
            continue
        lines.append(f"- [{p.stem}]({p.name})")
    lines.append("")
    return "\n".join(lines)


def _architecture_md(payload: dict[str, Any]) -> str:
    ws = payload.get("website_structure", {})
    return f"""# Website Architecture Report

## Summary

`https://voters.eci.gov.in/download-eroll` is a **client-side rendered React SPA** (Citizen Service Portal)
fronted by **Akamai**. Business data is fetched from `https://gateway-voters.eci.gov.in`.

## High-level diagram

```mermaid
flowchart TB
  User[Citizen Browser]
  CDN[Akamai Edge<br/>voters.eci.gov.in]
  SPA[React SPA<br/>#root CSR]
  GW[gateway-voters.eci.gov.in<br/>API Gateway]
  OS[Object Storage<br/>presigned URLs]
  VPD[gateway-vpd.eci.gov.in]
  CEO[State CEO websites<br/>historical SIR links]

  User --> CDN --> SPA
  SPA -->|JSON XHR/fetch<br/>applicationName=VSP| GW
  SPA -->|some content| VPD
  GW -->|preSignedUrl| OS
  SPA -->|external links map| CEO
```

## Stack signals

| Layer | Finding |
|-------|---------|
| UI | React + React Router routes (`/download-eroll`, `/download-final-roll`, `/download-sir-draft-roll`, …) |
| State/data | Redux Toolkit Query services (`contentLoaderServiceApi`, common services) |
| Bundling | CRA/Webpack hashed `/static/js/main.*.js` + many lazy chunks (`asset-manifest.json`) |
| Legacy | `/angular/*.js` script tags still loaded in shell HTML |
| CSS | Bootstrap + custom hashed CSS |
| Transliteration | jQuery + CDAC typing packages |
| RUM | Akamai mPulse Boomerang |

## Static vs dynamic

- **Static**: HTML shell, `/static/**`, `/Packages/**`, `/angular/**`, `asset-manifest.json`
- **Dynamic**: All eroll selectors and PDF links — JSON APIs after hydration
- **SSR/CSR**: CSR only (`noscript` message; empty `#root`)
- **Service Worker**: paths like `/service-worker.js` return SPA HTML fallback — **no real SW**

## CSP connect-src (allowed API hosts)

{chr(10).join('- ' + u for u in (ws.get('csp_connect_src') or [])[:20]) or '- (see Excel Headers sheet)'}

## Hierarchy (verified)

```
Country (IN)
  └─ State/UT (stateCd e.g. S24, U05)
       └─ District (districtNo / districtCd e.g. S2408)
            └─ Assembly Constituency (asmblyNo / acNumber)
                 └─ Year + Roll/Revision type (signed API)
                      └─ Language (get-ac-languages)
                           └─ Part
                                └─ PDF (presigned object-store URL)
```

**Not** on the primary download cascade: Parliamentary Constituency.
**Section** appears in SIR *search* UIs, not as a required PDF download level.
"""


def _download_flow_md(payload: dict[str, Any]) -> str:
    flow = payload.get("download_flow", {})
    steps = "\n".join(f"{k}. {v}" for k, v in flow.items()) if flow else "_See Excel Download Flow sheet._"
    return f"""# Download Flow Documentation

## User-visible cascade on `/download-eroll`

{steps}

## Sequence (logical)

```mermaid
sequenceDiagram
  participant U as User
  participant SPA as React SPA
  participant GW as gateway-voters
  participant OS as Object Store

  U->>SPA: Open /download-eroll
  SPA->>GW: GET /api/v1/common/states
  GW-->>SPA: states JSON
  U->>SPA: Select State
  SPA->>GW: GET /api/v1/common/districts/{{stateCd}}
  GW-->>SPA: districts JSON
  U->>SPA: Select District / AC
  SPA->>GW: GET /api/v1/common/constituencies?stateCode=
  GW-->>SPA: AC JSON
  SPA->>GW: POST /printing-publish/get-ac-languages
  GW-->>SPA: language map
  U->>SPA: Select Year / Roll type
  SPA->>GW: GET get-publish-eroll-type (SIGNED headers)
  GW-->>SPA: available revision types
  SPA->>GW: POST get-publish-part-list (SIGNED)
  GW-->>SPA: parts
  U->>SPA: Select Part + Download
  SPA->>GW: POST generate-published-pdfs (SIGNED)
  GW-->>SPA: file reference
  SPA->>GW: getPresignedFile / downloadPresignedFile
  GW-->>SPA: preSignedUrl
  SPA->>OS: GET preSignedUrl
  OS-->>U: PDF bytes
```

## PDF URL characteristics

| Property | Observation |
|----------|-------------|
| Predictable permanent URL? | **No** — goes through generate + object store |
| Presigned / temporary? | **Yes** (`preSignedUrl`) |
| Session / token linked? | Likely; signing headers + optional bearer on some document APIs |
| One-time? | Treat as short-lived; do not assume permanence |
| Mass enumerable? | **No** without signing + valid part metadata |

## Related routes

- `/download-eroll` — general published rolls
- `/download-final-roll` — SIR final roll UI
- `/download-sir-draft-roll` — SIR draft roll UI
- `/download-statutory-report` — statutory reports
- `/bh_2003_eroll` — Bihar 2003 historical
- External CEO links for older intensive revisions (per-state map in SPA)
"""


def _api_md(payload: dict[str, Any]) -> str:
    rows = payload.get("api_endpoints", [])
    lines = ["# API Inventory", "", "| Method | Path | Auth | Category | Notes |", "|--------|------|------|----------|-------|"]
    for r in rows:
        lines.append(
            f"| {r.get('method')} | `{r.get('path')}` | {r.get('auth_required')} | "
            f"{r.get('category')} | {str(r.get('notes', ''))[:120]} |"
        )
    lines.append("")
    lines.append("Full details are in the Excel workbook sheet **API Endpoints**.")
    lines.append("")
    return "\n".join(lines)


def _network_md(payload: dict[str, Any]) -> str:
    return f"""# Network Analysis Report

## Default client headers used by SPA / recon

- `applicationName: VSP`
- `PLATFORM-TYPE: web`
- `channelidobo: VSP` (and related channel constants)
- `Accept: application/json` on API calls
- Browser `User-Agent` on page loads

## Auth modes observed

1. **Public (no bearer)**: `/api/v1/common/states`, `/districts/{{cd}}`, `/constituencies`, `get-ac-languages`
2. **Bearer JWT**: many `/api/v1/*` routes → `401 WWW-Authenticate: Bearer`
3. **Request signing**: `accept_yek` + `accept_rotcev` headers + transformed query/body for printing-publish roll APIs
4. **CAPTCHA**: captcha-service endpoints for search/login-adjacent flows

## Caching

- HTML: `cache-control: no-cache, no-store` (often)
- Gateway JSON: `Cache-Control: no-cache, no-store, max-age=0, must-revalidate`
- CDN: Akamai `cdn-cache HIT/MISS` in `server-timing`

## Compression / transport

- TLS 1.3 to `*.eci.gov.in`
- HTTP/2 on website; gateway often HTTP/1.1 in curl probes

## Sample call count this run

- Recorded HTTP probes: {len(payload.get('network_calls', []))}
- Browser network events: {payload.get('overview', {}).get('browser_network_events', 'n/a')}
"""


def _feasibility_md(payload: dict[str, Any]) -> str:
    f = payload.get("feasibility", {})
    risks = "\n".join(f"- {r}" for r in f.get("risks", []))
    perf = "\n".join(f"- {r}" for r in f.get("performance_notes", []))
    return f"""# Technical Feasibility Report

## Verdict

{f.get('summary', '')}

## Recommended approach

**{f.get('recommended_approach', '')}**

Overall complexity: **{f.get('complexity_overall', '')}**

## Approach comparison

| Approach | Reliability | Complexity | Policy fit |
|----------|-------------|------------|------------|
{chr(10).join(
  f"| {a.get('approach')} | {a.get('reliability')} | {a.get('complexity')} | {a.get('policy_fit')} |"
  for a in f.get('approaches', [])
)}

## Risks

{risks}

## Performance / volume (estimates only)

{perf}

```json
{__import__('json').dumps(f.get('volume_estimates', {}), indent=2)}
```

## Maintainability

{chr(10).join('- ' + x for x in f.get('maintainability_notes', []))}
"""


def _crawler_design_md(payload: dict[str, Any]) -> str:
    design = payload.get("feasibility", {}).get("compliant_future_design", [])
    return f"""# Future Compliant Crawler — Software Design

## Principles

1. Prefer **official bulk channels** if/when ECI provides them.
2. Use **public geo APIs** for indexing only.
3. **Do not** reverse request-signing or CAPTCHA solvers.
4. Human-in-the-loop for any gated PDF retrieval.
5. Strict rate limits, audit logs, and legal review.

## Phased plan

{chr(10).join(f'- {x}' for x in design)}

## Suggested folder structure (future crawler — not this repo's scraper)

```
compliant_crawler/
  config/
  inventory/          # public API sync jobs
  browser_assisted/   # optional headed sessions
  storage/            # metadata DB + object store refs
  pipelines/
  monitoring/
  docs/legal/
```

## Suggested metadata schema

```sql
CREATE TABLE state (
  state_cd TEXT PRIMARY KEY,
  state_name TEXT,
  state_type TEXT,
  is_active TEXT
);

CREATE TABLE district (
  state_cd TEXT,
  district_no TEXT,
  district_cd TEXT,
  district_name TEXT,
  PRIMARY KEY (state_cd, district_no)
);

CREATE TABLE assembly (
  state_cd TEXT,
  asmbly_no INTEGER,
  district_cd TEXT,
  asmbly_name TEXT,
  category TEXT,
  PRIMARY KEY (state_cd, asmbly_no)
);

CREATE TABLE revision_notice (
  state_cd TEXT,
  year TEXT,
  roll_type TEXT,
  source TEXT,
  observed_at TIMESTAMPTZ
);

CREATE TABLE download_job (
  id UUID PRIMARY KEY,
  state_cd TEXT,
  asmbly_no INTEGER,
  part_no TEXT,
  language TEXT,
  status TEXT,
  authorized_by TEXT,
  created_at TIMESTAMPTZ
);
```

## Retry / logging / incremental strategy

| Concern | Recommendation |
|---------|----------------|
| Retry | Exponential backoff on 429/5xx only; never retry CAPTCHA failures with solvers |
| Logging | Structured JSON logs; never log secrets/signing material |
| Incremental | Re-sync geo weekly; track revision notices; download only deltas when authorized |
| Monitoring | Alert on bundle hash change, endpoint 401/403 spike, ToS updates |

## Entity relationship

```mermaid
erDiagram
  STATE ||--o{{ DISTRICT : contains
  DISTRICT ||--o{{ ASSEMBLY : contains
  ASSEMBLY ||--o{{ PART : contains
  ASSEMBLY ||--o{{ LANGUAGE : supports
  PART ||--o| PDF_ARTIFACT : yields
  REVISION_NOTICE ||--o{{ PDF_ARTIFACT : scopes
```
"""
