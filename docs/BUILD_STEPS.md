# Cómo se construyó, paso a paso

Cada paso dice qué se hizo, qué falló o se midió y qué se decidió. Es el registro real de la construcción, no una versión pulida.

## 1. Obtener los datos
**Qué:** Luma no ofrece una API pública. La página trae los primeros 20 eventos dentro de `__NEXT_DATA__` y el resto sale paginando el endpoint `calendar/get-items`; cada descripción vive en la página del evento.
**Falló:** al pedir los 105 eventos en paralelo, Luma respondió **429**. El scraper dejó 31 eventos sin descripción *sin avisar*.
**Decisión:** reintentos con espera (`Retry-After`), concurrencia baja y conservar la descripción anterior si un reintento falla. Modo alternativo con **Crawl4AI** y un perfil de navegador propio, para el caso en que Luma exija sesión.
**Detectado después:** en modo navegador el JSON llega dentro de un `<pre>` HTML y los nombres aparecían como `Fintech &amp; Proptech`. Se corrigió con `html.unescape`.

## 2. Elegir el modelo de embeddings
**Qué:** se compararon `paraphrase-multilingual-MiniLM-L12-v2` y `potion-multilingual-128M` con 15 consultas de respuesta conocida (`scripts/bench_embeddings.py`).
**Medido:** calidad equivalente (MRR 0.89 en ambos); MiniLM pesa la mitad y usa menos memoria. Se eligió MiniLM. Detalle en [ARCHITECTURE.md](ARCHITECTURE.md#decisiones).

## 3. Indexar en LanceDB
**Qué:** cada evento se divide en fragmentos y se guarda con su vector y metadatos (día, estado, distrito, formato) para poder prefiltrar con SQL.
**Falló (y no se veía):** el primer fragmentador cortaba por **70 palabras**. Al medir con el tokenizador real, **154 de 381 fragmentos (40 %) superaban los 128 tokens** del modelo, hasta 179, y el modelo descartaba el final en silencio.
**Decisión:** fragmentador por **tokens** (≤120, solape de 16) que mide con el mismo tokenizador. Resultado: 0 de 475 fragmentos sobre el límite, máximo 123. La calidad no cambió (MRR 0.894 → 0.890); fue un arreglo de corrección.

## 4. Buscar y puntuar
**Qué:** intérprete por reglas (días, horario, distrito, formato, objetivos), búsqueda vectorial con prefiltro y una matriz de 5 criterios con pesos que se adaptan al prompt.
**Falló en la primera prueba:**
- Un hackathon en **Trujillo** quedaba primero para alguien que vive en Surco: la penalización por distrito era mínima. Se añadió una penalización fuerte para eventos fuera de Lima.
- El texto "vivo en Surco, por las tardes" contaminaba el significado de la consulta. Ahora al índice solo llega el significado; lugar y horario los evalúa la logística.
- La logística pesaba tanto como la semántica. Se bajó su peso y se rebalanceó el resto.

## 5. Interfaz con razonamiento visible
Cada tarjeta muestra el rastro `[SEM] [OBJ] [DISP] [ESC] [LOG]` con la nota y la frase que la justifica, la matriz completa, los cruces de horario y los eventos parecidos que quedaron fuera con su motivo. Estilo inspirado en ai.engineer/code/2026.

## 6. Prueba local (encontró 4 errores)
Se ejercitó la API con varios prompts y la interfaz con un navegador real (Playwright):
1. `&amp;` en nombres (ver paso 1).
2. "**solo** virtual" se trataba como preferencia; ahora es filtro.
3. El selector de la interfaz siempre enviaba 5 y pisaba el "top 3" escrito en el texto.
4. Un texto sin sentido ("asdf") devolvía resultados sin aviso; se añadió un umbral de similitud de 0.40.

## 7. Endurecimiento de seguridad
Validación estricta de entrada, lista blanca de distrito (el valor acaba en un `WHERE`), límite de tasa por IP, cabeceras (CSP, HSTS, nosniff), sin `/docs`, imagen multi-etapa con usuario sin privilegios y sin red al arrancar. En Google Cloud: identidad de ejecución **sin roles**, deployer acotado a recursos concretos y federación de identidad restringida a la rama `main`. Detalle en [SECURITY.md](SECURITY.md).

## 8. Calibrar el coste
Memoria del servidor medida: **107 MB en reposo y 507 MB** con el modelo cargado tras 15 búsquedas, así que `1 GiB` en Cloud Run deja el doble de margen. La región `us-central1` es de nivel 1 de precios: según el catálogo oficial cuesta ~40 % menos por vCPU-segundo y GiB-segundo que `southamerica-west1`. Con `min-instances=0` no se paga mientras nadie la usa.

## 9. Automatizar
- **CI:** `ruff`, `pytest` (30 pruebas), `bandit`, `pip-audit`.
- **Refresco de datos cada 6 h:** re-scrapea, valida el JSON y, si cambió algo, hace commit y lanza el despliegue.
- **Despliegue:** construye la imagen, la sube a Artifact Registry y actualiza Cloud Run, autenticándose por OIDC.

## Qué aprendí
- Una medición vale más que una suposición: el límite de tokens y la elección del modelo se resolvieron con datos.
- Los errores silenciosos son los caros (429 sin aviso, truncado de tokens). Ahora el sistema falla en voz alta.
- Probar de verdad, con un navegador real y prompts reales, encontró cuatro errores que las pruebas unitarias no veían.
