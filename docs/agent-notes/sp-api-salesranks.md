---
name: sp-api-salesranks
description: SP-API Catalog Items DOES return BSR for sellers; the captcha-free migration path the user is most eligible for
metadata: 
  node_type: memory
  type: reference
---

The user is a **Seller Central (3P) seller** on amazon.com, so the **Selling Partner API (SP-API)** is available to them — NOT the Creators API (that needs affiliate referral sales; selling your own books doesn't count). See [[creators-api-has-bsr]].

**SP-API Catalog Items API v2022-04-01** (`getCatalogItem` / `searchCatalogItems`, `includedData=salesRanks`) returns BSR. Verified from Amazon's own canonical example response (user-supplied 2026-06-11): the `salesRanks` block has two arrays —
- `displayGroupRanks[]` → the **headline/department rank** (e.g. `title:"Electronics", rank:72855` = the "#72,855 in Electronics" on the page). For a book this carries the "#X in Books"/"Kindle Store" number — the primary metric.
- `classificationRanks[]` → **sub-category ranks** (e.g. `classificationId:"21489946011", title:"QLED TVs", rank:113`).

Maps cleanly to `src/parse.py`/db: `title`→category_name, `classificationId`→category_id, `rank`→rank; displayGroupRanks entry = headline BSR.

**Caveats:** (1) Known inconsistency (closed-stale issue amzn/selling-partner-api-models#2533) — API returns only a SUBSET of the ranks shown on the page ("highly relevant" only), so you may get fewer *sub*-category ranks than scraping; the headline rank generally comes through. (2) Setup: register a **private app**, **self-authorize** as Seller Central Primary User (no Amazon app review), LWA refresh token (renew yearly), no AWS SigV4 since 2023. Free.

**Status / next step:** not yet attempted. Decision pending an empirical test — user sets up SP-API self-auth, then run a script over all 90 ASINs to confirm the headline "Books/Kindle Store" rank returns reliably and count sub-ranks, before migrating off the (working, hardened) scraper. If good enough, this retires the captcha problem entirely.
