from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.ingest import router as ingest_router
from app.routes.chat import router as chat_router
from app.routes.search import router as search_router
from app.routes.status import router as status_router

app = FastAPI(title="Codebase RAG")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(status_router)
app.include_router(ingest_router)
app.include_router(search_router)
app.include_router(chat_router)