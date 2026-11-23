/** Formato en español, independiente del idioma del navegador. */

const nf = (cifras: number) =>
  new Intl.NumberFormat("es-ES", { minimumFractionDigits: cifras, maximumFractionDigits: cifras });

export const entero = (v: number) => nf(0).format(Math.round(v));
export const decimal = (v: number, cifras = 1) => nf(cifras).format(v);
export const porcentaje = (v: number, cifras = 0) =>
  new Intl.NumberFormat("es-ES", {
    style: "percent",
    minimumFractionDigits: cifras,
    maximumFractionDigits: cifras,
  }).format(v);
/** Cifras grandes abreviadas para los ejes y las tarjetas: 1,2 mil, 3,4 M. */
export function compacto(v: number): string {
  return new Intl.NumberFormat("es-ES", { notation: "compact", maximumFractionDigits: 1 }).format(
    v,
  );
}

export const NOMBRE_MES = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];

export function fecha(iso: string): string {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(a, m - 1, d)).toLocaleDateString("es-ES", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
