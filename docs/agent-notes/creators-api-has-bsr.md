---
name: creators-api-has-bsr
description: Amazon Creators API (PA-API successor) DOES return BSR/sales rank; the migration path that retires scraping
metadata: 
  node_type: memory
  type: reference
---

The Amazon **Creators API** (https://affiliate-program.amazon.com/creatorsapi/docs/, OAuth 2.0, successor to the retired PA-API v5 — PA-API deprecated 2026-04-30, shut down 2026-05-15) **does return sales rank / BSR**. Verified 2026-06-11 from the open-source Creators API client `goark/pa-api` (resource enums + passing decode tests), since Amazon's own docs are auth-gated (403 to web fetch).

BSR comes via the `browseNodeInfo` resource (camelCase = Creators API format):
- `browseNodeInfo.websiteSalesRank` → headline overall sales rank
- `browseNodeInfo.browseNodes[].salesRank` → per-category sub-rank (+ category id/name)

This maps cleanly onto what `src/parse.py` scrapes today (multiple category ranks per book). Migration would replace the HTML scrape+parse in `src/fetch.py`/`src/parse.py` with a `GetItems` call requesting `["browseNodeInfo.browseNodes","browseNodeInfo.websiteSalesRank"]` — no captchas, retiring the entire GitHub-Azure/Cloudflare IP-diversity setup. See [[cf-worker-defeats-captcha]].

**The blocker is eligibility, not data:** Creators API requires an Associates account with **10 qualifying sales in the last 30 days**. Whether the user qualifies is unknown (only their Associates Central shows it). Caveat: Amazon returns only "highly relevant" top ranks, so a few deep sub-category ranks visible on the page may be absent from the API (main BSR always present).
