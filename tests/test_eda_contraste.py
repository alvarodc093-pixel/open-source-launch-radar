"""Cifras del EDA y contraste con las estrellas de GitHub."""

from __future__ import annotations

import pandas as pd
import pytest

from radar import contraste, eda


def test_descargas_por_subida_mide_el_ruido(dataset: pd.DataFrame) -> None:
    # El conjunto sintético añade 300 descargas automáticas por subida.
    assert eda.descargas_por_subida(dataset) == pytest.approx(300)


def test_pct_usuario_sin_divisiones_por_cero() -> None:
    df = pd.DataFrame({"usuario_30d": [5, 0], "total_30d": [100, 0]})
    pct = eda.pct_usuario(df)
    assert pct.iloc[0] == 0.05
    assert pd.isna(pct.iloc[1])


def test_hallazgos(dataset: pd.DataFrame) -> None:
    h = eda.hallazgos(dataset)
    assert h["spearman_7_30"] > 0.9
    # El total depende de las subidas mucho más que las descargas de usuario.
    assert h["spearman_total_subidas"] > h["spearman_usuario_subidas"]
    assert set(h["epsilon2"]) == {"categoria", "propietario"}
    assert 0 <= h["epsilon2"]["categoria"] < 0.1  # categorías al azar


def test_epsilon_cuadrado() -> None:
    assert eda.epsilon_cuadrado(10.0, 101) == 0.1


def test_contraste_quita_repos_compartidos(dataset: pd.DataFrame) -> None:
    r = contraste.resumen(dataset)
    assert r["repos"] == int((~dataset["repo_compartido"]).sum())
    assert 0.5 < r["spearman"] < 1
    assert r["descargas_por_estrella"]["q25"] <= r["descargas_por_estrella"]["q75"]
    assert {c["categoria"] for c in r["por_categoria"]} <= set(dataset["categoria"])


def test_contraste_encuentra_los_desajustes() -> None:
    base = {
        "categoria": "Otras",
        "repo_compartido": False,
    }
    filas = [
        # Una recta limpia: 1 descarga por estrella…
        *[
            {
                **base,
                "paquete": f"p{i}",
                "repo": f"r/{i}",
                "estrellas": s,
                "usuario_30d": s,
            }
            for i, s in enumerate([10, 50, 100, 600, 1000, 6000, 10_000])
        ],
        # …y dos casos fuera de ella.
        {
            **base,
            "paquete": "hype",
            "repo": "r/hype",
            "estrellas": 5000,
            "usuario_30d": 20,
        },
        {
            **base,
            "paquete": "callada",
            "repo": "r/callada",
            "estrellas": 12,
            "usuario_30d": 90_000,
        },
    ]
    r = contraste.resumen(pd.DataFrame(filas))
    assert r["mas_estrellas_que_uso"][0]["paquete"] == "hype"
    assert r["mas_uso_que_estrellas"][0]["paquete"] == "callada"
    assert r["por_categoria"] == []  # menos de 30 repos por categoría
