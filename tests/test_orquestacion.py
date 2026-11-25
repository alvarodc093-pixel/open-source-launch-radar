"""Pasos de la ingesta de principio a fin, con las fuentes simuladas."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from radar import config
from radar.ingesta import __main__ as ingesta
from radar.ingesta.http import ErrorFuente

HOY = date(2026, 5, 20)  # ventana: 2025-05-20 a 2026-04-05


@pytest.fixture
def raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """data/raw en una carpeta temporal."""
    monkeypatch.setattr(ingesta, "DIR_LANZAMIENTOS", tmp_path / "lanzamientos")
    monkeypatch.setattr(ingesta, "RUTA_GITHUB", tmp_path / "github.json")
    monkeypatch.setattr(ingesta, "DIR_DESCARGAS", tmp_path / "descargas")
    monkeypatch.setattr(config, "token_github", lambda: "token-de-prueba")
    return tmp_path


def _paquete(nombre: str, subida: str = "2026-03-02 10:00:00") -> dict[str, Any]:
    return {
        "paquete": nombre,
        "primera_subida": subida,
        "urls": [f"https://github.com/dueno/{nombre}"],
    }


def test_paso_lanzamientos_pide_cada_mes_una_vez(
    raw: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pedidos: list[tuple[date, date]] = []

    def falso(_cliente, desde, hasta):  # noqa: ANN001, ANN202
        pedidos.append((desde, hasta))
        return [_paquete(f"p{desde:%Y%m}")]

    monkeypatch.setattr(ingesta.clickpy, "descargar_lanzamientos", falso)
    todos = ingesta.paso_lanzamientos(HOY)
    assert len(pedidos) == 12  # de mayo de 2025 a abril de 2026
    assert pedidos[0] == (date(2025, 5, 20), date(2025, 5, 31))
    assert pedidos[-1] == (date(2026, 4, 1), date(2026, 4, 5))
    assert len(todos) == 12

    # Al día siguiente solo cambian el primer mes y el último.
    pedidos.clear()
    ingesta.paso_lanzamientos(date(2026, 5, 21))
    assert [d for d, _ in pedidos] == [date(2025, 5, 21), date(2026, 4, 1)]


def test_paso_github_guarda_y_no_repite(
    raw: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lotes: list[list[str]] = []

    def falso(_cliente, repos):  # noqa: ANN001, ANN202
        lotes.append(repos)
        if "dueno/roto" in repos:
            raise ErrorFuente("lote roto")
        return {r: {"repo": r, "estrellas": 20} for r in repos}

    monkeypatch.setattr(ingesta.github, "descargar_repos", falso)
    monkeypatch.setattr(ingesta.github, "POR_CONSULTA", 2)
    lanzamientos = [_paquete("a"), _paquete("b"), _paquete("roto")]
    lanzamientos.append({"paquete": "x", "primera_subida": "2026-03-02", "urls": []})
    repos = ingesta.paso_github(lanzamientos)
    assert set(repos) == {"dueno/a", "dueno/b"}  # el lote roto se salta
    guardado = json.loads((raw / "github.json").read_text(encoding="utf-8"))
    assert set(guardado) == {"dueno/a", "dueno/b"}

    # El lote roto se reintenta una vez al final de la misma ejecución.
    assert lotes[-1] == ["dueno/roto"] and lotes.count(["dueno/roto"]) == 2

    lotes.clear()
    ingesta.paso_github(lanzamientos)
    assert lotes == [["dueno/roto"]] * 2  # solo vuelve a pedir lo que faltaba


def test_paso_github_sin_token(raw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "token_github", lambda: None)
    with pytest.raises(SystemExit, match="GITHUB_TOKEN"):
        ingesta.paso_github([_paquete("a")])


def test_paso_descargas_recorta_cada_serie_a_su_rango(
    raw: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pedidos: list[tuple[list[str], date, date]] = []

    def falso(_cliente, paquetes, desde, hasta):  # noqa: ANN001, ANN202
        pedidos.append((sorted(paquetes), desde, hasta))
        return {
            p: {"2026-01-01": [9, 9], "2026-03-02": [1, 50], "2026-12-01": [9, 9]}
            for p in paquetes
        }

    monkeypatch.setattr(ingesta.clickpy, "descargar_series", falso)
    repos = {
        "dueno/a": {"estrellas": 30},
        "dueno/b": {"estrellas": 30},
        "dueno/c": {"estrellas": 2},  # fuera de la muestra
    }
    lanzamientos = [
        _paquete("a"),
        _paquete("b", "2026-04-02 00:00:00"),
        _paquete("c"),
    ]
    ingesta.paso_descargas(lanzamientos, repos, HOY)
    assert [p for p, _, _ in pedidos] == [["a"], ["b"]]  # un lote por mes
    serie = json.loads((raw / "descargas" / "a.json").read_text(encoding="utf-8"))
    # Del día -30 al 89: ni el 1 de enero ni el 1 de diciembre entran.
    assert serie["dias"] == {"2026-03-02": [1, 50]}
    assert serie["hasta"] == "2026-05-19"  # ayer: el día 89 aún no ha llegado

    # Al día siguiente la serie se queda corta y se vuelve a pedir.
    pedidos.clear()
    ingesta.paso_descargas(lanzamientos, repos, date(2026, 5, 21))
    assert [p for p, _, _ in pedidos] == [["a"], ["b"]]


def test_paso_descargas_sigue_si_falla_un_lote(
    raw: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def falso(_cliente, paquetes, desde, hasta):  # noqa: ANN001, ANN202
        raise ErrorFuente("cupo")

    monkeypatch.setattr(ingesta.clickpy, "descargar_series", falso)
    ingesta.paso_descargas([_paquete("a")], {"dueno/a": {"estrellas": 30}}, HOY)
    assert not (raw / "descargas").exists()


def test_main_por_pasos(raw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llamados: list[str] = []
    monkeypatch.setattr(
        ingesta,
        "paso_lanzamientos",
        lambda hoy: llamados.append("lanzamientos") or [_paquete("a")],
    )
    monkeypatch.setattr(
        ingesta, "paso_github", lambda _l: llamados.append("github") or {}
    )
    monkeypatch.setattr(
        ingesta, "paso_descargas", lambda _l, _r, _h: llamados.append("descargas")
    )
    assert ingesta.main([], hoy=HOY) == 0
    assert llamados == ["lanzamientos", "github", "descargas"]

    # Un paso suelto lee lo que dejaron los anteriores (aún no hay ninguno).
    llamados.clear()
    assert ingesta.main(["--paso", "descargas"], hoy=HOY) == 1
    (raw / "lanzamientos").mkdir()
    (raw / "lanzamientos" / "2026-03.json").write_text(
        json.dumps({"paquetes": [_paquete("a")]}), encoding="utf-8"
    )
    assert ingesta.main(["--paso", "descargas"], hoy=HOY) == 0
    assert llamados == ["descargas"]


def test_paso_parcial_ignora_lo_que_salio_de_la_ventana(
    raw: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La caché conserva meses viejos y futuros: el parcial no los debe usar."""
    (raw / "lanzamientos").mkdir()
    for nombre, subida in [
        ("2025-04", "2025-04-10 00:00:00"),  # antes del inicio
        ("2026-03", "2026-03-02 10:00:00"),  # dentro
        ("2026-05", "2026-05-10 00:00:00"),  # después del cierre
    ]:
        (raw / "lanzamientos" / f"{nombre}.json").write_text(
            json.dumps({"paquetes": [_paquete(nombre, subida)]}), encoding="utf-8"
        )
    leidos: list[str] = []
    monkeypatch.setattr(
        ingesta,
        "paso_github",
        lambda lanz: leidos.extend(p["paquete"] for p in lanz) or {},
    )
    monkeypatch.setattr(ingesta, "paso_descargas", lambda _l, _r, _h: None)
    assert ingesta.main(["--paso", "github"], hoy=HOY) == 0
    assert leidos == ["2026-03"]


def test_ventana_y_token(monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.ventana_lanzamientos(HOY) == (date(2025, 5, 20), date(2026, 4, 5))
    assert config.en_ventana("2026-03-02 10:00:00", HOY)
    assert config.en_ventana("2026-04-05", HOY)  # el último día cuenta
    assert not config.en_ventana("2026-04-06", HOY)
    assert not config.en_ventana("2025-05-19", HOY)
    monkeypatch.setenv("GITHUB_TOKEN", " abc ")
    assert config.token_github() == "abc"
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setattr(config.shutil, "which", lambda _n: None)
    assert config.token_github() is None
