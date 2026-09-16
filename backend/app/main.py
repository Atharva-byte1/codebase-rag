from fastapi import FastAPI

from app.routes.status import router as status_router

app = FastAPI(title="Codebase RAG")
app.include_router(status_router)
