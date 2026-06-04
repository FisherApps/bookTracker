// Forwards GET /dp/<ASIN> requests to www.amazon.com from Cloudflare's edge,
// so our scraper doesn't have to send requests from GitHub Actions' (often
// captcha-blocked) Azure IP ranges. Auth is a single shared bearer token
// stored as a Worker secret (PROXY_TOKEN).

export default {
  async fetch(request, env) {
    if (request.headers.get('Authorization') !== `Bearer ${env.PROXY_TOKEN}`) {
      return new Response('Unauthorized', { status: 401 });
    }

    const url = new URL(request.url);
    if (!url.pathname.startsWith('/dp/')) {
      return new Response('Not Found', { status: 404 });
    }

    const target = `https://www.amazon.com${url.pathname}${url.search}`;

    const fwdHeaders = new Headers();
    for (const [k, v] of request.headers.entries()) {
      const lk = k.toLowerCase();
      if (lk === 'authorization' || lk === 'host' || lk.startsWith('cf-') || lk.startsWith('x-forwarded-')) continue;
      fwdHeaders.set(k, v);
    }

    const upstream = await fetch(target, {
      method: 'GET',
      headers: fwdHeaders,
      redirect: 'follow',
    });

    return new Response(upstream.body, {
      status: upstream.status,
      headers: upstream.headers,
    });
  },
};
