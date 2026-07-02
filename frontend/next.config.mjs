/** @type {import('next').NextConfig} */
// Serve under a sub-path (e.g. /cue) by setting NEXT_PUBLIC_BASE_PATH at build time. Empty =
// hosted at root. When set, Next prefixes all routes + assets so it works behind an nginx
// location like `/cue/`. The API base (NEXT_PUBLIC_API_URL) must point at the same public
// prefix, e.g. https://host/cue (its /api and /ws calls then land under /cue).
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: false, // avoid double WebSocket connects in dev
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
};

export default nextConfig;
