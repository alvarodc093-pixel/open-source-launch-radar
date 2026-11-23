"""Variables, exclusiones y categorías de la preparación, con datos sintéticos."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from radar import preparacion as prep


def _lanzamiento(paquete: str = "paq", **datos):  # noqa: ANN003, ANN202
    base = {
        "paquete": paquete,
        "nombre": paquete,
        "primera_subida": "2026-03-02 10:00:00.000",
        "resumen": "A small library",
        "licencia": "MIT",
        "requires_python": ">=3.10",
        "dependencias": 3,
        "clasificadores": [],
        "palabras_clave": "",
        "urls": [f"https://github.com/dueno/{paquete}"],
        "dias_subida": ["2026-03-02", "2026-03-05", "2026-04-20"],
        "versiones": 3,
    }
    base.update(datos)
    return base


def _repo(paquete: str = "paq", **datos):  # noqa: ANN003, ANN202
    base = {
        "repo": f"dueno/{paquete}",
        "estrellas": 50,
        "forks": 4,
        "repo_creado": "2026-02-20T00:00:00Z",
        "es_fork": False,
        "archivado": False,
        "lenguaje": "Python",
        "licencia_repo": "MIT",
        "temas": [],
        "propietario_tipo": "Organization",
        "propietario_creado": "2016-03-02T00:00:00Z",
    }
    base.update(datos)
    return base


def _serie(d0: date = date(2026, 3, 2), dias: int = 90, previas: int = 0):  # noqa: ANN202
    """Serie con 2 descargas de usuario y 10 totales cada día desde el día 0."""
    serie = {(d0 + timedelta(days=i)).isoformat(): [2, 10] for i in range(dias)}
    if previas:
        serie[(d0 - timedelta(days=10)).isoformat()] = [0, previas]
    return {
        "paquete": "paq",
        "desde": (d0 - timedelta(days=30)).isoformat(),
        "hasta": (d0 + timedelta(days=dias - 1)).isoformat(),
        "dias": serie,
    }


@pytest.mark.parametrize(
    ("clasificadores", "texto", "temas", "esperada"),
    [
        ([], "An MCP server for Claude", [], "Agentes y LLM"),
        ([], "Tools for LLM-powered agents", [], "Agentes y LLM"),
        (
            ["Topic :: Scientific/Engineering :: Artificial Intelligence"],
            "Image models",
            [],
            "Machine learning",
        ),
        (["Topic :: Scientific/Engineering :: Physics"], "", [], "Datos y ciencia"),
        ([], "Fast dataframe helpers", [], "Datos y ciencia"),
        (["Framework :: Django"], "", [], "Web y APIs"),
        ([], "A pytest plugin", [], "Herramientas de desarrollo"),
        ([], "", ["kubernetes"], "Sistema y automatización"),
        ([], "Poems", [], "Otras"),
        # «ai» como palabra suelta sí, dentro de otra palabra no.
        ([], "Email client", [], "Otras"),
    ],
)
def test_categoria(clasificadores, texto, temas, esperada) -> None:  # noqa: ANN001
    assert prep.categoria(clasificadores, texto, temas) == esperada


def test_fila_paquete_acumula_desde_el_dia_cero() -> None:
    fila, diaria = prep.fila_paquete(_lanzamiento(), _repo(), _serie())
    assert fila["usuario_7d"] == 14  # 7 días × 2
    assert fila["total_7d"] == 70
    assert fila["usuario_30d"] == 60
    # Subidas de los días 0 y 3 entran en la lectura del día 7; la del día 49 no.
    assert fila["subidas_7d"] == 2
    assert fila["subidas_30d"] == 2
    assert fila["dias_repo_previos"] == 10
    assert fila["anios_cuenta"] == pytest.approx(10.0, abs=0.01)
    assert fila["propietario_tipo"] == "Organización"
    assert fila["pct_previas"] == 0
    assert diaria["dia"].min() == 0
    assert set(diaria.columns) == {"paquete", "dia", "usuario", "total"}


@pytest.mark.parametrize(
    ("lanzamiento", "repo", "serie", "esperado"),
    [
        (_lanzamiento(), _repo(), _serie(), "apto"),
        (_lanzamiento(urls=[]), None, None, "sin_repo"),
        (_lanzamiento(), _repo(estrellas=9), None, "pocas_estrellas"),
        (_lanzamiento(), _repo(es_fork=True), _serie(), "repo_fork"),
        (_lanzamiento(), _repo(), None, "sin_descargas"),
        (_lanzamiento(), _repo(), _serie(dias=20), "mes_incompleto"),
        # 300 totales del primer mes: 16 descargas previas superan el 5 %.
        (_lanzamiento(), _repo(), _serie(previas=16), "versiones_previas_borradas"),
        (_lanzamiento(), _repo(), _serie(previas=15), "apto"),
        (
            _lanzamiento(),
            _repo(repo_creado="2024-01-01T00:00:00Z"),
            _serie(),
            "proyecto_anterior",
        ),
    ],
)
def test_estado(lanzamiento, repo, serie, esperado) -> None:  # noqa: ANN001
    fila, _ = prep.fila_paquete(lanzamiento, repo, serie)
    assert prep.estado(fila) == esperado


def test_construir_tablas_marca_repos_compartidos_y_quita_duplicados() -> None:
    lanzamientos = [
        _lanzamiento("a", urls=["https://github.com/dueno/mono"]),
        _lanzamiento("b", urls=["https://github.com/dueno/mono"]),
        _lanzamiento("c"),
        _lanzamiento("c"),  # el mismo mes en dos ficheros
    ]
    repos = {"dueno/mono": _repo("mono"), "dueno/c": _repo("c")}
    series = {"a": _serie(), "b": _serie(), "c": _serie()}
    paquetes, diaria = prep.construir_tablas(lanzamientos, repos, series)
    assert list(paquetes["paquete"]) == ["a", "b", "c"]
    assert list(paquetes["repo_compartido"]) == [True, True, False]
    assert set(diaria["paquete"]) == {"a", "b", "c"}

    radar = prep.dataset_radar(paquetes)
    assert len(radar) == 3
    assert {"usuario_7d", "subidas_14d", "usuario_30d"} <= set(radar.columns)


def test_embudo_resta_en_orden() -> None:
    lanzamientos = [
        _lanzamiento("a"),
        _lanzamiento("b", urls=[]),
        _lanzamiento("c"),
    ]
    repos = {"dueno/a": _repo("a"), "dueno/c": _repo("c", estrellas=1)}
    paquetes, _ = prep.construir_tablas(lanzamientos, repos, {"a": _serie()})
    pasos = prep.embudo(paquetes)
    assert pasos["con_enlace_a_github"] == 3
    assert pasos["tras_sin_repo"] == 2
    assert pasos["tras_pocas_estrellas"] == 1
    assert pasos["tras_proyecto_anterior"] == 1


def test_main_escribe_las_tablas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    (raw / "lanzamientos").mkdir(parents=True)
    (raw / "descargas").mkdir()
    (raw / "lanzamientos" / "2026-03.json").write_text(
        json.dumps(
            {
                "desde": "2026-03-01",
                "hasta": "2026-03-31",
                "paquetes": [_lanzamiento("paq"), _lanzamiento("otro", urls=[])],
            }
        ),
        encoding="utf-8",
    )
    (raw / "github.json").write_text(json.dumps({"dueno/paq": _repo()}))
    (raw / "descargas" / "paq.json").write_text(json.dumps(_serie()))
    procesado = tmp_path / "processed"
    monkeypatch.setattr(prep.config, "DIR_RAW", raw)
    monkeypatch.setattr(prep.config, "DIR_PROCESADO", procesado)
    assert prep.main() == 0
    assert (procesado / "dataset_radar.csv").exists()
    embudo = json.loads((procesado / "embudo.json").read_text(encoding="utf-8"))
    assert embudo["con_enlace_a_github"] == 2
    # paquetes.csv solo guarda los candidatos, no los que no tienen repositorio.
    assert "otro" not in (procesado / "paquetes.csv").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("paquete", "repo", "esperado"),
    [
        ("mseep-pptagent", "icip-cas/pptagent", "mseep"),
        ("iflow-mcp-smadi0x86-gdb-mcp", "smadi0x86/gdb-mcp", "iflow-mcp"),
        ("iflow-mcp-2niuhe-mcp-plantuml", "2niuhe/mcp_plantuml", "iflow-mcp"),
        ("django-ninja", "vitalik/django-ninja", None),  # el prefijo es del nombre
        ("nlr-elm", "natlabrockies/elm", "nlr"),  # patrón, pero de un solo dueño
        ("pandas", "pandas-dev/pandas", None),
    ],
)
def test_prefijo_ajeno(paquete: str, repo: str, esperado: str | None) -> None:
    assert prep.prefijo_ajeno(paquete, repo) == esperado


def test_republicadores_exigen_muchos_duenos() -> None:
    filas = [
        {"paquete": f"copia-proyecto{i}", "repo": f"dueno{i}/proyecto{i}"}
        for i in range(10)
    ]
    filas += [{"paquete": f"nlr-p{i}", "repo": f"natlab/p{i}"} for i in range(10)]
    assert prep.republicadores(pd.DataFrame(filas)) == {"copia"}


def test_construir_tablas_excluye_republicados() -> None:
    lanzamientos = [
        _lanzamiento(f"copia-p{i}", urls=[f"https://github.com/d{i}/p{i}"])
        for i in range(10)
    ] + [_lanzamiento("propio")]
    repos = {f"d{i}/p{i}": _repo(f"p{i}", repo=f"d{i}/p{i}") for i in range(10)}
    repos["dueno/propio"] = _repo("propio")
    series = {p["paquete"]: _serie() for p in lanzamientos}
    paquetes, _ = prep.construir_tablas(lanzamientos, repos, series)
    estados = dict(zip(paquetes["paquete"], paquetes["estado"], strict=True))
    assert estados["propio"] == "apto"
    assert {estados[f"copia-p{i}"] for i in range(10)} == {"republicado"}


def test_es_republicado_con_el_prefijo_ya_identificado() -> None:
    ajenos = {"mseep"}
    assert prep.es_republicado(
        "mseep-claude-agent-sdk", "anthropics/claude-agent-sdk-python", ajenos
    )
    assert not prep.es_republicado("mseep-tools", "mseep/tools", ajenos)  # suyo
    assert not prep.es_republicado("otro", "a/otro", ajenos)
    assert not prep.es_republicado("mseep-x", float("nan"), ajenos)
