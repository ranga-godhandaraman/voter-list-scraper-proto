# ECI Download E-Roll — Documentation

Public technical reconnaissance **plus** a compliant SPA-driven downloader.

This project does **not** bypass CAPTCHA, request signing, or anti-bot controls.

## Contents

- [01 Website Architecture](01_website_architecture.md)
- [02 Download Flow](02_download_flow.md)
- [03 API Inventory](03_api_inventory.md)
- [04 Network Analysis](04_network_analysis.md)
- [05 Feasibility & Recommendations](05_feasibility_and_recommendations.md)
- [06 Future Compliant Crawler Design](06_future_compliant_crawler_design.md)
- [07 DOM Inventory](07_dom_inventory.md)
- [08 Anti-Automation (Identify Only)](08_anti_automation.md)
- [09 Downloader](09_downloader.md)

## Primary deliverables

| Artifact | Path |
|----------|------|
| Excel workbook | `excel/eci_eroll_reconnaissance.xlsx` |
| Master JSON | `output/recon_master.json` |
| Downloader entry | `download_eroll.py` |
| Download ledger | `downloads/downloads.sqlite` |
