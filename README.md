# Codebase RAG

Codebase RAG is a production-style retrieval-augmented generation system for asking grounded questions about software repositories. It is a placement and portfolio project focused on the engineering work behind code search: repository ingestion, structural chunking, local embeddings, hybrid retrieval, reranking, and citation-aware answer generation. A React interface makes the workflow usable from a browser, while the FastAPI backend exposes the same pipeline as an API.

## Architecture

```text
Browser
  |
  v
React + Vite frontend (localhost:5173)
  |
  v
FastAPI backend (localhost:8000)
  |                         \
  v                          v
PostgreSQL 16 + pgvector    OpenRouter
  |                          cohere/north-mini-code:free
  |
  +-- Ingestion:
  |     GitHub URL or ZIP
  |       -> file filtering
  |       -> Python AST chunking
  |       -> local 384-dimensional embeddings
  |       -> PostgreSQL + pgvector
  |
  +-- Question answering:
        Question
          -> embedding
          -> vector search + BM25
          -> hybrid retrieval
          -> cross-encoder reranker
          -> top context
          -> LLM generation
          -> answer + numbered citations
          -> React UI
```

The database stores repositories, accepted files, function/class chunks, and embeddings. Retrieval combines lexical BM25 scoring with vector similarity, then applies a cross-encoder to the candidate chunks before building the context sent to the LLM.

## Tech Stack

### Backend

- Python web application with FastAPI and Uvicorn
- SQLAlchemy ORM and Alembic migrations
- PostgreSQL 16 with the pgvector extension
- Multipart ZIP uploads and GitHub archive download handling

### Frontend

- React 19
- Vite
- `lucide-react` icons
- Browser chat interface with loading, error, source, and backend-health states

### Infrastructure

- Docker and Docker Compose
- Three services: PostgreSQL, backend, and frontend
- Database health check and startup dependency ordering

### Retrieval and Generation

- `sentence-transformers/all-MiniLM-L6-v2` local embeddings, 384 dimensions
- BM25 plus vector similarity hybrid retrieval
- `cross-encoder/ms-marco-MiniLM-L-6-v2` reranking
- OpenRouter with `cohere/north-mini-code:free` for answer generation

## Features

- Ingest a public GitHub repository with `POST /ingest/github`.
- Upload a repository ZIP with `POST /ingest/zip`.
- Filter ignored directories such as `.git`, `node_modules`, `__pycache__`, virtual environments, build output, and oversized files.
- Parse Python source with the AST into class headers and function/method-level chunks, including symbol and line-range metadata.
- Generate local embeddings and persist them in PostgreSQL with pgvector.
- Search with BM25 and vector retrieval followed by cross-encoder reranking.
- Ask repository questions through `POST /chat` and receive an answer plus structured citations.
- Render citation file paths, symbols, and line ranges in the React frontend.
- Monitor ingestion state and database connectivity through status endpoints and the frontend health indicator.
- Run the complete stack with one Docker Compose command.

## Setup

### Prerequisites

- Docker Desktop with Docker Compose
- An OpenRouter API key for generated answers
- Git, if you plan to inspect or update the project locally

Create the environment file from the checked-in template. The template contains no real secret:

```powershell
Copy-Item .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env`. The remaining defaults are suitable for the Docker Compose stack. Do not commit `.env` or an API key.

Build and start PostgreSQL, the backend, and the frontend:

```powershell
docker compose up --build
```

Open the application at <http://localhost:5173>. The API is available at <http://localhost:8000>, and the interactive API documentation is available at <http://localhost:8000/docs>.

Check database connectivity:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Stop the stack with:

```powershell
docker compose down
```

## API Reference

All examples use the demo repository id `16` where a repository id is required.

### `GET /health`

Checks the database connection rather than only checking whether the process is running.

```json
{
  "status": "healthy",
  "database": "connected"
}
```

### `POST /ingest/github`

Downloads a public GitHub repository, filters accepted files, creates chunks and embeddings, and stores the repository. The request accepts either `url` or `source_url`.

```json
{
  "url": "https://github.com/pallets/flask"
}
```

Response shape:

```json
{
  "repo_id": 16,
  "status": "ready",
  "file_count": 123
}
```

### `POST /ingest/zip`

Uploads a ZIP archive as multipart form data using the field name `file`.

```powershell
curl.exe -X POST http://localhost:8000/ingest/zip -F "file=@flask.zip"
```

The response has the same shape as GitHub ingestion: `repo_id`, `status`, and `file_count`.

### `GET /ingest/status/{repo_id}`

Returns the current ingestion state and accepted file count.

```json
{
  "repo_id": 16,
  "status": "ready",
  "file_count": 123
}
```

### `GET /search`

Runs hybrid retrieval and reranking. `query` is required; `repo_id` and `top_k` are optional.

```text
GET /search?query=Where%20are%20Flask%20error%20handlers%20registered%3F&repo_id=16&top_k=10
```

Each result includes the matched content and retrieval metadata:

```json
{
  "results": [
    {
      "file_path": "flask-main/src/flask/app.py",
      "symbol_name": "Flask.handle_exception",
      "start_line": 1180,
      "end_line": 1210,
      "content": "...",
      "similarity": 0.82,
      "bm25_score": 3.14,
      "vector_score": 0.82,
      "hybrid_score": 0.91,
      "reranking_score": 4.27
    }
  ]
}
```

### `POST /chat`

Runs retrieval, context construction, and OpenRouter generation. The model is instructed to ground repository facts with numbered citations.

```json
{
  "message": "Where is Flask request exception handling customized? Cite repository sources using [1] and [2].",
  "repo_id": 16
}
```

Response shape:

