/** Validación de las entradas de la API, con mensajes que entiende el usuario. */

import type { EntradaPrevia, EntradaRadar, Propietario } from "./tipos.ts";

export type Resultado<T> = { ok: true; valor: T } | { ok: false; error: string };

const PROPIETARIOS: Propietario[] = ["Persona", "Organización"];

function numero(nombre: string, v: unknown, min: number, max: number, errores: string[]): number {
  if (typeof v !== "number" || !Number.isFinite(v)) {
    errores.push(`${nombre}: tiene que ser un número`);
    return Number.NaN;
  }
  if (v < min || v > max) errores.push(`${nombre}: entre ${min} y ${max}`);
  return v;
}

function entero(nombre: string, v: unknown, min: number, max: number, errores: string[]): number {
  const n = numero(nombre, v, min, max, errores);
  if (Number.isFinite(n) && !Number.isInteger(n)) errores.push(`${nombre}: número entero`);
  return n;
}

function texto(nombre: string, v: unknown, errores: string[]): string {
  if (typeof v !== "string" || !v.trim() || v.length > 60) {
    errores.push(`${nombre}: elige un valor de la lista`);
    return "";
  }
  return v.trim();
}

function propietario(v: unknown, errores: string[]): Propietario {
  if (!PROPIETARIOS.includes(v as Propietario)) {
    errores.push(`propietario_tipo: ${PROPIETARIOS.join(" u ")}`);
  }
  return v as Propietario;
}

function objeto(cuerpo: unknown): Record<string, unknown> | null {
  return typeof cuerpo === "object" && cuerpo !== null && !Array.isArray(cuerpo)
    ? (cuerpo as Record<string, unknown>)
    : null;
}

export function validarRadar(cuerpo: unknown, diasValidos: number[]): Resultado<EntradaRadar> {
  const c = objeto(cuerpo);
  if (!c) return { ok: false, error: "El cuerpo tiene que ser un objeto JSON." };
  const errores: string[] = [];
  const dia = numero("dia", c.dia, 0, 30, errores);
  if (!errores.length && !diasValidos.includes(dia)) {
    errores.push(`dia: el radar lee los días ${diasValidos.join(", ")}`);
  }
  const usuario = entero("usuario", c.usuario, 0, 10_000_000, errores);
  const total = entero("total", c.total, 0, 100_000_000, errores);
  if (Number.isFinite(usuario) && Number.isFinite(total) && total < usuario) {
    errores.push("total: incluye las de usuario, así que no puede ser menor");
  }
  const subidas = entero("subidas", c.subidas, 1, 100, errores);
  if (Number.isFinite(subidas) && Number.isFinite(dia) && subidas > dia) {
    errores.push("subidas: como mucho una por día desde el lanzamiento");
  }
  const dependencias = entero("dependencias", c.dependencias, 0, 500, errores);
  const tipo = propietario(c.propietario_tipo, errores);
  const categoria = texto("categoria", c.categoria, errores);
  if (errores.length) return { ok: false, error: errores.join("; ") };
  return {
    ok: true,
    valor: { dia, usuario, total, subidas, dependencias, propietario_tipo: tipo, categoria },
  };
}

export function validarPrevio(cuerpo: unknown): Resultado<EntradaPrevia> {
  const c = objeto(cuerpo);
  if (!c) return { ok: false, error: "El cuerpo tiene que ser un objeto JSON." };
  const errores: string[] = [];
  const categoria = texto("categoria", c.categoria, errores);
  const tipo = propietario(c.propietario_tipo, errores);
  const dependencias = entero("dependencias", c.dependencias, 0, 500, errores);
  let anios: number | null = null;
  if (c.anios_cuenta !== null && c.anios_cuenta !== undefined) {
    anios = numero("anios_cuenta", c.anios_cuenta, 0, 20, errores);
  }
  const previos = entero("dias_repo_previos", c.dias_repo_previos, -3650, 3650, errores);
  const mes = entero("mes_lanzamiento", c.mes_lanzamiento, 1, 12, errores);
  if (errores.length) return { ok: false, error: errores.join("; ") };
  return {
    ok: true,
    valor: {
      categoria,
      propietario_tipo: tipo,
      dependencias,
      anios_cuenta: anios,
      dias_repo_previos: previos,
      mes_lanzamiento: mes,
    },
  };
}
