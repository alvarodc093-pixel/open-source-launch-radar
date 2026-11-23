"""Panel de Power BI: tablas en estrella y proyecto .pbip que las lee.

Genera dos cosas:

- `powerbi/datos/`: seis CSV en estrella. `paquetes` (una fila por paquete
  candidato), `calendario` y `lecturas` (días 7, 14 y 21, y 0 para «antes de
  lanzar») como dimensiones; `curva_diaria` (el primer mes de cada paquete
  apto, día a día, con descargas de usuario y totales), `predicciones` (lo que
  estimó el radar para cada paquete del test frente a lo que pasó) y
  `metricas` (los candidatos de cada modelo en test) como hechos.
- `powerbi/OpenSourceLaunchRadar.*`: el proyecto de Power BI en formato de
  texto (modelo semántico en TMDL e informe en PBIR), que se abre con Power BI
  Desktop desde `OpenSourceLaunchRadar.pbip`.

Las consultas leen los CSV de la rama principal del repositorio en GitHub, así
que el informe se actualiza con un clic cuando llegan datos nuevos. El
parámetro `OrigenDatos` admite también una carpeta local.

Si el proyecto se abre y se guarda con Power BI Desktop, Desktop añade sus
propios metadatos. Por eso, sin `--proyecto`, solo se escriben los CSV:
regenerar el proyecto descartaría lo guardado en Desktop.

Uso:
    python -m radar.powerbi              # solo los datos (actualización mensual)
    python -m radar.powerbi --proyecto   # datos y proyecto desde cero
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from radar import config
from radar import modelo as m
from radar.exportar import cargar_procesados, predecir_python

logger = logging.getLogger("radar.powerbi")

DIR_POWERBI = config.RAIZ / "powerbi"
NOMBRE = "OpenSourceLaunchRadar"
ORIGEN_GITHUB = (
    "https://raw.githubusercontent.com/alvarodc093-pixel/open-source-launch-radar/"
    "main/powerbi/datos/"
)

ESTADOS = {
    "apto": "Apto",
    "republicado": "Copia de un proyecto ajeno",
    "repo_fork": "Repositorio fork",
    "sin_descargas": "Sin descargas",
    "mes_incompleto": "Primer mes sin cerrar",
    "versiones_previas_borradas": "Versiones anteriores borradas",
    "proyecto_anterior": "Proyecto anterior a PyPI",
}
MODELOS = {
    "mediana": "Mediana (baseline)",
    "ratio_tipico": "Ratio típico",
    "ridge": "Ridge",
    "gradient_boosting": "Gradient boosting",
}


# --- tablas ------------------------------------------------------------------


def tabla_paquetes(paquetes: pd.DataFrame, dataset: pd.DataFrame) -> pd.DataFrame:
    train, calib, test = m.particion_temporal(dataset)
    conjunto = {
        **dict.fromkeys(train["paquete"], "Entrenamiento"),
        **dict.fromkeys(calib["paquete"], "Calibración"),
        **dict.fromkeys(test["paquete"], "Test"),
    }
    usuario = paquetes["usuario_30d"].fillna(0)
    total = paquetes["total_30d"].fillna(0)
    t = pd.DataFrame(
        {
            "paquete": paquetes["paquete"],
            "nombre": paquetes["nombre"],
            "repo": paquetes["repo"],
            "fecha_lanzamiento": paquetes["fecha_lanzamiento"].dt.strftime("%Y-%m-%d"),
            "categoria": paquetes["categoria"],
            "propietario_tipo": paquetes["propietario_tipo"],
            "estrellas": paquetes["estrellas"].fillna(0).astype(int),
            "estado": paquetes["estado"],
            "estado_descripcion": paquetes["estado"]
            .map(ESTADOS)
            .fillna(paquetes["estado"]),
            "usuario_30d": usuario.astype(int),
            "total_30d": total.astype(int),
            "pct_usuario_30d": (usuario / total.replace(0, np.nan)).round(4),
            "subidas_30d": paquetes["subidas_30d"].fillna(0).astype(int),
            "conjunto": paquetes["paquete"].map(conjunto).fillna("Excluido"),
        }
    )
    return t.sort_values("paquete")


def tabla_calendario(paquetes: pd.DataFrame) -> pd.DataFrame:
    inicio = paquetes["fecha_lanzamiento"].min().replace(day=1)
    fin = paquetes["fecha_lanzamiento"].max() + pd.offsets.MonthEnd(0)
    fechas = pd.date_range(inicio, fin, freq="D")
    return pd.DataFrame(
        {
            "fecha": fechas.strftime("%Y-%m-%d"),
            "anio": fechas.year,
            "mes": fechas.strftime("%Y-%m"),
            "trimestre": [f"{f.year} T{f.quarter}" for f in fechas],
            "dia_semana": fechas.dayofweek + 1,
        }
    )


def tabla_curva(diarias: pd.DataFrame, dataset: pd.DataFrame) -> pd.DataFrame:
    """Primer mes de cada paquete apto: descargas por día, acumuladas y fracción.

    `dia` cuenta los días transcurridos (1 = el de la primera subida), igual que
    el eje de la app: el «día 7» incluye las descargas de los días 0 a 6.
    """
    aptos = dataset[["paquete", "usuario_30d", "total_30d"]]
    mes = diarias[(diarias["dia"] >= 0) & (diarias["dia"] < config.DIAS_VENTANA)]
    rejilla = pd.MultiIndex.from_product(
        [aptos["paquete"], range(config.DIAS_VENTANA)], names=["paquete", "dia"]
    ).to_frame(index=False)
    t = rejilla.merge(mes[["paquete", "dia", "usuario", "total"]], how="left")
    t[["usuario", "total"]] = t[["usuario", "total"]].fillna(0).astype(int)
    t["usuario_acumulado"] = t.groupby("paquete")["usuario"].cumsum()
    t["total_acumulado"] = t.groupby("paquete")["total"].cumsum()
    t = t.merge(aptos, on="paquete")
    t["fraccion_mes"] = (
        t["usuario_acumulado"] / t["usuario_30d"].replace(0, np.nan)
    ).round(4)
    t["fraccion_mes_total"] = (
        t["total_acumulado"] / t["total_30d"].replace(0, np.nan)
    ).round(4)
    t["dia"] += 1
    return t[
        [
            "paquete",
            "dia",
            "usuario",
            "total",
            "usuario_acumulado",
            "total_acumulado",
            "fraccion_mes",
            "fraccion_mes_total",
        ]
    ]


def tablas_modelo(dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Predicciones del radar en test y métricas de todos los candidatos."""
    _, _, test = m.particion_temporal(dataset)
    real = test["usuario_30d"].to_numpy(float)
    predicciones, metricas = [], []

    def filas_metricas(dia: int, res: m.Resultado) -> None:
        for nombre, valores in [(res.nombre, res.test), *res.test_baselines.items()]:
            metricas.append(
                {
                    "dia_lectura": dia,
                    "modelo": MODELOS[nombre],
                    "elegido": "Sí" if nombre == res.nombre else "No",
                    "mae_log": valores["mae_log"],
                    "factor_error": valores["factor_error_tipico"],
                    "dentro_x2": valores["dentro_de_x2"],
                    "cv_mae_log": round(
                        float(res.cv.loc[res.cv["modelo"] == nombre, "mae_log"].mean()),
                        4,
                    ),
                }
            )

    for dia in config.DIAS_LECTURA:
        res = m.entrenar(
            dataset, m.variables_radar(dia), columna_ratio=f"log_usuario_{dia}d"
        )
        filas_metricas(dia, res)
        log = predecir_python(res, test)
        lectura = test[f"usuario_{dia}d"].to_numpy(float)
        # Igual que la app: al mes no puede haber menos de lo que ya hay hoy.
        central = np.maximum(lectura, np.expm1(log))
        inferior = np.maximum(lectura, np.expm1(log - res.q90))
        superior = np.maximum(lectura, np.expm1(log + res.q90))
        error = np.abs(np.log1p(real) - log)
        predicciones.append(
            pd.DataFrame(
                {
                    "paquete": test["paquete"].to_numpy(),
                    "dia_lectura": dia,
                    "usuario_lectura": lectura.astype(int),
                    "estimacion": central.round(1),
                    "rango_inferior": inferior.round(1),
                    "rango_superior": superior.round(1),
                    "usuario_30d_reales": real.astype(int),
                    "error_log": error.round(4),
                    "dentro_rango": (error <= res.q90).astype(int),
                }
            )
        )
    filas_metricas(0, m.entrenar(dataset, m.VARIABLES_PREVIAS))
    return pd.concat(predicciones, ignore_index=True), pd.DataFrame(metricas)


