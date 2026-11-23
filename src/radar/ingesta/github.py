"""Repositorio de GitHub enlazado desde PyPI (API GraphQL).

Solo se piden datos agregados y públicos del repositorio: estrellas, forks,
fechas, temas y el tipo de propietario. Desde 2026 GitHub ya no publica quién
da cada estrella ni cuándo (el listado de stargazers responde 404 aunque haya
sesión y GH Archive dejó de recibir esos eventos), así que las estrellas son
el recuento de hoy y no sirven como señal temprana: se usan para filtrar la
muestra y como contraste externo de las descargas.

Con GraphQL se preguntan 100 repositorios en una sola petición, cada uno con
un alias. Un repositorio borrado o renombrado sin redirección devuelve null
con un error NOT_FOUND, que se trata como «sin repositorio».
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from radar.ingesta.http import ClienteHttp, ErrorFuente

logger = logging.getLogger(__name__)

URL = "https://api.github.com/graphql"
POR_CONSULTA = 100
PAUSA_S = 0.5

# Rutas de github.com que no son repositorios de un proyecto.
_NO_PROPIETARIOS = {
    "sponsors",
    "orgs",
    "users",
    "settings",
    "marketplace",
    "features",
    "topics",
    "apps",
}
_REPO = re.compile(
    r"github\.com[/:]+([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9_.-]+)", re.I
)

CAMPOS = """
    nameWithOwner
    stargazerCount
    forkCount
    createdAt
    isFork
    isArchived
    primaryLanguage { name }
    licenseInfo { spdxId }
    repositoryTopics(first: 10) { nodes { topic { name } } }
    owner { __typename login ... on User { createdAt } ... on Organization { createdAt } }
"""


def extraer_repo(urls: list[str]) -> str | None:
    """«propietario/nombre» del primer enlace a un repositorio de GitHub.

    Las URLs de PyPI son variadas («…/issues», «git+https://…/repo.git»,
    «…/tree/main/docs»): de cada una solo se toman los dos primeros tramos de
    la ruta y se quita un «.git» final.
    """
    for url in urls:
        coincidencia = _REPO.search(url or "")
        if not coincidencia:
            continue
        propietario, nombre = coincidencia.groups()
        nombre = re.sub(r"\.git$", "", nombre).rstrip(".")
        if propietario.lower() in _NO_PROPIETARIOS or not nombre:
            continue
        return f"{propietario}/{nombre}".lower()
    return None


def construir_consulta(repos: list[str]) -> str:
    """Consulta GraphQL con un alias por repositorio (r0, r1, …)."""
    partes = []
    for i, repo in enumerate(repos):
        propietario, nombre = repo.split("/", 1)
        partes.append(
            f"r{i}: repository(owner: {json.dumps(propietario)}, "
            f"name: {json.dumps(nombre)}) {{{CAMPOS}}}"
        )
    return "query {\n" + "\n".join(partes) + "\n rateLimit { remaining resetAt } }"


def parsear_repo(nodo: dict[str, Any] | None) -> dict[str, Any] | None:
    if not nodo:
        return None
    propietario = nodo.get("owner") or {}
    return {
        "repo": nodo["nameWithOwner"].lower(),
        "estrellas": nodo.get("stargazerCount", 0),
        "forks": nodo.get("forkCount", 0),
        "repo_creado": nodo.get("createdAt"),
        "es_fork": bool(nodo.get("isFork")),
        "archivado": bool(nodo.get("isArchived")),
        "lenguaje": (nodo.get("primaryLanguage") or {}).get("name"),
        "licencia_repo": (nodo.get("licenseInfo") or {}).get("spdxId"),
        "temas": [
            n["topic"]["name"]
            for n in (nodo.get("repositoryTopics") or {}).get("nodes", [])
        ],
        "propietario_tipo": propietario.get("__typename"),
        "propietario_creado": propietario.get("createdAt"),
    }


def descargar_repos(
    cliente: ClienteHttp, repos: list[str]
) -> dict[str, dict[str, Any] | None]:
    """{repo pedido: datos o None si no existe}, para un lote de hasta 100."""
    resp = cliente.post(URL, json={"query": construir_consulta(repos)})
    try:
        cuerpo = resp.json()
    except ValueError as exc:
        # GitHub a veces responde 200 con el cuerpo vacío cuando va cargado.
        raise ErrorFuente("GraphQL devolvió una respuesta que no es JSON") from exc
    errores = [e for e in cuerpo.get("errors") or [] if e.get("type") != "NOT_FOUND"]
    if errores:
        raise ErrorFuente(f"GraphQL: {errores[0].get('message', errores[0])}")
    datos = cuerpo.get("data") or {}
    restante = (datos.get("rateLimit") or {}).get("remaining")
    if isinstance(restante, int) and restante < 200:
        logger.warning("Quedan %d puntos de GraphQL esta hora", restante)
    return {repo: parsear_repo(datos.get(f"r{i}")) for i, repo in enumerate(repos)}
