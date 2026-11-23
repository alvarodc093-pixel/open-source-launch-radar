// Prueba de humo: arranca la app compilada (npm run build antes) y recorre
// páginas y API como lo haría un usuario. Sale con código 1 si algo falla.
import { spawn, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

const PUERTO = 3999;
const BASE = `http://127.0.0.1:${PUERTO}`;
const servidor = spawn(`npx next start -p ${PUERTO}`, { shell: true, stdio: "ignore" });

async function esperarServidor() {
  for (let i = 0; i < 60; i++) {
    try {
      await fetch(BASE);
      return;
    } catch {
      await new Promise((ok) => setTimeout(ok, 500));
    }
  }
  throw new Error("La app no arrancó en 30 s");
}

const fallos = [];
async function comprobar(nombre, peticion, esperado, validar = () => true) {
  const respuesta = await fetch(`${BASE}${peticion.ruta}`, peticion.opciones);
  const texto = await respuesta.text();
  const ok = respuesta.status === esperado && validar(texto);
  console.log(`${ok ? "ok  " : "FALLO"} ${respuesta.status} ${nombre}`);
  if (!ok) fallos.push(nombre);
}

const post = (ruta, cuerpo) => ({
  ruta,
  opciones: {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: typeof cuerpo === "string" ? cuerpo : JSON.stringify(cuerpo),
  },
});

try {
  await esperarServidor();
  const html = (t) => t.includes("Open Source Launch") && !t.includes("No se encuentran los datos");
  await comprobar("mercado", { ruta: "/" }, 200, html);
  await comprobar("metodología", { ruta: "/metodologia" }, 200, html);
  await comprobar("radar", { ruta: "/radar" }, 200, html);
  await comprobar("antes de lanzar", { ruta: "/antes-de-lanzar" }, 200, html);
  await comprobar("asistente", { ruta: "/asistente" }, 200, html);
  for (const [viejo, nuevo] of [
    ["/mercado", "/"],
    ["/?paquete=a&dia=7", "/radar?paquete=a&dia=7"],
  ]) {
    const r = await fetch(`${BASE}${viejo}`, { redirect: "manual" });
    const ok = r.status === 308 && new URL(r.headers.get("location"), BASE).href === BASE + nuevo;
    console.log(`${ok ? "ok  " : "FALLO"} ${r.status} enlace antiguo ${viejo}`);
    if (!ok) fallos.push(`enlace antiguo ${viejo}`);
  }
  await comprobar("página inexistente", { ruta: "/no-existe" }, 404);

  const radar = {
    dia: 7,
    usuario: 120,
    total: 2500,
    subidas: 3,
    dependencias: 4,
    propietario_tipo: "Persona",
    categoria: "Agentes y LLM",
  };
  await comprobar("API radar válida", post("/api/radar", radar), 200, (t) =>
    ["por_encima", "en_linea", "por_debajo"].includes(JSON.parse(t).lectura.veredicto),
  );
  await comprobar(
    "API radar con datos imposibles",
    post("/api/radar", { dia: 5, usuario: -1 }),
    400,
  );
  await comprobar("API radar sin JSON", post("/api/radar", "esto no es json"), 400);
  const previo = {
    categoria: "Datos y ciencia",
    propietario_tipo: "Organización",
    dependencias: 3,
    anios_cuenta: 4,
    dias_repo_previos: 20,
    mes_lanzamiento: 3,
  };
  await comprobar(
    "API previo válida",
    post("/api/previo", previo),
    200,
    (t) => typeof JSON.parse(t).lectura.superaBaseline === "boolean",
  );
  await comprobar(
    "API previo con mes 13",
    post("/api/previo", { ...previo, mes_lanzamiento: 13 }),
    400,
  );
  const { ejemplos } = JSON.parse(readFileSync("data/radar.json", "utf-8"));
  await comprobar(
    "API ejemplo existente",
    { ruta: `/api/ejemplos/${ejemplos[0].paquete}` },
    200,
    (t) => Array.isArray(JSON.parse(t).acumuladas),
  );
  await comprobar("API ejemplo inexistente", { ruta: "/api/ejemplos/no-existe-zzz" }, 404);
  await comprobar("API ejemplo mal escrito", { ruta: "/api/ejemplos/Mal_Nombre" }, 400);
  // Sin Ollama (como en CI) la respuesta trae igualmente las fuentes recuperadas.
  await comprobar(
    "API asistente válida",
    post("/api/asistente", { mensajes: [{ rol: "usuario", texto: "¿Qué modelo usa el radar?" }] }),
    200,
    (t) => JSON.parse(t.split("\n")[0]).fuentes.length > 0,
  );
  await comprobar("API asistente sin pregunta", post("/api/asistente", { mensajes: [] }), 400);
} finally {
  // En Windows npx deja procesos hijos: hay que cerrar el árbol entero.
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(servidor.pid), "/t", "/f"], { stdio: "ignore" });
  } else {
    servidor.kill();
  }
}

if (fallos.length) {
  console.error(`${fallos.length} comprobaciones fallidas`);
  process.exit(1);
}
console.log("Prueba de humo superada");
