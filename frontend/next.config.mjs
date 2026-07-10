/** @type {import('next').NextConfig} */
const backendProxy = process.env.BACKEND_PROXY_URL;

const nextConfig = {
  reactStrictMode: true,
  // When BACKEND_PROXY_URL is set (full-stack e2e / same-site deployments), the
  // frontend serves the API under its own origin so the session cookie is
  // same-site. Unset in normal dev (the client talks to the API directly).
  async rewrites() {
    if (!backendProxy) return [];
    return [{ source: "/api/:path*", destination: `${backendProxy}/api/:path*` }];
  },
};

export default nextConfig;
