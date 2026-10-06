from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.chat import (
    INSUFFICIENT_CONTEXT_MESSAGE,
    build_context,
    build_prompt,
    cited_sources,
)
from app.llm_service import OpenRouterError, OpenRouterService
from app.routes.search import search_code

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    repo_id: int | None = Field(default=None, ge=1)


class ChatResponse(BaseModel):
    answer: str
    sources: list["ChatSource"]


class ChatSource(BaseModel):
    citation_id: int
    file_path: str
    symbol_name: str | None
    start_line: int | None
    end_line: int | None


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    search_response = search_code(request.message, request.repo_id, top_k=10)
    context, context_sources = build_context(search_response.results)
    if not context:
        return ChatResponse(answer=INSUFFICIENT_CONTEXT_MESSAGE, sources=[])

    try:
        answer = OpenRouterService().complete(build_prompt(request.message, context))
    except OpenRouterError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    sources = [
        ChatSource(
            citation_id=source.citation_id,
            file_path=source.file_path,
            symbol_name=source.symbol_name,
            start_line=source.start_line,
            end_line=source.end_line,
        )
        for source in cited_sources(answer, context_sources)
    ]
    return ChatResponse(answer=answer, sources=sources)