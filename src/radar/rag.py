"""Índice del asistente (RAG): fragmentos de texto y sus embeddings.

El asistente de la app responde con lo que recupera de dos fuentes:

- la documentación del proyecto: el README y las celdas de texto de los
  notebooks, cortadas por secciones;
- una ficha por paquete candidato, escrita a partir de las tablas procesadas.

Cada fragmento se convierte en un vector con un modelo de embeddings de
Ollama. Los vectores se normalizan y se guardan cuantizados a int8 en base64:
así el índice de unos 4.000 fragmentos pesa unos pocos MB y la app calcula el
coseno como un producto escalar, sin dependencias.

Sin Ollama (o con `--sin-embeddings`) se escribe el índice solo con texto y
la app recupera únicamente por palabras (BM25).

Uso:
    python -m radar.rag
    python -m radar.rag --sin-embeddings
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from radar import config

logger = logging.getLogger("radar.rag")

RUTA_INDICE = config.DIR_APP_DATOS / "rag.json"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODELO_EMBEDDINGS = os.getenv("OLLAMA_EMBEDDINGS", "embeddinggemma")
# Prefijos con los que se entrenó embeddinggemma para búsqueda: la consulta y
# el documento no se codifican igual. La app usa los mismos (van en el JSON).
PREFIJO_CONSULTA = "task: search result | query: "
PREFIJO_DOCUMENTO = "title: {titulo} | text: "
LOTE = 64
MAX_CARACTERES = 1400  # unas 350 palabras: cabe de sobra en el contexto del modelo

# Secciones del README que no aportan nada a una pregunta sobre el proyecto.
SECCIONES_EXCLUIDAS = {"Convención de commits", "Licencia"}

_EXCLUIDO = "excluido, no entra en la muestra analizada ni en el entrenamiento porque "
ESTADOS = {
    "apto": "apto, entra en la muestra analizada",
    "repo_fork": _EXCLUIDO + "su repositorio es un fork de otro",
    "republicado": (
        _EXCLUIDO + "es una copia de un proyecto ajeno publicada por otra persona "
        "(enlaza el repositorio original)"
    ),
    "sin_descargas": _EXCLUIDO + "no tiene ninguna descarga registrada",
    "mes_incompleto": _EXCLUIDO + "aún no ha cumplido su primer mes",
    "versiones_previas_borradas": (
        _EXCLUIDO + "más del 5 % de sus descargas son anteriores a la primera "
        "subida que conserva PyPI (tuvo versiones que luego se borraron)"
    ),
    "proyecto_anterior": (
        _EXCLUIDO + "su repositorio tenía más de un año cuando se subió a PyPI: "
        "es un proyecto que ya existía, no un lanzamiento"
    ),
}


# --- documentación -----------------------------------------------------------


def _trocear(titulo: str, texto: str) -> list[str]:
    """Corta una sección larga por párrafos sin pasar de MAX_CARACTERES."""
    # Las tablas alineadas por Prettier llevan columnas de espacios y guiones
    # que solo gastan contexto.
    texto = re.sub(r"-{4,}", "---", re.sub(r" {2,}", " ", texto))
    trozos, actual = [], ""
    for parrafo in re.split(r"\n\s*\n", texto.strip()):
        if actual and len(actual) + len(parrafo) > MAX_CARACTERES:
            trozos.append(actual)
            actual = ""
        actual = f"{actual}\n\n{parrafo}" if actual else parrafo
    if actual:
        trozos.append(actual)
    return [f"{titulo}\n\n{t}" for t in trozos]


def _secciones_markdown(texto: str, nivel_max: int = 3) -> list[tuple[str, str]]:
    """Divide un Markdown en (título, cuerpo) por encabezados de nivel 2 y 3."""
    patron = re.compile(rf"^(#{{2,{nivel_max}}})\s+(.+)$", re.MULTILINE)
    marcas = list(patron.finditer(texto))
    secciones = []
    for i, marca in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        cuerpo = texto[marca.end() : fin].strip()
        if cuerpo:
            secciones.append((marca.group(2).strip(), cuerpo))
    return secciones


def fragmentos_readme(ruta: Path) -> list[dict[str, Any]]:
    fragmentos = []
    for titulo, cuerpo in _secciones_markdown(ruta.read_text(encoding="utf-8")):
        nombre = re.sub(r"^\d+\.\s*", "", titulo)
        if nombre in SECCIONES_EXCLUIDAS:
            continue
        for i, texto in enumerate(_trocear(f"README · {titulo}", cuerpo)):
            fragmentos.append(
                {
                    "id": f"readme-{len(fragmentos)}",
                    "tipo": "documentacion",
                    "titulo": f"README · {titulo}" + (f" ({i + 1})" if i else ""),
                    "texto": texto,
                }
            )
    return fragmentos


def fragmentos_notebook(ruta: Path) -> list[dict[str, Any]]:
    """Agrupa las celdas de texto de cada sección del notebook (las conclusiones)."""
    celdas = json.loads(ruta.read_text(encoding="utf-8"))["cells"]
    texto = "\n\n".join(
        "".join(c["source"]) for c in celdas if c["cell_type"] == "markdown"
    )
    nombre = ruta.stem
    fragmentos = []
    for titulo, cuerpo in _secciones_markdown(texto, nivel_max=2):
        for i, trozo in enumerate(_trocear(f"Notebook {nombre} · {titulo}", cuerpo)):
            fragmentos.append(
                {
                    "id": f"{nombre}-{len(fragmentos)}",
                    "tipo": "documentacion",
                    "titulo": f"Notebook {nombre} · {titulo}"
                    + (f" ({i + 1})" if i else ""),
                    "texto": trozo,
                }
            )
    return fragmentos


# --- fichas de paquetes -----------------------------------------------------


def ficha(paquete: pd.Series, en_test: bool) -> str:
    """Texto de un paquete con las cifras que alguien preguntaría sobre él.

    Evita las palabras de la documentación («modelo», «radar», «día»): las
    fichas son cortas y, si las repitieran, BM25 las pondría por delante de la
    documentación en las preguntas generales.
    """
    propietario = (
        "una organización"
        if paquete["propietario_tipo"] == "Organización"
        else "una persona"
    )
    lineas = [
        f"{paquete['nombre']} (paquete de PyPI {paquete['paquete']}) se subió a "
        f"PyPI por primera vez el {paquete['fecha_lanzamiento']}.",
        f"Descripción: {paquete['resumen']}" if pd.notna(paquete["resumen"]) else "",
        f"Categoría: {paquete['categoria']}. Repositorio en GitHub: "
        f"{paquete['repo']}, de {propietario}, con {int(paquete['estrellas'])} "
        f"estrellas y {int(paquete['forks'])} forks.",
        f"Dependencias obligatorias: {int(paquete['dependencias'])}. Versiones "
        f"publicadas: {int(paquete['versiones_total'])}.",
        f"Estado: {ESTADOS.get(paquete['estado'], paquete['estado'])}.",
    ]
    if pd.notna(paquete.get("usuario_30d")):
        usuario = [
            f"{int(paquete[f'usuario_{dia}d'])} a los {dia} días"
            for dia in config.DIAS_LECTURA
        ]
        lineas.append(
            f"Descargas de usuario (pip, uv, poetry…) acumuladas: {', '.join(usuario)}"
            f" y {int(paquete['usuario_30d'])} a los 30 días, de "
            f"{int(paquete['total_30d'])} descargas totales."
        )
    if en_test:
        lineas.append(
            "Está en el conjunto de test (no se usó para entrenar). "
            # Con /radar? la palabra entraría en miles de fichas y saldrían en
            # cualquier pregunta sobre el radar: la portada redirige.
            f"Enlace para probarlo: /?paquete={paquete['paquete']}"
        )
    return "\n".join(linea for linea in lineas if linea)


def fragmentos_paquetes(
    paquetes: pd.DataFrame, paquetes_test: set[str]
) -> list[dict[str, Any]]:
    return [
        {
            "id": f"paquete-{p['paquete']}",
            "tipo": "paquete",
            "titulo": str(p["nombre"]),
            "texto": ficha(p, p["paquete"] in paquetes_test),
            "paquete": p["paquete"],
        }
        for _, p in paquetes.iterrows()
    ]


def construir_corpus(raiz: Path = config.RAIZ) -> list[dict[str, Any]]:
    procesado = raiz / "data" / "processed"
    paquetes = pd.read_csv(procesado / "paquetes.csv")
    radar = json.loads((raiz / "app" / "data" / "radar.json").read_text("utf-8"))
    paquetes_test = {e["paquete"] for e in radar["ejemplos"]}

    corpus = fragmentos_readme(raiz / "README.md")
    for notebook in sorted((raiz / "notebooks").glob("*.ipynb")):
        corpus += fragmentos_notebook(notebook)
    corpus += fragmentos_paquetes(paquetes, paquetes_test)
    return corpus


# --- embeddings --------------------------------------------------------------


def embeddings(textos: list[str], sesion: requests.Session) -> np.ndarray:
    vectores = []
    for inicio in range(0, len(textos), LOTE):
        lote = textos[inicio : inicio + LOTE]
        r = sesion.post(
            f"{OLLAMA_HOST}/api/embed",
            json={"model": MODELO_EMBEDDINGS, "input": lote},
            timeout=300,
        )
        r.raise_for_status()
        vectores += r.json()["embeddings"]
        logger.info("Embeddings: %d / %d", len(vectores), len(textos))
    return np.asarray(vectores, dtype=np.float32)


def cuantizar(vectores: np.ndarray) -> str:
    """Normaliza a norma 1 y guarda cada componente como int8 (× 127)."""
    normas = np.linalg.norm(vectores, axis=1, keepdims=True)
    unitarios = vectores / np.where(normas == 0, 1, normas)
    enteros = np.clip(np.round(unitarios * 127), -127, 127).astype(np.int8)
    return base64.b64encode(enteros.tobytes()).decode("ascii")


def texto_documento(fragmento: dict[str, Any]) -> str:
    titulo = fragmento["titulo"] if fragmento["tipo"] == "paquete" else "none"
    return PREFIJO_DOCUMENTO.format(titulo=titulo) + fragmento["texto"]


def construir_indice(con_embeddings: bool = True) -> dict[str, Any]:
    corpus = construir_corpus()
    indice: dict[str, Any] = {
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "fragmentos": corpus,
        "embeddings": None,
    }
    if con_embeddings:
        with requests.Session() as sesion:
            vectores = embeddings([texto_documento(f) for f in corpus], sesion)
        indice["embeddings"] = {
            "modelo": MODELO_EMBEDDINGS,
            "dimension": int(vectores.shape[1]),
            "prefijo_consulta": PREFIJO_CONSULTA,
            "datos": cuantizar(vectores),
        }
    return indice


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--sin-embeddings",
        action="store_true",
        help="escribe solo el texto (la app recuperará por palabras)",
    )
    args = parser.parse_args()
    indice = construir_indice(con_embeddings=not args.sin_embeddings)
    RUTA_INDICE.write_text(
        json.dumps(indice, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    logger.info(
        "Escrito %s: %d fragmentos (%.1f MB)",
        RUTA_INDICE.name,
        len(indice["fragmentos"]),
        RUTA_INDICE.stat().st_size / 1e6,
    )


if __name__ == "__main__":
    main()
