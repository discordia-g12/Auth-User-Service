# Auth-User-Service

Servicio de usuarios de Discordia (Python 3.12, FastAPI, SQLAlchemy async y PostgreSQL). Guarda el
registro de negocio de cada usuario y su perfil público (nombre visible, bio, estado, avatar), y publica
eventos de dominio con un Transactional Outbox.

**No maneja credenciales.** Registro, login, contraseñas, verificación de email y emisión de tokens son de
Auth0. El servicio confía en la identidad que le pasa el API Gateway (Kong) en headers, después de validar
el JWT ([ADR-001](docs/ADR-001-Identidad-Auth0.md)).

## Requisitos

- Python 3.12 (la versión de la imagen y del CI).
- Docker, para PostgreSQL y, si se usa el worker de outbox, RabbitMQ.

## Levantarlo en local

```bash
# 1. Dependencias
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt        # runtime + test, lint y SAST

# 2. Configuración: el ejemplo apunta a Postgres en localhost:5436 y RabbitMQ en localhost:5672
cp .env.example .env

# 3. PostgreSQL (la misma versión que el RDS de producción)
docker run -d --name auth-db -p 5436:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=auth_db postgres:18-alpine

# 4. Migraciones y servidor con recarga en caliente
alembic upgrade head
uvicorn app.main:app --reload --port 8004
```

Probarlo (Swagger en `http://localhost:8004/docs`):

```bash
curl localhost:8004/livez     # {"status":"alive"}
curl localhost:8004/readyz    # {"status":"ready"} si llega a la base

# Sin Kong adelante, los headers de identidad se mandan a mano
curl -X POST localhost:8004/api/v1/users/me \
  -H 'X-User-Id: auth0|local-test' -H 'X-User-Email: test@example.com' -H 'X-User-Email-Verified: true' \
  -H 'Content-Type: application/json' -d '{"username":"localtest"}'
curl localhost:8004/api/v1/users/me -H 'X-User-Id: auth0|local-test'
```

El puerto `8004` va directo al servicio, sin pasar por Kong: sirve para desarrollo y nunca se publica en
producción, porque cualquiera podría mandar un `X-User-Id` falso.

Con `ENVIRONMENT=development` (el valor del ejemplo), SQLAlchemy loguea cada consulta.

### Worker de outbox (opcional)

Los cambios guardan su evento en `outbox_events` en la misma transacción. Un proceso aparte los publica en
RabbitMQ (exchange `user.events`). Sin el worker, la API funciona igual y los eventos esperan en la base.

```bash
docker run -d --name auth-rabbitmq -p 5672:5672 -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=admin -e RABBITMQ_DEFAULT_PASS=admin rabbitmq:3-management-alpine

python -m app.workers.outbox_publisher
# "Outbox publisher conectado a RabbitMQ" y después "Published user.registered (...)"
```

El panel de RabbitMQ queda en `http://localhost:15672` (`admin` / `admin`).

### Con la imagen de Docker

Es lo que corre en producción: aplica las migraciones y arranca uvicorn en el 8000.

```bash
docker build -t auth-service .
docker run --rm -p 8004:8000 -e DATABASE_HOST=host.docker.internal -e DATABASE_PORT=5436 auth-service

# El worker es la misma imagen con otro comando
docker run --rm -e DATABASE_HOST=host.docker.internal -e DATABASE_PORT=5436 \
  -e RABBITMQ_HOST=host.docker.internal auth-service python -m app.workers.outbox_publisher
```

### Con el resto del sistema

Para levantarlo junto con el Gateway y los demás servicios, usar el compose del orquestador
(`discordia-orchestrator/deploy/docker-compose.yml`, profile `local`). Ahí el servicio se llama
`auth-service`, el worker `auth-outbox-worker`, y se entra por Kong en `localhost:8000`.

Bajar los contenedores de esta guía: `docker rm -f auth-db auth-rabbitmq`.

## Variables de entorno

Se leen del entorno o de `.env` (el entorno tiene prioridad). Los defaults del código son los del compose;
los de `.env.example`, los del host.