def tabla_lecturas() -> pd.DataFrame:
    dias = [0, *config.DIAS_LECTURA]
    return pd.DataFrame(
        {
            "dia_lectura": dias,
            "lectura": ["Antes de lanzar", *(f"Día {d}" for d in config.DIAS_LECTURA)],
        }
    )


def escribir_datos(carpeta: Path) -> dict[str, pd.DataFrame]:
    dataset, paquetes, diarias, _ = cargar_procesados(config.DIR_PROCESADO)
    predicciones, metricas = tablas_modelo(dataset)
    tablas = {
        "paquetes": tabla_paquetes(paquetes, dataset),
        "calendario": tabla_calendario(paquetes),
        "lecturas": tabla_lecturas(),
        "curva_diaria": tabla_curva(diarias, dataset),
        "predicciones": predicciones,
        "metricas": metricas,
    }
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, tabla in tablas.items():
        tabla.to_csv(carpeta / f"{nombre}.csv", index=False, encoding="utf-8")
        logger.info("Escrito %s.csv (%d filas)", nombre, len(tabla))
    return tablas


# --- modelo semántico (TMDL) -----------------------------------------------


def _id(*partes: str) -> str:
    """Identificador estable: regenerar el proyecto no cambia los lineageTag."""
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, "open-source-launch-radar/" + "/".join(partes))
    )


