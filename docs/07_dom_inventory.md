# DOM Inventory (observed on /download-eroll)

Cold-load Playwright observation of the hydrated React form.

## Primary form controls

| Control | Selector hint | name attr | Notes |
|---------|---------------|-----------|-------|
| Title | `h1.form-title` | — | "Electoral Roll" |
| State | `select.form-select` | `stateCode` | Required; all 36 States/UTs |
| Year of Revision | `select.form-select` | `revyear` | Options: 2026, 2025, 2024 |
| Captcha | `input[name=captcha]` | `captcha` | Required; image from getCaptcha/EROLL |
| Submit | `button` | — | "Download Selected PDFs" |

## Cascaded controls (after State / Year)

Not present on cold load; appear after user interaction (District, AC, Language, Part, roll type).
These are populated from gateway JSON APIs documented in the API inventory.

## CSS / class patterns

- `form-title` — page heading
- `select-label` — field labels
- `form-select` — Bootstrap-style selects
- Root mount: `#root`

## Client storage

| Store | Keys observed |
|-------|----------------|
| localStorage | `persist:root` (redux-persist) |
| sessionStorage | (empty on cold load) |
| Cookies | HttpOnly `Path` cookie on voters.eci.gov.in; `cookiesession1` on gateway |

## Related routes (SPA)

See bundle route list in `output/recon_master.json` → `bundle_routes`.
