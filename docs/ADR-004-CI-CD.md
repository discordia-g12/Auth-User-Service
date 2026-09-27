# ADR-004: Pipeline de CI y alcance de CD

- **Estado:** Aceptado
- **Fecha:** 2026-09-27
- **Alcance:** `auth-user-service`
- **Reemplaza a:** `ADR-03-CI-CD-Pipeline.md`

---

## 1. Contexto

El enunciado exige un pipeline de CI que corra en cada push y **bloquee el merge** ante fallas, con
una cobertura mínima de 85% en los servicios backend. También recomienda análisis estático de
seguridad (SAST). Además exige CD (despliegue automático desde `main` o por tags), documentado.

## 2. Decisión

Workflow: `.github/workflows/ci.yml`. Se dispara en cada push y pull request a `main` y `develop`.

### Job `test`

| Paso | Herramienta | Notas |
|------|-------------|-------|
| Entorno | Python 3.12 + Postgres 16 como *service container* | Mismas versiones que la imagen (`python:3.12-slim`) y que `auth-db` en `discordia-orchestrator` (`postgres:16-alpine`) |
| Dependencias | `pip install -r requirements-dev.txt` | `requirements.txt` tiene solo el runtime (lo que instala la imagen); `requirements-dev.txt` le suma test, lint y SAST |
| Lint | `ruff check .` | Reglas `E`, `F`, `I`, `UP`; `alembic/versions` excluido por ser autogenerado |
| SAST | `bandit -r app -ll` | Liviano, específico de Python y sin requerir GitHub Advanced Security |
| Migraciones | `alembic upgrade head` contra el Postgres del job | Verifica que las migraciones aplican sobre un Postgres real |
| Tests y cobertura | `pytest --cov=app --cov-fail-under=85` | `pytest` + `pytest-asyncio` + `httpx` (`ASGITransport`, sin levantar un servidor); reporte `coverage.xml` como artefacto |

Toda la configuración de ruff, pytest y coverage vive en **`pyproject.toml`** (sin `ruff.toml` ni
`pytest.ini`), así el CI y la ejecución local usan exactamente las mismas reglas, incluido el umbral
`fail_under = 85`.

### Job `docker-build`

Depende de `test`. Corre `docker build` sobre el `Dockerfile` sin hacer push, para verificar en cada
cambio que la imagen de producción sigue compilando.

### Bloqueo de merge

El job `test` es un *required status check* en `main` y `develop`. El merge nunca es automático.

### Base de datos de los tests

**Los tests usan SQLite en memoria** (`aiosqlite` + `StaticPool`), no el Postgres del job. Ese
Postgres solo valida las migraciones. Se eligió SQLite por velocidad y aislamiento: se crea una base
nueva por test, sin estado compartido.

## 3. CD: fuera de alcance

El enunciado pide documentar en un ADR la plataforma de despliegue antes de automatizarlo. Como esa
decisión todavía no existe, **CD queda pendiente**: no se inventa un destino de despliegue solo para
completar el pipeline. Cuando exista, se agrega un job de CD y se actualiza este ADR.

## 4. Consecuencias

- Cualquier PR que rompa el lint, el SAST, las migraciones, un test, la cobertura o el build de la imagen queda bloqueado.
- **Riesgo conocido: SQLite puede enmascarar diferencias con Postgres,** como nombres de constraints y mensajes de `IntegrityError`, tipos (`JSON`/`JSONB`) o el manejo de zonas horarias. Hoy está acotado porque el servicio ante cualquier `IntegrityError` responde un `409` genérico, sin parsear el error del motor. **Mejora pendiente:** que `conftest.py` tome la URL de una variable (p. ej. `TEST_DATABASE_URL`), con SQLite por defecto en local, y que el CI corra la suite contra el Postgres del job.
- Con más lógica de negocio, el umbral de 85% va a exigir tests reales de esa lógica, no solo de health checks y modelos.