@dataclass
class Columna:
    nombre: str
    tipo: str  # int64, double, string, dateTime
    formato: str | None = None
    ordenar_por: str | None = None
    oculta: bool = False
    clave: bool = False  # la clave de la tabla de fechas


@dataclass
class Medida:
    nombre: str
    dax: str
    formato: str
    descripcion: str


M_TIPOS = {
    "int64": "Int64.Type",
    "double": "type number",
    "string": "type text",
    "dateTime": "type date",
}

COLUMNAS: dict[str, list[Columna]] = {
    "paquetes": [
        Columna("paquete", "string"),
        Columna("nombre", "string"),
        Columna("repo", "string"),
        Columna("fecha_lanzamiento", "dateTime", "dd/mm/yyyy"),
        Columna("categoria", "string"),
        Columna("propietario_tipo", "string"),
        Columna("estrellas", "int64", "#,0"),
        Columna("estado", "string"),
        Columna("estado_descripcion", "string"),
        Columna("usuario_30d", "int64", "#,0"),
        Columna("total_30d", "int64", "#,0"),
        Columna("pct_usuario_30d", "double", "0.0 %"),
        Columna("subidas_30d", "int64", "0"),
        Columna("conjunto", "string"),
    ],
    "calendario": [
        Columna("fecha", "dateTime", "dd/mm/yyyy", clave=True),
        Columna("anio", "int64", "0"),
        Columna("mes", "string"),
        Columna("trimestre", "string"),
        Columna("dia_semana", "int64", "0"),
    ],
    "lecturas": [
        Columna("dia_lectura", "int64", "0", oculta=True),
        Columna("lectura", "string", ordenar_por="dia_lectura"),
    ],
    "curva_diaria": [
        Columna("paquete", "string", oculta=True),
        Columna("dia", "int64", "0"),
        Columna("usuario", "int64", "#,0"),
        Columna("total", "int64", "#,0"),
        Columna("usuario_acumulado", "int64", "#,0"),
        Columna("total_acumulado", "int64", "#,0"),
        Columna("fraccion_mes", "double", "0 %"),
        Columna("fraccion_mes_total", "double", "0 %"),
    ],
    "predicciones": [
        Columna("paquete", "string", oculta=True),
        Columna("dia_lectura", "int64", "0", oculta=True),
        Columna("usuario_lectura", "int64", "#,0"),
        Columna("estimacion", "double", "#,0"),
        Columna("rango_inferior", "double", "#,0"),
        Columna("rango_superior", "double", "#,0"),
        Columna("usuario_30d_reales", "int64", "#,0"),
        Columna("error_log", "double", "0.000"),
        Columna("dentro_rango", "int64", "0"),
    ],
    "metricas": [
        Columna("dia_lectura", "int64", "0", oculta=True),
        Columna("modelo", "string"),
        Columna("elegido", "string"),
        Columna("mae_log", "double", "0.000"),
        Columna("factor_error", "double", "0.00"),
        Columna("dentro_x2", "double", "0 %"),
        Columna("cv_mae_log", "double", "0.000"),
    ],
}

# La lectura elegida en el segmentador, o la del día 7 si no hay ninguna: así
# las tarjetas y el gráfico de dispersión no mezclan las tres lecturas.
_LECTURA = "VAR d = SELECTEDVALUE(lecturas[dia_lectura], 7)\n"
_APTOS = 'paquetes[estado] = "apto"'

