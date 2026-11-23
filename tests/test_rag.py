"""El índice del asistente: troceado, fichas, cuantización y escritura."""

from __future__ import annotations

import base64
import json
import sys

import numpy as np
import pandas as pd
import pytest
import responses

from radar import rag


def test_secciones_y_troceado():
    texto = (
        "# Título\n\nintro\n\n## Uno\n\nA\n\n### Dos\n\nB\n\n## Vacía\n\n## Tres\n\nC"
    )
    secciones = rag._secciones_markdown(texto)
    assert [t for t, _ in secciones] == ["Uno", "Dos", "Tres"]

    largo = "\n\n".join(["palabra " * 60] * 6)  # unos 2.900 caracteres
    trozos = rag._trocear("Sección", largo)
    assert len(trozos) > 1
    assert all(t.startswith("Sección\n\n") for t in trozos)
    assert all(len(t) <= rag.MAX_CARACTERES + 500 for t in trozos)


def test_las_tablas_se_compactan():
    tabla = "| a      | b      |\n| ------ | ------ |\n| 1      | 2      |"
    (trozo,) = rag._trocear("T", tabla)
    assert "  " not in trozo
    assert "------" not in trozo


def _paquete(**cambios):
    base = {
        "paquete": "mi-libreria",
        "nombre": "mi_libreria",
        "fecha_lanzamiento": "2026-01-02",
        "resumen": "Una librería pequeña",
        "categoria": "Datos y ciencia",
        "repo": "dueno/mi-libreria",
        "propietario_tipo": "Organización",
        "estrellas": 120,
        "forks": 8,
        "dependencias": 3,
        "versiones_total": 5,
        "estado": "apto",
        "usuario_7d": 30,
        "usuario_14d": 60,
        "usuario_21d": 80,
        "usuario_30d": 120,
        "total_30d": 4000,
    }
    return pd.Series({**base, **cambios})


def test_ficha_con_descargas_y_en_test():
    texto = rag.ficha(_paquete(), en_test=True)
    assert "dueno/mi-libreria, de una organización, con 120 estrellas" in texto
    assert "30 a los 7 días, 60 a los 14 días, 80 a los 21 días y 120 a los 30" in texto
    assert "de 4000 descargas totales" in texto
    assert "/?paquete=mi-libreria" in texto
    for palabra in ("modelo", "radar", "día "):
        assert palabra not in texto


def test_ficha_de_un_excluido():
    texto = rag.ficha(
        _paquete(
            estado="proyecto_anterior",
            resumen=np.nan,
            usuario_30d=np.nan,
            propietario_tipo="Persona",
        ),
        False,
    )
    assert "más de un año" in texto
    assert "de una persona" in texto
    assert "Descripción" not in texto
    assert "Descargas de usuario" not in texto
    assert "conjunto de test" not in texto


def test_cuantizar_conserva_el_coseno():
    rng = np.random.default_rng(0)
    vectores = rng.normal(size=(5, 32)).astype(np.float32)
    enteros = np.frombuffer(base64.b64decode(rag.cuantizar(vectores)), dtype=np.int8)
    enteros = enteros.reshape(5, 32).astype(float) / 127
    unitarios = vectores / np.linalg.norm(vectores, axis=1, keepdims=True)
    assert np.allclose(enteros @ enteros.T, unitarios @ unitarios.T, atol=0.03)


def test_corpus_de_un_repositorio(tmp_path):
    raiz = tmp_path
    (raiz / "data" / "processed").mkdir(parents=True)
    (raiz / "app" / "data").mkdir(parents=True)
    (raiz / "notebooks").mkdir()
    (raiz / "README.md").write_text(
        "# Radar\n\n## 1. Datos\n\nTexto\n\n## Licencia\n\nMIT", encoding="utf-8"
    )
    cuaderno = {"cells": [{"cell_type": "markdown", "source": ["## EDA\n\nHallazgo"]}]}
    (raiz / "notebooks" / "02_eda.ipynb").write_text(json.dumps(cuaderno))
    pd.DataFrame([_paquete(), _paquete(paquete="otro", nombre="otro")]).to_csv(
        raiz / "data" / "processed" / "paquetes.csv", index=False
    )
    (raiz / "app" / "data" / "radar.json").write_text(
        json.dumps({"ejemplos": [{"paquete": "otro"}]})
    )
    corpus = rag.construir_corpus(raiz)
    tipos = {f["tipo"] for f in corpus}
    assert tipos == {"documentacion", "paquete"}
    assert sum("/?paquete=otro" in f["texto"] for f in corpus) == 1
    assert len({f["id"] for f in corpus}) == len(corpus)
    titulos = " ".join(f["titulo"] for f in corpus)
    assert "Licencia" not in titulos
    assert "Notebook 02_eda" in titulos


@responses.activate
def test_indice_con_embeddings(monkeypatch):
    corpus = [
        {"id": "a", "tipo": "documentacion", "titulo": "A", "texto": "uno"},
        {"id": "b", "tipo": "paquete", "titulo": "B", "texto": "dos", "paquete": "b"},
    ]
    monkeypatch.setattr(rag, "construir_corpus", lambda: corpus)
    responses.post(
        f"{rag.OLLAMA_HOST}/api/embed",
        json={"embeddings": [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]]},
    )
    indice = rag.construir_indice()
    enviado = json.loads(responses.calls[0].request.body)
    assert enviado["input"] == ["title: none | text: uno", "title: B | text: dos"]
    assert indice["embeddings"]["dimension"] == 3
    assert indice["embeddings"]["prefijo_consulta"] == rag.PREFIJO_CONSULTA


def test_main_sin_embeddings(monkeypatch, tmp_path):
    ruta = tmp_path / "rag.json"
    monkeypatch.setattr(rag, "RUTA_INDICE", ruta)
    monkeypatch.setattr(
        rag,
        "construir_corpus",
        lambda: [{"id": "a", "tipo": "documentacion", "titulo": "A", "texto": "x"}],
    )
    monkeypatch.setattr(sys, "argv", ["rag", "--sin-embeddings"])
    rag.main()
    indice = json.loads(ruta.read_text(encoding="utf-8"))
    assert indice["embeddings"] is None
    assert len(indice["fragmentos"]) == 1


@responses.activate
def test_error_de_ollama_se_propaga(monkeypatch):
    monkeypatch.setattr(
        rag,
        "construir_corpus",
        lambda: [{"id": "a", "tipo": "documentacion", "titulo": "A", "texto": "x"}],
    )
    responses.post(f"{rag.OLLAMA_HOST}/api/embed", status=404)
    with pytest.raises(Exception, match="404"):
        rag.construir_indice()
