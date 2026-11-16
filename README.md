# Megasalidas a bolsa: reproducción pública de precios

Este paquete reconstruye con datos gratuitos las **tablas de precios y retornos** de la cohorte de 16 IPO del estudio, edición de trabajo 5 (16-11-2026). Contiene solo código y metadatos de la cohorte: no incluye cotizaciones, factores descargados ni resultados derivados. Se puede ejecutar fuera de la infraestructura de ETF Equity Lab; no necesita `shared` ni rutas internas del estudio.

## Instalar y ejecutar

Se probó con **Python 3.15.2** y las versiones fijadas en `requirements.txt`. Desde esta carpeta, en un entorno Python 3.15 ya preparado:

```bash
python3.15 -m pip install -r requirements.txt
python3.15 fetch.py --out /tmp/mega_ipos_descarga_20261116
python3.15 compute.py \
  --input /tmp/mega_ipos_descarga_20261116 \
  --output /tmp/mega_ipos_calculo_20261116
```

Sustituye las dos rutas `/tmp/` por carpetas locales propias **fuera de `public_pipeline/` y del repositorio** si quieres conservar las salidas. Cada ruta de salida debe ser nueva: los programas rechazan carpetas existentes para evitar sobrescribir una ejecución anterior. La descarga necesita conexión a Yahoo Finance y a la [biblioteca de Kenneth French](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html). `fetch.py` consulta los 16 casos una vez y descarga un ZIP de factores; informa `received`, `empty` o `error` por caso en su manifiesto. Si termina con código 2, consulta ese manifiesto antes de calcular.

## Qué produce

| Carpeta | Archivo | Contenido |
|---|---|---|
| Descarga | `raw/yahoo/<símbolo>.csv` | Barras diarias devueltas por `yfinance.Ticker.history`; una por símbolo con datos. |
| Descarga | `raw/french/f_f_research_data_factors_daily_csv.zip` | Factor diario original de French. |
| Descarga | `manifest.json` | Hora UTC, versiones, parámetros, estado, filas y SHA-256 de cada respuesta guardada. |
| Cálculo | `case_horizon.csv` | 16 casos × 9 horizontes = 144 posiciones, con fecha objetivo, estado, pop y retornos cuando son calculables. |
| Cálculo | `case_summary.csv`, `coverage.csv`, `medians.csv` | Resumen por IPO, cobertura por horizonte y medianas con sus denominadores. |
| Cálculo | `summary.json`, `qa.json`, `manifest.json` | Recuentos, lagunas, comprobaciones de calendario, versiones y SHA-256 de entradas y salidas. |

Las fechas, precios de oferta, tickers y enlaces a los prospectos SEC de los 16 casos están en `cohort.json`. D0 es la fecha de primera sesión fijada por el estudio; el prospecto respalda la oferta, mientras que `d0_date_basis` identifica la procedencia de la fecha. El programa comprueba si la barra descargada contiene D0, pero no verifica de nuevo todos los hechos de la IPO.

## Definiciones del cálculo

La descarga comienza en D0 y termina en la sesión del **13-11-2026**, inclusive; la petición usa `end=2026-11-14`, exclusivo. `fetch.py` llama a [`Ticker.history`](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html) con `interval="1d"`, `auto_adjust=False`, `actions=True`, `repair=False`, `keepna=True` y `prepost=False`. Así se conservan `Close`, `Adj Close`, dividendos y splits para revisar los ajustes. Los CSV son la salida de *yfinance*, no una copia de la respuesta HTTP original de Yahoo.

