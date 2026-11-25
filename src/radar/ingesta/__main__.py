"""Ingesta reanudable: lanzamientos (PyPI) → repositorios (GitHub) → descargas.

Uso:
    python -m radar.ingesta                   # los tres pasos
    python -m radar.ingesta --paso descargas  # solo uno

Cada respuesta se guarda en data/raw/ en cuanto llega. Si la ejecución se
corta, al relanzarla se salta lo que ya está descargado.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from radar import config
from radar.ingesta import clickpy, github
from radar.ingesta.http import ClienteHttp, ErrorFuente

logger = logging.getLogger("radar.ingesta")

DIR_LANZAMIENTOS = config.DIR_RAW / "lanzamientos"
RUTA_GITHUB = config.DIR_RAW / "github.json"
DIR_DESCARGAS = config.DIR_RAW / "descargas"


def _leer(ruta: Path) -> Any:
    return json.loads(ruta.read_text(encoding="utf-8"))


def _guardar(ruta: Path, contenido: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(contenido, ensure_ascii=False, default=str), encoding="utf-8"
    )
    # Escritura atómica: un corte no deja JSON a medias. En Windows el
    # antivirus puede tener el fichero abierto un instante.
    for intento in range(5):
        try:
            tmp.replace(ruta)
            return
        except PermissionError:
            time.sleep(0.5 * (intento + 1))
    tmp.replace(ruta)


def meses(desde: date, hasta: date) -> list[tuple[date, date]]:
    """Meses naturales que cubren [desde, hasta], recortados por los extremos."""
    tramos = []
    inicio = desde.replace(day=1)
    while inicio <= hasta:
        siguiente = (inicio + timedelta(days=32)).replace(day=1)
        tramos.append((max(inicio, desde), min(siguiente - timedelta(days=1), hasta)))
        inicio = siguiente
    return tramos


def paso_lanzamientos(hoy: date) -> list[dict[str, Any]]:
    """Paquetes publicados por primera vez en la ventana, mes a mes.

    Un mes ya guardado no se vuelve a pedir si cubre el mismo tramo. El
    primero y el último de la ventana cambian cada día, así que se piden de
    nuevo si la ventana se ha movido.
    """
    cliente = ClienteHttp(pausa_s=clickpy.PAUSA_S)
    desde, hasta = config.ventana_lanzamientos(hoy)
    todos: list[dict[str, Any]] = []
    for inicio, fin in meses(desde, hasta):
        ruta = DIR_LANZAMIENTOS / f"{inicio:%Y-%m}.json"
        guardado = _leer(ruta) if ruta.exists() else None
        tramo = {"desde": inicio.isoformat(), "hasta": fin.isoformat()}
        if guardado is None or {k: guardado[k] for k in tramo} != tramo:
            filas = clickpy.descargar_lanzamientos(cliente, inicio, fin)
            guardado = {**tramo, "paquetes": filas}
            _guardar(ruta, guardado)
            logger.info("%s: %d lanzamientos con GitHub", f"{inicio:%Y-%m}", len(filas))
        todos.extend(guardado["paquetes"])
    # Meses que ya han salido de la ventana: no se borran, pero no se usan.
    logger.info("%d lanzamientos entre %s y %s", len(todos), desde, hasta)
    return todos


def paso_github(lanzamientos: list[dict[str, Any]]) -> dict[str, Any]:
    """Datos de cada repositorio enlazado, en lotes de 100."""
    token = config.token_github()
    if not token:
        raise SystemExit("Falta GITHUB_TOKEN (o una sesión de `gh`) para GraphQL.")
    cliente = ClienteHttp(
        pausa_s=github.PAUSA_S, cabeceras={"Authorization": f"bearer {token}"}
    )
    repos_guardados: dict[str, Any] = _leer(RUTA_GITHUB) if RUTA_GITHUB.exists() else {}
    enlazados = {github.extraer_repo(p["urls"]) for p in lanzamientos} - {None}
    pendientes = sorted(r for r in enlazados if r not in repos_guardados)
    logger.info("GitHub: %d pendientes de %d", len(pendientes), len(enlazados))
    # Los lotes fallidos se reintentan una vez al final, cuando la API ya se
    # ha recuperado del fallo pasajero.
    fallidos: list[list[str]] = []
    for i in range(0, len(pendientes), github.POR_CONSULTA):
        lote = pendientes[i : i + github.POR_CONSULTA]
        try:
            repos_guardados.update(github.descargar_repos(cliente, lote))
        except ErrorFuente as exc:
            logger.warning("Lote de GitHub sin descargar: %s", exc)
            fallidos.append(lote)
            continue
        _guardar(RUTA_GITHUB, repos_guardados)
        if (i // github.POR_CONSULTA) % 20 == 0:
            logger.info("GitHub: %d/%d", i + len(lote), len(pendientes))
    for lote in fallidos:
        try:
            repos_guardados.update(github.descargar_repos(cliente, lote))
        except ErrorFuente as exc:
            logger.warning("Lote de GitHub perdido (se pedirá otro día): %s", exc)
            continue
        _guardar(RUTA_GITHUB, repos_guardados)
    return repos_guardados


def en_muestra(paquete: dict[str, Any], repos: dict[str, Any]) -> bool:
    """Con repositorio en GitHub que existe y llega al mínimo de estrellas."""
    repo = github.extraer_repo(paquete["urls"])
    datos = repos.get(repo) if repo else None
    return bool(datos) and datos["estrellas"] >= config.ESTRELLAS_MIN


def rango_serie(primera_subida: str, hoy: date) -> tuple[date, date]:
    """Días de la serie de un paquete: del día −30 al 89, como mucho hasta ayer."""
    d0 = date.fromisoformat(primera_subida[:10])
    return (
        d0 + timedelta(days=config.DIA_PRIMERO),
        min(d0 + timedelta(days=config.DIA_ULTIMO), hoy - timedelta(days=1)),
    )


def paso_descargas(
    lanzamientos: list[dict[str, Any]], repos: dict[str, Any], hoy: date
) -> None:
    """Serie diaria de cada paquete de la muestra.

    Se piden juntos los paquetes lanzados el mismo mes, para que el rango de
    fechas de la consulta sea estrecho. Una serie se vuelve a pedir si en
    la descarga anterior aún no llegaba al día 89.
    """
    cliente = ClienteHttp(pausa_s=clickpy.PAUSA_S)
    muestra = [p for p in lanzamientos if en_muestra(p, repos)]
    pendientes = []
    for p in muestra:
        ruta = DIR_DESCARGAS / f"{p['paquete']}.json"
        _, hasta = rango_serie(p["primera_subida"], hoy)
        if not ruta.exists() or _leer(ruta)["hasta"] < hasta.isoformat():
            pendientes.append(p)
    logger.info("Descargas: %d pendientes de %d", len(pendientes), len(muestra))

    por_mes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in pendientes:
        por_mes[p["primera_subida"][:7]].append(p)

    hechos = 0
    for mes in sorted(por_mes):
        grupo = por_mes[mes]
        for i in range(0, len(grupo), clickpy.PAQUETES_POR_CONSULTA):
            lote = grupo[i : i + clickpy.PAQUETES_POR_CONSULTA]
            rangos = {p["paquete"]: rango_serie(p["primera_subida"], hoy) for p in lote}
            desde = min(r[0] for r in rangos.values())
            hasta = max(r[1] for r in rangos.values())
            try:
                series = clickpy.descargar_series(cliente, list(rangos), desde, hasta)
            except ErrorFuente as exc:
                logger.warning("Descargas de %s sin bajar: %s", mes, exc)
                continue
            for nombre, (inicio, fin) in rangos.items():
                dias = {
                    f: v
                    for f, v in series.get(nombre, {}).items()
                    if inicio.isoformat() <= f <= fin.isoformat()
                }
                _guardar(
                    DIR_DESCARGAS / f"{nombre}.json",
                    {"paquete": nombre, "desde": inicio, "hasta": fin, "dias": dias},
                )
            hechos += len(lote)
        logger.info("Descargas: %d/%d", hechos, len(pendientes))


def main(argv: list[str] | None = None, hoy: date | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--paso", choices=["lanzamientos", "github", "descargas"])
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    hoy = hoy or datetime.now(UTC).date()
    lanzamientos = (
        paso_lanzamientos(hoy)
        if args.paso in (None, "lanzamientos")
        # La caché conserva meses que ya han salido de la ventana.
        else [
            p
            for ruta in sorted(DIR_LANZAMIENTOS.glob("*.json"))
            for p in _leer(ruta)["paquetes"]
            if config.en_ventana(p["primera_subida"], hoy)
        ]
    )
    if not lanzamientos:
        logger.error("No hay lanzamientos: ejecuta antes el paso de lanzamientos.")
        return 1
    if args.paso in (None, "github"):
        repos = paso_github(lanzamientos)
    else:
        repos = _leer(RUTA_GITHUB) if RUTA_GITHUB.exists() else {}
    if args.paso in (None, "descargas"):
        paso_descargas(lanzamientos, repos, hoy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