MEDIDAS: dict[str, list[Medida]] = {
    "paquetes": [
        Medida(
            "Candidatos",
            "COUNTROWS(paquetes)",
            "#,0",
            "Paquetes nuevos de PyPI con un repositorio de 10 estrellas o más.",
        ),
        Medida(
            "Lanzamientos aptos",
            f"CALCULATE(COUNTROWS(paquetes), {_APTOS})",
            "#,0",
            "Paquetes que entran en el modelo tras la limpieza.",
        ),
        Medida(
            "% excluidos",
            "DIVIDE([Candidatos] - [Lanzamientos aptos], [Candidatos])",
            "0.0 %",
            "Parte de los candidatos que se excluye en el preprocesamiento.",
        ),
        Medida(
            "Mediana descargas de usuario 30 días",
            f"CALCULATE(MEDIAN(paquetes[usuario_30d]), {_APTOS})",
            "#,0",
            "Descargas de pip, uv, poetry… en el primer mes del paquete mediano.",
        ),
        Medida(
            "Mediana descargas totales 30 días",
            f"CALCULATE(MEDIAN(paquetes[total_30d]), {_APTOS})",
            "#,0",
            "Descargas con mirrors y bots en el primer mes del paquete mediano.",
        ),
        Medida(
            "% de usuario (mediana)",
            f"CALCULATE(MEDIAN(paquetes[pct_usuario_30d]), {_APTOS})",
            "0.0 %",
            "Parte de las descargas del primer mes que viene de usuarios.",
        ),
        Medida(
            "Mediana estrellas",
            f"CALCULATE(MEDIAN(paquetes[estrellas]), {_APTOS})",
            "#,0",
            "Estrellas de hoy del repositorio del paquete mediano.",
        ),
    ],
    "curva_diaria": [
        Medida(
            "% del mes recibido",
            "MEDIAN(curva_diaria[fraccion_mes])",
            "0 %",
            "Parte de las descargas de usuario del mes que ya ha llegado (mediana).",
        ),
        Medida(
            "% del mes recibido (totales)",
            "MEDIAN(curva_diaria[fraccion_mes_total])",
            "0 %",
            "Lo mismo con las descargas totales, que saltan el día de cada subida.",
        ),
        *(
            Medida(
                f"Recibido día {d}",
                f"CALCULATE([% del mes recibido], curva_diaria[dia] = {d})",
                "0 %",
                f"Parte del mes que ya ha llegado el día {d} (paquete mediano).",
            )
            for d in config.DIAS_LECTURA
        ),
    ],
    "predicciones": [
        Medida(
            "Paquetes de test",
            "DISTINCTCOUNT(predicciones[paquete])",
            "#,0",
            "Lanzamientos más recientes, que el modelo no vio al entrenar.",
        ),
        Medida(
            "Factor de error típico",
            _LECTURA + "RETURN CALCULATE(EXP(MEDIAN(predicciones[error_log])), "
            "lecturas[dia_lectura] = d)",
            "0.00",
            "exp(mediana del error en log): ×1,36 es un 36 % de desviación.",
        ),
        Medida(
            "Cobertura del rango",
            _LECTURA + "RETURN CALCULATE(AVERAGE(predicciones[dentro_rango]), "
            "lecturas[dia_lectura] = d)",
            "0 %",
            "Paquetes cuyo valor real cae dentro del rango del 90 %.",
        ),
        Medida(
            "Dentro de x2",
            _LECTURA + "RETURN CALCULATE(AVERAGEX(predicciones, "
            "IF(predicciones[error_log] <= LN(2), 1, 0)), lecturas[dia_lectura] = d)",
            "0 %",
            "Estimaciones entre la mitad y el doble del valor real.",
        ),
        Medida(
            "Estimación",
            _LECTURA + "RETURN CALCULATE(AVERAGE(predicciones[estimacion]), "
            "lecturas[dia_lectura] = d)",
            "#,0",
            "Descargas de usuario a 30 días que estimó el radar.",
        ),
        Medida(
            "Descargas reales",
            _LECTURA + "RETURN CALCULATE(AVERAGE(predicciones[usuario_30d_reales]), "
            "lecturas[dia_lectura] = d)",
            "#,0",
            "Descargas de usuario que tuvo de verdad al cumplir 30 días.",
        ),
    ],
    "metricas": [
        Medida(
            "Factor de error en test",
            _LECTURA + "RETURN CALCULATE(AVERAGE(metricas[factor_error]), "
            "lecturas[dia_lectura] = d)",
            "0.00",
            "Factor de error típico de cada candidato en test.",
        ),
    ],
}

