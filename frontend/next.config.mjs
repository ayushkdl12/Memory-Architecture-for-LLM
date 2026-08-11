/** @type {import('next').NextConfig} */
const nextConfig = {
  rewrites: async () => [
    { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
    { source: "/media/:path*", destination: "http://localhost:8000/media/:path*" },
  ],
};

export default nextConfig;
