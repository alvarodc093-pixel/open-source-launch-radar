"use client";

import { useState } from "react";

import { entero, NOMBRE_MES } from "@/lib/formato";
import type { LecturaPrevia } from "@/lib/radar";
import type { Propietario } from "@/lib/tipos";

interface Props {
  categorias: string[];
}

const esEntero = (v: string) => v.trim() !== "" && Number.isInteger(Number(v));

export default function FormularioPrevio({ categorias }: Props) {
  const [categoria, setCategoria] = useState("");
  const [propietario, setPropietario] = useState<Propietario>("Persona");
  const [dependencias, setDependencias] = useState("");
  const [anios, setAnios] = useState("");
  const [diasRepo, setDiasRepo] = useState("30");
  const [mes, setMes] = useState(String(new Date().getMonth() + 1));
  const [lectura, setLectura] = useState<LecturaPrevia | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function enviar(evento: React.FormEvent) {
    evento.preventDefault();
    setError(null);
    if (!categoria || !esEntero(dependencias) || !esEntero(diasRepo)) {
      setError("Elige una categoría e indica las dependencias y los días del repositorio.");
      return;
    }
    const aniosNum = anios.trim() === "" ? null : Number(anios.replace(",", "."));
    if (aniosNum !== null && (!Number.isFinite(aniosNum) || aniosNum < 0 || aniosNum > 20)) {
      setError("La antigüedad de la cuenta va de 0 a 20 años (o vacío si no la sabes).");
      return;
    }
    try {
      const r = await fetch("/api/previo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          categoria,
          propietario_tipo: propietario,
          dependencias: Number(dependencias),
          anios_cuenta: aniosNum,
          dias_repo_previos: Number(diasRepo),
          mes_lanzamiento: Number(mes),
        }),
      });
      const cuerpo = await r.json();
      if (!r.ok) setError(cuerpo.error ?? `Error ${r.status}`);
      else setLectura(cuerpo.lectura);
    } catch {
      setError("No se ha podido contactar con el servidor.");
    }
  }

  const l = lectura;
  return (
    <div className="dos-columnas">
      <form className="panel" onSubmit={enviar} noValidate>
        <div className="campo">
          <label htmlFor="c">Categoría</label>
          <select id="c" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
            <option value="">— Elige —</option>
            {categorias.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="campo">
          <label htmlFor="o">El repositorio es de</label>
          <select
            id="o"
            value={propietario}
            onChange={(e) => setPropietario(e.target.value as Propietario)}
          >
            <option value="Persona">Una persona</option>
            <option value="Organización">Una organización</option>
          </select>
        </div>
        <div className="campo">
          <label htmlFor="d">Dependencias obligatorias</label>
          <input
            id="d"
            inputMode="numeric"
            value={dependencias}
            onChange={(e) => setDependencias(e.target.value)}
          />
        </div>
        <div className="campo">
          <label htmlFor="a">Antigüedad de la cuenta de GitHub, en años</label>
          <input
            id="a"
            inputMode="decimal"
            placeholder="Vacío si no la sabes"
            value={anios}
            onChange={(e) => setAnios(e.target.value)}
          />
        </div>
        <div className="campo">
          <label htmlFor="r">Días que lleva el repositorio antes de subir a PyPI</label>
          <input
            id="r"
            inputMode="numeric"
            value={diasRepo}
            onChange={(e) => setDiasRepo(e.target.value)}
          />
        </div>
        <div className="campo">
          <label htmlFor="m">Mes de la primera subida</label>
          <select id="m" value={mes} onChange={(e) => setMes(e.target.value)}>
            {NOMBRE_MES.map((n, i) => (
              <option key={n} value={i + 1}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <button type="submit">Ver paquetes parecidos</button>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </form>

      <section aria-live="polite">
        {!l ? (
          <div className="panel nota">
            Elige la categoría y quién publica para ver cuántas descargas de usuario suelen sumar en
            su primer mes los paquetes parecidos de la muestra.
          </div>
        ) : (
          <>
            {l.benchmark ? (
              <div className="panel">
                <div className="etiqueta">
                  Paquetes parecidos: {l.benchmark.categoria}
                  {l.benchmark.propietario_tipo
                    ? ` · ${l.benchmark.propietario_tipo === "Persona" ? "de una persona" : "de una organización"}`
                    : " (personas y organizaciones)"}
                </div>
                <div className="cifra">{entero(l.benchmark.cuantiles[2])} descargas</div>
                <p className="nota" style={{ marginBottom: 0 }}>
                  de usuario es la mediana a 30 días de {l.benchmark.n} lanzamientos. La mitad
                  central va de {entero(l.benchmark.cuantiles[1])} a{" "}
                  {entero(l.benchmark.cuantiles[3])}, y uno de cada diez supera{" "}
                  {entero(l.benchmark.cuantiles[4])}.
                </p>
              </div>
            ) : (
              <p className="aviso">No hay suficientes paquetes de esa categoría en la muestra.</p>
            )}
            {l.superaBaseline ? (
              <p className="nota">
                Con lo que se sabe antes de publicar, el modelo estima ~
                {entero(l.estimacion.central)} descargas de usuario (rango del 90 %:{" "}
                {entero(l.estimacion.inferior)} – {entero(l.estimacion.superior)}).
              </p>
            ) : (
              <p className="aviso" style={{ marginTop: "1rem" }}>
                No mostramos una cifra concreta: con lo que se sabe antes de publicar, el modelo no
                acierta mejor que la mediana de la muestra en el paquete típico. Antes de lanzar lo
                útil es el rango de paquetes parecidos; la estimación fiable llega con la primera
                semana de descargas (pestaña Radar).
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
