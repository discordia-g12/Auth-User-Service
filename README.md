# Auth-User-Service

Servicio de dominio de usuarios de Discordia (FastAPI + SQLAlchemy async + PostgreSQL).
Gestiona el registro de negocio del usuario y su perfil público, y emite eventos de dominio
mediante Transactional Outbox.

**No gestiona credenciales.** Registro, login, contraseñas, verificación de email y emisión
de tokens son de Auth0. El servicio confía en la identidad que le inyecta el API Gateway
(Kong) vía headers, después de validar el JWT (ver [ADR-001](docs/ADR-001-Identidad-Auth0.md)).

## Endpoints

| Método | Path | Descripción | Respuestas |
|--------|------|-------------|------------|
| `POST` | `/api/v1/users/me` | Provisiona el usuario y su perfil para la identidad autenticada | `201`, `400`, `401`, `403`, `409`, `422` |
| `GET` | `/api/v1/users/me` | Devuelve el perfil propio. El `404` es el discriminador de onboarding del cliente | `200`, `401`, `404` |
| `GET` | `/livez` | Liveness, sin I/O | `200` |
| `GET` | `/readyz` | Readiness: verifica la base de datos. Ante una falla no expone el detalle del error, que solo queda en el log | `200`, `503` |

Los errores siguen RFC 7807 (`application/problem+json`). Los clientes solo deben ramificar
por el campo `type`: hoy el único `type` propio es
`https://discordia.app/problems/email-not-verified` (403).

Swagger UI: `http://localhost:8004/docs`.

### Contrato de headers (inyectados por Kong)

| Header | Uso en este servicio |
|--------|----------------------|
| `X-User-Id` | Obligatorio. Es el `sub` de Auth0 y se trata como identificador opaco (`401` si falta) |
| `X-User-Email` | Obligatorio para `POST /me` (`400` si falta) |
| `X-User-Email-Verified` | Para `POST /me` solo se acepta el literal `true`, sin distinguir mayúsculas. Cualquier otro valor da `403` (fail-closed) |
| `X-User-Role` | Este servicio no lo usa. La autorización por rol se hace en el Gateway |

## Desarrollo local

Este repo no tiene `docker-compose.yml` propio: el servicio se levanta desde
`discordia-orchestrator`, donde se llama `auth-service` y su base `auth-db`. Todos los
comandos de `docker compose` se corren desde el directorio del orquestador.

```bash
# Plataforma completa: las requests entran por Kong en :8000
docker compose up -d

# Solo este servicio y su base, sin el resto de la plataforma
docker compose up -d auth-service     # levanta también auth-db por depends_on
```

| Servicio | Dentro de `discordia-net` | Desde el host |
|----------|---------------------------|---------------|
| `auth-service` | `auth-service:8000` (así lo alcanza Kong) | `localhost:8004` (Swagger en `/docs`) |
| `auth-db` | `auth-db:5432` | `localhost:5436` |

El puerto `8004` va directo al servicio, salteando Kong: los headers `X-User-*` se mandan a
mano. Sirve para desarrollo y pruebas con Swagger; nunca debe publicarse en un entorno desplegado.

**Recarga en caliente:** el `docker-compose.override.yml.example` del orquestador monta este repo
como volumen y arranca uvicorn con `--reload`. Se activa copiándolo a `docker-compose.override.yml`.

### Tests, Alembic o la app desde el host

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt   # requirements.txt (runtime) + herramientas de test/lint/SAST
cp .env.example .env                  # apunta a auth-db del orquestador (localhost:5436)

# desde discordia-orchestrator
docker compose up -d auth-db

# desde este repo
alembic upgrade head
```

Los tests no necesitan base de datos: usan SQLite en memoria.

## Tests, lint y seguridad

```bash
ruff check .              # lint
bandit -r app -ll         # SAST
pytest --cov=app          # tests + cobertura (falla por debajo de 85%)
```

Toda la configuración de herramientas está en `pyproject.toml`. Los tests corren contra
SQLite en memoria (ver las limitaciones en [ADR-004](docs/ADR-004-CI-CD.md)).

El CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) corre estos mismos comandos,
más `alembic upgrade head` contra Postgres 16 y el build de la imagen, en cada push y PR a
`main` y `develop`. Si alguno falla, el merge queda bloqueado.

## Decisiones de arquitectura

| ADR | Tema | Estado |
|-----|------|--------|
| [ADR-001](docs/ADR-001-Identidad-Auth0.md) | Delegación de identidad en Auth0 y contrato de identidad con el Gateway | Aceptado |
| [ADR-002](docs/ADR-002-Suspension-Usuarios.md) | Suspensión de usuarios y corte de sesiones | Propuesto |
| [ADR-003](docs/ADR-003-Avatares.md) | Almacenamiento y gestión de avatares | Aceptado, implementación parcial |
| [ADR-004](docs/ADR-004-CI-CD.md) | Pipeline de CI y alcance de CD | Aceptado |
| [ADR-005](docs/ADR-005-Transactional-Outbox.md) | Transactional Outbox para eventos de dominio | Aceptado, implementación parcial |
