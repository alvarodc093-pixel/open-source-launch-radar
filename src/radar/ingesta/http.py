"""Cliente HTTP con espera entre peticiones y reintentos.

Las dos fuentes reciben la consulta por POST (SQL en ClickPy, GraphQL en
GitHub) y las dos tienen cupos por hora:

- ClickPy responde 500 con QUOTA_EXCEEDED cuando una misma consulta (con
  otros valores) se ha ejecutado 20 veces en la hora, y dice a qué hora
  termina el intervalo.
- GitHub responde 403 o 429 al agotar los puntos de la hora, con la hora de
  renovación en `X-RateLimit-Reset`.

En los dos casos se espera a que se renueve el cupo, sin gastar intentos. Los
demás 5xx se reintentan con espera creciente antes de dar el dato por perdido.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

import requests

from radar.config import USER_AGENT

logger = logging.getLogger(__name__)

INTENTOS = 4
ESPERA_BASE_S = 2.0
ESPERA_MAX_S = 3700.0  # los dos cupos se renuevan como mucho en una hora
ESPERAS_MAX = 6  # tope de esperas por cupo en una misma petición


class ErrorFuente(RuntimeError):
    """La fuente no devolvió un dato utilizable tras agotar los reintentos."""


class ClienteHttp:
    def __init__(
        self,
        pausa_s: float = 0.0,
        timeout_s: int = 120,
        cabeceras: dict[str, str] | None = None,
    ) -> None:
        self._pausa_s = pausa_s
        self._timeout_s = timeout_s
        self._ultima = 0.0
        self._sesion = requests.Session()
        self._sesion.headers["User-Agent"] = USER_AGENT
        self._sesion.headers.update(cabeceras or {})

    def post(
        self,
        url: str,
        *,
        datos: str | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        """POST con reintentos; devuelve la respuesta si el código es < 400."""
        motivo = "sin detalle"
        esperas = 0
        intento = 0
        while intento < INTENTOS:
            self._esperar_turno()
            try:
                resp = self._sesion.post(
                    url,
                    data=datos.encode("utf-8") if datos is not None else None,
                    json=json,
                    params=params,
                    timeout=self._timeout_s,
                )
            except requests.RequestException as exc:
                motivo = f"red: {exc}"
            else:
                if resp.status_code < 400:
                    return resp
                if _es_limite(resp) and esperas < ESPERAS_MAX:
                    espera = _espera_limite(resp, intento)
                    logger.warning("Cupo agotado en %s, espero %.0f s", url, espera)
                    time.sleep(espera)
                    esperas += 1
                    continue
                if resp.status_code < 500:
                    # Otro 4xx: la consulta está mal y reintentar no lo arregla.
                    raise ErrorFuente(
                        f"HTTP {resp.status_code} en {url}: {resp.text[:300]}"
                    )
                motivo = f"HTTP {resp.status_code}"
            logger.warning(
                "Intento %d/%d fallido en %s (%s)", intento + 1, INTENTOS, url, motivo
            )
            time.sleep(ESPERA_BASE_S * 2**intento)
            intento += 1
        raise ErrorFuente(f"{url}: {motivo} tras {INTENTOS} intentos")

    def _esperar_turno(self) -> None:
        restante = self._pausa_s - (time.monotonic() - self._ultima)
        if restante > 0:
            time.sleep(restante)
        self._ultima = time.monotonic()


_FIN_INTERVALO = re.compile(r"Interval will end at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def _es_limite(resp: requests.Response) -> bool:
    """429, el 403 de GitHub al agotar el cupo o el QUOTA_EXCEEDED de ClickPy."""
    if resp.status_code == 429 or "QUOTA_EXCEEDED" in resp.text:
        return True
    return resp.status_code == 403 and (
        resp.headers.get("X-RateLimit-Remaining") == "0"
        or "rate limit" in resp.text.lower()
    )


def _espera_limite(resp: requests.Response, intento: int) -> float:
    valor = resp.headers.get("Retry-After", "").strip()
    if valor.isdigit():
        return min(float(valor), ESPERA_MAX_S)
    fin = _FIN_INTERVALO.search(resp.text)
    if fin:
        # ClickHouse da la hora en UTC, sin zona.
        momento = datetime.fromisoformat(fin.group(1)).replace(tzinfo=UTC)
        return min(max(momento.timestamp() - time.time(), 1.0) + 30, ESPERA_MAX_S)
    reinicio = resp.headers.get("X-RateLimit-Reset", "").strip()
    if reinicio.isdigit():
        return min(max(float(reinicio) - time.time(), 1.0) + 1, ESPERA_MAX_S)
    return ESPERA_BASE_S * 2 ** (intento + 1)
