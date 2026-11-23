"""Exportación de los JSON de la app de principio a fin, con datos sintéticos."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from radar import config, exportar
from radar import modelo as m


@pytest.fixture
def salida(procesados: Path, tmp_path: Path) -> Path:
    carpeta = tmp_path / "app_data"
    exportar.exportar(procesados, carpeta, tmp_path / "casos.json")
    return carpeta


def _leer(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def test_escribe_los_tres_json(salida: Path) -> None:
    radar = _leer(salida / "radar.json")
    assert radar["dias_lectura"] == list(config.DIAS_LECTURA)
    assert set(radar["modelos"]) == {str(d) for d in config.DIAS_LECTURA}
    assert set(radar["cohortes"]["global"]) == {"7", "14", "21", "30"}
    assert len(radar["curva_tipica"]["global"]) == config.DIAS_VENTANA
    ejemplo = radar["ejemplos"][0]
    assert len(ejemplo["acumuladas"]) == config.DIAS_VENTANA
    assert ejemplo["acumuladas_total"][-1] == ejemplo["total_30d"]
    assert ejemplo["acumuladas"][-1] == ejemplo["usuario_30d"]

    previo = _leer(salida / "previo.json")
    assert previo["global"]["n"] == 400
    assert {"categoria", "propietario_tipo", "n"} <= set(
        previo["categoria_propietario"][0]
    )

    mercado = _leer(salida / "mercado.json")
    assert mercado["paquetes_aptos"] == 400
    assert mercado["exclusiones"]["versiones_previas_borradas"] == 3
    assert mercado["embudo"]["con_enlace_a_github"] == 5000
    assert 0 < mercado["mediana_pct_usuario_30d"] < 1
    assert "spearman" in mercado["contraste_estrellas"]


def test_aciertos_veredicto_cuentan_todo_el_test(salida: Path) -> None:
    radar = _leer(salida / "radar.json")
    n_test = radar["modelos"]["7"]["tamanos"]["test"]
    for cuentas in radar["aciertos_veredicto"].values():
        total = sum(
            c["por_encima"] + c["en_linea"] + c["por_debajo"] for c in cuentas.values()
        )
        assert total == n_test


def test_casos_dorados_reproducen_el_modelo(procesados: Path, tmp_path: Path) -> None:
    ruta = tmp_path / "casos.json"
    n = exportar.exportar(procesados, tmp_path / "salida", ruta)
    casos = json.loads(ruta.read_text(encoding="utf-8"))
    assert len(casos) == n
    n_test = 80  # 20 % de 400
    assert n == n_test * (len(config.DIAS_LECTURA) + 1)
    previo = next(c for c in casos if c["modelo"] == "previo")
    assert {"anios_cuenta", "dias_repo_previos", "mes_lanzamiento"} <= set(
        previo["entrada"]
    )
    radar7 = next(c for c in casos if c["modelo"] == "radar_7")
    assert {"usuario", "total", "subidas", "dia"} <= set(radar7["entrada"])


@pytest.mark.parametrize(
    "tipo", ["mediana", "ratio_tipico", "ridge", "gradient_boosting"]
)
def test_serializar_cada_tipo_de_modelo(dataset: pd.DataFrame, tipo: str) -> None:
    res = m.entrenar(dataset, m.variables_radar(7), columna_ratio="log_usuario_7d")
    train, _, _ = m.particion_temporal(dataset)
    x = m.preparar_variables(train, res.categorias)[res.variables.todas]
    y = np.log1p(train["usuario_30d"].to_numpy(float))
    modelo = m.candidatos(res.variables, "log_usuario_7d")[tipo].fit(x, y)
    res.nombre, res.modelo = tipo, modelo
    descripcion = exportar.serializar(res)
    assert descripcion["tipo"] == tipo
    clave = {
        "mediana": "mediana",
        "ratio_tipico": "ratio",
        "ridge": "ridge",
        "gradient_boosting": "gb",
    }[tipo]
    assert clave in descripcion
    json.dumps(exportar._redondear(descripcion))  # serializable sin numpy


def test_redondear_tipos_de_numpy() -> None:
    assert exportar._redondear({"a": np.float64(1.23456789), "b": np.int64(3)}) == {
        "a": 1.234568,
        "b": 3,
    }
    assert exportar._redondear([np.nan, np.bool_(True)]) == [None, True]


def test_faltan_procesados(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="radar.preparacion"):
        exportar.exportar(tmp_path, tmp_path / "s", tmp_path / "c.json")


def test_main_sin_datos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "DIR_PROCESADO", tmp_path)
    assert exportar.main() == 1
