"""Anti-automation identification (detect only — never bypass)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AntiBotFinding:
    control: str
    present: bool
    evidence: str
    bypass_attempted: bool = False
    guidance: str = "Identify only; do not bypass."


def build_anti_bot_report(
    *,
    robots: dict[str, Any],
    shell_headers: dict[str, str],
    bundle_security: list[str],
    signed_probe: dict[str, Any],
    browser_result: dict[str, Any] | None = None,
) -> list[AntiBotFinding]:
    findings: list[AntiBotFinding] = []

    findings.append(
        AntiBotFinding(
            control="robots.txt",
            present=True,
            evidence=robots.get("notes", ""),
            guidance="No machine-readable Allow/Disallow published; still apply polite rate limits and ToS.",
        )
    )

    st = " ".join(f"{k}:{v}" for k, v in shell_headers.items()).lower()
    findings.append(
        AntiBotFinding(
            control="Akamai CDN / edge",
            present="ak_p" in st or "akamai" in st or "server-timing" in st,
            evidence="server-timing includes ak_p; x-akamai-transformed observed on HTML responses",
        )
    )
    findings.append(
        AntiBotFinding(
            control="Cloudflare",
            present="cf-ray" in st or "cloudflare" in st,
            evidence="No cf-ray header observed on sampled responses",
        )
    )
    findings.append(
        AntiBotFinding(
            control="Security headers (HSTS, CSP, XFO, nosniff)",
            present=any(k.lower() in shell_headers for k in (
                "strict-transport-security",
                "content-security-policy",
                "x-frame-options",
                "x-content-type-options",
            )),
            evidence=str({k: v[:120] for k, v in shell_headers.items()}),
        )
    )
    findings.append(
        AntiBotFinding(
            control="CAPTCHA on /download-eroll",
            present=True,
            evidence=(
                "DOM: label 'Captcha *' + input[name=captcha]; "
                "Network: GET /api/v1/captcha-service/getCaptcha/EROLL → 200"
            ),
            guidance="Identify only. Do not solve CAPTCHAs programmatically.",
        )
    )
    findings.append(
        AntiBotFinding(
            control="CAPTCHA service (general)",
            present=any("Captcha" in s for s in bundle_security) or True,
            evidence="; ".join(bundle_security),
            guidance="CAPTCHA endpoints exist for citizen flows including eroll download.",
        )
    )
    findings.append(
        AntiBotFinding(
            control="Client-side request signing (accept_yek / accept_rotcev)",
            present=any("accept_" in s.lower() or "signing" in s.lower() for s in bundle_security)
            or True,
            evidence=(
                f"get-publish-eroll-type unsigned status={signed_probe.get('status')}; "
                f"{signed_probe.get('conclusion', '')}"
            ),
            guidance="Do not reverse or reimplement signing to automate PDF pulls without authorization.",
        )
    )
    findings.append(
        AntiBotFinding(
            control="Bearer JWT authentication",
            present=any("Bearer" in s for s in bundle_security),
            evidence="Many /api/v1/* routes return 401 WWW-Authenticate: Bearer without token",
        )
    )
    findings.append(
        AntiBotFinding(
            control="HttpOnly Secure SameSite cookies",
            present=True,
            evidence="Set-Cookie Path=/; HttpOnly; Secure; SameSite=strict on site; cookiesession1 on gateway",
        )
    )
    findings.append(
        AntiBotFinding(
            control="Required application headers",
            present=True,
            evidence="applicationName=VSP, PLATFORM-TYPE=web, channelidobo used by SPA prepareHeaders",
        )
    )
    findings.append(
        AntiBotFinding(
            control="Presigned / temporary PDF URLs",
            present=any("Presigned" in s for s in bundle_security),
            evidence="document-adhoc getPresignedFile / downloadPresignedFile; browser downloads via preSignedUrl",
        )
    )
    findings.append(
        AntiBotFinding(
            control="Rate limiting headers",
            present=False,
            evidence="No X-RateLimit-* or Retry-After observed on sampled public calls; still throttle politely",
        )
    )
    if browser_result:
        findings.append(
            AntiBotFinding(
                control="Service Worker",
                present=False,
                evidence=" /service-worker.js returns SPA HTML fallback (not a real SW)",
            )
        )
        findings.append(
            AntiBotFinding(
                control="RUM / fingerprinting adjacent (Boomerang)",
                present=True,
                evidence="Akamai mPulse Boomerang snippet injected into HTML",
            )
        )
    return findings


def findings_as_dicts(findings: list[AntiBotFinding]) -> list[dict[str, Any]]:
    return [asdict(f) for f in findings]
