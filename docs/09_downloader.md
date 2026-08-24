# Electoral Roll Downloader

Extends the reconnaissance project. Does **not** modify analyzer modules.

## Behaviour (CLI-first)

1. Resolve `--state GJ` and `--district Ahmedabad`
2. Discover assemblies + parts via public HTTP + **headless** Playwright (no visible browser)
3. Prefer **SIR Draft**; if unavailable, show a numbered list in the terminal and ask which roll type to use
4. Download **all parts** in the district, **one captcha per assembly** (batch select-all), captcha shown in terminal

## Proxies (optional)

If your local IP is blocked by Akamai, pass a text file with one proxy per line.
Without `--proxies`, traffic uses your **local machine IP** (default).

```bash
python download_eroll.py -s GJ --district Ahmedabad --proxies ./proxies.txt
```

Supported line formats:

```
1.2.3.4:8080
http://user:pass@1.2.3.4:8080
1.2.3.4:8080:user:pass
1.2.3.4:8080:user:pass:exit_ip
# comments and blank lines are ignored
```

The 5-field `host:port:user:pass:exit_ip` format (common with residential providers) is supported; the last field is ignored.

Proxies rotate automatically if the portal blocks a session (login / "Something went wrong").
Both HTTP API calls and the Playwright browser use the same active proxy.

## Terminal interaction

- Roll-type menu in terminal when SIR Draft is unavailable
- **Captcha in the browser** — type it in the visible window, then press Enter in the terminal
- **Paginated parts table** — ECI shows ~10 parts per page; discovery walks every page
- **One captcha per page batch** (select all on that page → download), not per individual part

## CLI

```bash
python download_eroll.py --state GJ --district Ahmedabad
python download_eroll.py -s TN --district Ariyalur --language ENG
python download_eroll.py -s GJ --district Ahmedabad --dry-run
python download_eroll.py --list-states
```

When SIR Draft is unavailable:

```bash
# Interactive — pick from numbered list in terminal
python download_eroll.py -s GJ --district Ahmedabad

# Non-interactive — pick roll #2 from the list
python download_eroll.py -s GJ --district Ahmedabad --roll-index 2
```

## Resume

Re-running skips files that already exist (and completed DB rows) unless `--force`.
