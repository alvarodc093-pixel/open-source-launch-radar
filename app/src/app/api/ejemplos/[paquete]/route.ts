/** GET /api/ejemplos/[paquete] — descargas diarias de un lanzamiento del conjunto de test. */

import { NextResponse } from "next/server";

import { datosRadar } from "@/lib/datos";

export async function GET(_request: Request, { params }: { params: Promise<{ paquete: string }> }) {
  const { paquete } = await params;
  // Nombres normalizados de PyPI (PEP 503): minúsculas, cifras y guiones.
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(paquete)) {
    return NextResponse.json(
      { error: "El nombre tiene que estar normalizado: minúsculas, cifras y guiones." },
      { status: 400 },
    );
  }
  let radar;
  try {
    radar = await datosRadar();
  } catch {
    return NextResponse.json(
      { error: "Faltan los datos del modelo. Ejecuta `python -m radar.exportar`." },
      { status: 503 },
    );
  }
  const ejemplo = radar.ejemplos.find((e) => e.paquete === paquete);
  if (!ejemplo) {
    return NextResponse.json({ error: "Ese paquete no está entre los ejemplos." }, { status: 404 });
  }
  return NextResponse.json(ejemplo, {
    headers: { "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400" },
  });
}