TABLA_FECHAS = "calendario"

RELACIONES = [
    ("paquetes", "fecha_lanzamiento", "calendario", "fecha"),
    ("curva_diaria", "paquete", "paquetes", "paquete"),
    ("predicciones", "paquete", "paquetes", "paquete"),
    ("predicciones", "dia_lectura", "lecturas", "dia_lectura"),
    ("metricas", "dia_lectura", "lecturas", "dia_lectura"),
]


def _sangrar(texto: str, tabs: int) -> str:
    return "\n".join("\t" * tabs + linea for linea in texto.splitlines())


def consulta_m(tabla: str, columnas: list[Columna]) -> str:
    tipos = ", ".join(f'{{"{c.nombre}", {M_TIPOS[c.tipo]}}}' for c in columnas)
    return "\n".join(
        [
            "let",
            f'    Ruta = OrigenDatos & "{tabla}.csv",',
            '    Contenido = if Text.StartsWith(Ruta, "http") then Web.Contents(Ruta)'
            " else File.Contents(Ruta),",
            '    Origen = Csv.Document(Contenido, [Delimiter = ",", Encoding = 65001,'
            " QuoteStyle = QuoteStyle.Csv]),",
            "    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars = true]),",
            # Cultura fija: los decimales del CSV llevan punto en cualquier equipo.
            f'    Tipos = Table.TransformColumnTypes(Encabezados, {{{tipos}}}, "en-US")',
            "in",
            "    Tipos",
        ]
    )


def tmdl_tabla(tabla: str) -> str:
    lineas = [f"table {tabla}"]
    if tabla == TABLA_FECHAS:
        # Marcada como tabla de fechas: Power BI no crea las suyas automáticas.
        lineas.append("\tdataCategory: Time")
    lineas += [f"\tlineageTag: {_id(tabla)}", ""]
    for medida in MEDIDAS.get(tabla, []):
        dax = medida.dax
        # En TMDL la descripción va como comentario /// encima del objeto.
        lineas.append(f"\t/// {medida.descripcion}")
        if "\n" in dax:
            lineas.append(f"\tmeasure '{medida.nombre}' = ```")
            lineas.append(_sangrar(dax, 3))
            lineas.append("\t\t\t```")
        else:
            lineas.append(f"\tmeasure '{medida.nombre}' = {dax}")
        lineas += [
            f"\t\tformatString: {medida.formato}",
            f"\t\tlineageTag: {_id(tabla, 'medida', medida.nombre)}",
            "",
        ]
    for c in COLUMNAS[tabla]:
        lineas += [f"\tcolumn {c.nombre}", f"\t\tdataType: {c.tipo}"]
        if c.clave:
            lineas.append("\t\tisKey")
        if c.formato:
            lineas.append(f"\t\tformatString: {c.formato}")
        if c.oculta:
            lineas.append("\t\tisHidden")
        lineas += [
            f"\t\tlineageTag: {_id(tabla, c.nombre)}",
            "\t\tsummarizeBy: none",
            f"\t\tsourceColumn: {c.nombre}",
        ]
        if c.ordenar_por:
            lineas.append(f"\t\tsortByColumn: {c.ordenar_por}")
        lineas.append("")
    lineas += [
        f"\tpartition {tabla} = m",
        "\t\tmode: import",
        "\t\tsource =",
        _sangrar(consulta_m(tabla, COLUMNAS[tabla]), 4),
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(lineas)


def escribir_modelo(carpeta: Path) -> None:
    definicion = carpeta / "definition"
    (definicion / "tables").mkdir(parents=True, exist_ok=True)
    _json(
        carpeta / "definition.pbism",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/"
            "semanticModel/definitionProperties/1.0.0/schema.json",
            "version": "4.2",
            "settings": {},
        },
    )
    _texto(definicion / "database.tmdl", "database\n\tcompatibilityLevel: 1600\n")
    _texto(
        definicion / "model.tmdl",
        "\n".join(
            [
                "model Model",
                "\tculture: es-ES",
                "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
                "\tsourceQueryCulture: es-ES",
                "\tdataAccessOptions",
                "\t\tlegacyRedirects",
                "\t\treturnErrorValuesAsNull",
                "",
                # Sin tablas de fecha automáticas: ya existe la de calendario.
                "annotation __PBI_TimeIntelligenceEnabled = 0",
                "",
                *(f"ref table {t}" for t in COLUMNAS),
                "",
            ]
        ),
    )
    _texto(
        definicion / "expressions.tmdl",
        f'expression OrigenDatos = "{ORIGEN_GITHUB}" meta [IsParameterQuery = true, '
        'Type = "Text", IsParameterQueryRequired = true]\n'
        f"\tlineageTag: {_id('OrigenDatos')}\n\n"
        "\tannotation PBI_ResultType = Text\n",
    )
    _texto(
        definicion / "relationships.tmdl",
        "\n".join(
            f"relationship {_id('relacion', desde, cd)}\n"
            f"\tfromColumn: {desde}.{cd}\n\ttoColumn: {hasta}.{ch}\n"
            for desde, cd, hasta, ch in RELACIONES
        ),
    )
    for tabla in COLUMNAS:
        _texto(definicion / "tables" / f"{tabla}.tmdl", tmdl_tabla(tabla))


