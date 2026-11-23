"""Datos procesados sintéticos, con la misma forma que los de radar.preparacion."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CATEGORIAS = ["Agentes y LLM", "Datos y ciencia", "Web y APIs", "Otras"]


def _dataset(n: int = 400, semilla: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lanzamientos con u30 ≈ 3 × u7 y un ruido de ~300 descargas por subida."""
    rng = np.random.default_rng(semilla)
    u7 = rng.lognormal(3, 1.2, n).round()
    u3 = np.floor(u7 * rng.uniform(0.3, 0.6, n))
    u14 = np.ceil(u7 * rng.uniform(1.3, 1.8, n))
    u21 = np.ceil(u14 * rng.uniform(1.1, 1.3, n))
    u30 = np.maximum(np.round(u7 * 3 * rng.lognormal(0, 0.2, n)), u21)
    subidas30 = rng.integers(1, 8, n)
    subidas = {d: np.minimum(subidas30, rng.integers(1, d + 1, n)) for d in (7, 14, 21)}
    estrellas = np.round(u30 * rng.lognormal(0, 0.8, n)).clip(10)
    df = pd.DataFrame(
        {
            "paquete": [f"paquete-{i}" for i in range(n)],
            "nombre": [f"paquete_{i}" for i in range(n)],
            "repo": [f"dueno/paquete-{i}" for i in range(n)],
            "fecha_lanzamiento": pd.date_range("2025-11-01", periods=n, freq="20h"),
            "categoria": rng.choice(CATEGORIAS, n),
            "propietario_tipo": rng.choice(["Persona", "Organización"], n),
            "dependencias": rng.integers(0, 15, n),
            "dias_repo_previos": rng.integers(-3, 200, n),
            "anios_cuenta": rng.uniform(0, 10, n).round(2),
            "mes_lanzamiento": 0,
            "estrellas": estrellas,
            "repo_compartido": rng.random(n) < 0.05,
        }
    )
    df["mes_lanzamiento"] = df["fecha_lanzamiento"].dt.month
    for d, u in {3: u3, 7: u7, 14: u14, 21: u21, 30: u30}.items():
        sub = subidas.get(d, subidas30)
        df[f"usuario_{d}d"] = u.astype(int)
        df[f"total_{d}d"] = (u + 300 * sub).astype(int)
        df[f"subidas_{d}d"] = sub
    # Serie diaria coherente con los acumulados: lo de cada tramo, repartido
    # el primer día del tramo (basta para las curvas y los ejemplos).
    filas = []
    for _, p in df.iterrows():
        previo_u = previo_t = 0
        for inicio, d in [(0, 3), (3, 7), (7, 14), (14, 21), (21, 30)]:
            filas.append(
                {
                    "paquete": p["paquete"],
                    "dia": inicio,
                    "usuario": p[f"usuario_{d}d"] - previo_u,
                    "total": p[f"total_{d}d"] - previo_t,
                }
            )
            previo_u, previo_t = p[f"usuario_{d}d"], p[f"total_{d}d"]
    return df, pd.DataFrame(filas)


@pytest.fixture
def dataset() -> pd.DataFrame:
    return _dataset()[0]


@pytest.fixture
def procesados(tmp_path: Path) -> Path:
    """Carpeta con los cuatro ficheros que escribe radar.preparacion."""
    df, diarias = _dataset()
    carpeta = tmp_path / "processed"
    carpeta.mkdir()
    df.to_csv(carpeta / "dataset_radar.csv", index=False)
    paquetes = df.assign(estado="apto")
    excluido = paquetes.iloc[:3].assign(estado="versiones_previas_borradas")
    pd.concat([paquetes, excluido]).to_csv(carpeta / "paquetes.csv", index=False)
    diarias.to_csv(carpeta / "descargas_diarias.csv", index=False)
    (carpeta / "embudo.json").write_text(
        json.dumps({"con_enlace_a_github": 5000, "tras_proyecto_anterior": 400})
    )
    return carpeta
