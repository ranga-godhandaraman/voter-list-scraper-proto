# API Inventory

| Method | Path | Auth | Category | Notes |
|--------|------|------|----------|-------|
| GET | `/api/v1/common/states` | none | geo | Public list of States/UTs |
| GET | `/api/v1/common/districts/{stateCd}` | none | geo | Public districts for a state code (e.g. S24) |
| GET | `/api/v1/common/constituencies?stateCode={stateCd}` | none | geo | Public assembly constituencies; fields include asmblyNo, districtCd |
| GET | `/api/v1/common/acs/{stateCd}` | none | geo | Alternate AC path; may return empty array depending on state |
| POST | `/api/v1/printing-publish/get-ac-languages` | none | eroll | Body: {stateCd, acNumber}. Returns language map e.g. {HIN:HINDI} |
| GET | `/api/v1/printing-publish/get-publish-eroll-type` | signed_headers | eroll | Requires query params stateCd, year, misKey AND client-generated headers accept_yek / accept_rotcev (request signing). N |
| POST | `/api/v1/printing-publish/get-publish-part-list` | signed_headers | eroll | Returns part list for selected AC/year/language/roll type. Likely goes through encrypting RTK baseQuery; empty HTTP 400  |
| POST | `/api/v1/printing-publish/generate-published-pdfs` | signed_headers | eroll | Triggers PDF generation / returns object-store reference or presigned URL. |
| POST | `/api/v1/printing-publish/download-statutory-report` | signed_headers | eroll | Statutory report download (related UI route /download-statutory-report). |
| GET | `/api/v1/document-adhoc/getPresignedFile` | bearer | storage | Presigned object-storage URL; query: bucketName, fileName |
| GET | `/api/v1/document-adhoc/downloadPresignedFile` | unknown | storage | Client uses returned preSignedUrl for browser download. |
| GET | `/api/v1/captcha-service/getCaptcha/{id}` | none | security | Returns captcha image/data payload for citizen flows (not always on download-eroll). |
| GET | `/api/v1/captcha-service/generateVoiceCaptcha/{id}` | none | security | Voice captcha asset URL pattern from SPA. |
| POST | `/api/v1/captcha-service/verifyCaptcha/` | none | security | Captcha verification endpoint (identify only). |
| GET | `/api/v1/common/part/get/bystatecd/districtcd/acNumber` | bearer | geo | Part master data; observed 401 without bearer token. |
| GET | `/api/v1/citizen/sir/getDistrict` | unknown | sir | SIR-specific district listing; requires state header in SPA. |
| GET | `/api/v1/citizen/sir/getAsmblyByDist` | unknown | sir | SIR assembly-by-district. |
| GET | `/api/v1/citizen/sir/getPartByAc` | unknown | sir | SIR parts by assembly. |
| POST | `/api/v1/elastic-sir-citizen/get-eroll-data-2003-by-epic-captcha` | captcha | sir_search | Historical SIR eroll search by EPIC + captcha. |

Full details are in the Excel workbook sheet **API Endpoints**.
