import { decimal, entero, porcentaje } from "@/lib/formato";
import type { DatosMercado } from "@/lib/tipos";

/**
 * Hallazgos de notebooks/02_eda.ipynb que deciden el producto. Todas las cifras
 * salen de mercado.json, calculadas por las mismas funciones que usa el
 * notebook (radar/eda.py y radar/contraste.py), así que se actualizan al
 * reentrenar.
 */
export default function HallazgosEda({ m }: { m: DatosMercado }) {
  const h = m.hallazgos;
  const c = m.contraste_estrellas;
  const fracciones = Object.entries(m.fraccion_mediana_del_mes);

  return (
    <section className="hallazgos" aria-labelledby="titulo-hallazgos">
      <h2 id="titulo-hallazgos">Lo que dicen los datos</h2>

      <div className="rejilla">
        <div className="panel">
          <h3>Casi todo es ruido</h3>
          <div className="cifra">{porcentaje(m.mediana_pct_usuario_30d)}</div>
          <p className="nota">
            de las descargas del primer mes vienen de alguien instalando el paquete con pip, uv o
            poetry (mediana). El resto son mirrors, escáneres y bots: el contador de PyPI no sirve
            para saber si un lanzamiento funciona.
          </p>
        </div>

        <div className="panel">
          <h3>Publicar versiones infla el contador</h3>
          <div className="cifra">~{entero(h.descargas_por_subida)}</div>
          <p className="nota">
            descargas automáticas por cada día con un fichero nuevo. Las totales siguen al número de
            subidas (ρ = {decimal(h.spearman_total_subidas, 2)}) mucho más que las de usuario (ρ ={" "}
            {decimal(h.spearman_usuario_subidas, 2)}).
          </p>
        </div>

        <div className="panel">
          <h3>El primer mes se decide pronto</h3>
          <ul className="hitos">
            {fracciones.map(([d, f]) => (
              <li key={d}>
                <span className="cifra">{porcentaje(f)}</span>
                <span className="nota">del mes ya ha llegado el día {d}</span>
              </li>
            ))}
          </ul>
          <p className="nota">
            Las descargas de usuario del día 7 y del día 30 tienen una correlación de rangos de{" "}
            {decimal(h.spearman_7_30, 2)}.
          </p>
        </div>

        <div className="panel">
          <h3>Las estrellas no miden el uso</h3>
          <div className="cifra">ρ = {decimal(c.spearman, 2)}</div>
          <p className="nota">
            entre las estrellas del repositorio y las descargas de usuario del primer mes (
            {entero(c.repos)} repositorios). Hay proyectos con miles de estrellas que casi nadie
            instala y dependencias con millones de descargas que nadie marca.
          </p>
        </div>
      </div>
    </section>
  );
}
