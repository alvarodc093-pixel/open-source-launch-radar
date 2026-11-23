import type { Metadata } from "next";
import Link from "next/link";

import SinDatos from "@/components/SinDatos";
import { datosMercado, datosPrevio, datosRadar } from "@/lib/datos";
import { decimal, entero, fecha, porcentaje } from "@/lib/formato";
import type { ModeloJson } from "@/lib/tipos";

export const metadata: Metadata = { title: "Metodología" };
export const dynamic = "force-dynamic";

const NOMBRE_MODELO: Record<string, string> = {
  mediana: "Mediana (sin información)",
  ratio_tipico: "Ratio típico de la muestra",
  ridge: "Regresión Ridge",
  gradient_boosting: "Gradient boosting",
};

function TablaCandidatos({ m }: { m: ModeloJson }) {
  const filas = Object.entries(m.cv_mae_log).sort((a, b) => a[1].mean - b[1].mean);
  return (
    <table>
      <caption>
        Error medio en log (MAE) en validación cruzada temporal dentro del entrenamiento. Se elige
        el menor; el test no interviene.
      </caption>
      <thead>
        <tr>
          <th scope="col">Candidato</th>
          <th scope="col" className="num">
            MAE (media ± desv.)
          </th>
        </tr>
      </thead>
      <tbody>
        {filas.map(([nombre, v]) => (
          <tr key={nombre}>
            <th scope="row">
              {NOMBRE_MODELO[nombre] ?? nombre}
              {nombre === m.tipo ? " ✓" : ""}
            </th>
            <td className="num">
              {decimal(v.mean, 3)} ± {decimal(v.std, 3)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const VEREDICTOS = {
  por_encima: "Por encima",
  en_linea: "En línea",
  por_debajo: "Por debajo",
} as const;

export default async function PaginaMetodologia() {
  let radar, previo, mercado;
  try {
    [radar, previo, mercado] = await Promise.all([datosRadar(), datosPrevio(), datosMercado()]);
  } catch {
    return <SinDatos titulo="Metodología" />;
  }
  const dias = radar.dias_lectura;
  const tam = radar.modelos[String(dias[0])].tamanos;
  const pm = previo.modelo;
  const base = pm.baselines_test.mediana;
  // El mismo criterio que usa /api/previo (leerPrevio) para mostrar o no la cifra.
  const previoSupera =
    pm.tipo !== "mediana" &&
    (!base ||
      (pm.metricas_test.mae_log < base.mae_log &&
        pm.metricas_test.mediana_error_log < base.mediana_error_log));
  const cuentas = (d: number) => radar.aciertos_veredicto[String(d)] ?? {};
  const n = (a?: { por_encima: number; en_linea: number; por_debajo: number }) =>
    a ? a.por_encima + a.en_linea + a.por_debajo : 0;
  const triviales = dias
    .map((d) => {
      const a = cuentas(d).por_encima;
      return a ? `${a.ya_superaba} de ${n(a)} el día ${d}` : null;
    })
    .filter(Boolean)
    .join(", ");
  const debajo = dias.map((d) => ({ dia: d, n: n(cuentas(d).por_debajo) }));
  const cohorte30 = radar.cohortes.global["30"];

  return (
    <>
      <h1>Cómo funciona</h1>
      <p className="entradilla">
        Qué datos usa la aplicación, cómo se han preparado, cómo se ha evaluado cada modelo y qué no
        puede decir.
      </p>

      <h2>Datos</h2>
      <div className="panel">
        <ul>
          <li>
            <strong>Lanzamientos:</strong> todos los paquetes subidos a PyPI por primera vez entre
            el {fecha(mercado.rango_lanzamientos.desde)} y el{" "}
            {fecha(mercado.rango_lanzamientos.hasta)} que enlazan un repositorio de GitHub con al
            menos 10 estrellas. Salen de ClickPy, la copia pública del dataset de PyPI que mantiene
            ClickHouse. Quedan {entero(mercado.paquetes_aptos)} de{" "}
            {entero(mercado.embudo.con_enlace_a_github)} (los filtros están en la pestaña Mercado).
          </li>
          <li>
            <strong>Descargas:</strong> las diarias de cada paquete, separadas por instalador. «De
            usuario» son las de pip, uv, poetry, pdm, pipenv y pex; «totales» incluye además mirrors
            (bandersnatch, Nexus…), navegadores y peticiones sin instalador, que son casi siempre
            bots.
          </li>
          <li>
            <strong>Repositorio:</strong> estrellas, forks, fecha de creación y tipo de propietario,
            vía la API GraphQL de GitHub. GitHub ya no publica cuándo se dio cada estrella, así que
            las estrellas son las de hoy y solo sirven de filtro y de contraste.
          </li>
        </ul>
      </div>

      <h2>El radar</h2>
      <div className="panel">
        <p>
          Objetivo: descargas de usuario acumuladas en los 30 primeros días, en escala logarítmica
          (un error de «el doble» pesa lo mismo con 50 descargas que con 5.000). Variables:
          descargas de usuario, descargas totales y días con subidas hasta el día de lectura,
          dependencias, tipo de propietario y categoría; nada posterior a ese día. Partición por
          fecha de lanzamiento: {entero(tam.train)} paquetes de entrenamiento,{" "}
          {entero(tam.calibracion)} de calibración y {entero(tam.test)} de test (los más recientes).
        </p>
        <div className="tabla">
          <table>
            <caption>Resultado en test, sobre lanzamientos que el modelo no vio.</caption>
            <thead>
              <tr>
                <th scope="col">Lectura</th>
                <th scope="col">Modelo elegido</th>
                <th scope="col" className="num">
                  Factor de error típico
                </th>
                <th scope="col" className="num">
                  Dentro de ×2
                </th>
                <th scope="col" className="num">
                  MAE log
                </th>
                <th scope="col" className="num">
                  MAE log del ratio típico
                </th>
                <th scope="col" className="num">
                  Cobertura del 90 %
                </th>
              </tr>
            </thead>
            <tbody>
              {dias.map((d) => {
                const m = radar.modelos[String(d)];
                const ratio =
                  m.tipo === "ratio_tipico" ? m.metricas_test : m.baselines_test.ratio_tipico;
                return (
                  <tr key={d}>
                    <th scope="row">Día {d}</th>
                    <td>{NOMBRE_MODELO[m.tipo]}</td>
                    <td className="num">×{decimal(m.metricas_test.factor_error_tipico, 2)}</td>
                    <td className="num">{porcentaje(m.metricas_test.dentro_de_x2)}</td>
                    <td className="num">{decimal(m.metricas_test.mae_log, 3)}</td>
                    <td className="num">{ratio ? decimal(ratio.mae_log, 3) : "—"}</td>
                    <td className="num">
                      {m.metricas_test.cobertura_90 !== undefined
                        ? porcentaje(m.metricas_test.cobertura_90)
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="nota">
          «Factor de error típico» es la desviación del paquete mediano: ×1,5 significa que la
          estimación queda entre dos tercios y vez y media del valor real. El rango del 90 % es
          conformal: el cuantil de los errores en el bloque de calibración. Los candidatos quedan
          muy cerca en la validación cruzada: la regla simple (descargas de hoy × ratio típico) es
          difícil de mejorar, y cuando un modelo la supera lo hace por poco.
        </p>
        {dias.map((d) => (
          <details key={d}>
            <summary>Candidatos comparados para el día {d}</summary>
            <div className="tabla">
              <TablaCandidatos m={radar.modelos[String(d)]} />
            </div>
          </details>
        ))}
      </div>

      <h2>¿Acierta el veredicto?</h2>
      <div className="panel">
        <p>
          Cada paquete del test, leído como lo haría la app, frente a dónde acabó de verdad a los 30
          días dentro de su cohorte: por encima de tres de cada cuatro paquetes parecidos, en la
          mitad central o por debajo.
        </p>
        <div className="tabla">
          <table>
            <caption>
              Veredicto del radar y posición real a 30 días, en los paquetes de test.
            </caption>
            <thead>
              <tr>
                <th scope="col">Lectura</th>
                <th scope="col">Veredicto</th>
                <th scope="col" className="num">
                  Paquetes
                </th>
                <th scope="col" className="num">
                  Acabó por encima
                </th>
                <th scope="col" className="num">
                  En la mitad central
                </th>
                <th scope="col" className="num">
                  Acabó por debajo
                </th>
              </tr>
            </thead>
            <tbody>
              {dias.flatMap((d) =>
                (["por_encima", "en_linea", "por_debajo"] as const).flatMap((v) => {
                  const a = cuentas(d)[v];
                  if (!a) return [];
                  const total = n(a);
                  return [
                    <tr key={`${d}-${v}`}>
                      <th scope="row">Día {d}</th>
                      <td>{VEREDICTOS[v]}</td>
                      <td className="num">{entero(total)}</td>
                      <td className="num">{porcentaje(a.por_encima / total)}</td>
                      <td className="num">{porcentaje(a.en_linea / total)}</td>
                      <td className="num">{porcentaje(a.por_debajo / total)}</td>
                    </tr>,
                  ];
                }),
              )}
            </tbody>
          </table>
        </div>
        <p className="nota" style={{ marginBottom: 0 }}>
          Cuando el radar se pronuncia, acierta casi siempre. Pero aquí hay una diferencia con otros
          mercados: el cuartil inferior de la cohorte son unas {entero(cohorte30[1])} descargas de
          usuario al mes, muy cerca del suelo que ponen los bots que usan pip, así que el rango
          estimado casi nunca queda entero por debajo. El «por debajo» solo aparece de verdad hacia
          el día {debajo.reduce((a, b) => (b.n > a.n ? b : a)).dia} (
          {debajo.map((x) => `${x.n} paquetes el día ${x.dia}`).join(", ")}). Y la mayoría de los
          «por encima» ya superaban, el día de la lectura, lo que tres de cada cuatro paquetes
          parecidos alcanzan en un mes ({triviales}): el veredicto lo confirma, pero el modelo
          apenas añade información. Lo más útil del radar es la estimación con su rango, no el
          veredicto.
        </p>
      </div>

      <h2>Antes de lanzar</h2>
      <div className="panel">
        <p>
          Mismo método con lo que se sabe antes de publicar: categoría, tipo de propietario,
          dependencias, antigüedad de la cuenta, días del repositorio y mes. En test, el modelo
          elegido ({NOMBRE_MODELO[pm.tipo]}) tiene un error medio en log de{" "}
          {decimal(pm.metricas_test.mae_log, 3)} y un error del paquete típico de{" "}
          {decimal(pm.metricas_test.mediana_error_log, 3)}; la mediana de la muestra,{" "}
          {base ? `${decimal(base.mae_log, 3)} y ${decimal(base.mediana_error_log, 3)}` : "—"}.{" "}
          {previoSupera
            ? "Mejora en las dos medidas, aunque por poco, así que la app muestra su estimación junto al rango de paquetes parecidos."
            : "No mejora en las dos a la vez, así que la app no da una cifra antes del lanzamiento: muestra el rango de paquetes parecidos."}
        </p>
        <TablaCandidatos m={pm} />
      </div>

      <h2>Contraste con las estrellas de GitHub</h2>
      <div className="panel">
        <p>
          Las estrellas son la otra cifra pública de popularidad de un proyecto open source y no
          dependen de PyPI. Entre {entero(mercado.contraste_estrellas.repos)} repositorios (uno por
          paquete; los monorepos se quitan porque sus paquetes comparten estrellas), la correlación
          de rangos entre estrellas y descargas de usuario del primer mes es de solo{" "}
          {decimal(mercado.contraste_estrellas.spearman, 2)}. El paquete mediano suma{" "}
          {decimal(mercado.contraste_estrellas.descargas_por_estrella.mediana, 1)} descargas de
          usuario por estrella, pero la mitad central va de{" "}
          {decimal(mercado.contraste_estrellas.descargas_por_estrella.q25, 1)} a{" "}
          {decimal(mercado.contraste_estrellas.descargas_por_estrella.q75, 1)}.
        </p>
        <p className="nota" style={{ marginBottom: 0 }}>
          Miden cosas distintas: las estrellas, atención (una demo o una aplicación las acumulan sin
          que nadie las instale); las descargas de usuario, uso (una dependencia que otro paquete
          arrastra se instala millones de veces sin que nadie visite su repositorio). Por eso el
          radar predice descargas de usuario y enseña las estrellas solo como contexto.
        </p>
      </div>

      <h2>Limitaciones</h2>
      <div className="panel">
        <ul>
          <li>
            Las descargas de usuario cuentan instalaciones, no personas: un proyecto con integración
            continua puede instalar un paquete cientos de veces al día. Y también hay bots que usan
            pip, así que ni siquiera esa cifra parte de cero.
          </li>
          <li>
            Solo entran repositorios con al menos 10 estrellas el día de la descarga: es un filtro
            sobre algo que se mide después del primer mes, y deja fuera los lanzamientos que no
            consiguieron ninguna atención.
          </li>
          <li>
            Se excluyen los paquetes de repositorios con más de un año (proyectos que ya tenían
            usuarios), los que tuvieron versiones borradas antes de la primera que conserva PyPI y
            las copias de proyectos ajenos.
          </li>
          <li>
            La categoría sale de reglas sobre los clasificadores de PyPI, el resumen y los temas del
            repositorio: es aproximada, y la mitad de la muestra cae en «Agentes y LLM».
          </li>
          <li>
            El rango del 90 % se cumple en promedio, no en cada paquete: uno de cada diez puede
            quedar fuera.
          </li>
          <li>
            Los días se cuentan en hora UTC desde la primera subida, como las fechas de las
            descargas en ClickPy.
          </li>
        </ul>
      </div>

      <h2>Asistente y panel de Power BI</h2>
      <div className="rejilla">
        <div className="panel">
          <h3>Asistente (RAG)</h3>
          <p className="nota">
            La página <Link href="/asistente">Asistente</Link> recupera fragmentos del README, de
            los notebooks y de una ficha por paquete (BM25, y embeddings cuando están disponibles) y
            un modelo de Ollama redacta la respuesta citándolos. Se evalúa con preguntas de
            referencia, separadas en un grupo de ajuste y otro de reserva; el detalle está en{" "}
            <code>docs/evaluacion_asistente.md</code>.
          </p>
        </div>
        <div className="panel">
          <h3>Panel de Power BI</h3>
          <p className="nota">
            El repositorio incluye un proyecto de Power BI (<code>powerbi/</code>) con un modelo en
            estrella y cuatro páginas: mercado, ruido de las descargas, calidad del modelo y detalle
            por paquete. Se genera desde Python con los mismos datos y un test comprueba que sus
            métricas coinciden con las de esta página.
          </p>
        </div>
      </div>
    </>
  );
}
