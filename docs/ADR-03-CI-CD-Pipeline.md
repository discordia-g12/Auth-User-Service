## ADR 03: Pipeline de CI y alcance de CD

**Contexto:**
El enunciado del TP exige un pipeline de CI que corra automáticamente ante cada push y **bloquee el merge** ante fallas en los tests, con cobertura mínima del 85% en los servicios backend, y recomienda incorporar análisis estático de seguridad (SAST). También exige CD (despliegue automático a producción desde `main` o por tags), documentado.

**Decisión:**

* **Test runner:** `pytest` + `pytest-asyncio` + `httpx` (cliente `ASGITransport` contra la app FastAPI, sin levantar un servidor real). Se agregaron los primeros tests del repo (`tests/test_health.py`, `tests/test_models.py`) — antes de este ADR `tests/` estaba vacío.
* **Lint:** `ruff`, con `alembic/versions/` excluido — son archivos autogenerados, y lintearlos rompería el CI en cada migración nueva por motivos de estilo, no de errores reales.
* **SAST:** `bandit -r app -ll`, tal como recomienda el enunciado. Se eligió por ser liviano, específico de Python, y no requerir GitHub Advanced Security (que exigiría un plan pago o repo público para usar CodeQL).
* **Cobertura:** `pytest-cov` con `--cov-fail-under=85`, bloqueando el merge por debajo del mínimo exigido. Se corrió Postgres como *service container* en el job para que las migraciones y los tests de modelo corran contra una base real, no mockeada.
* **Build de imagen:** job separado (`docker-build`) que corre `docker build` sobre el `Dockerfile` existente, sin push — valida que la imagen de producción sigue siendo buildable en cada push, pero no hay a dónde publicarla todavía (ver más abajo).
* **Bloqueo de merge:** el job `test` se configuró como *required status check* en `main` y `develop` desde GitHub (Settings → Branches) — un CI en rojo deshabilita el botón de merge del PR. El merge nunca es automático: pase o falle el CI, alguien tiene que clickear "Merge" a mano (no se activó auto-merge en ningún lado).

**CD — explícitamente fuera de alcance de este ADR:**
El enunciado exige documentar en un ADR la elección de plataforma de despliegue (PaaS, orquestador de contenedores gestionado, o cloud provider) antes de automatizar el deploy. A la fecha de este ADR no existe esa decisión en `docs/architecture/decisions/` del repo `.github` (llega hasta el ADR 0009, ninguno cubre infraestructura de despliegue). Automatizar un deploy sin ese ADR previo violaría el propio enunciado, así que **CD queda pendiente** hasta que exista esa decisión — no se inventa un target de despliegue solo para completar el pipeline.

**Consecuencias:**

* El pipeline queda verde con muy pocos tests reales — la cobertura del 85% se alcanza porque el código actual es casi todo configuración y modelos declarativos, no porque haya lógica de negocio bien testeada. A medida que se agreguen features, el umbral del 85% va a exigir tests reales de esa lógica, no solo de health checks.
* Cualquier PR que baje la cobertura por debajo del 85%, rompa el lint, falle un test, o rompa el build de la imagen Docker, queda bloqueado para mergear — consistente con la Red Line del enunciado ("Pipeline de CI roto... bloqueante").
* Cuando exista un ADR de infraestructura de despliegue, este ADR debe actualizarse (o crearse uno nuevo) agregando el job de CD correspondiente.
