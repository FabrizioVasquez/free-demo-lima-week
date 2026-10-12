# Brújula Tech Week

Recomendador de eventos de **Perú Tech Week 2026** (12–18 oct, Lima). Escribes quién eres y qué buscas; un buscador
vectorial **100 % local** elige los eventos y muestra, paso a paso, por qué.

- **Búsqueda semántica**: LanceDB + embeddings multilingües locales (`fastembed`, ONNX; sin GPU ni API keys).
- **Razonamiento visible**: cada evento recibe nota en 5 criterios con pesos que se adaptan a tu prompt
  (afinidad semántica, calce con tu objetivo, disponibilidad, alcance de la comunidad, logística).
  Ves la matriz, el rastro `[SEM] [OBJ] [DISP] [ESC] [LOG]`, los choques de horario y los eventos descartados con su motivo.
- **Agotados y cupos** salen de Luma, no de un modelo.
- **Scraper** con `httpx` o con **Crawl4AI** (navegador con tu sesión de Luma).

## Inicio rápido (uv)

```bash
uv sync                  # instala dependencias
uv run btw serve         # http://127.0.0.1:8000  (la primera vez baja el modelo, ~220 MB, e indexa)
```

`data/events.json` ya viene versionado, así que no necesitas scrapear para empezar.

## Comandos

| Comando | Qué hace |
|---|---|
| `uv run btw serve [--port 8000]` | Levanta la app web |
| `uv run btw ask "mi prompt" --top 3` | Consulta desde la terminal (JSON) |
| `uv run btw scrape` | Descarga los eventos de Luma (httpx) |
| `uv run btw index` | Reconstruye la base vectorial |
| `uv run btw refresh` | `scrape` + `index` |
| `uv run --extra browser btw login` | Abre un navegador para iniciar sesión en Luma (una vez) |
| `uv run --extra browser btw scrape --browser` | Scrapea con Crawl4AI usando esa sesión |

Para el modo navegador instala Chromium una vez: `uv run --extra browser python -m playwright install chromium`.
La sesión se guarda en `data/browser-profile/` (ignorado por git: **contiene cookies, nunca lo subas**).

## Cómo decide

1. **Interpreta tu prompt**: días, horario, distrito, formato, "top N" y objetivos (aprender, networking, empleo, inversión, construir).
2. **Recupera** fragmentos desde LanceDB con prefiltros (terminados, días, agotados, formato, distrito).
   Al índice solo le llega el significado de tu texto; lugar y horario los evalúa la logística.
3. **Pondera** 5 criterios. Los pesos cambian según lo que pides (sin objetivos explícitos, pesa más la semántica;
   con restricciones de lugar u horario, pesa más la logística).
4. **Explica** cada nota y lista los eventos parecidos que quedaron fuera.

## Estructura

```
src/brujula/   config · scrape · embed · index · search · server · cli · static/ (UI)
tests/         pruebas del intérprete de prompts
data/          events.json (versionado) · lancedb/ y models/ (se regeneran)
scripts/       gcp-setup.sh (prepara Google Cloud una sola vez)
.github/       ci.yml · deploy.yml · refresh-data.yml
```

## Mantenimiento con GitHub Actions

| Workflow | Cuándo | Qué hace |
|---|---|---|
| `ci.yml` | cada PR y push | `ruff` + `pytest` |
| `refresh-data.yml` | cada 6 h | re-scrapea Luma; si cambió algo, commitea `data/events.json` y dispara el despliegue |
| `deploy.yml` | push a `main` | construye la imagen y despliega en Cloud Run |

> `refresh-data.yml` está pensado para la semana del evento; desactívalo después del 18 de octubre de 2026.

## Despliegue en Google Cloud Run

Autenticación **sin llaves** (Workload Identity Federation): GitHub no guarda ningún secreto de Google.

```bash
gcloud auth login
scripts/gcp-setup.sh <PROJECT_ID> FabrizioVasquez/free-demo-lima-week
```

El script imprime cuatro variables (`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SERVICE_ACCOUNT`, `GCP_WIF_PROVIDER`).
Guárdalas en *Settings → Secrets and variables → Actions → Variables* y haz push a `main`.
El proyecto necesita **facturación activa** para Cloud Run y Artifact Registry. La imagen se construye con el índice y el modelo
ya dentro, así que el arranque no descarga nada. Con `--min-instances=0` no pagas mientras nadie la usa. La región es `us-central1` (Tier 1 de Cloud Run, ~40 % más barata que las de Sudamérica, que son Tier 2).

## Pruebas

```bash
uv run ruff check src tests
uv run pytest -q
```
