import Grafico from "@/components/Grafico";
import HallazgosEda from "@/components/HallazgosEda";
import SinDatos from "@/components/SinDatos";
import { datosMercado } from "@/lib/datos";
import { entero, fecha, porcentaje } from "@/lib/formato";

export const dynamic = "force-dynamic";

const PASOS: Record<string, string> = {
  con_enlace_a_github: "Primera subida a PyPI con un enlace a GitHub",
  tras_sin_repo: "El repositorio existe",
  tras_pocas_estrellas: "Tiene al menos 10 estrellas",
  tras_republicado: "No es una copia de un proyecto ajeno",
  tras_repo_fork: "El repositorio no es un fork",
  tras_sin_descargas: "Tiene descargas registradas",
  tras_mes_incompleto: "Ha cumplido su primer mes",
  tras_versiones_previas_borradas: "No tuvo versiones anteriores borradas",
  tras_proyecto_anterior: "Es un proyecto nuevo (repositorio de menos de un año)",
};

// La portada es el mercado: la presentación del proyecto empieza por los datos.
export default async function PaginaMercado() {
  let m;
  try {
    m = await datosMercado();
  } catch {
    return <SinDatos titulo="Mercado" />;
  }
  const dias = Object.keys(m.fraccion_mediana_del_mes);
  const categorias = [...m.por_categoria].sort((a, b) => b.mediana_30d - a.mediana_30d);
  const pasos = Object.entries(m.embudo);
  // Los pasos que no quitan ningún paquete no aportan nada a la tabla.
  const embudo = pasos.filter(([, n], i) => i === 0 || n !== pasos[i - 1][1]);
  const c = m.contraste_estrellas;

  return (
    <>
      <h1>El primer mes de una librería de Python en PyPI</h1>
      <p className="entradilla">
        Open Source Launch Radar estima, con las descargas de los primeros días, cuántas tendrá una
        librería nueva al cumplir su primer mes y si eso es mucho o poco para su categoría. Para
        saber qué es normal, primero hay que conocer el mercado: {entero(m.paquetes_aptos)}{" "}
        proyectos open source publicados por primera vez entre el{" "}
        {fecha(m.rango_lanzamientos.desde)} y el {fecha(m.rango_lanzamientos.hasta)}.
      </p>

      <div className="rejilla">
        <div className="panel">
          <div className="etiqueta">Lanzamientos analizados</div>
          <div className="cifra">{entero(m.paquetes_aptos)}</div>
          <div className="nota">
            de {entero(m.embudo.con_enlace_a_github)} paquetes nuevos con enlace a GitHub
          </div>
        </div>
        <div className="panel">
          <div className="etiqueta">Descargas de usuario en el primer mes</div>
          <div className="cifra">{entero(m.mediana_usuario_30d)}</div>
          <div className="nota">mediana por paquete</div>
        </div>
        <div className="panel">
          <div className="etiqueta">Descargas totales en el primer mes</div>
          <div className="cifra">{entero(m.mediana_total_30d)}</div>
          <div className="nota">mediana por paquete, con mirrors y bots</div>
        </div>
      </div>

      <HallazgosEda m={m} />

      <h2>Descargas totales frente a descargas de usuario</h2>
      <div className="panel">
        <Grafico
          tipo="line"
          etiquetas={m.curva_tipica.map((_, i) => String(i + 1))}
          series={[
            {
              etiqueta: "De usuario (pip, uv, poetry…)",
              valores: m.curva_tipica.map((v) => Math.round(v * 1000) / 10),
              color: "#1e7a52",
            },
            {
              etiqueta: "Totales",
              valores: m.curva_tipica_total.map((v) => Math.round(v * 1000) / 10),
              color: "#8a8f98",
              discontinua: true,
            },
          ]}
          ejeX="Día desde la primera subida"
          ejeY="% de las descargas del primer mes"
          resumen={`Las descargas totales se disparan el día de la subida, cuando los mirrors copian el paquete. Las de usuario llegan más repartidas: en el paquete típico, el día ${dias[0]} ya ha llegado el ${porcentaje(m.fraccion_mediana_del_mes[dias[0]])} de las del mes.`}
        />
      </div>

      <h2>¿Qué categorías se instalan más?</h2>
      <div className="panel">
        <Grafico
          tipo="bar"
          etiquetas={categorias.map((g) => `${g.categoria} (${entero(g.n)})`)}
          series={[
            {
              etiqueta: "Mediana de descargas de usuario a 30 días",
              valores: categorias.map((g) => g.mediana_30d),
              color: "#1e7a52",
            },
          ]}
          ejeY="Descargas de usuario a 30 días (mediana)"
          resumen={`Mediana de descargas de usuario a 30 días por categoría; entre paréntesis, el número de paquetes. Las diferencias son pequeñas: la categoría solo explica el ${porcentaje(m.hallazgos.epsilon2.categoria, 1)} de la variación.`}
        />
      </div>

      <h2>¿Cuántos lanzamientos hay cada mes?</h2>
      <div className="panel">
        <Grafico
          tipo="bar"
          etiquetas={m.por_mes.map((p) => p.mes)}
          series={[
            {
              etiqueta: "Lanzamientos en la muestra",
              valores: m.por_mes.map((p) => p.lanzamientos),
              color: "#8a6d00",
            },
          ]}
          ejeY="Paquetes"
          resumen="Lanzamientos de la muestra por mes. Entran los repositorios con al menos 10 estrellas el día de la descarga: los proyectos más recientes han tenido menos tiempo para llegar a esa cifra, así que los últimos meses pueden estar algo infrarrepresentados."
        />
      </div>

      <h2>Estrellas frente a uso</h2>
      <div className="dos-columnas">
        <div className="panel tabla">
          <table>
            <caption>Muchas estrellas, casi ninguna instalación</caption>
            <thead>
              <tr>
                <th scope="col">Paquete</th>
                <th scope="col" className="num">
                  Estrellas
                </th>
                <th scope="col" className="num">
                  Descargas
                </th>
              </tr>
            </thead>
            <tbody>
              {c.mas_estrellas_que_uso.map((p) => (
                <tr key={p.paquete}>
                  <th scope="row">{p.paquete}</th>
                  <td className="num">{entero(p.estrellas)}</td>
                  <td className="num">{entero(p.usuario_30d)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel tabla">
          <table>
            <caption>Muchas instalaciones, casi ninguna estrella</caption>
            <thead>
              <tr>
                <th scope="col">Paquete</th>
                <th scope="col" className="num">
                  Estrellas
                </th>
                <th scope="col" className="num">
                  Descargas
                </th>
              </tr>
            </thead>
            <tbody>
              {c.mas_uso_que_estrellas.map((p) => (
                <tr key={p.paquete}>
                  <th scope="row">{p.paquete}</th>
                  <td className="num">{entero(p.estrellas)}</td>
                  <td className="num">{entero(p.usuario_30d)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="nota">
        Descargas de usuario en el primer mes; estrellas de hoy. Las aplicaciones y demos atraen
        estrellas sin que nadie las instale como dependencia; las librerías que otro paquete
        arrastra se instalan millones de veces sin que nadie visite su repositorio.
      </p>

      <h2>¿Qué paquetes quedan fuera y por qué?</h2>
      <div className="panel tabla">
        <table>
          <caption>Paquetes que quedan tras cada filtro, en el orden en que se aplican.</caption>
          <tbody>
            {embudo.map(([paso, n]) => (
              <tr key={paso}>
                <th scope="row">{PASOS[paso] ?? paso}</th>
                <td className="num">{entero(n)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