# --- informe (PBIR) ----------------------------------------------------------

ESQUEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"


def _columna(tabla: str, nombre: str) -> dict[str, Any]:
    return {
        "Column": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": nombre}
    }


def _medida(tabla: str, nombre: str) -> dict[str, Any]:
    return {
        "Measure": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": nombre}
    }


def _proyeccion(campo: dict[str, Any]) -> dict[str, Any]:
    clave = next(iter(campo))
    tabla = campo[clave]["Expression"]["SourceRef"]["Entity"]
    nombre = campo[clave]["Property"]
    return {"field": campo, "queryRef": f"{tabla}.{nombre}", "nativeQueryRef": nombre}


def _literal(valor: str) -> dict[str, Any]:
    return {"expr": {"Literal": {"Value": valor}}}


@dataclass
class Visual:
    nombre: str
    tipo: str
    x: int
    y: int
    ancho: int
    alto: int
    roles: dict[str, list[dict[str, Any]]]
    titulo: str
    orden: dict[str, Any] | None = None
    objetos: dict[str, Any] | None = None

    def json(self, z: int) -> dict[str, Any]:
        consulta: dict[str, Any] = {
            "queryState": {
                rol: {"projections": [_proyeccion(c) for c in campos]}
                for rol, campos in self.roles.items()
            }
        }
        if self.orden:
            consulta["sortDefinition"] = {"sort": [self.orden], "isDefaultSort": False}
        visual: dict[str, Any] = {
            "visualType": self.tipo,
            "query": consulta,
            "visualContainerObjects": {
                "title": [
                    {
                        "properties": {
                            "show": _literal("true"),
                            "text": _literal(f"'{self.titulo}'"),
                        }
                    }
                ]
            },
            "drillFilterOtherVisuals": True,
        }
        if self.objetos:
            visual["objects"] = self.objetos
        return {
            "$schema": f"{ESQUEMA}/visualContainer/1.4.0/schema.json",
            "name": self.nombre,
            "position": {
                "x": self.x,
                "y": self.y,
                "z": z,
                "width": self.ancho,
                "height": self.alto,
                "tabOrder": z,
            },
            "visual": visual,
        }


def _segmentador(nombre: str, x: int, campo: dict[str, Any], titulo: str) -> Visual:
    desplegable = {"data": [{"properties": {"mode": _literal("'Dropdown'")}}]}
    return Visual(
        nombre,
        "slicer",
        x,
        16,
        300,
        64,
        {"Values": [campo]},
        titulo,
        objetos=desplegable,
    )


def _tarjeta(nombre: str, x: int, y: int, campo: dict[str, Any], titulo: str) -> Visual:
    return Visual(nombre, "card", x, y, 290, 120, {"Values": [campo]}, titulo)


def _descendente(campo: dict[str, Any]) -> dict[str, Any]:
    return {"field": campo, "direction": "Descending"}


def _ascendente(campo: dict[str, Any]) -> dict[str, Any]:
    return {"field": campo, "direction": "Ascending"}


