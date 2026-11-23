"""De data/raw a las tablas limpias de data/processed.

Uso:
    python -m radar.preparacion

Salidas:
    embudo.json            cuántos lanzamientos quedan en cada filtro
    paquetes.csv           un registro por paquete candidato (repositorio con
                           el mínimo de estrellas), con su estado: apto o el
                           motivo de exclusión
    descargas_diarias.csv  descargas por paquete y día relativo al lanzamiento
    dataset_radar.csv      paquetes aptos con las variables del modelo

El día 0 es el de la primera subida a PyPI, en UTC, como las fechas de las
descargas. «De usuario» son las descargas de pip, uv, poetry, pdm, pipenv y
pex; «totales» incluye además mirrors, navegadores y bots.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from radar import config
from radar.ingesta.github import extraer_repo

logger = logging.getLogger(__name__)

# Si antes del día 0 ya hubo más de un 5 % de las descargas del primer mes, el
# paquete tuvo versiones que luego se borraron de PyPI: su día 0 no es el
# estreno real.
PCT_PREVIAS_MAX = 0.05
# Un repositorio con más de un año antes de su primera subida a PyPI es un
# proyecto que ya tenía usuarios (o un paquete renombrado), no un lanzamiento.
DIAS_REPO_PREVIOS_MAX = 365
# Hay quien republica en PyPI proyectos ajenos con un prefijo propio delante
# del nombre del repositorio original (en 2026, «iflow-mcp-…» y «mseep-…», con
# cientos de servidores MCP). Esos paquetes enlazan el repositorio original y
# se quedarían con sus estrellas. Un prefijo cuenta como republicador si lo
# usan paquetes de repositorios de al menos 10 dueños distintos y si al menos
# la mitad de sus paquetes siguen ese patrón: en los ecosistemas de plugins
# («langchain-…», «django-…», «pytest-…») la mayoría de los paquetes vienen de
# un repositorio con el mismo nombre y el patrón no pasa del 20 %.
REPUBLICADOS_MIN_DUENOS = 10
REPUBLICADOS_FRACCION_MIN = 0.5

# Categorías, en orden de prioridad: un paquete de agentes que también es una
# herramienta de línea de comandos cuenta como «Agentes y LLM». Cada una se
# reconoce por los clasificadores «Topic ::» de PyPI o por palabras del
# resumen, las palabras clave y los temas del repositorio.
CATEGORIAS: list[tuple[str, tuple[str, ...], str]] = [
    (
        "Agentes y LLM",
        (),
        r"\b(llms?|agent(s|ic)?|mcp|gpt|openai|anthropic|claude|gemini|ollama|rag|"
        r"prompts?|langchain|chatbots?|copilot)\b",
    ),
    (
        "Machine learning",
        ("Topic :: Scientific/Engineering :: Artificial Intelligence",),
        r"\b(machine learning|deep learning|neural|pytorch|torch|tensorflow|jax|"
        r"transformers?|computer vision|ml|ai)\b",
    ),
    (
        "Datos y ciencia",
        ("Topic :: Scientific/Engineering", "Topic :: Database"),
        r"\b(data|dataframes?|pandas|polars|analytics|etl|sql|database|"
        r"bioinformatics|physics|chemistry|statistics|geospatial)\b",
    ),
    (
        "Web y APIs",
        ("Topic :: Internet", "Framework :: Django", "Framework :: Flask"),
        r"\b(web|http|api|rest|fastapi|django|flask|scraping|scraper|websocket)\b",
    ),
    (
        "Herramientas de desarrollo",
        ("Topic :: Software Development",),
        r"\b(cli|testing|pytest|lint(er)?|typing|devtools?|build|packaging|sdk|"
        r"library|framework|developer)\b",
    ),
    (
        "Sistema y automatización",
        ("Topic :: System", "Topic :: Utilities"),
        r"\b(automation|devops|docker|kubernetes|cloud|aws|monitoring|shell|"
        r"terminal|server)\b",
    ),
]
OTRAS = "Otras"


def categoria(
    clasificadores: list[str], texto: str, temas: list[str] | None = None
) -> str:
    """Primera categoría que encaja con el paquete, o «Otras»."""
    libre = " ".join([texto or "", *(temas or [])]).lower().replace("-", " ")
    for nombre, prefijos, patron in CATEGORIAS:
        if any(c.startswith(p) for c in clasificadores for p in prefijos):
            return nombre
        if re.search(patron, libre):
            return nombre
    return OTRAS


def _leer(ruta: Path) -> Any:
    return json.loads(ruta.read_text(encoding="utf-8"))


def cargar_raw(
    dir_raw: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    dir_raw = dir_raw or config.DIR_RAW
    lanzamientos = [
        p
        for ruta in sorted((dir_raw / "lanzamientos").glob("*.json"))
        for p in _leer(ruta)["paquetes"]
    ]
    ruta_github = dir_raw / "github.json"
    repos = _leer(ruta_github) if ruta_github.exists() else {}
    series = {ruta.stem: _leer(ruta) for ruta in (dir_raw / "descargas").glob("*.json")}
    return lanzamientos, repos, series


def serie_relativa(serie: dict[str, Any], d0: date) -> pd.DataFrame:
    """Descargas por día relativo al lanzamiento (solo los días con alguna)."""
    filas = [
        {
            "dia": (date.fromisoformat(fecha) - d0).days,
            "usuario": usuario,
            "total": total,
        }
        for fecha, (usuario, total) in serie["dias"].items()
    ]
    df = pd.DataFrame(filas, columns=["dia", "usuario", "total"])
    return df.sort_values("dia", ignore_index=True)


def acumulado(diaria: pd.DataFrame, columna: str, dias: int) -> int:
    """Descargas de los días 0 a `dias` - 1."""
    tramo = diaria[(diaria["dia"] >= 0) & (diaria["dia"] < dias)]
    return int(tramo[columna].sum())


def fila_paquete(
    lanzamiento: dict[str, Any],
    repo: dict[str, Any] | None,
    serie: dict[str, Any] | None,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    """Variables de un paquete y su serie diaria relativa (o None)."""
    d0 = date.fromisoformat(lanzamiento["primera_subida"][:10])
    dias_subida = [
        (date.fromisoformat(d) - d0).days for d in lanzamiento["dias_subida"]
    ]
    texto = " ".join(
        [lanzamiento.get("resumen") or "", lanzamiento.get("palabras_clave") or ""]
    )
    fila: dict[str, Any] = {
        "paquete": lanzamiento["paquete"],
        "nombre": lanzamiento["nombre"],
        "fecha_lanzamiento": d0,
        "resumen": (lanzamiento.get("resumen") or "").strip()[:200],
        "repo": repo["repo"] if repo else extraer_repo(lanzamiento["urls"]),
        "categoria": categoria(
            lanzamiento.get("clasificadores") or [],
            texto,
            (repo or {}).get("temas"),
        ),
        "dependencias": lanzamiento["dependencias"],
        "versiones_total": lanzamiento["versiones"],
        "mes_lanzamiento": d0.month,
    }
    for d in (*config.DIAS_LECTURA, config.DIAS_VENTANA):
        fila[f"subidas_{d}d"] = sum(0 <= x < d for x in dias_subida)
    if repo:
        repo_creado = date.fromisoformat(repo["repo_creado"][:10])
        propietario_creado = repo.get("propietario_creado")
        fila |= {
            "estrellas": repo["estrellas"],
            "forks": repo["forks"],
            "propietario_tipo": (
                "Organización"
                if repo.get("propietario_tipo") == "Organization"
                else "Persona"
            ),
            "dias_repo_previos": (d0 - repo_creado).days,
            "anios_cuenta": (
                round(
                    (d0 - date.fromisoformat(propietario_creado[:10])).days / 365.25, 2
                )
                if propietario_creado
                else np.nan
            ),
            "es_fork": repo["es_fork"],
        }
    if serie is None:
        return fila, None

    diaria = serie_relativa(serie, d0)
    for d in (*config.DIAS_LECTURA, config.DIAS_VENTANA):
        fila[f"usuario_{d}d"] = acumulado(diaria, "usuario", d)
        fila[f"total_{d}d"] = acumulado(diaria, "total", d)
    previas = int(diaria.loc[diaria["dia"] < 0, "total"].sum())
    total_30 = fila[f"total_{config.DIAS_VENTANA}d"]
    fila["pct_previas"] = previas / total_30 if total_30 else (1.0 if previas else 0.0)
    fila["dias_observados"] = (date.fromisoformat(str(serie["hasta"])) - d0).days + 1
    diaria.insert(0, "paquete", fila["paquete"])
    return fila, diaria


def _normalizar(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")


def prefijo_ajeno(paquete: str, repo: str) -> str | None:
    """El prefijo si el paquete es «prefijo-» + el repositorio de otro.

    `mseep-pptagent` para icip-cas/pptagent da «mseep»; `django-ninja` para
    vitalik/django-ninja no da nada, porque el prefijo es parte del nombre.
    """
    dueno, nombre = (_normalizar(x) for x in repo.split("/", 1))
    completo = f"{dueno}-{nombre}"
    partes = paquete.split("-")
    for i in range(1, min(3, len(partes))):
        prefijo, resto = "-".join(partes[:i]), "-".join(partes[i:])
        if prefijo in completo:
            continue
        sin_guiones = resto.replace("-", "")
        if resto in (nombre, completo) or sin_guiones in (
            nombre.replace("-", ""),
            completo.replace("-", ""),
        ):
            return prefijo
    return None


def republicadores(paquetes: pd.DataFrame) -> set[str]:
    """Prefijos que casi siempre van delante del repositorio de otro."""
    con_repo = paquetes.dropna(subset=["repo"])
    prefijos = pd.Series(
        [
            prefijo_ajeno(p, r)
            for p, r in zip(con_repo["paquete"], con_repo["repo"], strict=True)
        ],
        index=con_repo.index,
    )
    duenos = con_repo["repo"].str.split("/").str[0].groupby(prefijos).nunique()
    salida = set()
    for prefijo in duenos[duenos >= REPUBLICADOS_MIN_DUENOS].index:
        con_prefijo = paquetes["paquete"].str.startswith(f"{prefijo}-").sum()
        if (prefijos == prefijo).sum() >= REPUBLICADOS_FRACCION_MIN * con_prefijo:
            salida.add(prefijo)
    return salida


def es_republicado(paquete: str, repo: Any, ajenos: set[str]) -> bool:
    """Lleva el prefijo de un republicador y el repositorio no es suyo.

    Una vez identificado el prefijo, cuenta cualquier paquete que lo use,
    aunque el resto del nombre no coincida exactamente con el repositorio
    (`mseep-claude-agent-sdk` para anthropics/claude-agent-sdk-python).
    """
    if not isinstance(repo, str):
        return False
    dueno = _normalizar(repo.split("/", 1)[0])
    return any(
        paquete.startswith(f"{prefijo}-") and prefijo not in dueno for prefijo in ajenos
    )


def estado(fila: dict[str, Any]) -> str:
    """«apto» o el primer motivo por el que el paquete no entra en el modelo."""
    if fila.get("estrellas") is None:
        return "sin_repo"
    if fila["estrellas"] < config.ESTRELLAS_MIN:
        return "pocas_estrellas"
    if fila.get("es_fork"):
        return "repo_fork"
    if fila.get("dias_observados") is None:
        return "sin_descargas"
    if fila["dias_observados"] < config.DIAS_VENTANA:
        return "mes_incompleto"
    if fila["pct_previas"] > PCT_PREVIAS_MAX:
        return "versiones_previas_borradas"
    if fila["dias_repo_previos"] > DIAS_REPO_PREVIOS_MAX:
        return "proyecto_anterior"
    return "apto"


def construir_tablas(
    lanzamientos: list[dict[str, Any]],
    repos: dict[str, Any],
    series: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    filas, diarias = [], []
    vistos: set[str] = set()
    for lanzamiento in lanzamientos:
        # Un paquete solo aparece una vez aunque la ventana haya cubierto el
        # mismo mes en dos ficheros (al moverse de un día a otro).
        if lanzamiento["paquete"] in vistos:
            continue
        vistos.add(lanzamiento["paquete"])
        nombre_repo = extraer_repo(lanzamiento["urls"])
        repo = repos.get(nombre_repo) if nombre_repo else None
        fila, diaria = fila_paquete(
            lanzamiento, repo, series.get(lanzamiento["paquete"])
        )
        fila["estado"] = estado(fila)
        filas.append(fila)
        if diaria is not None:
            diarias.append(diaria)
    paquetes = pd.DataFrame(filas).sort_values("paquete", ignore_index=True)
    # Se decide con todos los paquetes a la vista, no uno a uno.
    ajenos = republicadores(paquetes)
    candidatos = ~paquetes["estado"].isin(["sin_repo", "pocas_estrellas"])
    republicado = [
        es_republicado(p, r, ajenos)
        for p, r in zip(paquetes["paquete"], paquetes["repo"], strict=True)
    ]
    paquetes.loc[candidatos & pd.Series(republicado), "estado"] = "republicado"
    # Varios paquetes del mismo repositorio (monorepos, plugins) comparten las
    # estrellas: sirven para el radar, pero no para contrastar estrellas.
    aptos = paquetes["estado"] == "apto"
    compartidos = paquetes.loc[aptos, "repo"].duplicated(keep=False)
    paquetes["repo_compartido"] = False
    paquetes.loc[compartidos[compartidos].index, "repo_compartido"] = True
    diaria = (
        pd.concat(diarias, ignore_index=True)
        if diarias
        else pd.DataFrame(columns=["paquete", "dia", "usuario", "total"])
    )
    return paquetes, diaria


def dataset_radar(paquetes: pd.DataFrame) -> pd.DataFrame:
    """Paquetes aptos con lo que se sabría en cada día de lectura y el objetivo."""
    columnas = [
        "paquete",
        "nombre",
        "repo",
        "fecha_lanzamiento",
        "categoria",
        "propietario_tipo",
        "dependencias",
        "dias_repo_previos",
        "anios_cuenta",
        "mes_lanzamiento",
    ]
    for d in config.DIAS_LECTURA:
        columnas += [f"usuario_{d}d", f"total_{d}d", f"subidas_{d}d"]
    columnas += [
        f"usuario_{config.DIAS_VENTANA}d",
        f"total_{config.DIAS_VENTANA}d",
        f"subidas_{config.DIAS_VENTANA}d",
        "estrellas",
        "repo_compartido",
    ]
    aptos = paquetes[paquetes["estado"] == "apto"]
    return aptos[columnas].sort_values("fecha_lanzamiento", ignore_index=True)


def embudo(paquetes: pd.DataFrame) -> dict[str, int]:
    """Lanzamientos que quedan tras cada filtro, en el orden en que se aplican."""
    estados = paquetes["estado"].value_counts()
    pasos = {"con_enlace_a_github": len(paquetes)}
    restantes = len(paquetes)
    for motivo in (
        "sin_repo",
        "pocas_estrellas",
        "republicado",
        "repo_fork",
        "sin_descargas",
        "mes_incompleto",
        "versiones_previas_borradas",
        "proyecto_anterior",
    ):
        restantes -= int(estados.get(motivo, 0))
        pasos[f"tras_{motivo}"] = restantes
    return pasos


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    lanzamientos, repos, series = cargar_raw()
    if not lanzamientos:
        logger.error("No hay datos en %s: ejecuta antes la ingesta.", config.DIR_RAW)
        return 1
    paquetes, diaria = construir_tablas(lanzamientos, repos, series)
    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    (config.DIR_PROCESADO / "embudo.json").write_text(
        json.dumps(embudo(paquetes), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paquetes = paquetes[~paquetes["estado"].isin(["sin_repo", "pocas_estrellas"])]
    paquetes.to_csv(config.DIR_PROCESADO / "paquetes.csv", index=False)
    # La serie diaria solo de los aptos: es la que usan el EDA, las curvas y
    # la app, y así el CSV del repositorio pesa la mitad.
    aptos = set(paquetes.loc[paquetes["estado"] == "apto", "paquete"])
    diaria = diaria[diaria["paquete"].isin(aptos)]
    diaria.to_csv(config.DIR_PROCESADO / "descargas_diarias.csv", index=False)
    radar = dataset_radar(paquetes)
    radar.to_csv(config.DIR_PROCESADO / "dataset_radar.csv", index=False)
    logger.info(
        "%d paquetes, %d aptos. Exclusiones: %s",
        len(paquetes),
        len(radar),
        paquetes["estado"].value_counts().to_dict(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
