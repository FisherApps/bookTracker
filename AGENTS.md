# bookTracker

## Notes from past sessions

Lessons and decisions from earlier work on this project, one per file in
`docs/agent-notes/`. Read the ones relevant to your task before starting.
When you learn something non-obvious (a trap, a decision and its reason, a
preference of Brian's), add a short file there and a line to this list.
Notes record what was true when written; check a file or flag still exists
before relying on it.

- [Scrape failure modes](docs/agent-notes/cf-worker-defeats-captcha.md) — two distinct causes: git commit bug (fixed) vs. intermittent captcha on CF egress IPs; retrying through the same CF Worker doesn't help
- [Creators API has BSR](docs/agent-notes/creators-api-has-bsr.md) — Amazon Creators API returns sales rank via browseNodeInfo, but needs affiliate sales (user not eligible — selling books ≠ Associates)
- [SP-API sales ranks](docs/agent-notes/sp-api-salesranks.md) — user is a 3P seller, so SP-API Catalog Items returns BSR (displayGroupRanks=headline, classificationRanks=subs); best captcha-free path, pending a test against the 90 ASINs
- [Run crosses UTC midnight](docs/agent-notes/run-crosses-utc-midnight.md) — per-book capture_date split one run across two days → dashboard showed ~half the books; fixed by fixing run_date once
