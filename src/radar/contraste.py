"""Contraste de las descargas con las estrellas del repositorio en GitHub.

Las descargas de usuario son la métrica del radar, pero un contador propio
siempre deja la duda de si mide lo que dice. Las estrellas son la otra cifra
pública de popularidad de un proyecto open source y no dependen de PyPI: si
las dos ordenan los paquetes de forma parecida, las descargas de usuario
miden algo real. Donde no coinciden está lo interesante: proyectos con mucha
atención y poco uso, o librerías que se instalan mucho sin que nadie las
marque con una estrella.

Las estrellas son las de hoy, no las del día 30 (GitHub ya no publica cuándo
se dio cada una), así que el contraste es de orden de magnitud y no entra en
el modelo. Solo se usa un paquete por repositorio: en un monorepo todos los
paquetes comparten las mismas estrellas.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

MIN_REPOS_CATEGORIA = 30
EXTREMOS = 5
# Para los extremos: proyectos con atención o uso suficientes para que el
# desajuste no sea ruido de cifras pequeñas.
ESTRELLAS_MIN_EXTREMO = 500
USUARIO_MIN_EXTREMO = 5_000


def un_paquete_por_repo(dataset: pd.DataFrame) -> pd.DataFrame:
    """Sin repositorios compartidos: sus estrellas no son de un solo paquete."""
    return dataset[~dataset["repo_compartido"].astype(bool)]


def _extremos(df: pd.DataFrame, columna: str) -> list[dict[str, Any]]:
    filas = df.nlargest(EXTREMOS, columna)
    return [
        {
            "paquete": f.paquete,
            "repo": f.repo,
            "estrellas": int(f.estrellas),
            "usuario_30d": int(f.usuario_30d),
        }
        for f in filas.itertuples()
    ]


def resumen(dataset: pd.DataFrame) -> dict[str, Any]:
    """Correlación de rangos, descargas por estrella y los casos más desajustados."""
    df = un_paquete_por_repo(dataset).copy()
    rho = float(stats.spearmanr(df["estrellas"], df["usuario_30d"]).statistic)
    por_estrella = df["usuario_30d"] / df["estrellas"]
    # Residuo de la recta en log: positivo = más uso del que «tocaría» por sus
    # estrellas; negativo = más estrellas que uso.
    x, y = np.log1p(df["estrellas"]), np.log1p(df["usuario_30d"])
    pendiente, corte = np.polyfit(x, y, 1)
    df["residuo"] = y - (pendiente * x + corte)

    por_categoria = []
    for categoria, grupo in df.groupby("categoria"):
        if len(grupo) >= MIN_REPOS_CATEGORIA:
            por_categoria.append(
                {
                    "categoria": categoria,
                    "repos": len(grupo),
                    "spearman": round(
                        float(
                            stats.spearmanr(
                                grupo["estrellas"], grupo["usuario_30d"]
                            ).statistic
                        ),
                        2,
                    ),
                }
            )
    atencion = df[df["estrellas"] >= ESTRELLAS_MIN_EXTREMO].assign(
        desajuste=lambda d: -d["residuo"]
    )
    uso = df[df["usuario_30d"] >= USUARIO_MIN_EXTREMO].assign(
        desajuste=lambda d: d["residuo"]
    )
    return {
        "repos": len(df),
        "spearman": round(rho, 2),
        "descargas_por_estrella": {
            "mediana": round(float(por_estrella.median()), 2),
            "q25": round(float(por_estrella.quantile(0.25)), 2),
            "q75": round(float(por_estrella.quantile(0.75)), 2),
        },
        "por_categoria": por_categoria,
        "mas_estrellas_que_uso": _extremos(atencion, "desajuste"),
        "mas_uso_que_estrellas": _extremos(uso, "desajuste"),
    }
