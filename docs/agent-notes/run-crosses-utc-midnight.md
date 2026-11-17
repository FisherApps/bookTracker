---
name: run-crosses-utc-midnight
description: Scrape runs that span UTC midnight split one run across two capture_dates, making the dashboard show ~half the books as unranked
metadata:
  type: project
---

Dad reported "lots of books not ranked" on 2026-11-17. Cause: the scrape starts ~23:00 UTC and takes ~1.5h, and `capture_date` was computed per book from `now` — so one run became e.g. 40 books on 11-16 + 49 on 11-17. The dashboard uses `MAX(capture_date)` as "latest", so it showed only 49/90. Run logs still said 89/90 succeeded, so check `snapshots` counts per capture_date, not just the log.

**Fix (2026-11-17):** `src/scrape.py` now fixes `run_date` once in `main()` and passes it through `run_pass`/`process_book`. Existing split days (2026-08-27, 11-02, 11-09, 11-16) were merged into the earlier date in bsr.db.

**How to apply:** if the dashboard again shows a partial set, query `select capture_date,count(distinct asin) from snapshots group by 1` first. Separate from [[cf-worker-defeats-captcha]] (real captcha/timeouts, a handful of books).
