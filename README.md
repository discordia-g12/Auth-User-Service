# Auth-User-Service

## Desarrollo local

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt   # incluye requirements.txt + herramientas de test/lint

docker compose up -d auth_db
alembic upgrade head
```

## Tests, lint y seguridad

```bash
ruff check .              # lint
bandit -r app -ll         # SAST
pytest --cov=app          # tests + cobertura (mínimo 85%, ver ADR-03)
```

El CI corre estos mismos comandos en cada push/PR contra `main`/`develop` y bloquea el merge si alguno falla — ver [`.github/workflows/ci.yml`](.github/workflows/ci.yml) y [`docs/ADR-03-CI-CD-Pipeline.md`](docs/ADR-03-CI-CD-Pipeline.md) para el detalle de qué corre y por qué CD todavía no está automatizado.