`compute.py` programa las sesiones +1, +2, +5, +10, +21, +42, +63, +126 y +252 con los calendarios de NYSE o Nasdaq de [`pandas_market_calendars`](https://pandas-market-calendars.readthedocs.io/). El **pop** compara el precio de oferta con el cierre **nominal** de D0; cuando hay splits posteriores, el cierre nominal se reconstruye desde `Close` y los factores de split. Es relevante para Visa, cuyo split 4:1 se observa en 2015. El retorno posterior compara `Adj Close` de la fecha objetivo con `Adj Close` de D0. El retorno desde oferta encadena pop y retorno posterior. Las columnas `*_pct` expresan porcentajes con ocho decimales; `post_minus_market_pp` expresa una diferencia en puntos porcentuales.

El comparador de mercado acumula `Mkt-RF + RF` de [Fama/French Research Data Factors, frecuencia diaria](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library/f-f_factors.html), desde la sesión posterior a D0 hasta la sesión objetivo incluida. Los factores de origen vienen en porcentajes y el código los divide por 100 antes de componerlos. `post_minus_market_pp` resta el retorno compuesto del mercado al retorno posterior de la acción. La curva de mediana fija hasta +126 usa solo los casos con retorno disponible en +126; la curva pareada con mercado usa el subconjunto con ambos retornos. +252 se presenta aparte, con su denominador real.

## Límites de interpretación y reproducción

- **Cobertura:** en la prueba del 16-11-2026 hubo D0 válido para 15/16, retorno en +63 para 15, en +126 para 14 y en +252 para 12. KVUE no devolvió D0; sus retornos quedan vacíos. Las fechas objetivo posteriores al corte aparecen como `inmaduro_al_corte`, no como cero.
- **Continuidad bursátil:** DIDI se descarga con el ticker actual `DIDIY`, sustentado por el [20-F ante la SEC](https://www.sec.gov/Archives/edgar/data/1764757/000110465923053304/didi-20221231x20f.htm). Su tramo desde el 13-06-2022 se rotula OTC, incluido +252; no se presenta como cotización continua en NYSE.
- **Benchmark:** en la prueba, el archivo French llegaba al **30-09-2026**. Si la acción tiene precio posterior y el factor aún no cubre la fecha, el retorno de mercado y el exceso quedan vacíos. Los datos de la biblioteca pueden ampliarse en otra ejecución.
- **Cambios de proveedor:** una nueva descarga puede diferir de la edición 5 aunque el código y el corte sean iguales. En la comprobación local del 16-11-2026 variaron valores de `Adj Close` en **BABA, GM, META y V**; `Close`, fechas, dividendos y splits de esos casos permanecieron iguales. Hubo diferencias pequeñas en retornos derivados, sin cambios de cobertura ni fechas objetivo. El paquete deja hashes y versiones para que cada ejecución sea auditable; no atribuye una causa interna al proveedor.
- **Alcance:** los scripts reproducen tablas con las que se construyen las figuras de precios y retornos, pero no generan gráficos ni reconstruyen las series de Wikipedia o Google Trends. La comparación automática con los archivos congelados de ed5 se hizo en el entorno del estudio; esos archivos no forman parte del paquete público. Para cotejar cifras publicadas, usa el artículo web público cuando esté disponible y los archivos de tu propia ejecución.

Las ausencias siempre conservan su estado en `case_horizon.csv` y `coverage.csv`; ninguna se rellena con retorno cero.

## Fuentes y condiciones de uso

Los precios proceden de [Yahoo Finance mediante yfinance](https://ranaroussi.github.io/yfinance/); la biblioteca documenta su interfaz de descarga. Los factores provienen de la [Data Library de Kenneth French](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html). Los precios de oferta se acreditan con un enlace al prospecto final de la [SEC](https://www.sec.gov/edgar/search/) por caso en `cohort.json`. Consulta las condiciones de cada proveedor antes de redistribuir sus datos: este paquete distribuye el procedimiento y las referencias, no las series descargadas.

## Licencia

El código propio de `fetch.py` y `compute.py` se ofrece bajo la [licencia MIT](LICENSE). La licencia no concede derechos sobre las cotizaciones de Yahoo Finance, los factores de Kenneth French ni los documentos de la SEC. Los archivos descargados permanecen en el equipo del lector y están sujetos a las condiciones de sus respectivas fuentes. `cohort.json` contiene metadatos y enlaces de procedencia; no incluye series de mercado.