| Variable | Default | Descripción |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | En `development`, SQLAlchemy loguea las consultas |
| `DATABASE_HOST` / `DATABASE_PORT` | `auth-db` / `5432` | PostgreSQL |
| `DATABASE_NAME` / `DATABASE_USER` / `DATABASE_PASSWORD` | `auth_db` / `postgres` / `postgres` | Base y credenciales |
| `RABBITMQ_HOST` / `RABBITMQ_PORT` | `rabbitmq` / `5672` | Broker del worker de outbox |
| `RABBITMQ_USER` / `RABBITMQ_PASSWORD` | `admin` / `admin` | Credenciales del broker |
| `RABBITMQ_EXCHANGE` | `user.events` | Exchange (topic) donde se publican los eventos |
| `AUTH0_DOMAIN` | — | Dominio del tenant. Sin él, el recupero de contraseña responde `503` |
| `AUTH0_CLIENT_ID` | — | `client_id` público de la app de Auth0 (el mismo que usan web y mobile) |
| `AUTH0_DB_CONNECTION` | `Username-Password-Authentication` | Conexión de base de datos de Auth0 |
| `AUTH0_TIMEOUT_SECONDS` | `5.0` | Timeout de las llamadas a Auth0 |
| `AUTH0_MGMT_CLIENT_ID` / `AUTH0_MGMT_CLIENT_SECRET` | — | Aplicación *Machine to Machine* de Auth0 con `read:users` y `update:users` sobre la Management API. Bloquea y desbloquea cuentas al suspender. Sin ellas, suspender responde `503`. El secret no se commitea |
| `GATEWAY_REDIS_HOST` / `GATEWAY_REDIS_PORT` | `gateway-redis` / `6379` | Redis del Gateway, donde va la lista de cuentas suspendidas que consulta Kong |
| `SUSPENSION_DENYLIST_TTL_SECONDS` | `86400` | Vida máxima del access token en Auth0. Tiene que coincidir con el valor configurado en la API de Auth0 |
| `PASSWORD_RESET_MAX_REQUESTS` / `PASSWORD_RESET_WINDOW_SECONDS` | `3` / `900` | Límite de pedidos de recupero por email |
| `AWS_REGION` | `us-east-1` | Región del bucket |
| `S3_BUCKET` | — | Bucket de avatares. Sin bucket o sin claves, la subida responde `503` y el resto funciona |
| `S3_PUBLIC_BASE_URL` | `https://<bucket>.s3.<region>.amazonaws.com` | Base de las URLs públicas que se guardan |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | Claves del usuario IAM del servicio, o de uno de desarrollo (pedirlas al equipo; no se commitean) |

## Endpoints

