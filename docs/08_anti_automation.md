# Anti-Automation Identification Report

**Policy: identify only — do not bypass.**

| Control | Present? | Evidence |
|---------|----------|----------|
| robots.txt | Path exists but returns SPA HTML | No Allow/Disallow directives published |
| Akamai CDN | Yes | `server-timing` `ak_p`; `x-akamai-transformed` |
| Cloudflare | Not observed | No `cf-ray` |
| CAPTCHA on download-eroll | **Yes** | DOM Captcha*; `GET .../getCaptcha/EROLL` → 200 |
| Request signing | **Yes** | `accept_yek` / `accept_rotcev` for printing-publish type API |
| Bearer JWT | Yes (many routes) | Gateway `401 WWW-Authenticate: Bearer` |
| Required app headers | Yes | `applicationName=VSP`, `PLATFORM-TYPE=web` |
| HttpOnly Secure cookies | Yes | SameSite=strict on site |
| Presigned PDF URLs | Yes | `preSignedUrl` via document-adhoc APIs |
| Service Worker | No real SW | `/service-worker.js` → SPA HTML fallback |
| RUM / Boomerang | Yes | Akamai mPulse snippet |
| Explicit rate-limit headers | Not observed | Still throttle politely |

## Implication for future work

Any compliant crawler must treat CAPTCHA + request signing as hard stops for unattended PDF download.
Geo inventory via public unsigned APIs remains the safe automation surface.
