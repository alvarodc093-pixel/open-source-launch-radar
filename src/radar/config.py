"""Rutas y parámetros compartidos por la ingesta, la preparación y el modelo."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

DIR_RAW = RAIZ / "data" / "raw"
DIR_PROCESADO = RAIZ / "data" / "processed"
DIR_APP_DATOS = RAIZ / "app" / "data"

# Muestra: paquetes publicados por primera vez en PyPI en los últimos doce
# meses, con la ventana de 30 días ya cerrada. ClickPy tiene todo el
# histórico, pero un año basta para tener varios miles de lanzamientos y
# mantiene la muestra cerca de cómo se publica hoy.
HISTORICO_DIAS = 365
DIAS_MARGEN = 45  # hasta hoy - 45 días: la ventana de 30 días está cerrada

# Solo entran paquetes con repositorio en GitHub y un mínimo de estrellas: el
# radar está pensado para proyectos open source que alguien sigue, no para los
# miles de paquetes de prueba, plantillas o spam que se suben cada mes.
ESTRELLAS_MIN = 10

DIAS_VENTANA = 30
# Días tras el lanzamiento en los que el radar hace su lectura. No hay lectura
# el día 3: los tres primeros días son siempre de ruido (ver DIAS_RUIDO).
DIAS_LECTURA = (7, 14, 21)
# Los mirrors de PyPI descargan cada versión nueva el día que se publica y los
# dos siguientes. Esos días no cuentan como descargas orgánicas.
DIAS_RUIDO = 3
# Días que se guardan de cada serie diaria: un mes antes (para detectar
# versiones borradas) y hasta el día 89 (para la curva de la app).
DIA_PRIMERO = -30
DIA_ULTIMO = 89

CONTACTO = os.getenv("CONTACTO_USER_AGENT", "").strip()
USER_AGENT = "open-source-launch-radar/0.1" + (f" (+{CONTACTO})" if CONTACTO else "")


def ventana_lanzamientos(hoy: date) -> tuple[date, date]:
    """Lanzamientos cuyo primer mes completo ya se puede medir hoy."""
    return hoy - timedelta(days=HISTORICO_DIAS), hoy - timedelta(days=DIAS_MARGEN)


def token_github() -> str | None:
    """GITHUB_TOKEN del entorno o, en local, el de la sesión de `gh`."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        return token
    gh = shutil.which("gh")
    if not gh:
        return None
    resultado = subprocess.run(
        [gh, "auth", "token"], capture_output=True, text=True, check=False
    )
    return resultado.stdout.strip() or None