```json
{
  "answer": "Flask registers exception handlers through ... [1]. The default handling path is implemented in ... [2].",
  "sources": [
    {
      "citation_id": 1,
      "file_path": "flask-main/src/flask/app.py",
      "symbol_name": "Flask.errorhandler",
      "start_line": 120,
      "end_line": 145
    }
  ]
}
```

## Ingest a Repository and Ask Questions

1. Start the stack and wait for `GET /health` to report a connected database.
2. From the frontend, either choose a ZIP file and select **Upload ZIP**, or enter a public GitHub repository URL and select **Import**. The frontend polls the ingestion status and, when ingestion is ready, switches the active in-memory `repo_id` to the new repository for subsequent chat questions. An ingestion failure is shown in the panel and leaves the previous active repository unchanged.
3. To submit a public repository URL through the API instead:

   ```powershell
   $body = @{ url = "https://github.com/pallets/flask" } | ConvertTo-Json
   Invoke-RestMethod http://localhost:8000/ingest/github -Method Post -ContentType "application/json" -Body $body
   ```

4. Save the returned `repo_id` and poll `/ingest/status/{repo_id}` until the status is `ready`.
5. Ask a question from the frontend, or call `/chat` with the repository id:

   ```powershell
   $body = @{
     message = "How does Flask dispatch an incoming request? Cite sources using [1] and [2]."
     repo_id = 16
   } | ConvertTo-Json
   Invoke-RestMethod http://localhost:8000/chat -Method Post -ContentType "application/json" -Body $body
   ```

The current demo dataset is Flask: repository id `16`, 123 files, 920 chunks, and 920 embeddings, with status `ready`.

## Example Questions

The system is designed for repository-specific questions such as:

- How does Flask handle database connections during a request, and where is that behavior implemented?
- What happens inside Flask when an HTTP request comes in, from the WSGI entry point through response handling?
- Where is URL routing implemented in Flask, and how are routes matched to view functions?
- Where is the application context implemented, and why does Flask need it?
- What files would I need to modify to add a new Flask CLI command?
- What could be affected if I change the Flask class `__init__` method?
- How are request and application globals implemented, and what happens outside an active context?

Questions should identify a repository behavior or implementation detail and should ask for citations when a cited answer is needed.

## Evaluation

The fixed evaluation set contains nine realistic Flask questions in `backend/eval/questions.json`. Run it against the live backend from the repository root:

```powershell
python backend/eval/run_eval.py
```

The script sends each question to `/chat` using repository id `16` and writes timestamped JSON and Markdown results under `backend/eval/results/`. It records the answer, response time, citation markers, returned sources, HTTP status, and errors. By definition, a question passes when the response is HTTP 200 and includes at least one structured citation.

This is a structural smoke test, not automated correctness grading. A recent verified run passed 9 of 9 questions; results can vary because the free-tier LLM is nondeterministic, so the generated Markdown should be reviewed by a human for grounding and answer quality.

## Known Limitations

### Reranker sensitivity for one exception-handling question

One evaluation question about how Flask processes view exceptions can be sensitive to phrasing and may not surface the most relevant chunks in the final top 10. Hybrid retrieval can find chunks such as `Scaffold.errorhandler` and `Flask.handle_exception` at reasonable candidate ranks, but the cross-encoder may demote them for that particular phrasing. This is a retrieval-quality limitation rather than a correctness guarantee; the evaluation output should be reviewed for grounding and answer quality.

### Free-tier generation latency

Responses from the free OpenRouter model average approximately 30 to 50 seconds per question and can occasionally exceed 60 seconds. This is an inference-speed and rate-limit constraint of the selected free-tier model. A production deployment would use a faster or provisioned model, request queuing, and explicit latency budgets.

### Python-only structural chunking

The ingestion pipeline accepts and filters a broader set of file extensions, but AST-based function and method chunking currently produces structural chunks for Python. Matching granularity for other languages would require language-specific parsers, most naturally an extension based on Tree-sitter.

### Transitive dependency scope

Repository indexing covers the selected repository's own source, not its transitive dependencies. Questions about dependency internals are therefore scoped to how the indexed repository uses that dependency, not the dependency's own implementation.

### Synchronous large-repository ingestion

Repository ingestion runs inside the HTTP request. This is suitable for the demo-scale Flask dataset, but large repositories would tie up a request for too long. The production fix would be a background job queue with durable progress and retry state.

## Project Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── chat.py                 # Context construction, prompts, citations
│   │   ├── config.py               # Environment-backed settings
│   │   ├── llm_service.py          # OpenRouter client
│   │   ├── search_scoring.py       # BM25, vector, hybrid, reranking helpers
│   │   ├── db/                     # SQLAlchemy models and sessions
│   │   └── routes/
│   │       ├── chat.py             # POST /chat
│   │       ├── ingest.py           # ZIP/GitHub ingestion and chunking
│   │       ├── search.py           # GET /search
│   │       └── status.py           # GET /health and ingestion status
│   ├── alembic/                    # Database migrations
│   ├── eval/                       # Questions, runner, and result artifacts
│   └── tests/                      # Backend unit tests
├── frontend/
│   └── src/                        # React application and styles
├── docker-compose.yml              # PostgreSQL, backend, and frontend
└── .env.example                    # Configuration template without secrets
```

## What I Would Build Next

- Add Tree-sitter-based chunkers for JavaScript, TypeScript, Java, Go, and other supported file types.
- Move ingestion to a background worker with durable progress and retry state.
- Benchmark reranker models and candidate-window strategies against a curated relevance set.
- Add an Ollama-backed local generation option to remove dependence on free-tier latency and rate limits.
- Add richer evaluation labels so answer correctness and citation grounding are measured separately from HTTP success and citation presence.