# Prices Screen Contract 1.2

`prices_screen.json` publica directamente el contrato de pantalla `prices_ohlcv`. La versión 1.2 conserva las secciones `context`, `badges`, `kpis`, `widgets`, `selectors`, `charts`, `tables`, `comparison`, `events` y `quality`.

## Tiempo y series sintéticas

La corrida sintética utiliza un único `reference_timestamp`. Solo genera Spot/Futures `1m` y `15m`, ordenados hacia atrás desde el último bucket cerrado. Processing deriva `5m` desde `1m` y `1h/4h/1d` desde `15m` con agregación OHLCV. General se construye después del resampling mediante la media de precios Spot/Futures y la suma de sus volúmenes.

El fixture conserva 600 registros fuente `1m` y 5,760 registros fuente `15m`. Esto produce 120 velas `5m`, 1,440 velas `1h`, 360 velas `4h` y 60 velas `1d`, dando cobertura suficiente para SMA/WMA 50 en el timeframe diario.

## Historia de cálculo y ventana visual

Input y Processing conservan toda la historia disponible. El Contract Builder aplica después de todos los cálculos una ventana de presentación de 120 registros. OHLCV, indicadores, overlays y eventos se recortan al mismo rango temporal; `current`, KPI, estadísticas, performance y bias permanecen calculados sobre la historia completa. La metadata de cada timeframe declara registros disponibles/devueltos y los límites temporales de ambas ventanas.

Cada market/timeframe declara `reference_timestamp`, `data_as_of`, intervalo, fuente real, condición de resampling, cierre, parcialidad, registros esperados/usados y cobertura. El contexto separa `generated_at`, `updated_at` y `selected_data_as_of`.

## Ventana 24H

KPI y widgets comparten una única selección de las últimas 24 velas `1h` cerradas. High, Low y Volume utilizan exactamente esas 24 velas. Change compara el último close con el close de hace 24 horas. Average Volume divide el volumen acumulado entre 24.

## Tablas

MACD, MACD Signal y MACD Histogram conservan sus tres valores independientes. La presentación normaliza el cero redondeado para evitar `-0.00`. Cada fila separa señal/estado de sus tokens visuales mediante `signal_color_token`, `display_signal` y `display_color_token`.

Los parámetros proceden de Classification y conservan la configuración efectiva, incluido TSI 25/13. Standard Deviation, VaR y CVaR declaran por separado valor visible, retorno usado para clasificación, unidades y bases metodológicas.

## Eventos

Los eventos viven una sola vez en `events.by_id`. Su `event_uid` determinista combina mercado, timeframe, timestamp, tipo e identificador. `technical_cross_ids`, `candlestick_pattern_ids`, las anotaciones por timestamp y el widget de patrones contienen referencias, no copias de los eventos.

## Quality y disponibilidad

`quality.status` mantiene el vocabulario global `ok|partial|invalid`. Los elementos visuales utilizan exclusivamente `available|partial|unavailable|invalid`.

- `contract_complete`: estructura y serialización completas.
- `data_complete`: todos los KPI y widgets disponen de datos.
- `availability`: conteos disponibles/totales por tipo de bloque.
- `is_complete`: alias temporal de `contract_complete`, documentado en `compatibility_alias`.

## Vista ligera de selector

`build_prices_view(vertical_output=..., market=..., timeframe=...)` construye una respuesta `selected_view` desde Processing y Classification ya calculados. No ejecuta nuevamente ninguna etapa y devuelve únicamente KPI, widgets, filas seleccionadas, comparación actual y Quality para la selección solicitada.

Esta función es el adaptador previsto para `GET /api/screens/prices/view?market=spot&timeframe=15m`. El bootstrap conserva charts y eventos globales; la vista ligera no los duplica. Sus respuestas sintéticas típicas ocupan aproximadamente 21–24 KB sin comprimir.

Market Cap, Beta, Volume Profile, pivots, zonas, histograma, correlación y forecast permanecen `unavailable` mientras no existan fuentes o algoritmos reales.
