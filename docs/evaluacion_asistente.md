# Evaluación del asistente

Generado con `npm run evaluar-asistente` el 2026-11-23.
Modelo de lenguaje: `qwen3.5`; embeddings: `embeddinggemma`; índice de
10654 fragmentos. 43 preguntas de referencia
(`app/tests/preguntas_asistente.json`). Las de **ajuste** se usaron para decidir cómo
busca el asistente; las de **reserva** se escribieron después y no intervinieron en esas
decisiones, así que miden si generalizan. Las **reformuladas** evitan las palabras de la
documentación. 3 preguntas son ajenas al proyecto.

La versión local usa la búsqueda híbrida. Desplegada en Vercel con Ollama Cloud, que no
ofrece embeddings, la app busca solo por palabras: por eso se miden los dos modos.

## Recuperación: la fuente esperada está entre los 6 fragmentos

| Búsqueda | Ajuste · directas | Ajuste · reformuladas | Reserva · directas | Reserva · reformuladas |
| --- | --- | --- | --- | --- |
| Palabras (BM25) | 19/19 | 3/5 | 9/10 | 5/6 |
| Embeddings (embeddinggemma) | 17/19 | 4/5 | 10/10 | 4/6 |
| Híbrida (RRF) | 17/19 | 4/5 | 10/10 | 5/6 |

## Respuestas con el dato esperado

| Grupo | Palabras (BM25) | Híbrida (RRF) |
| --- | --- | --- |
| Ajuste · directas | 18/19 | 18/19 |
| Ajuste · reformuladas | 2/5 | 4/5 |
| Reserva · directas | 7/10 | 8/10 |
| Reserva · reformuladas | 4/6 | 3/6 |
| Ajenas al proyecto rechazadas | 3/3 | 3/3 |
| Respuestas que citan una fuente | 40/40 | 40/40 |
| Tiempo medio de respuesta | 1.6 s | 1.5 s |

La comprobación es automática: busca la cifra o el término esperado en la
respuesta, así que una respuesta correcta redactada de otra forma puede contar
como fallo. Por eso se guardan las respuestas:

