---
name: cf-worker-defeats-captcha
description: "Two distinct scrape failure modes: a git commit bug (fixed) and intermittent Amazon captcha on CF egress IPs"
metadata: 
  node_type: memory
  type: project
---

The daily scrape (`.github/workflows/scrape.yml`, via `src/fetch.py` + Cloudflare Worker proxy `cloudflare-worker/src/worker.js`, routed by `AMAZON_PROXY_URL`/`AMAZON_PROXY_TOKEN`) has had TWO separate failure modes — don't conflate them:

1. **Git commit bug (FIXED 2026-06-11, commit e293480).** Runs June 5–8 scraped 90/90 fine but died at the commit step: `git pull --rebase` ran *before* `git add`, and the scrape always leaves `bsr.db`/`dashboard.html` modified-unstaged → `cannot pull with rebase: You have unstaged changes` (exit 128). Reordered to add → commit → pull --rebase → push in all 4 jobs. June 10 then succeeded.

2. **Intermittent captcha on the CF Worker (ONGOING).** The CF Worker proxy does NOT reliably defeat captcha — it's intermittent. Clean June 8 & 10 (90/90), fully blocked June 11 (captcha from the first request, all 4 jobs tripped the circuit breaker, 0 books). Amazon captchas Cloudflare's shared egress IPs on some days.

**Key insight:** routing *all* traffic (incl. the 3 retry jobs) through the CF Worker removed the IP diversity that originally made retries work — each GH-Actions retry used to get a fresh Azure IP; now all 4 jobs share the same CF egress pool, so when CF is blocked, retrying through CF is useless and all 4 fail identically.

**How to apply:** when a run "fails", grep the Actions log for `Run complete` and `CIRCUIT BREAKER` / `[error]`. Commit-step exit 128 = the git bug (should be gone). `circuit breaker tripped` / `captcha_string_detected` = real captcha — and retrying through the same CF Worker won't help. A reliable fix likely needs IP diversity (e.g. retry passes going direct for fresh Azure IPs) or a non-scraping data source.
