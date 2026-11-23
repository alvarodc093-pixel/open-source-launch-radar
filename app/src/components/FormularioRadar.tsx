"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import Grafico, { type Serie } from "@/components/Grafico";
import PortadaRadar, { type DatosPortada } from "@/components/PortadaRadar";
import { entero, fecha, porcentaje } from "@/lib/formato";
import type { LecturaRadar, Veredicto } from "@/lib/radar";
import type { Ejemplo, EjemploResumen, Propietario } from "@/lib/tipos";

interface Props {
  dias: number[];
  categorias: string[];
  /** Solo nombre y fecha: los datos de cada paquete se piden al elegirlo. */
  ejemplos: EjemploResumen[];
  /** Lectura que abrir al cargar (enlace compartible ?paquete=…&dia=…). */
  inicial?: { ejemplo: Ejemplo; dia: number };
  /** Lo que se enseña en la columna del resultado antes de la primera lectura. */
  portada: DatosPortada;
}

const TITULO: Record<Veredicto, string> = {
  por_encima: "Por encima de lo habitual",
  en_linea: "Dentro de lo habitual",
  por_debajo: "Por debajo de lo habitual",
};

const EXPLICACION: Record<Veredicto, string> = {
  por_encima:
    "Incluso en el escenario prudente, el paquete cerraría el mes por encima de tres de cada cuatro lanzamientos parecidos.",
  en_linea:
    "El rango de la estimación se solapa con la mitad central de los lanzamientos parecidos: todavía no hay señal clara en ningún sentido.",
  por_debajo:
    "Incluso en el escenario optimista, el paquete cerraría el mes por debajo de tres de cada cuatro lanzamientos parecidos.",
};

const VACIO = {
  usuario: "",
  total: "",
  subidas: "1",
  dependencias: "",
  propietario: "Persona" as Propietario,
  categoria: "",
};
type Campos = typeof VACIO;

const esEntero = (v: string, min: number) => Number.isInteger(Number(v)) && Number(v) >= min;

/** Comprobación previa con los nombres que ve el usuario (la API valida otra vez). */
function errorEnCampos(c: Campos, dia: number): string | null {
  if (c.usuario === "" || c.total === "" || c.dependencias === "" || !c.categoria) {
    return "Rellena las descargas, las dependencias y la categoría.";
  }
  if (!esEntero(c.usuario, 0) || !esEntero(c.total, 0)) {
    return "Las descargas tienen que ser números enteros, 0 o más.";
  }
  if (Number(c.total) < Number(c.usuario)) {
    return "Las descargas totales incluyen las de usuario: no pueden ser menos.";
  }
  if (!esEntero(c.subidas, 1) || Number(c.subidas) > dia) {
    return `Los días con subidas van de 1 (el del lanzamiento) a ${dia}.`;
  }
  if (!esEntero(c.dependencias, 0) || Number(c.dependencias) > 500) {
    return "Las dependencias tienen que ser un número entero entre 0 y 500.";
  }
  return null;
}

function camposDe(e: Ejemplo, d: number, categorias: string[]): Campos {
  const l = e.lecturas[String(d)];
  return {
    usuario: String(l.usuario),
    total: String(l.total),
    subidas: String(l.subidas),
    dependencias: String(e.dependencias),
    propietario: e.propietario_tipo,
    categoria: categorias.includes(e.categoria) ? e.categoria : "Otras",
  };
}