def paginas() -> list[tuple[str, str, list[Visual]]]:
    categoria = _columna("paquetes", "categoria")
    propietario = _columna("paquetes", "propietario_tipo")
    lectura = _columna("lecturas", "lectura")
    mediana = _medida("paquetes", "Mediana descargas de usuario 30 días")
    escala_log = {
        eje: [{"properties": {"axisScale": _literal("'log'")}}]
        for eje in ("categoryAxis", "valueAxis")
    }
    return [
        (
            "mercado",
            "Mercado",
            [
                _segmentador("mercado_categoria", 16, categoria, "Categoría"),
                _segmentador("mercado_propietario", 332, propietario, "Propietario"),
                _tarjeta(
                    "mercado_aptos",
                    16,
                    96,
                    _medida("paquetes", "Lanzamientos aptos"),
                    "Lanzamientos analizados",
                ),
                _tarjeta(
                    "mercado_mediana",
                    322,
                    96,
                    mediana,
                    "Descargas de usuario a 30 días (mediana)",
                ),
                _tarjeta(
                    "mercado_estrellas",
                    628,
                    96,
                    _medida("paquetes", "Mediana estrellas"),
                    "Estrellas del repositorio (mediana)",
                ),
                _tarjeta(
                    "mercado_excluidos",
                    934,
                    96,
                    _medida("paquetes", "% excluidos"),
                    "Candidatos excluidos en la limpieza",
                ),
                Visual(
                    "mercado_por_mes",
                    "clusteredColumnChart",
                    16,
                    232,
                    1248,
                    220,
                    {
                        "Category": [_columna("calendario", "mes")],
                        "Y": [_medida("paquetes", "Lanzamientos aptos")],
                    },
                    "Lanzamientos por mes",
                    orden=_ascendente(_columna("calendario", "mes")),
                ),
                Visual(
                    "mercado_por_categoria",
                    "clusteredBarChart",
                    16,
                    468,
                    616,
                    236,
                    {"Category": [categoria], "Y": [mediana]},
                    "Descargas de usuario a 30 días por categoría (mediana)",
                    orden=_descendente(mediana),
                ),
                Visual(
                    "mercado_por_estado",
                    "clusteredBarChart",
                    648,
                    468,
                    616,
                    236,
                    {
                        "Category": [_columna("paquetes", "estado_descripcion")],
                        "Y": [_medida("paquetes", "Candidatos")],
                    },
                    "Candidatos por estado (aptos y motivos de exclusión)",
                    orden=_descendente(_medida("paquetes", "Candidatos")),
                ),
            ],
        ),
        (
            "ruido",
            "Ruido de las descargas",
            [
                _segmentador("ruido_categoria", 16, categoria, "Categoría"),
                _segmentador("ruido_propietario", 332, propietario, "Propietario"),
                _tarjeta(
                    "ruido_pct",
                    16,
                    96,
                    _medida("paquetes", "% de usuario (mediana)"),
                    "De usuario sobre el total (mediana)",
                ),
                _tarjeta(
                    "ruido_total",
                    322,
                    96,
                    _medida("paquetes", "Mediana descargas totales 30 días"),
                    "Descargas totales a 30 días (mediana)",
                ),
                *(
                    _tarjeta(
                        f"ruido_dia_{d}",
                        628 + i * 216,
                        96,
                        _medida("curva_diaria", f"Recibido día {d}"),
                        f"Del mes recibido el día {d}",
                    )
                    for i, d in enumerate(config.DIAS_LECTURA[:2])
                ),
                Visual(
                    "ruido_curva",
                    "lineChart",
                    16,
                    232,
                    1248,
                    472,
                    {
                        "Category": [_columna("curva_diaria", "dia")],
                        "Y": [
                            _medida("curva_diaria", "% del mes recibido"),
                            _medida("curva_diaria", "% del mes recibido (totales)"),
                        ],
                    },
                    "Parte del primer mes que ya ha llegado, día a día: de usuario frente a totales (paquete mediano)",
                    orden=_ascendente(_columna("curva_diaria", "dia")),
                ),
            ],
        ),
        (
            "modelo",
            "Calidad del modelo",
            [
                _segmentador(
                    "modelo_lectura", 16, lectura, "Lectura (día 7 si no eliges)"
                ),
                _tarjeta(
                    "modelo_test",
                    16,
                    96,
                    _medida("predicciones", "Paquetes de test"),
                    "Paquetes de test",
                ),
                _tarjeta(
                    "modelo_factor",
                    322,
                    96,
                    _medida("predicciones", "Factor de error típico"),
                    "Factor de error típico",
                ),
                _tarjeta(
                    "modelo_cobertura",
                    628,
                    96,
                    _medida("predicciones", "Cobertura del rango"),
                    "Aciertos del rango del 90 %",
                ),
                _tarjeta(
                    "modelo_x2",
                    934,
                    96,
                    _medida("predicciones", "Dentro de x2"),
                    "Entre la mitad y el doble",
                ),
                Visual(
                    "modelo_dispersion",
                    "scatterChart",
                    16,
                    232,
                    760,
                    472,
                    {
                        "Category": [_columna("paquetes", "paquete")],
                        "X": [_medida("predicciones", "Estimación")],
                        "Y": [_medida("predicciones", "Descargas reales")],
                    },
                    "Estimación frente a lo que pasó (escala logarítmica)",
                    objetos=escala_log,
                ),
                Visual(
                    "modelo_candidatos",
                    "clusteredBarChart",
                    792,
                    232,
                    472,
                    472,
                    {
                        "Category": [_columna("metricas", "modelo")],
                        "Y": [_medida("metricas", "Factor de error en test")],
                    },
                    "Factor de error de cada candidato en test (menos es mejor)",
                    orden=_ascendente(_medida("metricas", "Factor de error en test")),
                ),
            ],
        ),
        (
            "detalle",
            "Detalle por paquete",
            [
                _segmentador("detalle_categoria", 16, categoria, "Categoría"),
                _segmentador("detalle_lectura", 332, lectura, "Lectura"),
                Visual(
                    "detalle_tabla",
                    "tableEx",
                    16,
                    96,
                    1248,
                    608,
                    {
                        "Values": [
                            _columna("paquetes", "paquete"),
                            _columna("paquetes", "categoria"),
                            _columna("paquetes", "estrellas"),
                            _columna("lecturas", "lectura"),
                            _columna("predicciones", "usuario_lectura"),
                            _columna("predicciones", "estimacion"),
                            _columna("predicciones", "rango_inferior"),
                            _columna("predicciones", "rango_superior"),
                            _columna("predicciones", "usuario_30d_reales"),
                            _columna("predicciones", "dentro_rango"),
                        ]
                    },
                    "Paquetes de test: lo que estimó el radar y lo que pasó (dentro_rango = 1 si acertó)",
                ),
            ],
        ),
    ]


