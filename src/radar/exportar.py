"""Entrena los modelos y escribe los JSON que lee la aplicación (app/data).

Vercel no ejecuta Python, así que cada modelo se exporta como datos
(medianas de imputación, escalado, categorías y coeficientes o árboles) y
la app lo evalúa en TypeScript. `casos_dorados.json` guarda predicciones
hechas aquí para que los tests de la app comprueben que dan lo mismo.

Uso:
    python -m radar.exportar
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from radar import config, contraste, eda
from radar import modelo as m

logger = logging.getLogger("radar.exportar")

CUANTILES = [0.1, 0.25, 0.5, 0.75, 0.9]
MIN_COHORTE = (
    20  # por debajo, la cohorte de la categoría no es fiable: se usa la global
)
RUTA_CASOS_DORADOS = config.RAIZ / "app" / "tests" / "casos_dorados.json"
DIAS_CON_OBJETIVO = (*config.DIAS_LECTURA, config.DIAS_VENTANA)


def _redondear(valor: Any, cifras: int = 6) -> Any:
    if isinstance(valor, float | np.floating):
        return None if np.isnan(valor) else round(float(valor), cifras)
    if isinstance(valor, np.integer):
        return int(valor)
    if isinstance(valor, np.bool_):
        return bool(valor)
    if isinstance(valor, dict):
        return {k: _redondear(v, cifras) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_redondear(v, cifras) for v in valor]
    return valor


def _escribir(
    ruta: Path, contenido: Any, cifras: int = 6, indent: int | None = 1
) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(_redondear(contenido, cifras), ensure_ascii=False, indent=indent)
    ruta.write_text(texto, encoding="utf-8")
    logger.info("Escrito %s (%.0f KB)", ruta.name, ruta.stat().st_size / 1024)


def _cuantiles(serie: pd.Series) -> list[float]:
    return [float(serie.quantile(q)) for q in CUANTILES]


# --- serialización del modelo ----------------------------------------------


def serializar(res: m.Resultado) -> dict[str, Any]:
    """Describe el modelo elegido de forma que TypeScript pueda reproducirlo."""
    descripcion: dict[str, Any] = {
        "tipo": res.nombre,
        "numericas": res.variables.numericas,
        "categoricas": res.variables.categoricas,
        "categorias_modelo": res.categorias,
        "q90": res.q90,
        "metricas_test": res.test,
        "baselines_test": res.test_baselines,
        "cv_mae_log": res.cv.groupby("modelo")["mae_log"]
        .agg(["mean", "std"])
        .round(4)
        .to_dict("index"),
        "tamanos": res.tamanos,
    }
    modelo = res.modelo
    if res.nombre == "mediana":
        descripcion["mediana"] = modelo.valor_
        return descripcion
    if res.nombre == "ratio_tipico":
        descripcion["ratio"] = {
            "columna": modelo.columna,
            "desplazamiento": modelo.desplazamiento_,
        }
        return descripcion

    pre = modelo.named_steps["pre"]
    num = pre.named_transformers_["num"]
    numericas = res.variables.numericas
    descripcion["medianas"] = dict(
        zip(numericas, num.named_steps["imputar"].statistics_, strict=True)
    )
    if "escalar" in num.named_steps:
        escalador = num.named_steps["escalar"]
        descripcion["medias"] = dict(zip(numericas, escalador.mean_, strict=True))
        descripcion["escalas"] = dict(zip(numericas, escalador.scale_, strict=True))
    if res.variables.categoricas:
        codificador = pre.named_transformers_["cat"]
        descripcion["categorias"] = {
            col: [str(c) for c in cats]
            for col, cats in zip(
                res.variables.categoricas, codificador.categories_, strict=True
            )
        }

    estimador = modelo.named_steps["modelo"]
    if res.nombre == "ridge":
        descripcion["ridge"] = {
            "coef": estimador.coef_.tolist(),
            "intercepto": estimador.intercept_,
        }
    else:
        descripcion["gb"] = {
            "inicial": float(estimador.init_.constant_.ravel()[0]),
            "tasa": estimador.learning_rate,
            "arboles": [
                {
                    "izq": arbol.tree_.children_left.tolist(),
                    "der": arbol.tree_.children_right.tolist(),
                    "variable": arbol.tree_.feature.tolist(),
                    "umbral": arbol.tree_.threshold.tolist(),
                    "valor": arbol.tree_.value[:, 0, 0].tolist(),
                }
                for arbol in estimador.estimators_.ravel()
            ],
        }
    return descripcion


# --- tablas de referencia ---------------------------------------------------


def cohortes(train: pd.DataFrame) -> dict[str, Any]:
    """Descargas de usuario por día de lectura, global y por categoría.

    Se calcula solo con el train, igual que el modelo: un paquete del test no
    se compara contra una cohorte que lo incluye a él.
    """
    salida: dict[str, Any] = {
        "cuantiles": CUANTILES,
        "n_global": len(train),
        "global": {
            str(k): _cuantiles(train[f"usuario_{k}d"]) for k in DIAS_CON_OBJETIVO
        },
        "por_categoria": {},
    }
    for categoria, grupo in train.groupby("categoria"):
        if len(grupo) >= MIN_COHORTE:
            salida["por_categoria"][categoria] = {
                "n": len(grupo),
                **{
                    str(k): _cuantiles(grupo[f"usuario_{k}d"])
                    for k in DIAS_CON_OBJETIVO
                },
            }
    return salida


def _tabla_diaria(
    diarias: pd.DataFrame, columna: str, paquetes: pd.Series | None = None
) -> pd.DataFrame:
    """Paquetes × días 0-29 con las descargas de `columna` (0 si no hubo)."""
    ventana = diarias[diarias["dia"].between(0, config.DIAS_VENTANA - 1)]
    if paquetes is not None:
        ventana = ventana[ventana["paquete"].isin(paquetes)]
    tabla = ventana.pivot_table(
        index="paquete", columns="dia", values=columna, aggfunc="sum"
    )
    return tabla.reindex(columns=range(config.DIAS_VENTANA), fill_value=0).fillna(0)


def curva_tipica(
    diarias: pd.DataFrame, paquetes: pd.Series, columna: str = "usuario"
) -> list[float]:
    """Mediana de la fracción acumulada de las descargas a 30 días, día a día."""
    acumulada = _tabla_diaria(diarias, columna, paquetes).cumsum(axis=1)
    fraccion = acumulada.div(
        acumulada[config.DIAS_VENTANA - 1].replace(0, np.nan), axis=0
    )
    return fraccion.median().round(4).tolist()


def ejemplos(test: pd.DataFrame, diarias: pd.DataFrame) -> list[dict[str, Any]]:
    """Paquetes del test (no vistos al entrenar) para probar el radar con datos reales."""
    tablas = {c: _tabla_diaria(diarias, c) for c in ("usuario", "total")}
    filas = []
    for _, paquete in test.iterrows():
        acumuladas = {}
        for columna, tabla in tablas.items():
            if paquete["paquete"] in tabla.index:
                diario = tabla.loc[paquete["paquete"]]
            else:
                diario = pd.Series(0, index=range(config.DIAS_VENTANA))
            acumuladas[columna] = diario.cumsum().astype(int).tolist()
        filas.append(
            {
                "paquete": paquete["paquete"],
                "nombre": paquete["nombre"],
                "fecha_lanzamiento": paquete["fecha_lanzamiento"].date().isoformat(),
                "categoria": paquete["categoria"],
                "propietario_tipo": paquete["propietario_tipo"],
                "dependencias": int(paquete["dependencias"]),
                "estrellas": int(paquete["estrellas"]),
                "lecturas": {
                    str(k): {
                        "usuario": int(paquete[f"usuario_{k}d"]),
                        "total": int(paquete[f"total_{k}d"]),
                        "subidas": int(paquete[f"subidas_{k}d"]),
                    }
                    for k in config.DIAS_LECTURA
                },
                "usuario_30d": int(paquete["usuario_30d"]),
                "total_30d": int(paquete["total_30d"]),
                "acumuladas": acumuladas["usuario"],
                "acumuladas_total": acumuladas["total"],
            }
        )
    return filas


def benchmark(dataset: pd.DataFrame) -> dict[str, Any]:
    """Descargas de usuario a 30 días por categoría y tipo de propietario."""

    def resumen(grupo: pd.DataFrame) -> dict[str, Any]:
        return {"n": len(grupo), "cuantiles": _cuantiles(grupo["usuario_30d"])}

    return {
        "cuantiles": CUANTILES,
        "global": resumen(dataset),
        "por_categoria": [
            {"categoria": c, **resumen(x)} for c, x in dataset.groupby("categoria")
        ],
        "por_propietario": [
            {"propietario_tipo": p, **resumen(x)}
            for p, x in dataset.groupby("propietario_tipo")
        ],
        "categoria_propietario": [
            {"categoria": c, "propietario_tipo": p, **resumen(x)}
            for (c, p), x in dataset.groupby(["categoria", "propietario_tipo"])
        ],
    }


def exclusiones_del_embudo(embudo: dict[str, int]) -> dict[str, int]:
    """Motivos de exclusión con su cuenta, derivados de los pasos del embudo.

    El embudo recorre la muestra completa, incluidos los paquetes sin
    repositorio o con pocas estrellas, que no llegan a `paquetes.csv`. Por eso
    los motivos se leen de ahí y no del CSV: sumados con los aptos dan el total
    de la muestra. Los motivos sin casos no se listan.
    """
    pasos = list(embudo.items())
    return {
        nombre.removeprefix("tras_"): anterior - actual
        for (_, anterior), (nombre, actual) in zip(pasos, pasos[1:], strict=False)
        if nombre.startswith("tras_") and (anterior - actual) > 0
    }


def resumen_mercado(
    dataset: pd.DataFrame,
    diarias: pd.DataFrame,
    embudo: dict[str, int],
) -> dict[str, Any]:
    """Indicadores del panel: muestra, exclusiones, ruido y ritmo de descargas."""
    por_mes = dataset.groupby(dataset["fecha_lanzamiento"].dt.to_period("M")).agg(
        lanzamientos=("paquete", "size"), mediana_30d=("usuario_30d", "median")
    )

    def por(columna: str) -> list[dict[str, Any]]:
        return [
            {
                columna: valor,
                "n": len(x),
                "mediana_30d": float(x["usuario_30d"].median()),
            }
            for valor, x in dataset.groupby(columna)
        ]

    total_30 = dataset["total_30d"].replace(0, np.nan)
    return {
        "embudo": embudo,
        "paquetes_candidatos": embudo["con_enlace_a_github"],
        "paquetes_aptos": len(dataset),
        "exclusiones": exclusiones_del_embudo(embudo),
        "rango_lanzamientos": {
            "desde": dataset["fecha_lanzamiento"].min().date().isoformat(),
            "hasta": dataset["fecha_lanzamiento"].max().date().isoformat(),
        },
        "mediana_usuario_30d": float(dataset["usuario_30d"].median()),
        "mediana_total_30d": float(dataset["total_30d"].median()),
        "mediana_pct_usuario_30d": float((dataset["usuario_30d"] / total_30).median()),
        "fraccion_mediana_del_mes": {
            str(k): float(
                (
                    dataset[f"usuario_{k}d"] / dataset["usuario_30d"].replace(0, np.nan)
                ).median()
            )
            for k in config.DIAS_LECTURA
        },
        "por_mes": [
            {
                "mes": str(periodo),
                "lanzamientos": int(fila["lanzamientos"]),
                "mediana_30d": float(fila["mediana_30d"]),
            }
            for periodo, fila in por_mes.iterrows()
        ],
        "por_categoria": por("categoria"),
        "por_propietario": por("propietario_tipo"),
        "curva_tipica": curva_tipica(diarias, dataset["paquete"]),
        "curva_tipica_total": curva_tipica(diarias, dataset["paquete"], "total"),
        "hallazgos": eda.hallazgos(dataset),
        "contraste_estrellas": contraste.resumen(dataset),
    }


def cohorte_de(categoria: str, tabla_cohortes: dict[str, Any]) -> dict[str, Any]:
    """Cohorte de la categoría si tiene una propia; si no, toda la muestra.

    Misma regla que `cohorte()` en app/src/lib/radar.ts: no depende de las
    categorías que distingue el modelo, solo de que la categoría tenga cohorte.
    """
    return tabla_cohortes["por_categoria"].get(categoria, tabla_cohortes["global"])


def _posicion(valor: float, q25: float, q75: float) -> str:
    if valor > q75:
        return "por_encima"
    if valor < q25:
        return "por_debajo"
    return "en_linea"


def aciertos_veredicto(
    radar: dict[int, m.Resultado], test: pd.DataFrame, tabla_cohortes: dict[str, Any]
) -> dict[str, Any]:
    """¿Acierta el veredicto? Cada paquete del test, leído como lo haría la app.

    El veredicto se calcula igual que en app/src/lib/radar.ts: el rango del
    90 % (con el mínimo de las descargas que ya tiene) frente al primer y
    tercer cuartil de su cohorte a 30 días. Se compara con dónde acabó de
    verdad el paquete en esa misma cohorte.

    `ya_superaba` cuenta los «por encima» en los que el paquete, el día de la
    lectura, ya tenía más descargas que el tercer cuartil a 30 días: esos
    aciertan sin que el modelo aporte nada, porque las descargas solo suben.
    """
    i25, i75 = CUANTILES.index(0.25), CUANTILES.index(0.75)
    salida: dict[str, Any] = {}
    for dia, res in radar.items():
        log = predecir_python(res, test)
        lectura = test[f"usuario_{dia}d"].to_numpy(float)
        inferior = np.maximum(lectura, np.expm1(log - res.q90))
        superior = np.maximum(lectura, np.expm1(log + res.q90))
        cuentas: dict[str, dict[str, int]] = {}
        for categoria, hoy, inf, sup, real in zip(
            test["categoria"],
            lectura,
            inferior,
            superior,
            test["usuario_30d"],
            strict=True,
        ):
            cohorte = cohorte_de(categoria, tabla_cohortes)
            q25, q75 = cohorte["30"][i25], cohorte["30"][i75]
            if sup < q25:
                veredicto = "por_debajo"
            elif inf > q75:
                veredicto = "por_encima"
            else:
                veredicto = "en_linea"
            fila = cuentas.setdefault(
                veredicto,
                {"por_encima": 0, "en_linea": 0, "por_debajo": 0, "ya_superaba": 0},
            )
            fila[_posicion(real, q25, q75)] += 1
            fila["ya_superaba"] += int(veredicto == "por_encima" and hoy > q75)
        salida[str(dia)] = cuentas
    return salida


# --- casos dorados para los tests de la app ---------------------------------


def predecir_python(res: m.Resultado, entrada: pd.DataFrame) -> np.ndarray:
    x = m.preparar_variables(entrada, res.categorias)[res.variables.todas]
    return res.modelo.predict(x)


def entradas_app(df: pd.DataFrame, dia: int | None) -> list[dict[str, Any]]:
    """La misma entrada que manda el formulario de la app."""
    filas = []
    for _, paquete in df.iterrows():
        fila: dict[str, Any] = {
            "categoria": paquete["categoria"],
            "propietario_tipo": paquete["propietario_tipo"],
            "dependencias": int(paquete["dependencias"]),
        }
        if dia is not None:
            fila |= {
                "dia": dia,
                "usuario": int(paquete[f"usuario_{dia}d"]),
                "total": int(paquete[f"total_{dia}d"]),
                "subidas": int(paquete[f"subidas_{dia}d"]),
            }
        else:
            anios = paquete["anios_cuenta"]
            fila |= {
                "anios_cuenta": None if pd.isna(anios) else float(anios),
                "dias_repo_previos": int(paquete["dias_repo_previos"]),
                "mes_lanzamiento": int(paquete["mes_lanzamiento"]),
            }
        filas.append(fila)
    return filas


def casos_dorados(
    radar: dict[int, m.Resultado], previo: m.Resultado, test: pd.DataFrame
) -> list[dict[str, Any]]:
    casos = []
    for dia, res in radar.items():
        casos += [
            {"modelo": f"radar_{dia}", "entrada": fila, "esperado": float(pred)}
            for fila, pred in zip(
                entradas_app(test, dia), predecir_python(res, test), strict=True
            )
        ]
    casos += [
        {"modelo": "previo", "entrada": fila, "esperado": float(pred)}
        for fila, pred in zip(
            entradas_app(test, None), predecir_python(previo, test), strict=True
        )
    ]
    return casos


# --- orquestación -----------------------------------------------------------


def cargar_procesados(
    carpeta: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    rutas = {
        nombre: carpeta / f"{nombre}.csv"
        for nombre in ("dataset_radar", "paquetes", "descargas_diarias")
    }
    rutas["embudo"] = carpeta / "embudo.json"
    faltan = [str(r) for r in rutas.values() if not r.exists()]
    if faltan:
        raise FileNotFoundError(
            f"Faltan {', '.join(faltan)}: ejecuta antes python -m radar.preparacion."
        )
    dataset = pd.read_csv(rutas["dataset_radar"], parse_dates=["fecha_lanzamiento"])
    paquetes = pd.read_csv(rutas["paquetes"], parse_dates=["fecha_lanzamiento"])
    diarias = pd.read_csv(rutas["descargas_diarias"])
    embudo = json.loads(rutas["embudo"].read_text(encoding="utf-8"))
    return dataset, paquetes, diarias, embudo


def exportar(carpeta_procesados: Path, carpeta_salida: Path, ruta_casos: Path) -> int:
    """Entrena, escribe los tres JSON de la app y los casos dorados; devuelve cuántos."""
    dataset, _, diarias, embudo = cargar_procesados(carpeta_procesados)
    train, _, test = m.particion_temporal(dataset)

    radar = {
        dia: m.entrenar(
            dataset, m.variables_radar(dia), columna_ratio=f"log_usuario_{dia}d"
        )
        for dia in config.DIAS_LECTURA
    }
    previo = m.entrenar(dataset, m.VARIABLES_PREVIAS)
    generado = datetime.now(UTC).isoformat(timespec="seconds")
    curvas = {"global": curva_tipica(diarias, train["paquete"])}
    for categoria, grupo in train.groupby("categoria"):
        if len(grupo) >= MIN_COHORTE:
            curvas[categoria] = curva_tipica(diarias, grupo["paquete"])

    tabla_cohortes = cohortes(train)
    _escribir(
        carpeta_salida / "radar.json",
        {
            "generado_en": generado,
            "dias_lectura": list(config.DIAS_LECTURA),
            "modelos": {str(dia): serializar(res) for dia, res in radar.items()},
            "cohortes": tabla_cohortes,
            "aciertos_veredicto": aciertos_veredicto(radar, test, tabla_cohortes),
            "curva_tipica": curvas,
            "ejemplos": ejemplos(test, diarias),
        },
    )
    _escribir(
        carpeta_salida / "previo.json",
        {"generado_en": generado, "modelo": serializar(previo), **benchmark(dataset)},
    )
    _escribir(
        carpeta_salida / "mercado.json",
        {
            "generado_en": generado,
            **resumen_mercado(dataset, diarias, embudo),
        },
    )
    casos = casos_dorados(radar, previo, test)
    _escribir(ruta_casos, casos, cifras=10, indent=None)
    return len(casos)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        n = exportar(config.DIR_PROCESADO, config.DIR_APP_DATOS, RUTA_CASOS_DORADOS)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Casos dorados: %d", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
