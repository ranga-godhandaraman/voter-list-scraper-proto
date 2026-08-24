# Network Analysis Report

## Default client headers used by SPA / recon

- `applicationName: VSP`
- `PLATFORM-TYPE: web`
- `channelidobo: VSP` (and related channel constants)
- `Accept: application/json` on API calls
- Browser `User-Agent` on page loads

## Auth modes observed

1. **Public (no bearer)**: `/api/v1/common/states`, `/districts/{cd}`, `/constituencies`, `get-ac-languages`
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

- Recorded HTTP probes: 112
- Browser network events: 85
