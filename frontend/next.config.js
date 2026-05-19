/** @type {import('next').NextConfig} */
const nextConfig = {
  // El frontend corre en el contenedor Docker, el backend en otro contenedor.
  // rewrites() actúa como proxy inverso para evitar problemas de CORS en dev.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
