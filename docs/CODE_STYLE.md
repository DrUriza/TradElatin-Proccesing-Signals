# Compact Column-Aligned Python Style

Este repositorio utiliza el **estilo Python columnar compacto y alineado**. Su objetivo es hacer visibles las relaciones entre imports, constantes y asignaciones sin expandir innecesariamente el código.

## Reglas

1. Los imports `from ... import ...` consecutivos se alinean por la palabra `import`.
2. Las constantes relacionadas se alinean por el signo `=`.
3. Las asignaciones locales consecutivas y relacionadas se alinean por el signo `=`.
4. Los atributos consecutivos de una instancia se alinean por el signo `=`.
5. Las firmas y llamadas permanecen en horizontal mientras sean legibles.
6. Cuando sea necesario dividir una firma o llamada, se utiliza continuación compacta alineada; no se coloca automáticamente un argumento por línea.
7. Los diccionarios, listas y retornos pequeños permanecen en una sola línea.
8. Las estructuras grandes solo se dividen cuando la separación mejora realmente la lectura.
9. La indentación es siempre de cuatro espacios. No se permiten tabs.
10. Las funciones y clases de nivel superior se separan con dos líneas en blanco.
11. La longitud objetivo es de 160 caracteres; se toleran hasta 200 cuando la forma compacta es más clara.
12. No se ejecutan Black ni `ruff format`, porque eliminarían la alineación intencional.
13. Ruff se utiliza únicamente para linting. Las reglas `E221`, `E241` y `E272` se ignoran porque entran en conflicto con la alineación columnar.
14. El formateo nunca debe modificar lógica, firmas públicas, contratos, cálculos ni resultados.
15. Las mismas reglas se aplican a `src/`, `tests/` y `scripts/`.

## Ejemplos

```python
from __future__       import annotations
from collections.abc import Callable, Mapping
from typing           import Any


FIRST_CONSTANT  = "first"
SECOND_CONSTANT = "second"


market    = request["market"]
timeframe = request["timeframe"]
limit     = request["limit"]

self.fetcher            = fetcher
self.symbol             = symbol
self.exchange           = exchange
self.bootstrap_limit    = bootstrap_limit
self.incremental_limits = incremental_limits
```

## Herramienta local

El formateo mecánico conservador puede aplicarse con:

```text
python scripts/format_columnar.py src tests scripts
```

Para comprobar que no quedan cambios mecánicos pendientes:

```text
python scripts/format_columnar.py --check src tests scripts
```

La herramienta solo alinea construcciones simples y elimina tabs o espacios finales; no reescribe el AST ni compacta código de forma agresiva.