| Híbrida | Palabras | Pregunta | Respuesta (solo palabras, como en Vercel) |
| --- | --- | --- | --- |
| ✓ | ✓ | ¿Qué parte de las descargas de un paquete nuevo son descargas de usuario? | En el caso mediano, solo el 5 % de las descargas totales corresponden a usuarios reales (pip, uv o poetry), mientras que la mayoría provienen de bots y mirrors [4]. Por ello, Open  |
| ✓ | ✓ | ¿Qué modelo usa el radar a día 14? | A día 14, el radar utiliza la regla del ratio típico como modelo elegido [2]. Este enfoque reduce el error estimado al factor ×1,36 y logra una cobertura del rango del 90 % del 89  |
| ✓ | ✓ | ¿Cuál es el factor de error típico del radar a día 7? | El factor de error típico del radar a los 7 días es ×1,80 [2]. Este valor representa la desviación en el paquete mediano entre las estimaciones iniciales y las descargas reales al  |
| ✓ | ✓ | ¿Cuántos paquetes son aptos para el modelo? | De unos 79.000 paquetes nuevos con enlace a GitHub quedan solo **5.217** considerados aptos tras aplicar los filtros de exclusión [1]. El radar utiliza estos datos específicos, jun |
| ✓ | ✗ | ¿Por qué el radar no usa las estrellas de GitHub como señal temprana? | El radar predice descargas de usuario porque la correlación entre estrellas y uso es muy baja (0,20), ya que miden cosas distintas [1][2]. Además, en 2026 GitHub dejó de publicar d |
| ✓ | ✓ | ¿Cuántos paquetes se excluyeron por ser copias de proyectos ajenos? | Se excluyeron 385 paquetes porque eran copias o republicaciones masivas de otros proyectos [1][3]. Ten en cuenta que el radar estima descargas basándose únicamente en las realizada |
| ✓ | ✓ | ¿Cómo se calcula el intervalo del 90 %? | El intervalo del 90 % se calcula utilizando un enfoque conformal basado en los errores observados durante el bloque de calibración [3]. Este método permite proporcionar una estimac |
| ✓ | ✓ | ¿Cómo se reparten los paquetes entre entrenamiento, calibración y test? | Los datos están divididos en 3.130 paquetes para entrenamiento, 1.043 para calibración y 1.044 para prueba [1]. Esta partición por fecha de lanzamiento se utiliza para validar el m |
| ✓ | ✓ | ¿Cuántas descargas automáticas trae cada día con una subida a PyPI? | Cada vez que se sube un nuevo fichero a PyPI, generan automáticamente unas 520 descargas adicionales [1][2]. Estas cifras corresponden al contador total de la aplicación y no inclu |
| ✓ | ✓ | ¿Por qué la página Antes de lanzar no da una cifra fiable? | La aplicación evita dar una cifra exacta antes del lanzamiento porque casi no hay señal predictiva y la mejora sobre la mediana es mínima [1][4]. Por ello, el producto muestra siem |
| ✓ | ✓ | ¿Cada cuánto se actualizan los datos de la aplicación? | Los datos se descargan automáticamente cada día 1 de cada mes o manualmente a petición [2]. Esta actualización incluye nuevos lanzamientos, reentrenamiento del modelo y ejecución d |
| ✓ | ✓ | ¿Qué correlación hay entre las estrellas de GitHub y las descargas de usuario? | La correlación de rangos entre las estrellas de GitHub (de hoy) y las descargas de usuario del primer mes es de 0,20 [3]. Esto indica que ambas métricas miden cosas distintas: las  |
| ✗ | ✓ | ¿Por qué el radar no hace una lectura el día 3? | El radar evita hacer lecturas a los tres primeros días porque estas descargas son "casi solo ruido" provocado por la subida inicial de archivos, lo que impide obtener datos fiables |
| ✓ | ✓ | ¿Qué parte de las descargas de usuario del mes ha llegado el día 7? | El día 7 ya se han registrado la mitad (50 %) de las descargas de usuario que tendrá el paquete al cumplir su primer mes [1][2]. Es importante notar que los tres primeros días suel |
| ✓ | ✓ | ¿Qué instaladores cuentan como descargas de usuario? | Las descargas de usuario incluyen las realizadas a través de `pip`, `uv`, `poetry`, `pdm`, `pipenv` y `pex`. [1] Estas son las que utiliza el radar para predecir el uso real, difer |
| ✓ | ✓ | ¿Por qué se excluyen los repositorios con más de un año? | Se excluyen los repositorios con más de un año porque la mitad tienen más de 8 meses y una cuarta parte más de tres años al subir a PyPI, lo que indica que son proyectos con usuari |
| ✓ | ✓ | ¿Cuántas descargas de usuario tuvo uncalled-for en su primer mes? | El paquete `uncalled-for` acumuló 48.753.650 descargas de usuario (pip, uv, poetry...) durante sus primeros 30 días [5]. Este dato se refiere específicamente a las instalaciones re |
| ✓ | ✓ | ¿Cuántas estrellas tiene el repositorio de strix-sandbox? | El repositorio `usestrix/strix` asociado a la librería **strix-sandbox** cuenta con 77.208 estrellas [1]. Ten en cuenta que estas son las estrellas actuales del repositorio y no re |
| ✓ | ✓ | ¿El modelo sobreestima en el periodo de test? | Sí, el modelo sobreestima en aproximadamente un 30 % durante el periodo de prueba [1][2]. Esto ocurre porque la tasa de crecimiento real del primer mes ha disminuido respecto a los |
| ✓ | ✗ | ¿Cuánto se equivoca la herramienta dos semanas después de publicar? | La aplicación no proporciona una cifra exacta del error a las dos semanas, pero indica que el modelo tiende a sobreestimar casi siempre en todos los periodos [5]. Además, advierte  |
| ✓ | ✓ | ¿Sirve el número que enseña PyPI para saber si mi librería está teniendo éxito? | No, el contador total de descargas de PyPI no sirve porque incluye ruido significativo como mirrors y bots; por ejemplo, un paquete sin usuarios reales puede rondar las 500 descarg |
| ✓ | ✓ | Si mi proyecto tiene muchas estrellas, ¿quiere decir que la gente lo usa? | No necesariamente; las estrellas miden atención mientras que el radar predice uso basado en descargas de usuario [4][5]. Un paquete puede tener decenas de miles de estrellas pero a |
| ✓ | ✗ | ¿Cambia algo que lo publique una empresa en vez de una persona? | No se puede determinar si el hecho de ser publicado por una empresa cambia la estimación con las fuentes actuales, ya que ninguna fuente proporciona datos comparativos entre lanzam |
| ✗ | ✗ | ¿Hay gente que sube a PyPI proyectos que no son suyos? | Sí, existen cuentas que publican cientos de servidores MCP ajenos en PyPI manteniendo sus propias estrellas y enlazando al repositorio original [2]. Estos casos se filtran automáti |
| ✓ | ✓ | (reserva) ¿Cuál es el factor de error típico del radar a día 21? | El factor de error típico del radar a los 21 días es ×1,16 [2]. Este valor indica la desviación en el paquete mediano entre las descargas estimadas y reales al cumplir un mes. |
| ✓ | ✓ | (reserva) ¿Cuántos paquetes nuevos con enlace a GitHub había en la ventana de lanzamientos? | Hubo unos 79.000 paquetes publicados por primera vez en los doce meses de la ventana que tenían algún enlace a github.com [2]. De este total, tras aplicar filtros como el número mí |
| ✓ | ✗ | (reserva) ¿Qué categoría tiene más paquetes en la muestra? | No es posible responder a esta pregunta con las cifras exactas, ya que ninguna de las fuentes proporcionadas especifica cuántos paquetes hay por categoría ni cuál es el total absol |
| ✓ | ✓ | (reserva) ¿Qué cobertura tiene el rango del 90 % a día 14? | A día 14, la cobertura del rango del 90 % cubre entre el **89 % y el 92 %** de los casos [3]. Este resultado se mantiene tanto en las pruebas con Ridge como con el ratio típico seg |
| ✗ | ✗ | (reserva) ¿Por qué se pasó de las estrellas de GitHub a las descargas de PyPI? | Se cambió porque en el verano de 2026 GitHub dejó de publicar datos públicos sobre quién da cada estrella y cuándo, haciendo imposible obtener series temporales fiables [3]. Por el |
| ✓ | ✓ | (reserva) ¿Cuántas veces por hora permite ClickPy repetir una consulta? | ClickPy limita las consultas a 20 ejecuciones del mismo tipo por hora [3]. Esta restricción afecta tanto al acceso público como a la ingesta de datos, lo que obliga a optimizar las |
| ✗ | ✗ | (reserva) ¿Qué es el ratio típico? | El "ratio típico" es una regla simple utilizada por la aplicación para estimar las descargas totales a 30 días basándose en las descargas de usuario acumuladas hasta ese momento [1 |
| ✓ | ✓ | (reserva) ¿Cuántos paquetes se excluyeron por tener versiones anteriores borradas? | Se excluyeron 481 paquetes porque tenían versiones anteriores borradas de PyPI antes de su día 0 [3]. Este recorte eliminó más del 5 % del volumen descargado en el primer mes, ya q |
| ✓ | ✓ | (reserva) ¿Cuál es la mediana de descargas de usuario de un paquete en su primer mes? | La mediana de descargas de usuario para un paquete en su primer mes es de 93 [1][5]. Ten en cuenta que este valor se refiere a las instalaciones reales (pip, uv, etc.) y no incluye |
| ✓ | ✓ | (reserva) ¿Acierta el veredicto «por debajo»? | El veredictivo "por debajo" casi nunca puede afirmarse antes del día 21 porque la mayoría de los paquetes con pocas descargas iniciales terminan en ese rango debido al ruido de las |
| ✓ | ✗ | (reserva) ¿Cuánto tráfico de bots recibe una librería solo por publicar una versión nueva? | Las descargas totales mostradas en PyPI incluyen ruido significativo proveniente de mirrors, escáneres y bots que no representan uso real [2]. Por ejemplo, un paquete nuevo sin usu |
| ✗ | ✓ | (reserva) Si en la primera semana llevo 50 instalaciones reales, ¿cuántas tendré al mes más o menos? | Basado únicamente en las fuentes proporcionadas, no es posible calcular una cifra exacta para tu caso específico de "instalaciones" (descargas de usuario), ya que el documento [3]  |
| ✗ | ✓ | (reserva) ¿Qué pasa con las librerías que otro paquete instala por debajo sin que nadie las elija? | Las descargas del radar solo cuentan instalaciones reales (de pip, uv, poetry, etc.) y no incluyen los casos donde un paquete es instalado automáticamente como dependencia pero nun |
| ✓ | ✓ | (reserva) ¿Por qué no fiarse de una sola cifra antes de haber publicado nada? | Antes del lanzamiento casi no hay señal predictiva fiable porque la mejora sobre la mediana es mínima y existen muchas variables aleatorias [2]. Por ello, la aplicación evita dar u |
| ✗ | ✗ | (reserva) ¿Cómo sé que los paquetes con los que se comprobó el resultado no se usaron para aprender? | No hay indicios en las fuentes de que los datos de prueba (los usados para comprobar el resultado) hayan sido utilizados durante la fase de aprendizaje del modelo. El documento [5] |
| ✓ | ✓ | (reserva) ¿Se nota que los proyectos más recientes salen menos en los datos? | Sí, los proyectos publicados recientemente aparecen con menor frecuencia debido a un "sesgo de selección" causado por la exigencia de tener al menos 10 estrellas el día del análisi |
| ✓ | ✓ | ¿Cuál es la capital de Australia? | No puedo responder a tu pregunta sobre la capital de Australia utilizando las fuentes proporcionadas [1], [2]. Estas fuentes contienen datos técnicos sobre paquetes de Python (desc |
| ✓ | ✓ | ¿Qué videojuego de Steam vendió más copias en 2025? | No puedo responder a tu pregunta sobre qué videojuego de Steam vendió más copias en 2025 utilizando las fuentes proporcionadas, ya que estas solo contienen datos estadísticos del r |
| ✓ | ✓ | ¿Cómo instalo Docker en Ubuntu? | No puedo responder a tu pregunta sobre cómo instalar Docker en Ubuntu con los datos proporcionados, ya que estas fuentes solo contienen estadísticas de descargas y estrellas para p |
