"""PyPI a través de ClickPy, la copia pública del dataset de PyPI en ClickHouse.

ClickHouse mantiene en `sql-clickhouse.clickhouse.com` las mismas tablas que
PyPI publica en BigQuery, actualizadas a diario y consultables con el usuario
`demo` sin clave. Las consultas van por HTTP: el SQL en el cuerpo del POST y la
respuesta en JSONEachRow, una fila JSON por línea.

Cuatro límites del usuario demo, comprobados en noviembre de 2026, condicionan
cómo se pregunta:

- Cada resultado tiene como mucho 10.000 filas. Las consultas que pueden
  pasar de ahí se paginan con ORDER BY + LIMIT/OFFSET.
- Si el límite salta a mitad de la respuesta, el servidor ya ha enviado un
  200 y el error llega como texto al final del cuerpo («Code: 396»). Por eso
  se revisa el cuerpo y no solo el código HTTP.
- Cada consulta (con otros valores) se puede ejecutar 20 veces por hora. Por
  eso se pregunta por meses y no por semanas, y las series diarias llegan
  como un array por paquete en lugar de una fila por día.
- La tabla con el detalle por instalador cubre todos los paquetes si se
  filtra con una lista IN (...), pero con un JOIN devuelve solo una parte.

Los nombres de paquete se normalizan como lo hace PyPI (PEP 503): minúsculas
y cualquier serie de «-», «_» o «.» convertida en un guion. Las tablas de
descargas ya los guardan así; la de metadatos (`projects`) no.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from typing import Any

from radar.ingesta.http import ClienteHttp, ErrorFuente

URL = "https://sql-clickhouse.clickhouse.com/"
PARAMS = {"user": "demo", "default_format": "JSONEachRow"}
PAUSA_S = 1.0
FILAS_POR_PAGINA = 9_000  # por debajo del máximo de 10.000 del usuario demo
PAQUETES_POR_CONSULTA = 1_000  # el SQL queda en unos 40 KB

# Instaladores que usa una persona o un proyecto al instalar, frente a los
# mirrors (bandersnatch, Nexus, devpi…), los navegadores y las peticiones sin
# instalador identificado, que son casi siempre bots o escáneres.
INSTALADORES_USUARIO = ("pip", "uv", "poetry", "pdm", "pipenv", "pex")

_NOMBRE_VALIDO = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_NORMALIZAR_SQL = "lower(replaceRegexpAll(name, '[-_.]+', '-'))"


def normalizar(nombre: str) -> str:
    """Nombre canónico de un paquete según PEP 503."""
    return re.sub(r"[-_.]+", "-", nombre).lower()


def consultar(cliente: ClienteHttp, sql: str) -> list[dict[str, Any]]:
    """Ejecuta una consulta y devuelve sus filas como diccionarios."""
    resp = cliente.post(URL, datos=sql, params=PARAMS)
    texto = resp.text
    if "Code: " in texto and "DB::Exception" in texto:
        detalle = texto[texto.index("Code: ") :].splitlines()[0]
        raise ErrorFuente(f"ClickPy: {detalle[:300]}")
    filas = []
    for linea in texto.splitlines():
        if linea.strip():
            filas.append(json.loads(linea))
    return filas


def consultar_paginado(
    cliente: ClienteHttp, sql: str, orden: str
) -> list[dict[str, Any]]:
    """Recorre una consulta en páginas para no pasar del máximo de filas.

    `orden` debe identificar cada fila de forma única; si no, una fila podría
    caer en dos páginas o en ninguna.
    """
    filas: list[dict[str, Any]] = []
    desplazamiento = 0
    while True:
        pagina = consultar(
            cliente,
            f"{sql}\nORDER BY {orden}\n"
            f"LIMIT {FILAS_POR_PAGINA} OFFSET {desplazamiento}",
        )
        filas.extend(pagina)
        if len(pagina) < FILAS_POR_PAGINA:
            return filas
        desplazamiento += FILAS_POR_PAGINA


def _lista_sql(paquetes: Iterable[str]) -> str:
    """Lista de nombres para un IN (...), solo con nombres ya normalizados.

    Los nombres vienen de la propia ClickPy, pero se validan igualmente: van
    pegados al SQL y no se puede dejar pasar ni una comilla.
    """
    validos = sorted({p for p in paquetes if _NOMBRE_VALIDO.match(p)})
    if not validos:
        raise ValueError("Ningún nombre de paquete válido para la consulta")
    return ", ".join(f"'{p}'" for p in validos)


def sql_lanzamientos(desde: date, hasta: date) -> str:
    """Un registro por paquete cuya primera subida cae entre `desde` y `hasta`.

    Solo paquetes que enlazan github.com en alguna de sus URLs: la muestra los
    necesita y así cada mes cabe en una o dos páginas. Los metadatos (resumen,
    clasificadores, URLs…) son los de la última subida, que es la que enseña
    PyPI. `dias_subida` incluye cualquier fichero nuevo, no solo versiones
    nuevas: los mirrors también lo descargan.
    """
    return f"""