| Método | Path | Descripción | Respuestas |
|--------|------|-------------|------------|
| `POST` | `/api/v1/users/me` | Crea el usuario y su perfil para la identidad autenticada | `201`, `400`, `401`, `403`, `409`, `422` |
| `GET` | `/api/v1/users/me` | Perfil propio. El `404` le indica al cliente que falta crear el perfil (onboarding). Una cuenta suspendida recibe `403` (`account-suspended`) | `200`, `401`, `403`, `404` |
| `POST` | `/api/v1/users/bulk` | Perfiles públicos de hasta 100 usuarios (`{"user_ids": [...]}`). De una cuenta suspendida solo vuelve el nombre, con `is_suspended: true` (perfil no disponible) | `200`, `401`, `422` |
| `PATCH` | `/api/v1/users/me/profile` | Edita `username`, `display_name`, `bio` o `custom_status` | `200`, `401`, `404`, `409`, `422` |
| `PATCH` | `/api/v1/users/me/profile/avatar` | Sube el avatar (`multipart/form-data`, campo `file`; JPEG, PNG o WebP hasta 5 MB). Se guarda en S3 como WebP de 256×256 | `200`, `401`, `422` (formato o tamaño), `503` (sin S3) |
| `GET` | `/api/v1/users/{user_id}/profile` | Perfil público con `relationship` (`none`, `friend`, `request_sent`, `request_received`, `blocked`). Nunca trae el email ni dice si el otro te bloqueó. Si la cuenta está suspendida o no existe, `404` | `200`, `401`, `404` |
| `GET` | `/api/v1/users/me/friends` | Amigos. Un amigo suspendido solo muestra el nombre | `200`, `401` |
| `DELETE` | `/api/v1/users/me/friends/{user_id}` | Saca la amistad. Idempotente | `204`, `401` |
| `GET` | `/api/v1/users/me/friend-requests` | Solicitudes pendientes: `{ incoming, outgoing }` | `200`, `401` |
| `POST` | `/api/v1/users/me/friend-requests` | Pide amistad con `target` (username o email) o `user_id`, y `message` opcional (hasta 190). Con una solicitud inversa pendiente quedan amigos. Por email o si hay un bloqueo responde `202 {"status": "sent"}`: no confirma nada de la otra cuenta | `201`, `202`, `401`, `404`, `409`, `422` |
| `POST` | `/api/v1/users/me/friend-requests/{id}/accept` | Acepta una solicitud recibida: `{ friend }`. Repetirla responde lo mismo | `200`, `401`, `404` |
| `POST` | `/api/v1/users/me/friend-requests/{id}/decline` | Rechaza una solicitud recibida. Se puede volver a pedir | `204`, `401`, `404` |
| `DELETE` | `/api/v1/users/me/friend-requests/{id}` | Cancela una solicitud propia | `204`, `401`, `404` |
| `GET` | `/api/v1/users/me/blocks` | Usuarios bloqueados por mí | `200`, `401` |
| `PUT` | `/api/v1/users/me/blocks/{user_id}` | Bloquea. En la misma transacción borra la amistad y cancela las solicitudes pendientes de los dos lados. Idempotente | `204`, `401`, `404`, `422` (uno mismo) |
| `DELETE` | `/api/v1/users/me/blocks/{user_id}` | Desbloquea. Solo deshace el bloqueo propio. Idempotente | `204`, `401` |
| `POST` | `/api/v1/auth/password-reset` | **Pública.** Le pide a Auth0 el email de recupero. Responde igual exista o no la cuenta; hasta 3 pedidos por email cada 15 min ([ADR-006](docs/ADR-006-Recupero-de-Contrasena.md)) | `202`, `422`, `429`, `503` |
| `POST` | `/api/v1/admin/users/suspensions` | **Solo staff.** Suspende una cuenta (`{"user": "email, @usuario o id", "reason": "..."}`): la bloquea en Auth0, la agrega a la lista de bloqueados del Gateway y publica `user.suspended` ([ADR-002](docs/ADR-002-Suspension-Usuarios.md)) | `201`, `400` (la propia), `401`, `403`, `404`, `409` (ya suspendida), `422`, `503` |
| `DELETE` | `/api/v1/admin/users/{user_id}/suspension` | **Solo staff.** Reactiva la cuenta y publica `user.reactivated` | `200`, `401`, `403`, `404`, `409` (no estaba suspendida), `503` |
| `GET` | `/api/v1/admin/users/suspended` | **Solo staff.** Cuentas suspendidas, la más reciente primero | `200`, `401`, `403` |
| `GET` | `/livez` | El proceso está vivo, sin I/O | `200` |
| `GET` | `/readyz` | Llega a la base. Ante una falla no muestra el detalle, que queda en el log | `200`, `503` |

Con login federado, `X-User-Id` y cualquier `{user_id}` pueden ser un alias: se resuelven al id canónico, que
es el único que se guarda en `friendships`, `friend_requests` y `user_blocks`.

### Endpoints internos

Los consulta Chat desde el nodo realtime. No cuelgan de `/api/v1`, así que Kong no los expone, y no piden
identidad de usuario: se limitan por red.

| Método | Path | Descripción | Respuestas |
|--------|------|-------------|------------|
| `GET` | `/internal/users/{id}/canonical` | Resuelve un alias: `{ user_id, suspended }` | `200`, `404`, también si el alias todavía no se vinculó |
| `GET` | `/internal/relations?actor={id}&other={id}` | `{ exists, suspended, friends, blocked_by_actor, blocked_by_other }`. `suspended` habla de `other`. Si alguno de los dos no existe, todo viene en `false` | `200`, `422` |

El contrato completo (OpenAPI) lo genera FastAPI: `http://localhost:8004/docs` y `/openapi.json`.

Los errores siguen RFC 7807 (`application/problem+json`). Los clientes solo deben decidir por el campo
`type`. Los propios son:

