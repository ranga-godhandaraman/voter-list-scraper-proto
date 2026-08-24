# Technical Feasibility Report

## Verdict

Public geographic hierarchy is crawlable via documented JSON APIs. PDF download path is gated by client-side request signing and object-store presigned URLs. A compliant future system should inventory via public APIs and treat PDF retrieval as an authorized, rate-limited, preferably human-supervised step — not a silent scraper.

## Recommended approach

**Hybrid: HTTP for hierarchy + browser for signed PDF steps**

Overall complexity: **High (PDF path); Medium (geo inventory)**

## Approach comparison

| Approach | Reliability | Complexity | Policy fit |
|----------|-------------|------------|------------|
| requests / httpx (pure HTTP) | Low–Medium | Medium | Good for public geo APIs only |
| aiohttp high-concurrency | Low | High | Poor if aggressive |
| Playwright / Selenium browser automation | Medium–High (human-paced) | High | Best for interactive compliant use |
| Hybrid: HTTP for hierarchy + browser for signed PDF steps | Highest for compliant design | High | Best overall |

## Risks

- Akamai edge may throttle or challenge anomalous clients
- Request signing algorithm can change without notice (bundle hash changes often)
- Presigned URLs expire; not permanent public links
- Legal/ToS risk if mass-downloading electoral rolls without permission
- CAPTCHA and auth flows adjacent to SIR/search features
- State CEO sites host some historical SIR rolls outside this portal

## Performance / volume (estimates only)

- Geo inventory: ~36 states × (districts+ACs+lang) ≈ hundreds of polite calls
- Estimated mid PDF count ~1,156,120 (not downloaded)
- Estimated mid storage ~2822.6 GB

```json
{
  "states": 36,
  "districts": 787,
  "assembly_constituencies": 4129,
  "parts_per_ac_assumed": {
    "low": 80,
    "mid": 200,
    "high": 350
  },
  "estimated_pdfs": {
    "low": 330320,
    "mid": 1156120,
    "high": 2890300
  },
  "estimated_storage_gb_at_2_5mb": {
    "low": 806.4,
    "mid": 2822.6,
    "high": 7056.4
  },
  "estimated_runtime_hours_at_2s_polite": {
    "mid": 642.3,
    "note": "Only if explicitly authorized; not performed by this project"
  }
}
```

## Maintainability

- Pin SPA bundle hash / re-run recon when main.*.js changes
- Keep endpoint catalog versioned in Excel/API inventory
- Prefer official bulk channels if ECI provides them later
