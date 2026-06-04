# amazon-proxy Cloudflare Worker

A tiny request forwarder. The scraper calls this Worker; the Worker calls Amazon. This puts the outgoing request on Cloudflare's edge IPs (which Amazon almost never blocks) instead of GitHub Actions' Azure IPs (which Amazon increasingly does).

## Deploy

```bash
cd cloudflare-worker
npx wrangler login      # one-time browser auth
npx wrangler secret put PROXY_TOKEN   # paste the shared token
npx wrangler deploy
```

The deploy prints a URL like `https://amazon-proxy.<your-subdomain>.workers.dev`. Add that URL and the same `PROXY_TOKEN` to GitHub Actions secrets as `AMAZON_PROXY_URL` and `AMAZON_PROXY_TOKEN`.
