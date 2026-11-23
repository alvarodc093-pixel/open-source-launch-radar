"""Cifras del análisis exploratorio que también enseña la aplicación.

El notebook 02_eda las calcula con estas funciones y `exportar` las guarda en
mercado.json, así que la portada de la app no repite cifras escritas a mano
que dejarían de ser ciertas al reentrenar con datos nuevos.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

MIN_PAQUETES_CATEGORIA = 15


def epsilon_cuadrado(h: float, n: int) -> float:
    """Tamaño del efecto de Kruskal-Wallis: fracción de la varianza de rangos explicada."""
    return h / (n - 1)


def spearman(dataset: pd.DataFrame, a: str, b: str) -> float:
    return float(stats.spearmanr(dataset[a], dataset[b]).statistic)


def descargas_por_subida(dataset: pd.DataFrame) -> float:
    """Descargas que no son de usuario por cada día con un fichero nuevo.

    Mediana, en el primer mes, de (totales − de usuario) / subidas: lo que un
    paquete recibe de mirrors y bots solo por publicar, lo use alguien o no.
    """
    automaticas = dataset["total_30d"] - dataset["usuario_30d"]
    return float((automaticas / dataset["subidas_30d"]).median())


def pct_usuario(dataset: pd.DataFrame, dia: int = 30) -> pd.Series:
    """Fracción de las descargas que viene de instaladores de usuario."""
    return dataset[f"usuario_{dia}d"] / dataset[f"total_{dia}d"].replace(0, np.nan)


def efecto_grupos(dataset: pd.DataFrame) -> dict[str, float]:
    """ε² de Kruskal-Wallis de las descargas de usuario a 30 días por categoría
    y por tipo de propietario."""
    frecuentes = (
        dataset["categoria"]
        .value_counts()
        .loc[lambda s: s >= MIN_PAQUETES_CATEGORIA]
        .index
    )
    salida = {}
    for nombre, columna, datos in [
        ("categoria", "categoria", dataset[dataset["categoria"].isin(frecuentes)]),
        ("propietario", "propietario_tipo", dataset),
    ]:
        grupos = [g["usuario_30d"] for _, g in datos.groupby(columna)]
        h, _ = stats.kruskal(*grupos)
        salida[nombre] = round(float(epsilon_cuadrado(h, len(datos))), 3)
    return salida


def hallazgos(dataset: pd.DataFrame) -> dict[str, Any]:
    """Las cifras del EDA que se enseñan en la portada de la aplicación."""
    return {
        "spearman_7_30": round(spearman(dataset, "usuario_7d", "usuario_30d"), 2),
        "spearman_total_subidas": round(
            spearman(dataset, "total_30d", "subidas_30d"), 2
        ),
        "spearman_usuario_subidas": round(
            spearman(dataset, "usuario_30d", "subidas_30d"), 2
        ),
        "descargas_por_subida": round(descargas_por_subida(dataset), 1),
        "epsilon2": efecto_grupos(dataset),
    }