- `https://discordia.app/problems/email-not-verified` (403)
- `https://discordia.app/problems/password-reset-throttled` (429, con `Retry-After`)
- `https://discordia.app/problems/account-suspended` (403): la cuenta está suspendida por la plataforma
- `https://discordia.app/problems/staff-only` (403): el endpoint es solo para el staff

### Headers de identidad (los agrega Kong)

| Header | Uso |
|--------|-----|
| `X-User-Id` | Obligatorio. Es el `sub` de Auth0, un identificador opaco (`401` si falta) |
| `X-User-Email` | Obligatorio para `POST /me` (`400` si falta) |
| `X-User-Email-Verified` | Para `POST /me` solo se acepta `true` (sin distinguir mayúsculas). Cualquier otro valor da `403` |
| `X-User-Role` | Los endpoints `/admin/*` exigen exactamente `staff` (`403` si no). Es la segunda barrera: la primera es `validate("staff")` en Kong |

### Eventos que publica

| Evento (routing key) | Cuándo |
|---|---|
| `user.registered` | Al crear el perfil (`POST /users/me`) |
| `user.profile.updated` | Al editar el perfil o el avatar |
| `user.suspended` | Al suspender una cuenta. Trae `user_id`, `identities` (el id y sus identidades federadas), `reason`, `suspended_by` y `suspended_at`. Chat y Voz cierran las conexiones de esas identidades |
| `user.reactivated` | Al reactivarla |

## Tests, lint y seguridad

Los mismos comandos que corre el CI:

```bash
ruff check .                 # lint
bandit -r app -ll            # SAST
pytest --cov=app             # tests + cobertura (falla por debajo de 85 %)
```

Los tests no necesitan base de datos ni broker: usan SQLite en memoria y simulan RabbitMQ, S3 y Auth0. La
configuración de las herramientas está en `pyproject.toml`. El CI además corre `alembic upgrade head`
contra un Postgres real ([ADR-004](docs/ADR-004-CI-CD.md)).

### Migraciones

```bash
alembic upgrade head                                   # aplicar
alembic revision --autogenerate -m "describe el cambio"  # crear una (revisar el archivo generado)
alembic downgrade -1                                   # deshacer la última
```

## Estructura

```text
app/
├── main.py            app de FastAPI, /livez y /readyz
├── api/v1/            rutas (users, profile, social, password_reset) y dependencias de identidad
├── api/internal.py    rutas internas para otros servicios, fuera de Kong
├── services/          lógica de negocio, validación de imágenes y S3
├── repositories/      acceso a datos
├── models/            modelos de SQLAlchemy (users, user_profiles, friendships, outbox_events, ...)
├── schemas/           modelos de Pydantic y Problem Details
├── clients/auth0.py   Authentication API de Auth0 (recupero de contraseña)
├── workers/           publicador del outbox
└── core/              configuración, logging y excepciones
alembic/               migraciones
tests/
```

## CI/CD

`.github/workflows/ci.yml`, en cada push y PR a `main` y `develop`:

1. `test`: ruff, bandit, migraciones contra Postgres y pytest con cobertura mínima de 85 %.
2. `docker`: construye la imagen; en push la publica como `ghcr.io/discordia-g12/auth-service:<sha>`.
3. `deploy`: en push a `main`, la despliega en el nodo **edge** (servicio y worker) con el workflow del
   orquestador. Si no queda sana, vuelve sola a la versión anterior.

## Decisiones de arquitectura

| ADR | Tema | Estado |
|-----|------|--------|
| [ADR-001](docs/ADR-001-Identidad-Auth0.md) | Identidad delegada en Auth0 y contrato con el Gateway | Aceptado |
| [ADR-002](docs/ADR-002-Suspension-Usuarios.md) | Suspensión de usuarios y corte de sesiones | Propuesto |
| [ADR-003](docs/ADR-003-Avatares.md) | Almacenamiento y gestión de avatares | Aceptado, implementación parcial |
| [ADR-004](docs/ADR-004-CI-CD.md) | Pipeline de CI y alcance de CD | Aceptado |
| [ADR-005](docs/ADR-005-Transactional-Outbox.md) | Transactional Outbox para eventos de dominio | Aceptado, implementación parcial |
| [ADR-006](docs/ADR-006-Recupero-de-Contrasena.md) | Recupero de contraseña con límite por email | Aceptado |
