from fastapi import FastAPI

from app.routes.ingest import router as ingest_router
from app.routes.status import router as status_router

app = FastAPI(title="Codebase RAG")
app.include_router(status_router)
app.include_router(ingest_router)
