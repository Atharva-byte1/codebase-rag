# Codebase RAG

Codebase RAG will eventually index codebases and answer questions with retrieval-augmented generation. Phase 1 provides only the backend foundation and database schema.

## Phase 1

- FastAPI health endpoint
- PostgreSQL 16 with pgvector
- SQLAlchemy ORM and Alembic migrations
- Docker Compose services for PostgreSQL and the backend

## Structure

- `backend/app`: FastAPI application, configuration, database session, models, and routes
- `backend/alembic`: migration configuration and initial schema migration
- `docker-compose.yml`: PostgreSQL and backend services

## Configure and start

Copy `.env.example` to `.env` and set the PostgreSQL values as needed:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

Run the migration against the running database:

```powershell
docker compose exec backend alembic upgrade head
```

Check the API at <http://localhost:8000/health>. Stop the stack with:

```powershell
docker compose down
```
