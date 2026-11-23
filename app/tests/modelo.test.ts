import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { percentil, predecirLog, variablesPrevias, variablesRadar } from "../src/lib/modelo.ts";
import { leerPrevio, leerRadar, veredicto } from "../src/lib/radar.ts";
import type {
  DatosPrevio,
  DatosRadar,
  EntradaPrevia,
  EntradaRadar,
  Propietario,
} from "../src/lib/tipos.ts";
import { validarPrevio, validarRadar } from "../src/lib/validacion.ts";

const leer = async <T>(ruta: string): Promise<T> => JSON.parse(await readFile(ruta, "utf-8"));

interface Caso {
  modelo: string;
  entrada: Partial<EntradaRadar> &
    Partial<EntradaPrevia> & { categoria: string; propietario_tipo: Propietario };
  esperado: number;
}

test("TypeScript reproduce las predicciones de Python (casos dorados)", async () => {
  const radar = await leer<DatosRadar>("data/radar.json");
  const previo = await leer<DatosPrevio>("data/previo.json");
  const casos = await leer<Caso[]>("tests/casos_dorados.json");
  assert.ok(casos.length > 50, `pocos casos dorados: ${casos.length}`);

  let peor = 0;
  for (const c of casos) {
    let obtenido: number;
    if (c.modelo === "previo") {
      obtenido = predecirLog(
        previo.modelo,
        variablesPrevias(c.entrada as EntradaPrevia, previo.modelo.categorias_modelo),
      );
    } else {
      const m = radar.modelos[String(c.entrada.dia)];
      obtenido = predecirLog(m, variablesRadar(c.entrada as EntradaRadar, m.categorias_modelo));
    }
    peor = Math.max(peor, Math.abs(obtenido - c.esperado));
  }
  // El JSON redondea a 6 decimales: diferencias por debajo de 1e-4 en log son ruido.
  assert.ok(peor < 1e-4, `diferencia máxima ${peor}`);
});

const radarValido = {
  dia: 7,
  usuario: 120,
  total: 2500,
  subidas: 3,
  dependencias: 4,
  propietario_tipo: "Persona",
  categoria: "Agentes y LLM",
};

test("validación del radar: rechaza entradas imposibles con mensaje claro", () => {
  const dias = [7, 14, 21];
  assert.equal(validarRadar(radarValido, dias).ok, true);

  const mal = validarRadar(
    { dia: 5, usuario: -1, total: 1.5, subidas: 0, propietario_tipo: "Bot", categoria: "" },
    dias,
  );
  assert.equal(mal.ok, false);
  if (!mal.ok) {
    for (const campo of ["dia", "usuario", "total", "subidas", "dependencias", "propietario_tipo"])
      assert.match(mal.error, new RegExp(campo));
    assert.match(mal.error, /categoria/);
  }
  assert.equal(validarRadar("texto", dias).ok, false);

  // Las totales incluyen las de usuario; y no puede haber más días con subidas que días.
  const menos = validarRadar({ ...radarValido, total: 50 }, dias);
  assert.ok(!menos.ok && /total/.test(menos.error));
  const subidas = validarRadar({ ...radarValido, subidas: 9 }, dias);
  assert.ok(!subidas.ok && /subidas/.test(subidas.error));
});

const previoValido = {
  categoria: "Datos y ciencia",
  propietario_tipo: "Organización",
  dependencias: 3,
  anios_cuenta: null,
  dias_repo_previos: 20,
  mes_lanzamiento: 3,
};

test("validación previa", () => {
  assert.equal(validarPrevio(previoValido).ok, true);
  assert.equal(validarPrevio({ ...previoValido, anios_cuenta: 4.5 }).ok, true);
  assert.equal(validarPrevio({ ...previoValido, mes_lanzamiento: 13 }).ok, false);
  assert.equal(validarPrevio({ ...previoValido, anios_cuenta: 40 }).ok, false);
});

test("veredicto: solo se pronuncia si todo el intervalo queda fuera de la mitad central", () => {
  const cuantiles = [10, 50, 100, 200, 400];
  assert.equal(veredicto({ central: 30, inferior: 20, superior: 45 }, cuantiles), "por_debajo");
  assert.equal(veredicto({ central: 30, inferior: 20, superior: 60 }, cuantiles), "en_linea");
  assert.equal(veredicto({ central: 300, inferior: 210, superior: 500 }, cuantiles), "por_encima");
});

test("percentil interpola entre cuantiles y satura en los extremos", () => {
  const niveles = [0.1, 0.25, 0.5, 0.75, 0.9];
  const q = [10, 20, 40, 80, 160];
  assert.equal(percentil(5, niveles, q), 0.1);
  assert.equal(percentil(30, niveles, q), 0.375);
  assert.equal(percentil(1000, niveles, q), 0.9);
});

test("leerRadar con datos reales: rango coherente y trayectoria que acaba en la estimación", async () => {
  const datos = await leer<DatosRadar>("data/radar.json");
  const categoria = Object.keys(datos.cohortes.por_categoria)[0];
  const lectura = leerRadar(datos, { ...radarValido, categoria } as EntradaRadar);
  const { inferior, central, superior } = lectura.estimacion;
  assert.ok(inferior <= central && central <= superior);
  assert.ok(central >= 120, "al mes no puede haber menos descargas que el día 7");
  assert.equal(lectura.cohorte.nombre, categoria);
  assert.equal(lectura.trayectoria.length, 30);
  assert.ok(Math.abs(lectura.trayectoria[29] - central) < 1e-6);

  const otro = leerRadar(datos, {
    ...radarValido,
    dia: 14,
    usuario: 0,
    total: 0,
    categoria: "Inventada",
  } as EntradaRadar);
  assert.equal(otro.cohorte.nombre, "toda la muestra");
  assert.ok(otro.estimacion.central >= 0);
});

test("leerPrevio: referencia por categoría y propietario, o solo por categoría", async () => {
  const datos = await leer<DatosPrevio>("data/previo.json");
  const grande = [...datos.categoria_propietario].sort((a, b) => b.n - a.n)[0];
  const exacta = leerPrevio(datos, {
    ...previoValido,
    categoria: grande.categoria,
    propietario_tipo: grande.propietario_tipo,
  } as EntradaPrevia);
  assert.equal(exacta.benchmark?.propietario_tipo, grande.propietario_tipo);
  assert.equal(exacta.benchmark?.n, grande.n);

  const sinDatos = leerPrevio(datos, { ...previoValido, categoria: "Inventada" } as EntradaPrevia);
  assert.equal(sinDatos.benchmark, null);
});
