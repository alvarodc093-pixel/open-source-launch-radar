import type { Metadata } from "next";

import FormularioRadar from "@/components/FormularioRadar";
import type { DatosPortada, Destacado } from "@/components/PortadaRadar";
import SinDatos from "@/components/SinDatos";
import { datosMercado, datosRadar } from "@/lib/datos";
import { leerRadar, type Veredicto } from "@/lib/radar";
import type { DatosRadar } from "@/lib/tipos";

export const metadata: Metadata = { title: "Radar" };
export const dynamic = "force-dynamic";

const DIA_DESTACADOS = 7;
const ORDEN: Veredicto[] = ["por_encima", "en_linea", "por_debajo"];

/**
 * Un paquete de test por veredicto para la portada: el de más descargas entre
 * los que cerraron el mes dentro del rango estimado, para que el ejemplo
 * enseñe cómo funciona el radar y no un caso raro.
 */
function destacados(radar: DatosRadar, dia: number, categorias: string[]): Destacado[] {
  const mejores = new Map<Veredicto, { destacado: Destacado; final: number }>();
  for (const e of radar.ejemplos) {
    const l = e.lecturas[String(dia)];
    if (!l) continue;
    const lectura = leerRadar(radar, {
      dia,
      usuario: l.usuario,
      total: l.total,
      subidas: l.subidas,
      dependencias: e.dependencias,
      propietario_tipo: e.propietario_tipo,
      categoria: categorias.includes(e.categoria) ? e.categoria : "Otras",
    });
    const { inferior, superior, central } = lectura.estimacion;
    if (e.usuario_30d < inferior || e.usuario_30d > superior) continue;
    const actual = mejores.get(lectura.veredicto);
    if (!actual || e.usuario_30d > actual.final) {
      mejores.set(lectura.veredicto, {
        final: e.usuario_30d,
        destacado: {
          paquete: e.paquete,
          nombre: e.nombre,
          categoria: e.categoria,
          estrellas: e.estrellas,
          usuario: l.usuario,
          veredicto: lectura.veredicto,
          estimacion: central,
        },
      });
    }
  }
  return ORDEN.flatMap((v) => mejores.get(v)?.destacado ?? []);
}

export default async function PaginaRadar({
  searchParams,
}: {
  searchParams: Promise<{ paquete?: string; dia?: string }>;
}) {
  const { paquete, dia } = await searchParams;
  let radar;
  try {
    radar = await datosRadar();
  } catch {
    return <SinDatos titulo="Radar de lanzamiento" />;
  }
  // Sin mercado.json el radar funciona igual: la curva sale de radar.json.
  const mercado = await datosMercado().catch(() => null);
  // Las cohortes por categoría son las que distingue el veredicto.
  const categorias = Object.keys(radar.cohortes.por_categoria).sort((a, b) =>
    a.localeCompare(b, "es"),
  );
  const ejemplos = radar.ejemplos
    .map(({ paquete, nombre, fecha_lanzamiento }) => ({ paquete, nombre, fecha_lanzamiento }))
    .sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
  const diaPortada = radar.dias_lectura.includes(DIA_DESTACADOS)
    ? DIA_DESTACADOS
    : radar.dias_lectura[0];
  const portada: DatosPortada = {
    dia: diaPortada,
    destacados: destacados(radar, diaPortada, categorias),
    precision: radar.dias_lectura.map((d) => ({
      dia: d,
      factor: radar.modelos[String(d)].metricas_test.factor_error_tipico,
      cobertura: radar.modelos[String(d)].metricas_test.cobertura_90,
    })),
    // La de toda la muestra, la misma que citan Mercado y el README.
    curva: mercado?.curva_tipica ?? radar.curva_tipica.global,
    nEntrenamiento: radar.modelos[String(radar.dias_lectura[0])].tamanos.train,
  };
  const ejemploInicial = paquete ? radar.ejemplos.find((e) => e.paquete === paquete) : undefined;

  return (
    <>
      <h1>¿Cómo va tu lanzamiento?</h1>
      <p className="entradilla">
        Con las descargas de usuario que lleva tu librería a los {radar.dias_lectura.join(", ")}{" "}
        días de su primera subida a PyPI, el radar estima cuántas tendrá al cumplir el primer mes y
        te dice si eso está por encima, en línea o por debajo de lo habitual en paquetes de su
        categoría. Sirve para saber pronto si el lanzamiento ha llegado a alguien o si hace falta
        moverlo (un artículo, una demo, un anuncio en la comunidad) antes de que se enfríe.
      </p>
      <FormularioRadar
        dias={radar.dias_lectura}
        categorias={categorias}
        ejemplos={ejemplos}
        inicial={ejemploInicial ? { ejemplo: ejemploInicial, dia: Number(dia ?? 7) } : undefined}
        portada={portada}
      />
    </>
  );
}
