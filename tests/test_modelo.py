"""Partición, baselines, intervalo conformal y ausencia de fugas."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from radar import config
from radar import modelo as m


@pytest.fixture
def dataset() -> pd.DataFrame:
    """300 lanzamientos sintéticos: u30 ≈ 3 × u7 con ruido."""
    rng = np.random.default_rng(0)
    n = 300
    u7 = rng.lognormal(3, 1.2, n).round()
    subidas = rng.integers(1, 6, n)
    return pd.DataFrame(
        {
            "paquete": [f"p{i}" for i in range(n)],
            "fecha_lanzamiento": pd.date_range("2025-01-01", periods=n, freq="D"),
            "categoria": rng.choice(
                ["Agentes y LLM", "Datos y ciencia", "Web y APIs", "Rara"],
                n,
                p=[0.4, 0.3, 0.29, 0.01],
            ),
            "propietario_tipo": rng.choice(["Persona", "Organización"], n),
            "dependencias": rng.integers(0, 20, n),
            "dias_repo_previos": rng.integers(-5, 300, n),
            "anios_cuenta": rng.uniform(0, 12, n),
            "mes_lanzamiento": rng.integers(1, 13, n),
            "usuario_7d": u7,
            "total_7d": u7 + 300 * subidas,
            "subidas_7d": subidas,
            "usuario_30d": np.round(u7 * 3 * rng.lognormal(0, 0.2, n)),
        }
    )


def test_particion_cronologica_sin_solapes(dataset) -> None:  # noqa: ANN001
    train, calib, test = m.particion_temporal(dataset.sample(frac=1, random_state=1))
    assert len(train) + len(calib) + len(test) == len(dataset)
    assert train["fecha_lanzamiento"].max() <= calib["fecha_lanzamiento"].min()
    assert calib["fecha_lanzamiento"].max() <= test["fecha_lanzamiento"].min()


def test_variables_del_radar_no_miran_el_futuro() -> None:
    for dia in config.DIAS_LECTURA:
        nombres = m.variables_radar(dia).todas
        assert not any("30d" in v for v in nombres)
        posteriores = [d for d in config.DIAS_LECTURA if d > dia]
        assert not any(f"_{d}d" in v for v in nombres for d in posteriores)
    # Antes de lanzar no hay descargas, ni estrellas (que son las de hoy).
    previas = m.VARIABLES_PREVIAS.todas
    assert not any("usuario" in v or "total" in v or "estrellas" in v for v in previas)


def test_preparar_variables() -> None:
    df = pd.DataFrame(
        {
            "usuario_7d": [0, 9],
            "total_7d": [99, 999],
            "dependencias": [0, 3],
            "dias_repo_previos": [-2, 10],
            "propietario_tipo": ["Persona", "Organización"],
            "categoria": ["Web y APIs", "Rara"],
        }
    )
    out = m.preparar_variables(df, ["Web y APIs"])
    np.testing.assert_allclose(out["log_usuario_7d"], np.log1p([0, 9]))
    # Un repositorio creado después de la primera subida cuenta como 0 días.
    np.testing.assert_allclose(out["log_dias_repo_previos"], np.log1p([0, 10]))
    assert list(out["organizacion"]) == [0.0, 1.0]
    assert list(out["categoria_modelo"]) == ["Web y APIs", "Otras"]


def test_ratio_tipico_aprende_el_desplazamiento() -> None:
    x = pd.DataFrame({"log_u": np.log1p([10.0, 20.0, 40.0])})
    y = x["log_u"].to_numpy() + np.log(3)
    pred = m.RatioTipico("log_u").fit(x, y).predict(x)
    np.testing.assert_allclose(pred, y)


def test_cuantil_conformal_con_correccion_de_muestra_finita() -> None:
    residuos = np.arange(1, 11, dtype=float)  # n = 10 → nivel ceil(11·0,9)/10 = 1
    assert m.cuantil_conformal(residuos, 0.9) == 10
    assert m.cuantil_conformal(np.arange(1, 101, dtype=float), 0.9) == 91


def test_metricas_de_un_baseline_constante() -> None:
    resultado = m.metricas(np.log1p([10.0, 20.0]), np.log1p([15.0, 15.0]))
    assert resultado["spearman"] is None
    assert resultado["dentro_de_x2"] == 1.0


def test_entrenar_radar_supera_a_la_mediana_y_cubre(dataset) -> None:  # noqa: ANN001
    res = m.entrenar(dataset, m.variables_radar(7), columna_ratio="log_usuario_7d")
    assert res.nombre != "mediana"
    assert res.test["mae_log"] < res.test_baselines["mediana"]["mae_log"] / 2
    assert 0.7 <= res.test["cobertura_90"] <= 1.0
    assert res.tamanos == {"train": 180, "calibracion": 60, "test": 60}
    # La categoría rara del train no llega al mínimo y se agrupa en «Otras».
    assert "Rara" not in res.categorias


def test_entrenar_previo_sin_ratio(dataset) -> None:  # noqa: ANN001
    res = m.entrenar(dataset, m.VARIABLES_PREVIAS)
    assert "ratio_tipico" not in res.test_baselines
    assert set(res.cv["modelo"]) == {"mediana", "ridge", "gradient_boosting"}
