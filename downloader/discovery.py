"""Hierarchy discovery using existing public gateway APIs + SPA observation.

Public HTTP (no captcha / no signing reverse-engineering):
  - states, districts, constituencies, get-ac-languages

SPA (Playwright drives the real site JS — signing stays inside the browser):
  - revision years with downloadable roll types
  - roll type / district / AC / language / part lists from the live form
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from downloader.models import AssemblyInfo, DistrictInfo, PartInfo, RollTypeInfo
from downloader.proxy import mask_proxy, proxy_for_playwright
from downloader.state_mapping import StateInfo
from downloader.utils import classify_roll_kind
from network.gateway import GatewayProbe
from utils.config import Settings, get_settings

# Akamai blocks custom/bot user agents — use a normal Chrome fingerprint for the SPA.
_REALISTIC_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_PORTAL_HOME = "https://voters.eci.gov.in/"


class GeoDiscovery:
    """Discover districts / ACs / languages via existing public gateway helpers."""

    def __init__(
        self,
        settings: Settings | None = None,
        delay: float = 0.45,
        *,
        proxy: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.probe = GatewayProbe(self.settings, proxy=proxy)
        self.delay = delay

    def set_proxy(self, proxy: str | None) -> None:
        self.probe.set_proxy(proxy)

    def _pause(self) -> None:
        if self.delay > 0:
            time.sleep(self.delay)

    def districts(self, state: StateInfo) -> list[DistrictInfo]:
        raw = self.probe.get_districts(state.eci_state_cd)
        self._pause()
        out: list[DistrictInfo] = []
        for d in raw:
            # API returns districtNo + state; portal uses districtCd like S0104
            dist_no = str(d.get("districtNo", "")).strip()
            state_field = d.get("state") or state.eci_state_cd
            district_cd = d.get("districtCd") or f"{state_field}{dist_no.zfill(2)}"
            out.append(
                DistrictInfo(
                    district_cd=str(district_cd),
                    district_name=str(d.get("districtValue") or dist_no),
                    state_cd=state.eci_state_cd,
                )
            )
        logger.info("{}: {} districts", state.short_code, len(out))
        return out

    def assemblies(self, state: StateInfo) -> list[AssemblyInfo]:
        raw = self.probe.get_constituencies(state.eci_state_cd)
        self._pause()
        out: list[AssemblyInfo] = []
        for a in raw:
            out.append(
                AssemblyInfo(
                    ac_number=str(a.get("asmblyNo")),
                    ac_name=str(a.get("asmblyName") or a.get("asmblyNo")).strip(),
                    district_cd=str(a.get("districtCd") or ""),
                    state_cd=state.eci_state_cd,
                    category=a.get("category"),
                )
            )
        logger.info("{}: {} assemblies", state.short_code, len(out))
        return out

    def assemblies_for_district(
        self, state: StateInfo, district_cd: str
    ) -> list[AssemblyInfo]:
        return [a for a in self.assemblies(state) if a.district_cd == district_cd]

    def languages(self, state: StateInfo, ac_number: str | int) -> dict[str, str]:
        langs = self.probe.get_ac_languages(state.eci_state_cd, ac_number)
        self._pause()
        return langs


class SpaFormDriver:
    """Drive the public /download-eroll form via Playwright (no captcha bypass)."""

    def __init__(
        self,
        *,
        headless: bool = True,
        user_agent: str = "ECI-Eroll-Downloader/1.0 (+polite)",
        delay: float = 1.0,
        navigation_timeout_ms: int = 60_000,
        proxy: str | None = None,
    ) -> None:
        self.headless = headless
        self.user_agent = user_agent
        self.delay = delay
        self.navigation_timeout_ms = navigation_timeout_ms
        self.proxy = proxy
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self.download_url = "https://voters.eci.gov.in/download-eroll"

    def __enter__(self) -> SpaFormDriver:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        launch_args = ["--disable-blink-features=AutomationControlled"]
        try:
            # Installed Chrome is less likely to be flagged than bundled Chromium
            self._browser = self._pw.chromium.launch(
                headless=self.headless,
                channel="chrome",
                args=launch_args,
            )
        except Exception:
            try:
                self._browser = self._pw.chromium.launch(
                    headless=self.headless,
                    args=launch_args,
                )
            except Exception as exc:
                msg = str(exc)
                if "Executable doesn't exist" in msg or "playwright install" in msg.lower():
                    raise RuntimeError(
                        "Playwright Chromium is not installed for this environment.\n"
                        "Run:\n"
                        "  source .venv/bin/activate\n"
                        "  python -m playwright install chromium\n"
                        "Then retry your download_eroll.py command."
                    ) from exc
                raise

        ua = self._effective_user_agent()
        self._new_context(ua)
        return self

    def _new_context(self, ua: str | None = None) -> None:
        assert self._browser
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        ctx_kwargs: dict[str, Any] = {
            "user_agent": ua or self._effective_user_agent(),
            "viewport": {"width": 1366, "height": 900},
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
            "accept_downloads": True,
            "extra_http_headers": {"Accept-Language": "en-IN,en;q=0.9"},
        }
        if self.proxy:
            ctx_kwargs["proxy"] = proxy_for_playwright(self.proxy)
            logger.info("Browser using proxy {}", mask_proxy(self.proxy))
        self._context = self._browser.new_context(**ctx_kwargs)
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(self.navigation_timeout_ms)

    def set_proxy(self, proxy: str | None) -> None:
        """Switch proxy by recreating the browser context."""
        self.proxy = proxy
        if self._browser:
            self._new_context()

    def _effective_user_agent(self) -> str:
        ua = (self.user_agent or "").strip()
        if not ua or "ECI-Eroll" in ua or "bot" in ua.lower():
            return _REALISTIC_CHROME_UA
        return ua

    def __exit__(self, *exc: Any) -> None:
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def _pause(self, mult: float = 1.0) -> None:
        time.sleep(max(0.2, self.delay * mult))

    def open(self) -> None:
        """Open /download-eroll with session warm-up and retry on Akamai/login bounce."""
        assert self.page
        self._navigate_to_download_form()

    def session_broken(self) -> bool:
        """True when Akamai/login sent us away from the download form."""
        assert self.page
        url = self.current_url().lower()
        if "login" in url:
            return True
        try:
            text = str(
                self.page.evaluate("() => (document.body?.innerText || '').toLowerCase()")
            )
            if "something went wrong" in text:
                return True
        except Exception:
            pass
        if "download-eroll" in url:
            return not bool(self.page.query_selector('select[name="stateCode"]'))
        return True

    def _navigate_to_download_form(self, *, max_attempts: int = 3) -> None:
        assert self.page
        last_err = "unknown"
        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Opening {} (attempt {}/{})",
                self.download_url,
                attempt,
                max_attempts,
            )
            if attempt > 1:
                try:
                    self.page.context.clear_cookies()
                except Exception:
                    pass
                self._pause(2.0)

            # Warm Akamai session via homepage first
            try:
                self.page.goto(
                    _PORTAL_HOME,
                    wait_until="domcontentloaded",
                    timeout=self.navigation_timeout_ms,
                )
                self._pause(1.5)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Homepage warm-up skipped: {}", exc)

            self.page.goto(
                self.download_url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
            self._pause(2.0)

            if self.session_broken():
                last_err = f"redirected or error page (url={self.current_url()})"
                logger.warning("Session broken on attempt {}: {}", attempt, last_err)
                continue

            try:
                self.page.wait_for_selector(
                    'select[name="stateCode"]', timeout=60_000, state="visible"
                )
                logger.info("Download form ready at {}", self.current_url())
                self._pause(1.0)
                return
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                if not self.session_broken():
                    try:
                        self.page.wait_for_load_state("networkidle", timeout=20_000)
                        self.page.wait_for_selector(
                            'select[name="stateCode"]', timeout=20_000, state="visible"
                        )
                        return
                    except Exception as exc2:  # noqa: BLE001
                        last_err = str(exc2)
                logger.warning("Form not ready on attempt {}: {}", attempt, last_err)

        raise RuntimeError(
            "Could not load the ECI download form — the portal redirected to login "
            f"or showed 'Something went wrong' ({last_err}). "
            "Wait a minute and retry. If it persists, open "
            "https://voters.eci.gov.in/download-eroll manually in Chrome to confirm "
            "the site is up."
        )

    def available_years(self) -> list[str]:
        assert self.page
        years = self.page.evaluate(
            """() => {
              const s = document.querySelector('select[name=revyear]');
              if (!s) return [];
              return Array.from(s.options).map(o => o.value).filter(Boolean);
            }"""
        )
        return list(years)

    def select_state(self, state: StateInfo) -> None:
        assert self.page
        self.page.wait_for_selector('select[name="stateCode"]')
        self.page.select_option('select[name="stateCode"]', value=state.eci_state_cd)
        self._pause()

    def select_year(self, year: str) -> None:
        assert self.page
        self.page.wait_for_selector('select[name="revyear"]')
        self.page.select_option('select[name="revyear"]', value=str(year))
        self._pause(2.0)
        self.page.wait_for_timeout(int(1500 + self.delay * 1000))

    def roll_types(self) -> list[RollTypeInfo]:
        assert self.page
        raw = self.page.evaluate(
            """() => {
              const s = document.querySelector('select[name=roleType]');
              if (!s) return [];
              return Array.from(s.options).filter(o => o.value)
                .map(o => ({value: o.value, label: o.text.trim()}));
            }"""
        )
        out: list[RollTypeInfo] = []
        for item in raw:
            value = item["value"]
            label = item["label"]
            year_m = re.search(r"(20\d{2})", value) or re.search(r"(20\d{2})", label)
            year = year_m.group(1) if year_m else ""
            out.append(
                RollTypeInfo(
                    value=value,
                    label=label,
                    year=year,
                    kind=classify_roll_kind(value, label),
                )
            )
        return out

    def select_roll_type(self, value: str) -> None:
        assert self.page
        self.page.wait_for_selector('select[name="roleType"]', timeout=30_000)
        self.page.select_option('select[name="roleType"]', value=value)
        self._pause(1.5)
        # District cascade often appears only after roll type is chosen
        try:
            self.page.wait_for_selector('select[name="district"]', timeout=20_000)
        except Exception:
            logger.warning("District select did not appear after roll type {}", value)

    def district_options(self) -> list[tuple[str, str]]:
        assert self.page
        return self.page.evaluate(
            """() => {
              const s = document.querySelector('select[name=district]');
              if (!s) return [];
              return Array.from(s.options).filter(o => o.value)
                .map(o => [o.value, o.text.trim()]);
            }"""
        )

    def select_district(self, district_cd: str) -> None:
        assert self.page
        self.page.wait_for_selector('select[name="district"]', timeout=20_000)
        self.page.select_option('select[name="district"]', value=district_cd)
        self._pause(1.5)
        self._wait_for_constituency_select()

    def has_district_select(self) -> bool:
        assert self.page
        return bool(self.page.query_selector('select[name="district"]'))

    def has_constituency_select(self) -> bool:
        assert self.page
        return bool(self.page.query_selector('select[name="constituency"]'))

    def _wait_for_constituency_select(self, timeout_ms: int = 20_000) -> bool:
        """Wait until AC/constituency control is populated after district change."""
        assert self.page
        try:
            self.page.wait_for_selector(
                'select[name="constituency"]', timeout=timeout_ms, state="visible"
            )
            self.page.wait_for_function(
                """() => {
                  const s = document.querySelector('select[name=constituency]');
                  return s && s.options.length > 1;
                }""",
                timeout=timeout_ms,
            )
            return True
        except Exception:
            # Some states still use react-select for AC
            try:
                self.page.wait_for_selector(
                    'input[id^="react-select-"]', timeout=5_000, state="visible"
                )
                return True
            except Exception:
                return False

    def selected_constituency(self) -> str:
        assert self.page
        return str(
            self.page.evaluate(
                "() => (document.querySelector('select[name=constituency]') || {}).value || ''"
            )
            or ""
        )

    def selected_district(self) -> str:
        assert self.page
        return str(
            self.page.evaluate(
                "() => (document.querySelector('select[name=district]') || {}).value || ''"
            )
            or ""
        )

    def selected_language(self) -> str:
        assert self.page
        return str(
            self.page.evaluate(
                "() => (document.querySelector('select[name=langCd]') || {}).value || ''"
            )
            or ""
        )

    def current_assembly_label(self) -> str:
        """Visible AC label, e.g. '149 - Ariyalur' (native select or react-select)."""
        assert self.page
        return str(
            self.page.evaluate(
                """() => {
                  const sel = document.querySelector('select[name=constituency]');
                  if (sel && sel.selectedOptions.length) {
                    return (sel.selectedOptions[0].textContent || '').trim();
                  }
                  const el = document.querySelector(
                    '[class*="singleValue"], [class*="ValueContainer"]'
                  );
                  return el ? (el.textContent || '').trim() : '';
                }"""
            )
            or ""
        )

    def assembly_appears_selected(self, ac_number: str, ac_name: str = "") -> bool:
        ac_number = str(ac_number).strip()
        if self.has_constituency_select():
            selected = self.selected_constituency()
            if selected == ac_number:
                return True
        label = self.current_assembly_label()
        if not label or label.lower().startswith("select"):
            return False
        if label.startswith(f"{ac_number} -") or label.startswith(f"{ac_number}-"):
            return True
        if ac_name and ac_name.strip() and ac_name.strip().lower() in label.lower():
            return True
        return False

    def form_ready_for_download(
        self, ac_number: str, _language: str, ac_name: str = ""
    ) -> bool:
        """True when AC looks selected and part checkboxes are present."""
        if not self.assembly_appears_selected(ac_number, ac_name):
            return False
        return self.wait_for_parts_table(timeout_ms=3_000)

    def _select_assembly_native(self, ac_number: str, ac_name: str = "") -> bool:
        assert self.page
        query = str(ac_number).strip()
        self._wait_for_constituency_select()
        try:
            self.page.select_option('select[name="constituency"]', value=query)
        except Exception:
            if ac_name:
                pattern = re.compile(
                    rf"^{re.escape(query)}\s*[-–]\s*{re.escape(ac_name)}",
                    re.I,
                )
                self.page.select_option(
                    'select[name="constituency"]', label=pattern
                )
            else:
                pattern = re.compile(rf"^{re.escape(query)}\s*[-–]")
                self.page.select_option(
                    'select[name="constituency"]', label=pattern
                )
        self._pause(1.5)
        return bool(
            self.language_options() or self.assembly_appears_selected(query, ac_name)
        )

    def _select_assembly_react(self, ac_number: str, ac_name: str = "") -> bool:
        assert self.page
        query = str(ac_number).strip()

        clear_btn = self.page.locator(
            '[class*="clearIndicator"], [aria-label="Clear"]'
        ).first
        try:
            if clear_btn.count() and clear_btn.is_visible():
                clear_btn.click()
                self._pause(0.3)
        except Exception:
            pass

        inp = self.page.locator('input[id^="react-select-"]').first
        if inp.count() == 0:
            return False

        inp.click()
        self._pause(0.2)
        self.page.keyboard.press("ControlOrMeta+A")
        self.page.keyboard.press("Backspace")
        self._pause(0.2)
        inp.type(query, delay=40)
        self._pause(1.0)

        options = self.page.locator('[class*="option"], [id*="-option-"]')
        matched = False
        count = options.count()
        for i in range(min(count, 40)):
            text = options.nth(i).inner_text().strip()
            if text.startswith(f"{query} -") or text.startswith(f"{query}-"):
                options.nth(i).click()
                matched = True
                break
        if not matched:
            self.page.keyboard.press("ArrowDown")
            self.page.keyboard.press("Enter")
        self._pause(2.0)

        if self.language_options() or self.assembly_appears_selected(query, ac_name):
            return True

        if ac_name:
            inp.click()
            self.page.keyboard.press("ControlOrMeta+A")
            self.page.keyboard.press("Backspace")
            inp.type(ac_name[:48], delay=40)
            self._pause(1.0)
            self.page.keyboard.press("ArrowDown")
            self.page.keyboard.press("Enter")
            self._pause(2.0)
        return bool(
            self.language_options() or self.assembly_appears_selected(query, ac_name)
        )

    def select_assembly_by_number(self, ac_number: str, ac_name: str = "") -> bool:
        """Select AC via native <select> or react-select. Returns False if selection failed."""
        assert self.page
        query = str(ac_number).strip()

        if self.assembly_appears_selected(query, ac_name) and self.language_options():
            logger.info("AC already selected: {}", self.current_assembly_label())
            return True

        if self.has_constituency_select():
            if self._select_assembly_native(query, ac_name):
                return True
            logger.warning("Native constituency select failed for AC {}", query)

        if self._select_assembly_react(query, ac_name):
            return True

        logger.warning("Could not select AC {} ({})", query, ac_name or "?")
        return False

    def language_options(self) -> list[tuple[str, str]]:
        assert self.page
        return self.page.evaluate(
            """() => {
              const s = document.querySelector('select[name=langCd]');
              if (!s) return [];
              return Array.from(s.options).filter(o => o.value).map(o => [o.value, o.text.trim()]);
            }"""
        )

    def select_language(self, lang_cd: str) -> None:
        assert self.page
        self.page.select_option('select[name="langCd"]', value=lang_cd)
        self._pause(1.0)
        self.wait_for_parts_table()
        self._pause(1.0)

    def scrape_parts(self) -> list[tuple[str, str]]:
        """Return all (part_number, part_name) rows, walking every table page."""
        assert self.page
        if not self.wait_for_parts_table(timeout_ms=15_000):
            logger.warning("Parts table did not appear")
            return []

        self.go_to_first_parts_page()
        all_parts: list[tuple[str, str]] = []
        seen: set[str] = set()
        page_no = 0
        while True:
            page_no += 1
            for part_no, part_name in self._scrape_parts_current_page():
                if part_no not in seen:
                    seen.add(part_no)
                    all_parts.append((part_no, part_name))
            logger.debug("Parts page {} → {} rows ({} total)", page_no, len(seen), len(all_parts))
            if not self.go_to_next_parts_page():
                break
        logger.info("Scraped {} parts across {} page(s)", len(all_parts), page_no)
        return all_parts

    def _scrape_parts_current_page(self) -> list[tuple[str, str]]:
        """Parts visible on the current table page only."""
        assert self.page
        parts = self.page.evaluate(
            """() => {
              const out = [];
              const seen = new Set();
              document.querySelectorAll('table tr').forEach(tr => {
                const cb = tr.querySelector('input[type=checkbox]');
                if (!cb || cb.id === 'selectAll') return;
                const text = (tr.innerText || '').trim().replace(/\\s+/g, ' ');
                const m = text.match(/^(\\d+)\\s*-\\s*(.+)$/);
                if (m && !seen.has(m[1])) {
                  seen.add(m[1]);
                  out.push([m[1], m[2].trim()]);
                }
              });
              return out;
            }"""
        )
        return [(str(a), str(b)) for a, b in parts]

    def _first_part_row_text(self) -> str:
        assert self.page
        return str(
            self.page.evaluate(
                """() => {
                  const cb = document.querySelector('table input[type=checkbox]:not(#selectAll)');
                  return cb ? (cb.closest('tr').innerText || '').trim() : '';
                }"""
            )
            or ""
        )

    def has_parts_pagination(self) -> bool:
        assert self.page
        return bool(self.page.query_selector(".pagination-outer button.control-btn"))

    def go_to_first_parts_page(self) -> None:
        """Rewind the parts table to page 1 (no-op if already there)."""
        assert self.page
        if not self.has_parts_pagination():
            return
        for _ in range(100):
            at_first = bool(
                self.page.evaluate(
                    """() => {
                      const outer = document.querySelector('.pagination-outer');
                      if (!outer) return true;
                      const btns = Array.from(outer.querySelectorAll('button.control-btn'));
                      const rewind = btns.find(b => (b.textContent || '').trim() === '<<');
                      if (!rewind || rewind.disabled) return true;
                      rewind.click();
                      return false;
                    }"""
                )
            )
            if at_first:
                break
            self._pause(0.8)
        self._pause(0.3)

    def go_to_next_parts_page(self) -> bool:
        """Advance to the next parts-table page. Returns False on the last page."""
        assert self.page
        if not self.has_parts_pagination():
            return False
        before = self._first_part_row_text()
        clicked = bool(
            self.page.evaluate(
                """() => {
                  const outer = document.querySelector('.pagination-outer');
                  if (!outer) return false;
                  const btns = Array.from(outer.querySelectorAll('button.control-btn'));
                  const next = btns.find(b => (b.textContent || '').trim() === '>');
                  if (!next || next.disabled) return false;
                  next.click();
                  return true;
                }"""
            )
        )
        if not clicked:
            return False
        try:
            self.page.wait_for_function(
                """(before) => {
                  const cb = document.querySelector('table input[type=checkbox]:not(#selectAll)');
                  const now = cb ? (cb.closest('tr').innerText || '').trim() : '';
                  return now && now !== before;
                }""",
                before,
                timeout=15_000,
            )
        except Exception:
            self._pause(1.0)
        self.wait_for_parts_table(timeout_ms=10_000)
        self._pause(0.3)
        return True

    def current_parts_page_number(self) -> int:
        assert self.page
        raw = self.page.evaluate(
            """() => {
              const strong = document.querySelector('.pagination-outer span.control-btn2 strong');
              return strong ? strong.textContent.trim() : '1';
            }"""
        )
        try:
            return int(str(raw))
        except ValueError:
            return 1

    def select_part_checkbox(self, part_number: str) -> bool:
        """Tick the parts-table checkbox whose row starts with ``N -``."""
        assert self.page
        part_no = str(part_number).strip()
        return bool(
            self.page.evaluate(
                """(partNo) => {
                  const rows = Array.from(document.querySelectorAll('table tr'));
                  for (const tr of rows) {
                    const cb = tr.querySelector('input[type=checkbox]');
                    if (!cb || cb.id === 'selectAll') continue;
                    const text = (tr.innerText || '').trim();
                    // Match "1 - ..." but not "10 - ..." when looking for "1"
                    const m = text.match(/^(\\d+)\\s*-/);
                    if (m && m[1] === String(partNo)) {
                      if (!cb.checked) cb.click();
                      return cb.checked || true;
                    }
                  }
                  return false;
                }""",
                part_no,
            )
        )

    def clear_part_checkboxes(self) -> None:
        assert self.page
        self.page.evaluate(
            """() => {
              document.querySelectorAll('table input[type=checkbox]').forEach(cb => {
                if (cb.id === 'selectAll') {
                  if (cb.checked) cb.click();
                  return;
                }
                if (cb.checked) cb.click();
              });
            }"""
        )

    def wait_for_parts_table(self, timeout_ms: int = 20_000) -> bool:
        assert self.page
        try:
            self.page.wait_for_selector(
                'table input[type=checkbox]:not(#selectAll)', timeout=timeout_ms
            )
            return True
        except Exception:
            return False

    def select_all_parts_on_page(self) -> bool:
        """Click the Select All checkbox in the parts table header."""
        assert self.page
        return bool(
            self.page.evaluate(
                """() => {
                  const cb = document.querySelector('#selectAll');
                  if (!cb) return false;
                  if (!cb.checked) cb.click();
                  return true;
                }"""
            )
        )

    def captcha_input_ready(self) -> bool:
        assert self.page
        return bool(self.page.query_selector('input[name="captcha"]'))

    def wait_for_human_captcha(self, timeout_seconds: int = 300) -> str:
        """Wait until the operator finishes the captcha, then confirms in the terminal.

        Important: do **not** treat the first typed character as "done" — that caused
        premature Download clicks, captcha refreshes, and redirects to /login.
        """
        assert self.page
        from rich.console import Console

        console = Console()
        # Enter inside the captcha box submits the wrong form control and often
        # navigates to /login — block that while we wait for terminal confirmation.
        self._guard_captcha_enter_key(enabled=True)

        console.print()
        console.print(
            "[bold yellow]Batch download — one captcha covers ALL selected parts "
            "for this assembly.[/bold yellow]"
        )
        console.print(
            "[bold yellow]1) In the browser, type the FULL captcha into the Captcha field.[/bold yellow]"
        )
        console.print(
            "[bold yellow]2) Do NOT press Enter in the captcha box or click Download.[/bold yellow]"
        )
        console.print(
            "[bold yellow]3) Press Enter here when finished.[/bold yellow]"
        )
        console.print(f"[dim]Timeout: {timeout_seconds}s[/dim]")

        deadline = time.time() + timeout_seconds
        # Block until user confirms — avoids firing mid-keystroke
        while time.time() < deadline:
            # Non-blocking-ish: use input() which waits for Enter
            try:
                # Show live preview of captcha length without racing on first char
                preview = self.page.evaluate(
                    """() => {
                      const el = document.querySelector('input[name=captcha]');
                      if (!el) return {ok:false, reason:'no-field', len:0, url: location.href};
                      return {
                        ok: true,
                        len: (el.value || '').trim().length,
                        value: (el.value || '').trim(),
                        url: location.href
                      };
                    }"""
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Browser page became unavailable while waiting for captcha: {exc}. "
                    "If you were sent to /login, close that tab flow and re-run; "
                    "download-eroll should stay on the electoral roll form."
                ) from exc

            if preview and "login" in str(preview.get("url", "")).lower():
                raise RuntimeError(
                    "Browser redirected to the Login page. "
                    "The download form session was lost (often after a too-early Download click "
                    "or captcha refresh). Re-run the command and wait for the terminal "
                    "prompt before finishing the captcha."
                )

            console.print(
                f"[dim]Captcha field length right now: {preview.get('len', 0)} "
                f"(URL: {preview.get('url', '?')})[/dim]"
            )
            try:
                answer = input("Press Enter after the FULL captcha is typed (or type 'abort'): ")
            except EOFError as exc:
                raise TimeoutError("No terminal input available for captcha confirmation") from exc

            if str(answer).strip().lower() in {"abort", "q", "quit"}:
                self._guard_captcha_enter_key(enabled=False)
                raise RuntimeError("Captcha wait aborted by user")

            val = self.page.evaluate(
                "() => ((document.querySelector('input[name=captcha]')||{}).value || '').trim()"
            )
            url = self.page.evaluate("() => location.href")
            if "login" in str(url).lower():
                self._guard_captcha_enter_key(enabled=False)
                raise RuntimeError(
                    "Browser is on /login — usually from pressing Enter in the captcha "
                    "box or clicking the green full-AC download button. "
                    "Form will be restored; type captcha without Enter, confirm here."
                )
            if val and len(val) >= 4:
                # Stability check: value unchanged briefly
                time.sleep(0.4)
                val2 = self.page.evaluate(
                    "() => ((document.querySelector('input[name=captcha]')||{}).value || '').trim()"
                )
                if val2 == val:
                    # Blur captcha so a lingering Enter cannot submit the green button
                    self.page.evaluate(
                        """() => {
                          const el = document.querySelector('input[name=captcha]');
                          if (el) el.blur();
                        }"""
                    )
                    console.print(
                        f"[green]Captcha confirmed (length {len(val)}). "
                        "Clicking 'Download Selected PDFs'…[/green]"
                    )
                    self._guard_captcha_enter_key(enabled=False)
                    return val
                console.print("[yellow]Captcha still changing — finish typing, then press Enter again.[/yellow]")
                continue
            console.print(
                "[yellow]Captcha looks empty/too short. Type the full code in the browser, "
                "then press Enter here.[/yellow]"
            )

        self._guard_captcha_enter_key(enabled=False)
        raise TimeoutError("Timed out waiting for human captcha confirmation")

    def _guard_captcha_enter_key(self, *, enabled: bool) -> None:
        """Prevent Enter in the captcha field from submitting the wrong button."""
        assert self.page
        self.page.evaluate(
            """(enabled) => {
              const el = document.querySelector('input[name=captcha]');
              if (!el) return;
              if (el.__eciEnterGuard) {
                el.removeEventListener('keydown', el.__eciEnterGuard, true);
                el.__eciEnterGuard = null;
              }
              if (!enabled) return;
              const handler = (e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  e.stopPropagation();
                  e.stopImmediatePropagation();
                }
              };
              el.__eciEnterGuard = handler;
              el.addEventListener('keydown', handler, true);
            }""",
            enabled,
        )

    def current_url(self) -> str:
        assert self.page
        return str(self.page.evaluate("() => location.href") or "")

    def on_login_page(self) -> bool:
        url = self.current_url().lower()
        if "login" in url:
            return True
        try:
            text = str(
                self.page.evaluate("() => (document.body?.innerText || '').toLowerCase()")
            )
            return "something went wrong" in text
        except Exception:
            return False

    def ensure_on_download_page(self) -> None:
        assert self.page
        url = self.current_url()
        if "login" in url.lower():
            raise RuntimeError(
                f"Unexpected navigation to login ({url}). "
                "Wrong/expired captcha often causes this — form will be restored."
            )
        if "download-eroll" not in url and "download" not in url.lower():
            logger.warning("Unexpected URL during download: {}", url)

    def selected_year(self) -> str:
        assert self.page
        return str(
            self.page.evaluate(
                "() => (document.querySelector('select[name=revyear]') || {}).value || ''"
            )
            or ""
        )

    def selected_roll_type(self) -> str:
        assert self.page
        return str(
            self.page.evaluate(
                "() => (document.querySelector('select[name=roleType]') || {}).value || ''"
            )
            or ""
        )

    def prepare_form_for_ac(
        self,
        *,
        state: StateInfo,
        year: str,
        roll_value: str,
        district_cd: str,
        ac_number: str,
        ac_name: str,
        language: str,
    ) -> None:
        """Ensure district/AC/language/parts table are ready (recovers from /login)."""
        assert self.page
        need_top = (
            self.on_login_page()
            or "download-eroll" not in self.current_url()
            or self.selected_year() != str(year)
            or (self.selected_roll_type() and self.selected_roll_type() != roll_value)
        )
        if need_top:
            if self.on_login_page() or "download-eroll" not in self.current_url():
                logger.warning(
                    "Browser left download-eroll (url={}); reopening form",
                    self.current_url(),
                )
            else:
                logger.info(
                    "Re-applying revision {} / {} (form had year={} roll={})",
                    year,
                    roll_value,
                    self.selected_year(),
                    self.selected_roll_type(),
                )
            self._navigate_to_download_form()
            self.select_state(state)
            self.select_year(year)
            self.select_roll_type(roll_value)

        if self.form_ready_for_download(ac_number, language, ac_name):
            if self.language_options() and self.selected_language() != language:
                self.select_language(language)
                if not self.wait_for_parts_table(timeout_ms=20_000):
                    raise RuntimeError("Parts table missing after language select")
            return

        if self.selected_district() != district_cd or not self.has_district_select():
            if not self.has_district_select():
                self._navigate_to_download_form()
                self.select_state(state)
                self.select_year(year)
                self.select_roll_type(roll_value)
            self.select_district(district_cd)

        if not self.select_assembly_by_number(ac_number, ac_name):
            raise RuntimeError(
                f"Could not select assembly {ac_number} ({ac_name}) while restoring form"
            )
        if self.language_options():
            self.select_language(language)
        if not self.wait_for_parts_table(timeout_ms=20_000):
            raise RuntimeError("Parts table not visible after restoring form")

    def click_download_selected_pdfs(self) -> None:
        """Click only the blue 'Download Selected PDFs' control.

        Important: do **not** match ``button.submit`` — that often hits the green
        'Download … Draft Roll for full AC' button, which redirects to /login.
        """
        assert self.page
        self.ensure_on_download_page()
        # Prefer exact role/name; fall back to text contains, excluding draft/full-AC.
        btn = self.page.get_by_role("button", name="Download Selected PDFs")
        if btn.count() == 0:
            btn = self.page.locator("button").filter(
                has_text=re.compile(r"Download Selected PDFs", re.I)
            )
        if btn.count() == 0:
            raise RuntimeError("Could not find 'Download Selected PDFs' button")
        target = btn.first
        label = (target.inner_text() or "").strip()
        if re.search(r"full\s*AC|Draft\s*Roll", label, re.I):
            raise RuntimeError(
                f"Refusing to click the wrong download button: {label!r}"
            )
        target.click()

    def download_selected_pdf(self, dest: Path, *, timeout_ms: int = 60_000) -> Path:
        """Click Download Selected PDFs and save, failing fast on /login redirects."""
        assert self.page
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_on_download_page()
        try:
            with self.page.expect_download(timeout=timeout_ms) as di:
                self.click_download_selected_pdfs()
            download = di.value
            download.save_as(str(dest))
        except Exception as exc:
            if self.on_login_page():
                raise RuntimeError(
                    "Site redirected to /login after download click. Usually this means "
                    "(1) Enter was pressed in the captcha box, or (2) the green "
                    "'Download … full AC' button was used, or (3) captcha was wrong. "
                    "Type captcha without Enter, confirm in the terminal only."
                ) from exc
            raise
        if self.on_login_page():
            raise RuntimeError("Site redirected to /login after Download")
        if not dest.exists() or dest.stat().st_size == 0:
            raise RuntimeError("Downloaded file missing or empty")
        return dest

    def download_selected_parts_batch(
        self,
        *,
        part_downloads: list[tuple[str, Path]],
        captcha_timeout_seconds: int = 300,
        timeout_ms: int = 180_000,
    ) -> list[Path]:
        """Select-all per table page, captcha, download — repeats for every page.

        The ECI portal shows ~10 parts per page. Selection does not carry across
        pages, so we batch-download each page the same way (select all → captcha →
        download).
        """
        assert self.page

        if not part_downloads:
            return []

        pending: dict[str, Path] = {str(no): path for no, path in part_downloads}
        self.ensure_on_download_page()
        if not self.wait_for_parts_table(timeout_ms=15_000):
            raise RuntimeError("Parts table not visible")

        self.go_to_first_parts_page()
        saved: list[Path] = []
        page_idx = 0

        while pending:
            page_idx += 1
            if not self.wait_for_parts_table(timeout_ms=15_000):
                raise RuntimeError("Parts table not visible during pagination")

            page_parts = self._scrape_parts_current_page()
            wanted = [no for no, _ in page_parts if no in pending]
            if not wanted:
                if not self.go_to_next_parts_page():
                    break
                continue

            page_num = self.current_parts_page_number()
            logger.info(
                "Parts page {} — batching {} part(s) (select all → captcha → download)",
                page_num,
                len(wanted),
            )

            self.clear_part_checkboxes()
            if len(wanted) == len(page_parts):
                if not self.select_all_parts_on_page():
                    raise RuntimeError("Could not select all parts on page")
            else:
                for part_no in wanted:
                    if not self.select_part_checkbox(part_no):
                        raise RuntimeError(f"Could not select part {part_no} on page {page_num}")

            self.wait_for_human_captcha(captcha_timeout_seconds)

            page_dests = [pending[no] for no in wanted]
            page_saved = self._download_selected_on_current_page(
                dest_paths=page_dests,
                timeout_ms=timeout_ms,
            )
            for no, path in zip(wanted, page_saved):
                if path.exists() and path.stat().st_size > 0:
                    pending.pop(no, None)
                    saved.append(path)

            if pending and not self.go_to_next_parts_page():
                break

        if pending:
            logger.warning(
                "Batch download finished with {} part(s) still pending: {}",
                len(pending),
                ", ".join(sorted(pending.keys(), key=lambda x: int(x))[:12]),
            )
        return saved

    def _download_selected_on_current_page(
        self,
        *,
        dest_paths: list[Path],
        timeout_ms: int = 180_000,
    ) -> list[Path]:
        """Click Download Selected PDFs for the current page selection."""
        assert self.page
        if not dest_paths:
            return []

        collected: list = []
        saved: list[Path] = []

        def _on_download(download) -> None:
            collected.append(download)

        self.page.on("download", _on_download)
        try:
            self.click_download_selected_pdfs()
            deadline = time.time() + (timeout_ms / 1000.0)
            while time.time() < deadline:
                if self.on_login_page():
                    raise RuntimeError(
                        "Redirected to /login — captcha was wrong or expired."
                    )
                if len(collected) >= len(dest_paths):
                    break
                if len(collected) == 1 and len(dest_paths) == 1:
                    break
                self.page.wait_for_timeout(500)
            else:
                if not collected:
                    raise RuntimeError(
                        "No download started — captcha may be wrong or the site is slow"
                    )
        finally:
            self.page.remove_listener("download", _on_download)

        if len(collected) == 1 and len(dest_paths) > 1:
            dest_paths[0].parent.mkdir(parents=True, exist_ok=True)
            collected[0].save_as(str(dest_paths[0]))
            return [dest_paths[0]]

        for i, download in enumerate(collected[: len(dest_paths)]):
            dest = dest_paths[i]
            dest.parent.mkdir(parents=True, exist_ok=True)
            download.save_as(str(dest))
            saved.append(dest)

        if len(saved) < len(dest_paths):
            logger.warning(
                "Expected {} files on page, received {}",
                len(dest_paths),
                len(saved),
            )
        return saved


def pick_preferred_roll(
    rolls: list[RollTypeInfo], prefer_kinds: list[str]
) -> RollTypeInfo | None:
    if not rolls:
        return None

    def score(r: RollTypeInfo) -> tuple[int, int, int, str]:
        """Lower is better. Prefer Draft over Final when SIR Final is already out."""
        blob = f"{r.value} {r.label}".upper()
        bye_penalty = 50 if ("BY" in blob or "BYE" in blob) else 0
        kind_rank = 99
        upper_pref = [k.upper() for k in prefer_kinds]
        for i, kind in enumerate(upper_pref):
            if r.kind.upper() == kind or kind in r.kind.upper() or kind in blob:
                kind_rank = i
                break
        # Among drafts, prefer SIR Draft (matches the portal's SIR draft roll)
        sir_draft_boost = 0 if ("SIR" in blob and r.kind in {"DR", "DRAFT"}) else 1
        # Deprioritize supplements
        supp_penalty = 5 if "SUPP" in blob else 0
        return (
            bye_penalty + supp_penalty + kind_rank,
            sir_draft_boost,
            len(r.label),
            r.value,
        )

    return sorted(rolls, key=score)[0]


def pick_language(
    available: list[tuple[str, str]], preferred: str | None
) -> tuple[str, str] | None:
    if not available:
        return None
    if preferred:
        pref = preferred.upper()
        for code, name in available:
            if code.upper() == pref or name.upper().startswith(pref):
                return code, name
    # Prefer ENG when present
    for code, name in available:
        if code.upper() == "ENG":
            return code, name
    return available[0]
