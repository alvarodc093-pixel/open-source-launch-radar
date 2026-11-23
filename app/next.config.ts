import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Sin el AGENTS.md que `next dev` escribe por defecto en la carpeta de la app.
  agentRules: false,
  // Los JSON de data/ se leen en el servidor; hay que incluirlos en el bundle
  // de las funciones de Vercel porque no se importan de forma estática.
  outputFileTracingIncludes: { "/**": ["./data/**/*.json"] },
  // Las fichas del asistente enlazan /?paquete=…: la portada lo manda al radar.
  async redirects() {
    return [
      { source: "/mercado", destination: "/", permanent: true },
      {
        source: "/",
        has: [{ type: "query", key: "paquete" }],
        destination: "/radar",
        permanent: true,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