SELECT
    {_NORMALIZAR_SQL} AS paquete,
    argMax(name, upload_time) AS nombre,
    toString(min(upload_time)) AS primera_subida,
    argMax(summary, upload_time) AS resumen,
    substring(argMax(license, upload_time), 1, 120) AS licencia,
    argMax(requires_python, upload_time) AS requires_python,
    length(arrayFilter(
        d -> NOT match(d, 'extra\\\\s*=='), argMax(requires_dist, upload_time)
    )) AS dependencias,
    argMax(classifiers, upload_time) AS clasificadores,
    argMax(keywords, upload_time) AS palabras_clave,
    argMax(arrayConcat(project_urls, [home_page]), upload_time) AS urls,
    arraySort(arrayMap(d -> toString(d), groupUniqArray(toDate(upload_time))))
        AS dias_subida,
    uniqExact(version) AS versiones
FROM pypi.projects
GROUP BY paquete
HAVING toDate(min(upload_time)) BETWEEN '{desde.isoformat()}' AND '{hasta.isoformat()}'
   AND match(arrayStringConcat(urls, ' '), '(?i)github\\\\.com/')"""


def descargar_lanzamientos(
    cliente: ClienteHttp, desde: date, hasta: date
) -> list[dict[str, Any]]:
    filas = consultar_paginado(cliente, sql_lanzamientos(desde, hasta), "paquete")
    for fila in filas:
        fila["versiones"] = int(fila["versiones"])
        fila["dependencias"] = int(fila["dependencias"])
    return filas


def sql_descargas(paquetes: Iterable[str], desde: date, hasta: date) -> str:
    """Serie diaria de un grupo de paquetes: una fila por paquete.

    Cada fila lleva los días como un array de [fecha, de usuario, totales], así
    que 1.000 paquetes son 1.000 filas y no 100.000. La tabla por instalador
    cubre todos los paquetes cuando se filtra con una lista IN (...); con un
    JOIN contra otra consulta devuelve solo una parte, así que los nombres
    siempre van en la lista.
    """
    usuario = ", ".join(f"'{i}'" for i in INSTALADORES_USUARIO)
    return f"""
SELECT paquete, groupArray([fecha, toString(usuario), toString(total)]) AS dias
FROM (
    SELECT project AS paquete, toString(date) AS fecha,
           sumIf(count, installer IN ({usuario})) AS usuario,
           sum(count) AS total
    FROM pypi.pypi_downloads_per_day_by_version_by_installer_by_type
    WHERE project IN ({_lista_sql(paquetes)})
      AND date BETWEEN '{desde.isoformat()}' AND '{hasta.isoformat()}'
    GROUP BY paquete, fecha
)
GROUP BY paquete"""


def descargar_series(
    cliente: ClienteHttp, paquetes: Iterable[str], desde: date, hasta: date
) -> dict[str, dict[str, list[int]]]:
    """{paquete: {fecha: [de usuario, totales]}}; los días sin descargas no
    aparecen."""
    series: dict[str, dict[str, list[int]]] = {}
    sql = sql_descargas(paquetes, desde, hasta)
    for fila in consultar_paginado(cliente, sql, "paquete"):
        series[fila["paquete"]] = {
            fecha: [int(usuario), int(total)]
            for fecha, usuario, total in sorted(fila["dias"])
        }
    return series