export default function FormularioRadar({ dias, categorias, ejemplos, inicial, portada }: Props) {
  const ejemploInicial = inicial?.ejemplo ?? null;
  const diaInicial = inicial && dias.includes(inicial.dia) ? inicial.dia : (dias[1] ?? dias[0]);
  const [dia, setDia] = useState(diaInicial);
  const [campos, setCampos] = useState<Campos>(
    ejemploInicial ? camposDe(ejemploInicial, diaInicial, categorias) : VACIO,
  );
  const [ejemplo, setEjemplo] = useState<Ejemplo | null>(ejemploInicial);
  const [lectura, setLectura] = useState<LecturaRadar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  const consultado = useRef(false);

  // El buscador muestra «Nombre (fecha)»; si dos paquetes coinciden en ambas
  // cosas, se añade el nombre normalizado para que cada texto lleve a uno solo.
  const etiquetas = useMemo(() => {
    const base = (e: EjemploResumen) => `${e.nombre} (${fecha(e.fecha_lanzamiento)})`;
    const repetidas = new Set<string>();
    const vistas = new Set<string>();
    for (const e of ejemplos) {
      const t = base(e);
      if (vistas.has(t)) repetidas.add(t);
      vistas.add(t);
    }
    const porPaquete = new Map<string, string>();
    const porTexto = new Map<string, string>();
    for (const e of ejemplos) {
      const t = repetidas.has(base(e)) ? `${base(e)} · ${e.paquete}` : base(e);
      porPaquete.set(e.paquete, t);
      porTexto.set(t, e.paquete);
    }
    return { porPaquete, porTexto };
  }, [ejemplos]);
  const [busqueda, setBusqueda] = useState(
    ejemploInicial ? (etiquetas.porPaquete.get(ejemploInicial.paquete) ?? "") : "",
  );

  /** Cada letra filtra la lista; el paquete se carga al coincidir con uno. */
  function buscar(texto: string) {
    setBusqueda(texto);
    const paquete = etiquetas.porTexto.get(texto);
    if (paquete !== undefined) void elegirEjemplo(paquete);
    else if (!texto.trim() && ejemplo) void elegirEjemplo("");
  }

  function rellenar(e: Ejemplo | null, d: number) {
    if (e) setCampos(camposDe(e, d, categorias));
  }

  async function cargarEjemplo(paquete: string): Promise<Ejemplo | null> {
    setCargando(true);
    try {
      const r = await fetch(`/api/ejemplos/${paquete}`);
      if (!r.ok) throw new Error(String(r.status));
      const e: Ejemplo = await r.json();
      setEjemplo(e);
      return e;
    } catch {
      setError("No se ha podido cargar ese paquete. Prueba de nuevo en unos segundos.");
      return null;
    } finally {
      setCargando(false);
    }
  }

  async function elegirEjemplo(paquete: string) {
    setLectura(null);
    setError(null);
    if (!paquete) {
      setEjemplo(null);
      setCampos(VACIO);
      return;
    }
    const e = await cargarEjemplo(paquete);
    if (e) rellenar(e, dia);
  }

  /** Atajo de la portada: carga el paquete y lee el radar en el día de los destacados. */
  async function probar(paquete: string) {
    setError(null);
    const e = await cargarEjemplo(paquete);
    if (!e) return;
    setBusqueda(etiquetas.porPaquete.get(e.paquete) ?? e.nombre);
    const c = camposDe(e, portada.dia, categorias);
    setDia(portada.dia);
    setCampos(c);
    await consultar(c, portada.dia);
  }

  function elegirDia(d: number) {
    setDia(d);
    setLectura(null);
    rellenar(ejemplo, d);
  }

  function cambiar(campo: keyof Campos, valor: string) {
    setCampos((c) => ({ ...c, [campo]: valor }));
    setEjemplo(null);
    setBusqueda("");
    setLectura(null);
  }

  async function consultar(c: Campos, d: number) {
    const problema = errorEnCampos(c, d);
    setError(problema);
    if (problema) return;
    setCargando(true);
    try {
      const r = await fetch("/api/radar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dia: d,
          usuario: Number(c.usuario),
          total: Number(c.total),
          subidas: Number(c.subidas),
          dependencias: Number(c.dependencias),
          propietario_tipo: c.propietario,
          categoria: c.categoria,
        }),
      });
      const cuerpo = await r.json();
      if (!r.ok) setError(cuerpo.error ?? `Error ${r.status}`);
      else setLectura(cuerpo.lectura);
    } catch {
      setError("No se ha podido contactar con el servidor. Prueba de nuevo en unos segundos.");
    } finally {
      setCargando(false);
    }
  }

  function enviar(evento: React.FormEvent) {
    evento.preventDefault();
    void consultar(campos, dia);
  }

  // Con un enlace ?paquete=…&dia=… la lectura se hace sola al abrir la página.
  useEffect(() => {
    if (ejemploInicial && !consultado.current) {
      consultado.current = true;
      void consultar(camposDe(ejemploInicial, diaInicial, categorias), diaInicial);
    }
    // Solo al montar: después manda el formulario.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="dos-columnas">
      <form className="panel" onSubmit={enviar} noValidate>
        <div className="campo">
          <label htmlFor="ejemplo">Probar con un lanzamiento real</label>
          <input
            id="ejemplo"
            type="search"
            list="ejemplos-lista"
            placeholder="Escribe el nombre de un paquete"
            autoComplete="off"
            value={busqueda}
            onChange={(e) => buscar(e.target.value)}
          />
          <datalist id="ejemplos-lista">
            {ejemplos.map((e) => (
              <option key={e.paquete} value={etiquetas.porPaquete.get(e.paquete)} />
            ))}
          </datalist>
          <span className="nota">
            {ejemplos.length} paquetes que el modelo no vio al entrenar: puedes comparar su
            estimación con lo que pasó de verdad. Bórralo para usar tus propios datos.
          </span>
        </div>

        <fieldset className="campo" style={{ border: 0, padding: 0, margin: "0 0 0.9rem" }}>
          <legend style={{ fontWeight: 600, fontSize: "0.92rem", marginBottom: "0.25rem" }}>
            Días desde la primera subida a PyPI
          </legend>
          <div className="segmentos">
            {dias.map((d) => (
              <label key={d}>
                <input type="radio" name="dia" checked={d === dia} onChange={() => elegirDia(d)} />
                <span>{d} días</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="campo">
          <label htmlFor="usuario">Descargas de usuario acumuladas hasta hoy</label>
          <input
            id="usuario"
            inputMode="numeric"
            value={campos.usuario}
            onChange={(e) => cambiar("usuario", e.target.value)}
          />
          <span className="nota">
            Las de pip, uv, poetry, pdm, pipenv y pex. En ClickPy se ven separadas por instalador.
          </span>
        </div>
        <div className="campo">
          <label htmlFor="total">Descargas totales acumuladas hasta hoy</label>
          <input
            id="total"
            inputMode="numeric"
            value={campos.total}
            onChange={(e) => cambiar("total", e.target.value)}
          />
          <span className="nota">
            El contador de siempre, con mirrors y bots: sirve para medir el ruido.
          </span>
        </div>
        <div className="campo">
          <label htmlFor="subidas">
            Días con alguna subida a PyPI, contando el del lanzamiento
          </label>
          <input
            id="subidas"
            inputMode="numeric"
            value={campos.subidas}
            onChange={(e) => cambiar("subidas", e.target.value)}
          />
        </div>
        <div className="campo">
          <label htmlFor="dependencias">Dependencias obligatorias</label>
          <input
            id="dependencias"
            inputMode="numeric"
            value={campos.dependencias}
            onChange={(e) => cambiar("dependencias", e.target.value)}
          />
          <span className="nota">Las de requires-dist, sin contar los extras.</span>
        </div>
        <div className="campo">
          <label htmlFor="propietario">El repositorio es de</label>
          <select
            id="propietario"
            value={campos.propietario}
            onChange={(e) => cambiar("propietario", e.target.value)}
          >
            <option value="Persona">Una persona</option>
            <option value="Organización">Una organización</option>
          </select>
        </div>
        <div className="campo">
          <label htmlFor="categoria">Categoría</label>
          <select
            id="categoria"
            value={campos.categoria}
            onChange={(e) => cambiar("categoria", e.target.value)}
          >
            <option value="">— Elige —</option>
            {categorias.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
            {!categorias.includes("Otras") && <option value="Otras">Otras</option>}
          </select>
        </div>
        <button type="submit" disabled={cargando}>
          {cargando ? "Calculando…" : "Leer el radar"}
        </button>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </form>

      <section aria-live="polite">
        {lectura ? (
          <Resultado
            lectura={lectura}
            dia={dia}
            usuario={Number(campos.usuario)}
            ejemplo={ejemplo}
          />
        ) : (
          <PortadaRadar datos={portada} onProbar={(p) => void probar(p)} cargando={cargando} />
        )}
      </section>
    </div>
  );
}

function Resultado({
  lectura,
  dia,
  usuario,
  ejemplo,
}: {
  lectura: LecturaRadar;
  dia: number;
  usuario: number;
  ejemplo: Ejemplo | null;
}) {
  const { estimacion: est, cohorte } = lectura;
  const [, q25, q50, q75] = cohorte.cuantiles30d;

  const series = useMemo<Serie[]>(() => {
    const escala = (v: number) => lectura.trayectoria.map((t) => (t / est.central) * v);
    // La banda se dibuja rellenando desde la serie 1 (rango alto) hasta la 0
    // (rango bajo, invisible).
    const s: Serie[] = [
      {
        etiqueta: "Rango bajo",
        valores: escala(est.inferior),
        color: "#1e7a5200",
        enLeyenda: false,
      },
      {
        etiqueta: "Rango del 90 %",
        valores: escala(est.superior),
        color: "#1e7a52",
        rellenarHasta: 0,
      },
      {
        etiqueta: "Trayectoria esperada",
        valores: lectura.trayectoria,
        color: "#1e7a52",
        discontinua: true,
      },
      {
        etiqueta: `Hoy (día ${dia})`,
        valores: lectura.trayectoria.map((_, i) => (i === dia - 1 ? usuario : null)),
        color: "#b3402a",
        soloPuntos: true,
      },
    ];
    if (ejemplo) {
      s.push({ etiqueta: "Lo que pasó", valores: ejemplo.acumuladas, color: "#2f5bd7" });
    }
    return s;
  }, [lectura, est, dia, usuario, ejemplo]);

  const etiquetas = useMemo(() => lectura.trayectoria.map((_, i) => String(i + 1)), [lectura]);
  const dentro =
    ejemplo && ejemplo.usuario_30d >= est.inferior && ejemplo.usuario_30d <= est.superior;

  return (
    <>
      <div className={`veredicto ${lectura.veredicto}`}>
        <strong>{TITULO[lectura.veredicto]}</strong>
        <p style={{ margin: "0.3rem 0 0" }}>{EXPLICACION[lectura.veredicto]}</p>
      </div>

      <div className="rejilla" style={{ marginTop: "1rem" }}>
        <div className="panel">
          <div className="etiqueta">Descargas de usuario a 30 días</div>
          <div className="cifra">~{entero(est.central)}</div>
          <div className="nota">
            Rango del 90 %: {entero(est.inferior)} – {entero(est.superior)}
          </div>
        </div>
        <div className="panel">
          <div className="etiqueta">Hoy frente a su cohorte</div>
          <div className="cifra">{porcentajeCohorte(lectura.percentilLectura)}</div>
          <div className="nota">
            de los paquetes de {cohorte.nombre} tenían menos descargas el día {dia} (n = {cohorte.n}
            )
          </div>
        </div>
        <div className="panel">
          <div className="etiqueta">Un mes típico en su cohorte</div>
          <div className="cifra">{entero(q50)}</div>
          <div className="nota">
            descargas; la mitad central va de {entero(q25)} a {entero(q75)}
          </div>
        </div>
      </div>

      {ejemplo && (
        <p className={dentro ? "nota" : "aviso"} style={{ marginTop: "1rem" }}>
          {ejemplo.nombre} ({entero(ejemplo.estrellas)} estrellas en GitHub) cerró su primer mes con{" "}
          <strong>{entero(ejemplo.usuario_30d)}</strong> descargas de usuario, de{" "}
          {entero(ejemplo.total_30d)} totales:{" "}
          {dentro
            ? "dentro del rango estimado."
            : "fuera del rango estimado (pasa en torno a 1 de cada 10 paquetes)."}
        </p>
      )}

      <div className="panel" style={{ marginTop: "1rem" }}>
        <Grafico
          tipo="line"
          etiquetas={etiquetas}
          series={series}
          ejeX="Día desde el lanzamiento"
          ejeY="Descargas de usuario acumuladas"
          resumen={`Trayectoria típica de ${cohorte.nombre} escalada a la estimación: unas ${entero(est.central)} descargas de usuario el día 30, con un rango de ${entero(est.inferior)} a ${entero(est.superior)}.`}
        />
      </div>

      <p className="nota">
        Error típico del modelo en paquetes que no había visto: la estimación se desvía un factor ×
        {lectura.modelo.factorError.toFixed(2).replace(".", ",")} del valor real
        {lectura.modelo.cobertura !== undefined &&
          `, y el rango del 90 % acertó en el ${porcentaje(lectura.modelo.cobertura)} de los casos`}{" "}
        (test de {lectura.modelo.nTest} lanzamientos).
      </p>
    </>
  );
}

function porcentajeCohorte(p: number): string {
  if (p <= 0.1) return "< 10 %";
  if (p >= 0.9) return "> 90 %";
  return porcentaje(p);
}
