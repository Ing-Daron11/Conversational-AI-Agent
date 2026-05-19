/** @type {import('next').NextConfig} */
const nextConfig = {
  // El frontend corre en el contenedor Docker, el backend en otro contenedor.
  // rewrites() actúa como proxy inverso para evitar problemas de CORS en dev.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        // Las rewrites se evalúan en el servidor Next.js (dentro de Docker).
      // Usar API_INTERNAL_URL (hostname Docker) en lugar de localhost.
      destination: `${process.env.API_INTERNAL_URL || "http://backend:8000"}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
