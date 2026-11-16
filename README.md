# Lunar Landing Analyzer

Aplicación en español para explorar, comparar y registrar evaluaciones preliminares de sitios lunares. En ejecución local escucha en `http://localhost:8080`; para producción incluye configuración de Render y Gunicorn.

## Descargar y abrir usando PyCharm

1. Pulsa el adjunto ZIP de esta conversación para descargarlo; después, en el Explorador de archivos, usa **Extraer todo**. El ZIP contiene una carpeta raíz llamada `LunarLandingAnalyzer` con todo el proyecto dentro.
2. Abre PyCharm y selecciona **Open**; elige esa carpeta `LunarLandingAnalyzer`. Si aparece una confirmación de confianza, selecciona **Trust Project**.
3. Si PyCharm solicita un intérprete, abre **Add Interpreter** y selecciona o crea un entorno local con Python 3.10 o posterior. Si no tienes Python instalado, usa **Download Python** desde el asistente de intérprete de PyCharm cuando esté disponible. La aplicación sí requiere ese intérprete; no requiere que descargues manualmente ningún otro archivo.
4. Abre `requirements.txt` en PyCharm y acepta **Install requirements**. También puedes abrir **Settings > Project > Python Interpreter > Add Package**, instalar `Flask` y `ReportLab`, y dejar que PyCharm resuelva sus dependencias. Solo si vas a activar SPICE, instala además `requirements-spice.txt` o el paquete `spiceypy`; es opcional para el uso normal.
5. En la lista de configuraciones de ejecución, selecciona **Lunar Landing Analyzer** y pulsa el botón verde **Run ▶**. La configuración ya viene incluida; no escribas comandos.
6. Cuando la consola de PyCharm indique que el servidor está activo, abre [http://localhost:8080](http://localhost:8080) en tu navegador.

No necesitas instalar Node.js ni descargar recursos gráficos. La base SQLite se inicializa al arrancar. Si el puerto 8080 ya está ocupado, detén desde PyCharm la ejecución anterior de la aplicación. Horizons y PDS requieren internet; el modelo analítico sigue disponible sin conexión.

## Desplegar en Render

El archivo `render.yaml` configura un servicio web Python con el comando de compilación `pip install -r requirements.txt`, arranque de producción `gunicorn app:app --bind 0.0.0.0:$PORT` y comprobación de salud en `/health`. También solicita el plan pago de servicio web `0.5c-512mb` y un disco persistente de 1 GB montado en `/var/data`, con SQLite apuntando automáticamente a `/var/data/lunar_analyzer.sqlite3`. `gunicorn` está incluido en `requirements.txt`; no uses la configuración `.run` de PyCharm en Render. Para desplegar, conecta el repositorio Git desde Render como Blueprint; revisa el costo vigente del servicio y del disco antes de confirmar la creación.

La app ejecuta `data/schema.sql` automáticamente al arrancar. En local, SQLite se guarda por defecto en `data/lunar_analyzer.sqlite3`; `LUNAR_DATABASE_PATH` permite elegir otra ubicación. El disco persistente conserva la base de datos entre reinicios y despliegues, pero Render solo permite que lo use una instancia del servicio a la vez; el Blueprint mantiene el servicio en una instancia. La configuración de un disco no crea ni respalda por sí sola una copia externa de la base de datos. El servicio y el almacenamiento persistente generan cargos según los precios vigentes de Render; no se da por hecho ningún precio fijo.

El comando de compilación predeterminado instala solo dependencias básicas. SPICE continúa siendo opcional: si quieres instalar su librería en Render, cambia el Build Command a `pip install -r requirements.txt -r requirements-spice.txt` y configura `LUNAR_SPICE_META_KERNEL` para kernels compatibles que estén disponibles en el servicio. No se incluyen kernels; sin ellos, la app informa el estado y usa su respaldo.

## Funciones

- Catálogo local con sitios históricos y puntos polares de referencia; entrada y edición de coordenadas.
- Globo lunar interactivo en 3D: rotación, zoom, puntos de referencia seleccionables y selección de coordenadas sobre la esfera.
- Panel de control inspirado en centros de operaciones espaciales: telemetría por pestañas, estado de misión, gráficas, ventanas y eventos recientes.
- Los tres emblemas de misión giran lentamente sobre su eje; la animación respeta la preferencia del sistema para reducir movimiento.
- Balance radiativo estimado, desglose de flujo incidente/absorbido/emitido y conversión K/°C.
- Efemérides analíticas de baja precisión dependientes de fecha, distancia Sol-Luna y vector solar en un marco lunar síncrono aproximado.
- Consulta opcional de vectores Sol/Tierra de JPL Horizons para la fecha evaluada; se muestra el estado y se conserva el modelo local como respaldo.
- Búsqueda espacial bajo demanda de metadatos de productos LRO Diviner/LOLA mediante PDS Geosciences Node ODE REST.
- Uso opcional de kernels NASA SPICE locales configurados con un meta-kernel para calcular vectores en el marco IAU_MOON.
- Incidencia local `μ = N·S`, irradiancia `E₀ = 1361 / d²` (con `d` en UA), flujo incidente/reflejado y punto subsolar, todos ligados a la fecha seleccionada.
- La luz del globo 3D y la irradiancia/temperatura de sitio cambian al mover la fecha o el control temporal de 72 horas.
- Fracción iluminada de la superficie global (esfera ideal), fracción iluminada del disco visible desde la Tierra, y cribado cada seis horas durante 30 días.
- Evaluación geométrica aproximada de visibilidad terrestre, evaluación de terreno con valores del catálogo y comparación lado a lado.
- Diagnóstico Favorable/Precaución/Desfavorable con factores, riesgos, datos faltantes y limitaciones.
- Historial SQLite, descarga de informes PDF y CSV.

Los sitios con sufijo “referencia” son ubicaciones representativas para demostración; no son coordenadas oficiales de sitios de aterrizaje aprobados. La fecha seleccionada se consulta en Horizons al generar una evaluación; las coordenadas se envían a PDS ODE solo cuando pulsas el botón de búsqueda de productos. No se envían credenciales ni se necesita una clave API. Los SVG, estilos y JavaScript se sirven localmente; la previsualización no se guarda en el historial hasta que pulses **Evaluar sitio**.

## Alcance científico y datos que no están incluidos

Es un **demostrador de cribado**, no una herramienta de navegación o certificación de misión. Las consultas remotas tienen timeout y sus errores se muestran en la interfaz; si Horizons o SPICE no están disponibles, se usa el modelo analítico local. La búsqueda PDS es explícita y no activa descargas.

- El módulo térmico calcula un equilibrio radiativo instantáneo aproximado: flujo solar incidente, albedo, emisividad y radiación térmica emitida. Aplica un piso de demostración de 35 K en oscuridad; no resuelve fuentes térmicas subsuperficiales, conducción transitoria del regolito ni reproduce el instrumento Diviner.
- No se distribuyen observaciones LRO Diviner. El archivo `data/diviner_reference.csv` solo registra fuentes públicas. El botón **Buscar productos LRO** consulta el catálogo ODE por una caja de ±0,1° alrededor del punto e informa enlaces de productos Diviner (`DLRE/RDR4`) y LOLA (`LOLA/RDR4`). Los productos no se descargan, abren ni procesan dentro de la aplicación.
- Cada evaluación intenta consultar JPL Horizons para vectores de Sol y Tierra respecto al centro lunar en la fecha indicada. Sin SPICE, se proyectan al marco lunar síncrono aproximado del modelo; el cálculo no equivale a una orientación lunar de alta precisión. Si Horizons no responde, se conserva íntegramente el modelo kepleriano local.
- Los perfiles de 72 horas y el cribado de 30 días continúan con el modelo analítico local; Horizons/SPICE se aplican al instante evaluado, no a cada punto temporal de esas gráficas.
- No se distribuyen kernels SPICE. `spiceypy` es una dependencia opcional declarada en `requirements-spice.txt`; para activar SPICE, instálala, obtén kernels compatibles con la fecha estudiada y crea un meta-kernel `.tm` que cargue un kernel de segundos intercalares (LSK), orientación lunar (PCK) y efemérides planetarias (SPK). En PyCharm, configura la variable de entorno `LUNAR_SPICE_META_KERNEL` en **Run > Edit Configurations > Environment variables** con la ruta absoluta a ese `.tm`. Los kernels deben cubrir la fecha y marcos solicitados; si faltan o no cubren la fecha, la interfaz informa el problema y conserva Horizons o el modelo analítico. No se incluyen kernels grandes ni se atribuye precisión SPICE sin cargarlos correctamente. En Windows, si PyPI no ofrece un wheel compatible con el Python instalado, `spiceypy` puede requerir herramientas de compilación; el resto de la app no depende de esta instalación opcional.
- Para un punto de la superficie, el modelo evalúa `μ = N·S` sobre una esfera y usa `E_local = E₀ × max(μ, 0)`. El 50% global iluminado es una propiedad geométrica de una esfera sin relieve; el porcentaje del disco visible es una estimación de fase. Ninguna de esas cifras representa sombras de cráteres.
- No se incluye un DEM/LOLA validado. Por ello, **las sombras topográficas, la pendiente orientada y la irradiancia de facetas inclinadas no se calculan**. Las pendientes del catálogo son referencias demostrativas y las coordenadas personalizadas se muestran sin pendiente. El panel lo informa en vez de inventar cobertura topográfica.
- El globo 3D se genera localmente con relieve visual, variación de albedo, cráteres y sombreado esférico. En cada vista solo se proyecta el hemisferio frontal; la cara posterior y sus marcadores quedan ocultos por profundidad, y al rotar cambia el hemisferio orientado al observador. Es una visualización ilustrativa, no un modelo de elevación ni terreno LRO. Pendientes y rugosidad de los sitios de referencia son datos de demostración.
- La elevación de la Tierra es una visibilidad geométrica aproximada, no una predicción de enlace de comunicaciones.
- La puntuación y el diagnóstico son orientativos, no constituyen una aprobación de NASA.

Para análisis de misión real, se deben descargar y validar por separado los productos Diviner/DEM y kernels SPICE adecuados; su volumen, cobertura, licencias y configuración dependen del estudio. La aplicación no convierte los metadatos PDS en mediciones térmicas o topográficas.

## Fuentes de las integraciones

- JPL Horizons API: [documentación](https://ssd-api.jpl.nasa.gov/doc/horizons.html) · endpoint `https://ssd.jpl.nasa.gov/api/horizons.api`.
- PDS Geosciences Node ODE REST: [interfaz y manual](https://oderest.rsl.wustl.edu/).
- NASA NAIF SPICE: [catálogo de kernels](https://naif.jpl.nasa.gov/naif/data.html).

## Estructura

```text
LunarLandingAnalyzer/
├── app.py
├── lunar_analyzer/
│   ├── __init__.py
│   ├── integrations.py
│   └── science.py
├── data/
│   ├── sites.json
│   ├── diviner_reference.csv
│   └── schema.sql
├── static/
│   ├── css/app.css
│   ├── js/app.js
│   └── img/
│       ├── moon.svg
│       ├── mission-emblem.png
│       └── lander.svg
├── templates/index.html
├── tests/
│   ├── test_dashboard.py
│   └── test_science.py
├── .run/Lunar Landing Analyzer.run.xml
├── render.yaml
├── requirements.txt
├── requirements-spice.txt
└── README.md
```

El ZIP de entrega excluye entornos virtuales, cachés, carpetas de configuración personal de PyCharm y la base SQLite mutable; SQLite se crea al iniciar la app.
