# Modelo de amenazas

Alcance: la app pública en Cloud Run, su imagen, el pipeline de GitHub Actions y la identidad en Google Cloud. La app no tiene cuentas de usuario, base de datos de usuarios ni secretos; el dato más sensible que procesa es el texto que alguien escribe como perfil.

## Superficie y controles

| # | Amenaza | Control | Dónde | Cómo se comprueba |
|---|---|---|---|---|
| 1 | Inyección en los filtros de búsqueda (día, distrito, formato) | **No se construye texto de consulta**: Qdrant recibe objetos tipados, así que un valor malicioso es solo un dato que no coincide con nada. Además: días con regex estricta, formato en lista cerrada, distrito en lista blanca, y la validación se repite dentro de `search()` | `server.py`, `search.py` | `test_invalid_payloads_are_rejected` (10 casos), `test_filter_values_are_data_not_query_text` |
| 2 | XSS desde datos de terceros (los nombres vienen de Luma) | Todo texto dinámico pasa por `esc()` antes de entrar al DOM; URL de evento construida por código con prefijo fijo; CSP `script-src 'self'` sin `unsafe-eval` ni scripts en línea | `static/app.js`, `security.py` | `test_security_headers_everywhere`; revisión de `innerHTML` |
| 3 | Datos de Luma manipulados entran al repositorio | El job de refresco valida cantidad, forma de la URL (`https://luma.com/`) y estados antes de hacer commit | `refresh-data.yml` | Falla el job si no se cumple |
| 4 | Abuso y gasto (cada búsqueda cuesta CPU) | 20 búsquedas/min por IP (se usa la IP que **añade** Google, no la que escribe el cliente), cuerpo ≤ 8 KB, prompt ≤ 1500 caracteres, `--max-instances=2`, `--timeout=30s` | `security.py`, `deploy.yml` | `test_rate_limiter_*`, `test_client_ip_ignores_spoofed_prefix`, `test_oversized_body_is_rejected_early` |
| 5 | Reconocimiento de la API | Sin `/docs`, `/redoc` ni `/openapi.json`; errores genéricos sin trazas; `--no-server-header` | `server.py`, `Dockerfile` | `test_api_is_not_cached_and_docs_are_off` |
| 6 | Recorrido de rutas en archivos estáticos | Solo se sirve `src/brujula/static`; el recorrido devuelve 404 | `server.py` | `test_wrong_method_and_path_traversal` |
| 7 | Escalada si alguien ejecuta código en el contenedor | Usuario 10001 sin shell; código y índice propiedad de root (solo lectura para la app); imagen final sin `uv`, compiladores ni caché de apt; sin red hacia Hugging Face (`HF_HUB_OFFLINE=1`) | `Dockerfile` | Ver *Verificación de la imagen* en el README |
| 8 | Escalada en Google Cloud desde ese contenedor | La app corre como `brujula-runtime`, que **no tiene ningún rol** | `scripts/gcp-setup.sh` | El paso 8 del script lista los roles de cada cuenta |
| 9 | Robo de credenciales de despliegue | No existen llaves: Workload Identity Federation. Solo el repositorio `FabrizioVasquez/free-demo-lima-week` y solo la rama `main` pueden asumir el deployer | `gcp-setup.sh` (condición del proveedor) | Un workflow de otra rama o repo es rechazado por Google |
| 10 | El deployer se usa para escalar | Sus permisos están acotados a **un** repositorio de imágenes, **un** servicio de Cloud Run y la identidad `brujula-runtime`. No puede cambiar el IAM del servicio ni crear otros | `gcp-setup.sh` | Roles listados a nivel de proyecto: solo `serviceUsageConsumer` |
| 11 | Cadena de suministro en CI | Acciones fijadas por SHA de commit; `permissions` mínimos por workflow; `persist-credentials: false` salvo en el job que hace push; Dependabot semanal para acciones, Docker y `uv` | `.github/` | `grep "@[0-9a-f]{40}"` en los workflows |
| 12 | Dependencias vulnerables | `pip-audit` y `bandit` en CI en cada PR; `uv.lock` con versiones exactas y `--frozen` | `ci.yml` | Última ejecución local: 0 vulnerabilidades, 0 hallazgos de severidad media o alta |
| 13 | Secretos en el repositorio | `.gitignore` excluye `data/browser-profile` (cookies de Luma), `.env`, índice y modelos; búsqueda de patrones de claves en todo el historial | `.gitignore` | Escaneo del historial: sin coincidencias |
| 14 | Sustitución de imagen publicada | Repositorio de imágenes con tags inmutables; las imágenes se etiquetan con el SHA del commit | `gcp-setup.sh`, `deploy.yml` | — |

## Riesgos residuales (decisiones conscientes)

- **El servicio es público** (`allUsers` con `run.invoker`): es el propósito de la app. Cualquiera puede invocarlo; el daño posible se limita a CPU y a un máximo de 2 instancias.
- **El límite de tasa es por instancia** y en memoria. Una persona con muchas IPs puede superarlo; no sustituye a un WAF (Cloud Armor), que aquí costaría más que la app.
- **Las imágenes base se fijan por etiqueta, no por digest.** Dependabot propone las actualizaciones; fijar el digest daría reproducibilidad total a cambio de mantenimiento manual.
- **El raspado depende de la estructura de Luma.** Si cambia, el job de refresco falla en voz alta en vez de publicar datos rotos.
- **Falta configurar en GitHub** (no se puede desde el código): protección de la rama `main` (PR obligatorio y CI en verde) y *secret scanning*. Se recomienda activarlos.
- **Falta una alerta de presupuesto** en Google Cloud para avisar de un gasto inesperado.

## Reportar una vulnerabilidad

Abre un *Security advisory* privado en el repositorio de GitHub.
