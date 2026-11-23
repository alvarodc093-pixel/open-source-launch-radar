import type { Metadata } from "next";
import Link from "next/link";

import Secciones, { Siguiente } from "@/components/Secciones";
import "./globals.css";

const DESCRIPCION =
  "Con las descargas de los primeros días, estima cómo cerrará el primer mes de una librería de Python en PyPI y lo compara con lanzamientos parecidos.";

export const metadata: Metadata = {
  metadataBase: new URL("https://open-source-launch-radar.vercel.app"),
  title: { default: "Open Source Launch Radar", template: "%s · Open Source Launch Radar" },
  description: DESCRIPCION,
  openGraph: {
    title: "Open Source Launch Radar",
    description: DESCRIPCION,
    locale: "es_ES",
    type: "website",
  },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <a className="saltar" href="#contenido">
          Saltar al contenido
        </a>
        <header className="cabecera">
          <div className="contenedor">
            <Link href="/" className="marca">
              Open Source Launch <span>Radar</span>
            </Link>
            <Secciones />
          </div>
        </header>
        <main id="contenido" className="contenedor">
          {children}
          <Siguiente />
        </main>
        <footer className="pie">
          <div className="contenedor">
            Datos públicos de PyPI (a través de ClickPy) y de GitHub. Las descargas de usuario son
            una aproximación al uso de una librería: cuentan instalaciones, no personas.
          </div>
        </footer>
      </body>
    </html>
  );
}
