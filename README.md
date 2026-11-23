# Open Source Launch Radar

Estima con las descargas de los primeros días cuántas tendrá una librería de Python
nueva al cumplir su primer mes en PyPI y si eso es mucho o poco para su categoría.

> Proyecto en desarrollo.

## Problema

Quien publica una librería open source pasa el primer mes a ciegas. PyPI enseña un
contador de descargas, pero un paquete recién subido recibe cientos de descargas de
mirrors y bots aunque no lo use nadie, así que el número no dice si el proyecto está
despegando. El radar separa las descargas orgánicas del ruido de cada versión y
compara el lanzamiento con otros de su categoría.

## Datos

| Fuente                                                           | Qué aporta                                                       |
| ---------------------------------------------------------------- | ---------------------------------------------------------------- |
| [ClickPy](https://clickpy.clickhouse.com) (ClickHouse, sin clave) | Metadatos de cada versión de PyPI y descargas diarias por paquete |
| API GraphQL de GitHub                                            | Estrellas, forks, propietario y temas del repositorio enlazado   |

## Puesta en marcha

```bash
uv venv --python 3.13 .venv
uv pip install -r requirements.txt
```
