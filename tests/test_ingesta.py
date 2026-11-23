"""Parsers, paginación y reintentos de la ingesta, con respuestas simuladas."""

from __future__ import annotations

import json
from datetime import date

import pytest
import responses

from radar.ingesta import clickpy, github
from radar.ingesta.__main__ import en_muestra, meses, rango_serie
from radar.ingesta.http import ClienteHttp, ErrorFuente


def _cliente() -> ClienteHttp:
    return ClienteHttp(pausa_s=0)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los reintentos no esperan de verdad en los tests."""
    monkeypatch.setattr("radar.ingesta.http.time.sleep", lambda _s: None)


# --- ClickPy -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [
        ("Requests", "requests"),
        ("zope.interface", "zope-interface"),
        ("My__Weird-._Pkg", "my-weird-pkg"),
    ],
)
def test_normalizar_pep503(nombre: str, esperado: str) -> None:
    assert clickpy.normalizar(nombre) == esperado


@responses.activate
def test_consultar_lee_json_each_row() -> None:
    cuerpo = '{"paquete": "a", "n": 1}\n{"paquete": "b", "n": 2}\n'
    responses.post(clickpy.URL, body=cuerpo)
    assert clickpy.consultar(_cliente(), "SELECT 1") == [
        {"paquete": "a", "n": 1},
        {"paquete": "b", "n": 2},
    ]


@responses.activate
def test_consultar_detecta_el_error_al_final_de_un_200() -> None:
    # El límite de filas salta con la respuesta ya empezada: llega un 200 con
    # filas buenas y el error como texto al final.
    cuerpo = (
        '{"paquete": "a"}\n'
        "Code: 396. DB::Exception: Limit for result exceeded, max rows: 10.00 "
        "thousand. (TOO_MANY_ROWS_OR_BYTES)\n"
    )
    responses.post(clickpy.URL, body=cuerpo)
    with pytest.raises(ErrorFuente, match="Code: 396"):
        clickpy.consultar(_cliente(), "SELECT 1")


@responses.activate
def test_consultar_paginado_recorre_hasta_la_ultima_pagina(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(clickpy, "FILAS_POR_PAGINA", 2)
    paginas = [[{"i": 0}, {"i": 1}], [{"i": 2}, {"i": 3}], [{"i": 4}]]
    for pagina in paginas:
        responses.post(clickpy.URL, body="\n".join(json.dumps(f) for f in pagina))
    filas = clickpy.consultar_paginado(_cliente(), "SELECT i FROM t", "i")
    assert [f["i"] for f in filas] == [0, 1, 2, 3, 4]
    sql_enviado = [c.request.body.decode() for c in responses.calls]
    assert "LIMIT 2 OFFSET 0" in sql_enviado[0]
    assert "LIMIT 2 OFFSET 4" in sql_enviado[2]


@responses.activate
def test_cuota_de_clickpy_espera_al_final_del_intervalo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    esperas: list[float] = []
    monkeypatch.setattr("radar.ingesta.http.time.sleep", esperas.append)
    monkeypatch.setattr("radar.ingesta.http.time.time", lambda: 1_795_441_200.0)
    error = (
        '{"exception": "Code: 201. DB::Exception: Quota for user `demo` for 3600s '
        "has been exceeded: queries_per_normalized_hash = 22/20. Interval will "
        'end at 2026-11-23 14:00:00. (QUOTA_EXCEEDED)"}'
    )
    responses.post(clickpy.URL, status=500, body=error)
    responses.post(clickpy.URL, body='{"ok": 1}')
    assert clickpy.consultar(_cliente(), "SELECT 1") == [{"ok": 1}]
    # 14:00 UTC es 1_795_442_400: 1.200 s de espera más 30 de margen.
    assert esperas == [1230.0]


def test_lista_sql_rechaza_nombres_no_normalizados() -> None:
    assert clickpy._lista_sql(["b", "a", "a"]) == "'a', 'b'"
    # Una comilla no puede llegar nunca al SQL.
    assert clickpy._lista_sql(["ok", "x'); DROP TABLE t; --"]) == "'ok'"
    with pytest.raises(ValueError):
        clickpy._lista_sql(["No_Normalizado"])


def test_sql_lanzamientos_filtra_por_la_primera_subida() -> None:
    sql = clickpy.sql_lanzamientos(date(2026, 3, 2), date(2026, 3, 8))
    assert "BETWEEN '2026-03-02' AND '2026-03-08'" in sql
    assert "GROUP BY paquete" in sql


@responses.activate
def test_descargar_series_agrupa_por_paquete_y_dia() -> None:
    filas = [
        {
            "paquete": "a",
            "dias": [["2026-03-03", "5", "40"], ["2026-03-02", "3", "300"]],
        },
        {"paquete": "b", "dias": [["2026-03-02", "0", "12"]]},
    ]
    responses.post(clickpy.URL, body="\n".join(json.dumps(f) for f in filas))
    series = clickpy.descargar_series(
        _cliente(), ["a", "b"], date(2026, 3, 1), date(2026, 3, 31)
    )
    assert series == {
        "a": {"2026-03-02": [3, 300], "2026-03-03": [5, 40]},
        "b": {"2026-03-02": [0, 12]},
    }
    assert "installer IN ('pip', 'uv'" in responses.calls[0].request.body.decode()


# --- GitHub ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("urls", "esperado"),
    [
        (["https://github.com/Psf/Requests"], "psf/requests"),
        (["git+https://github.com/a/b.git"], "a/b"),
        (["https://github.com/a/b/tree/main/docs"], "a/b"),
        (["https://pypi.org/x", "https://github.com/a/b/issues"], "a/b"),
        (["https://github.com/sponsors/alguien"], None),
        (["https://gitlab.com/a/b"], None),
        ([], None),
    ],
)
def test_extraer_repo(urls: list[str], esperado: str | None) -> None:
    assert github.extraer_repo(urls) == esperado


def test_construir_consulta_escapa_nombres() -> None:
    consulta = github.construir_consulta(["a/b", 'c/d"x'])
    assert 'r0: repository(owner: "a", name: "b")' in consulta
    assert 'name: "d\\"x"' in consulta  # la comilla va escapada
    assert "rateLimit" in consulta


def _nodo(**datos):  # noqa: ANN003, ANN202
    base = {
        "nameWithOwner": "A/B",
        "stargazerCount": 42,
        "forkCount": 3,
        "createdAt": "2026-01-02T00:00:00Z",
        "isFork": False,
        "isArchived": False,
        "primaryLanguage": {"name": "Python"},
        "licenseInfo": None,
        "repositoryTopics": {"nodes": [{"topic": {"name": "llm"}}]},
        "owner": {"__typename": "User", "login": "a", "createdAt": "2020-01-01"},
    }
    base.update(datos)
    return base


@responses.activate
def test_descargar_repos_trata_not_found_como_sin_repo() -> None:
    responses.post(
        github.URL,
        json={
            "data": {"r0": _nodo(), "r1": None, "rateLimit": {"remaining": 4999}},
            "errors": [{"type": "NOT_FOUND", "path": ["r1"]}],
        },
    )
    repos = github.descargar_repos(_cliente(), ["a/b", "x/y"])
    assert repos["x/y"] is None
    assert repos["a/b"]["estrellas"] == 42
    assert repos["a/b"]["temas"] == ["llm"]
    assert repos["a/b"]["licencia_repo"] is None
    assert repos["a/b"]["propietario_tipo"] == "User"


@responses.activate
def test_descargar_repos_falla_con_otros_errores() -> None:
    responses.post(
        github.URL, json={"data": None, "errors": [{"message": "Bad credentials"}]}
    )
    with pytest.raises(ErrorFuente, match="Bad credentials"):
        github.descargar_repos(_cliente(), ["a/b"])


# --- Cliente HTTP ------------------------------------------------------------


@responses.activate
def test_reintenta_tras_5xx_y_limite() -> None:
    responses.post("https://x.test/", status=502)
    responses.post("https://x.test/", status=429, headers={"Retry-After": "1"})
    responses.post(
        "https://x.test/",
        status=403,
        body="API rate limit exceeded",
        headers={"X-RateLimit-Remaining": "0"},
    )
    responses.post("https://x.test/", json={"ok": True})
    # El límite (429 o el 403 de GitHub) no gasta intentos: solo el 502 cuenta.
    assert _cliente().post("https://x.test/").json() == {"ok": True}


@responses.activate
def test_no_reintenta_un_4xx_corriente() -> None:
    responses.post("https://x.test/", status=400, body="consulta mal formada")
    with pytest.raises(ErrorFuente, match="HTTP 400"):
        _cliente().post("https://x.test/")
    assert len(responses.calls) == 1


@responses.activate
def test_se_rinde_tras_agotar_los_intentos() -> None:
    responses.post("https://x.test/", status=503)
    with pytest.raises(ErrorFuente, match="tras 4 intentos"):
        _cliente().post("https://x.test/")


# --- Orquestación ------------------------------------------------------------


def test_meses_naturales_recortados() -> None:
    assert meses(date(2025, 11, 23), date(2026, 2, 9)) == [
        (date(2025, 11, 23), date(2025, 11, 30)),
        (date(2025, 12, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 9)),
    ]


def test_rango_serie_no_pasa_de_ayer() -> None:
    assert rango_serie("2026-03-10 12:00:00.000", date(2026, 11, 23)) == (
        date(2026, 2, 8),
        date(2026, 6, 7),
    )
    assert rango_serie("2026-11-01 00:00:00", date(2026, 11, 23))[1] == date(
        2026, 11, 22
    )


def test_en_muestra_exige_repo_existente_y_estrellas() -> None:
    repos = {"a/b": {"estrellas": 10}, "c/d": {"estrellas": 9}, "e/f": None}
    paquete = lambda url: {"urls": [url]}  # noqa: E731
    assert en_muestra(paquete("https://github.com/a/b"), repos)
    assert not en_muestra(paquete("https://github.com/c/d"), repos)
    assert not en_muestra(paquete("https://github.com/e/f"), repos)
    assert not en_muestra(paquete("https://example.com"), repos)
