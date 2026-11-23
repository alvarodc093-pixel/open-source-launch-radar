import type { Metadata } from "next";

import FormularioPrevio from "@/components/FormularioPrevio";
import SinDatos from "@/components/SinDatos";
import { datosPrevio } from "@/lib/datos";
import { entero } from "@/lib/formato";

export const metadata: Metadata = { title: "Antes de lanzar" };
export const dynamic = "force-dynamic";

export default async function PaginaPrevia() {
  let previo;
  try {
    previo = await datosPrevio();
  } catch {
    return <SinDatos titulo="Antes de lanzar" />;
  }
  const categorias = previo.por_categoria
    .filter((c) => c.n >= 10)
    .map((c) => c.categoria)
    .sort((a, b) => a.localeCompare(b, "es"));
  const filas = [...previo.por_categoria].sort((a, b) => b.cuantiles[2] - a.cuantiles[2]);

  return (
    <>
      <h1>Antes de lanzar: ¿qué es normal para una librería como la tuya?</h1>
      <p className="entradilla">
        Antes de publicar no hay descargas que mirar, pero sí paquetes parecidos que ya pasaron por
        su primer mes. Esta pantalla te da ese punto de referencia para fijar expectativas.
      </p>
      <FormularioPrevio categorias={categorias} />

      <h2>Descargas de usuario en el primer mes según la categoría</h2>
      <div className="panel tabla">
        <table>
          <caption>
            {entero(previo.global.n)} lanzamientos de la muestra. Mediana y mitad central (del
            percentil 25 al 75) de las descargas de usuario a 30 días.
          </caption>
          <thead>
            <tr>
              <th scope="col">Categoría</th>
              <th scope="col" className="num">
                Paquetes
              </th>
              <th scope="col" className="num">
                Mediana
              </th>
              <th scope="col" className="num">
                Mitad central
              </th>
            </tr>
          </thead>
          <tbody>
            {filas.map((c) => (
              <tr key={c.categoria}>
                <th scope="row">{c.categoria}</th>
                <td className="num">{entero(c.n)}</td>
                <td className="num">{entero(c.cuantiles[2])}</td>
                <td className="num">
                  {entero(c.cuantiles[1])} – {entero(c.cuantiles[3])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="nota">
        Las categorías se solapan mucho: dentro de cada una hay paquetes que apenas pasan de unas
        decenas de descargas y otros con miles. Por eso la categoría sirve como contexto, no como
        predicción.
      </p>
    </>
  );
}
