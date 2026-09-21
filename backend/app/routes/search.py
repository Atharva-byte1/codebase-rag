from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import Chunk, Embedding, File as RepoFile
from app.db.session import SessionLocal
from app.routes.ingest import _get_embedding_model

router = APIRouter()


class SearchResult(BaseModel):
    file_path: str
    symbol_name: str | None
    start_line: int | None
    end_line: int | None
    content: str
    similarity: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


@router.get("/search", response_model=SearchResponse)
def search(
    query: str = Query(..., min_length=1),
    repo_id: int | None = Query(default=None, ge=1),
    top_k: int = Query(default=10, ge=1, le=100),
) -> SearchResponse:
    try:
        vector = _get_embedding_model().encode(
            [query],
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0].tolist()
        distance = Embedding.vector.cosine_distance(vector)
        statement = (
            select(
                RepoFile.path,
                Chunk.symbol_name,
                Chunk.start_line,
                Chunk.end_line,
                Chunk.content,
                (1 - distance).label("similarity"),
            )
            .join(Chunk, Chunk.file_id == RepoFile.id)
            .join(Embedding, Embedding.chunk_id == Chunk.id)
            .order_by(distance)
            .limit(top_k)
        )
        if repo_id is not None:
            statement = statement.where(RepoFile.repo_id == repo_id)

        with SessionLocal() as session:
            rows = session.execute(statement).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Search failed") from exc

    return SearchResponse(
        results=[
            SearchResult(
                file_path=file_path,
                symbol_name=symbol_name,
                start_line=start_line,
                end_line=end_line,
                content=content,
                similarity=float(similarity),
            )
            for file_path, symbol_name, start_line, end_line, content, similarity in rows
        ]
    )