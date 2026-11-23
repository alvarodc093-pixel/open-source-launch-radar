/** Lectura del radar: estimación a 30 días y comparación con paquetes parecidos. */

import { estimar, percentil, variablesPrevias, variablesRadar, type Estimacion } from "./modelo.ts";
import type { DatosPrevio, DatosRadar, EntradaPrevia, EntradaRadar } from "./tipos.ts";

export type Veredicto = "por_encima" | "en_linea" | "por_debajo";

export interface LecturaRadar {
  estimacion: Estimacion;
  cohorte: { nombre: string; n: number; cuantiles30d: number[] };
  percentilLectura: number;
  percentilEstimacion: number;
  veredicto: Veredicto;
  trayectoria: number[];
  modelo: { tipo: string; factorError: number; cobertura: number | undefined; nTest: number };
}

/** Cohorte de la categoría si hay paquetes suficientes; si no, toda la muestra. */
function cohorte(radar: DatosRadar, categoria: string) {
  const propia = radar.cohortes.por_categoria[categoria];
  if (propia) {
    return { nombre: categoria, n: propia.n as number, tabla: propia as Record<string, number[]> };
  }
  return { nombre: "toda la muestra", n: radar.cohortes.n_global, tabla: radar.cohortes.global };
}

/**
 * El veredicto mira el intervalo entero, no solo la cifra central: solo se
 * dice «por debajo» si incluso el extremo optimista queda bajo el cuartil
 * inferior de su cohorte (y al revés para «por encima»).
 */
export function veredicto(est: Estimacion, cuantiles30d: number[]): Veredicto {
  const [, q25, , q75] = cuantiles30d;
  if (est.superior < q25) return "por_debajo";
  if (est.inferior > q75) return "por_encima";
  return "en_linea";
}

export function leerRadar(radar: DatosRadar, e: EntradaRadar): LecturaRadar {
  const modelo = radar.modelos[String(e.dia)];
  // Al mes no puede haber menos descargas de las que ya hay el día de lectura.
  const est = estimar(modelo, variablesRadar(e, modelo.categorias_modelo), e.usuario);
  const c = cohorte(radar, e.categoria);
  const niveles = radar.cohortes.cuantiles;
  const cuantiles30d = c.tabla["30"];
  const curva = radar.curva_tipica[c.nombre] ?? radar.curva_tipica.global;
  return {
    estimacion: est,
    cohorte: { nombre: c.nombre, n: c.n, cuantiles30d },
    percentilLectura: percentil(e.usuario, niveles, c.tabla[String(e.dia)]),
    percentilEstimacion: percentil(est.central, niveles, cuantiles30d),
    veredicto: veredicto(est, cuantiles30d),
    trayectoria: curva.map((f) => f * est.central),
    modelo: {
      tipo: modelo.tipo,
      factorError: modelo.metricas_test.factor_error_tipico,
      cobertura: modelo.metricas_test.cobertura_90,
      nTest: modelo.tamanos.test,
    },
  };
}

export interface LecturaPrevia {
  estimacion: Estimacion;
  superaBaseline: boolean;
  benchmark: {
    categoria: string;
    propietario_tipo: string | null;
    n: number;
    cuantiles: number[];
  } | null;
}

export function leerPrevio(previo: DatosPrevio, e: EntradaPrevia): LecturaPrevia {
  const m = previo.modelo;
  const base = m.baselines_test.mediana;
  const exacta = previo.categoria_propietario.find(
    (g) => g.categoria === e.categoria && g.propietario_tipo === e.propietario_tipo,
  );
  const categoria = previo.por_categoria.find((g) => g.categoria === e.categoria);
  // Con menos de 10 paquetes los cuartiles bailan demasiado: se sube un nivel.
  const benchmark =
    exacta && exacta.n >= 10
      ? {
          categoria: e.categoria,
          propietario_tipo: e.propietario_tipo,
          n: exacta.n,
          cuantiles: exacta.cuantiles,
        }
      : categoria
        ? {
            categoria: e.categoria,
            propietario_tipo: null,
            n: categoria.n,
            cuantiles: categoria.cuantiles,
          }
        : null;
  return {
    estimacion: estimar(m, variablesPrevias(e, m.categorias_modelo)),
    // Tiene que mejorar a la mediana en el error medio y también en el del
    // paquete típico: bajar solo el medio puede deberse a unos pocos aciertos
    // en paquetes extremos mientras empeora el caso normal.
    superaBaseline:
      m.tipo !== "mediana" &&
      (!base ||
        (m.metricas_test.mae_log < base.mae_log &&
          m.metricas_test.mediana_error_log < base.mediana_error_log)),
    benchmark,
  };
}
