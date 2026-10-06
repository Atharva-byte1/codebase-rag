import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sentence_transformers import CrossEncoder
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import Chunk, Embedding, File as RepoFile
from app.db.session import SessionLocal
from app.routes.ingest import _get_embedding_model
from app.search_scoring import (
    bm25_scores,
    cosine_similarity,
    hybrid_scores,
    rerank_scores,
)

router = APIRouter()
logger = logging.getLogger(__name__)
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CANDIDATE_MULTIPLIER = 5
_reranker: CrossEncoder | None = None


class SearchResult(BaseModel):
    chunk_id: int = Field(..., exclude=True)
    file_path: str
    symbol_name: str | None
    start_line: int | None
    end_line: int | None
    content: str
    similarity: float
    bm25_score: float
    vector_score: float
    hybrid_score: float
    reranking_score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        try:
            _reranker = CrossEncoder(
                RERANKER_MODEL_NAME,
                device="cpu",
                model_kwargs={"low_cpu_mem_usage": False},
            )
        except Exception as exc:
            logger.exception("Unable to initialize reranker %s", RERANKER_MODEL_NAME)
            raise HTTPException(
                status_code=503,
                detail="Search temporarily unavailable; please retry.",
            ) from exc
    return _reranker

def search_code(query: str, repo_id: int | None = None, top_k: int = 10) -> SearchResponse:
    if not query.strip():
        return SearchResponse(results=[])

    try:
        vector = _get_embedding_model().encode(
            [query],
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0].tolist()
        statement = (
            select(
                Chunk.id,
                RepoFile.path,
                Chunk.symbol_name,
                Chunk.start_line,
                Chunk.end_line,
                Chunk.content,
                Embedding.vector,
            )
            .join(Chunk, Chunk.file_id == RepoFile.id)
            .join(Embedding, Embedding.chunk_id == Chunk.id)
        )
        if repo_id is not None:
            statement = statement.where(RepoFile.repo_id == repo_id)

        with SessionLocal() as session:
            rows = session.execute(statement).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Search failed") from exc

    if not rows:
        return SearchResponse(results=[])

    documents = [row.content for row in rows]
    bm25_values = bm25_scores(query, documents)
    vector_values = [
        cosine_similarity(vector, row.vector)
        for row in rows
    ]
    combined_values = hybrid_scores(bm25_values, vector_values)
    hybrid_ranked_rows = sorted(
        zip(rows, bm25_values, vector_values, combined_values),
        key=lambda item: (
            -item[3],
            -item[1],
            -item[2],
            item[0].path,
            item[0].start_line or 0,
            item[0].id,
        ),
    )
    candidate_rows = hybrid_ranked_rows[: top_k * CANDIDATE_MULTIPLIER]
    candidate_documents = [item[0].content for item in candidate_rows]
    reranking_values = rerank_scores(
        query,
        candidate_documents,
        _get_reranker().predict,
    )
    ranked_rows = sorted(
        zip(candidate_rows, reranking_values),
        key=lambda item: (
            -item[1],
            -item[0][3],
            -item[0][1],
            -item[0][2],
            item[0][0].path,
            item[0][0].start_line or 0,
            item[0][0].id,
        ),
    )[:top_k]

    return SearchResponse(
        results=[
            SearchResult(
                chunk_id=row.id,
                file_path=row.path,
                symbol_name=row.symbol_name,
                start_line=row.start_line,
                end_line=row.end_line,
                content=row.content,
                similarity=float(vector_score),
                bm25_score=float(bm25_score),
                vector_score=float(vector_score),
                hybrid_score=float(hybrid_score),
                reranking_score=float(reranking_score),
            )
            for (row, bm25_score, vector_score, hybrid_score), reranking_score
            in ranked_rows
        ]
    )


@router.get("/search", response_model=SearchResponse)
def search(
    query: str = Query(..., min_length=1),
    repo_id: int | None = Query(default=None, ge=1),
    top_k: int = Query(default=10, ge=1, le=100),
) -> SearchResponse:
    return search_code(query, repo_id, top_k)