def escribir_informe(carpeta: Path) -> None:
    definicion = carpeta / "definition"
    _json(
        carpeta / "definition.pbir",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definitionProperties/2.0.0/schema.json",
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{NOMBRE}.SemanticModel"}},
        },
    )
    _json(
        definicion / "version.json",
        {"$schema": f"{ESQUEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"},
    )
    _json(
        definicion / "report.json",
        {
            "$schema": f"{ESQUEMA}/report/1.2.0/schema.json",
            "themeCollection": {},
            "layoutOptimization": "None",
        },
    )
    lista = paginas()
    _json(
        definicion / "pages" / "pages.json",
        {
            "$schema": f"{ESQUEMA}/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [nombre for nombre, _, _ in lista],
            "activePageName": lista[0][0],
        },
    )
    for nombre, titulo, visuales in lista:
        carpeta_pagina = definicion / "pages" / nombre
        _json(
            carpeta_pagina / "page.json",
            {
                "$schema": f"{ESQUEMA}/page/1.3.0/schema.json",
                "name": nombre,
                "displayName": titulo,
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
            },
        )
        for z, visual in enumerate(visuales):
            _json(
                carpeta_pagina / "visuals" / visual.nombre / "visual.json",
                visual.json(z),
            )


# --- proyecto ----------------------------------------------------------------


def _json(ruta: Path, contenido: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _texto(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8", newline="\n")


def escribir_proyecto(carpeta: Path) -> None:
    for parte in ("Report", "SemanticModel"):
        destino = carpeta / f"{NOMBRE}.{parte}"
        # Se regenera entero, salvo la configuración local de Power BI Desktop.
        if destino.exists():
            for hijo in destino.iterdir():
                if hijo.name != ".pbi":
                    shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()
    _json(
        carpeta / f"{NOMBRE}.pbip",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/"
            "pbipProperties/1.0.0/schema.json",
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{NOMBRE}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        },
    )
    escribir_modelo(carpeta / f"{NOMBRE}.SemanticModel")
    escribir_informe(carpeta / f"{NOMBRE}.Report")


def main(argumentos: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--proyecto",
        action="store_true",
        help="regenera también el proyecto .pbip (descarta lo guardado en Desktop)",
    )
    args = parser.parse_args(argumentos)
    escribir_datos(DIR_POWERBI / "datos")
    if args.proyecto:
        escribir_proyecto(DIR_POWERBI)
        logger.info("Proyecto escrito en %s", DIR_POWERBI / f"{NOMBRE}.pbip")


if __name__ == "__main__":
    main()
