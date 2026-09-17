import ast
import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from fastapi import APIRouter, File as UploadFileField, HTTPException, UploadFile
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from sqlalchemy import func, select

from app.db.models import Chunk, Embedding, File as RepoFile
from app.db.models import Repo
from app.db.session import SessionLocal

router = APIRouter(prefix="/ingest")

MAX_FILE_SIZE = 1024 * 1024
IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "coverage",
}
LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
}

AcceptedFile = tuple[Path, str, str, bytes]
ChunkData = tuple[str, int, int, str]
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
_embedding_model: SentenceTransformer | None = None


class GithubIngestRequest(BaseModel):
    url: str | None = None
    source_url: str | None = None


def _safe_relative_path(member_name: str) -> Path:
    normalized_name = member_name.replace("\\", "/")
    relative_path = PurePosixPath(normalized_name)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("ZIP contains an unsafe path")
    if not relative_path.parts or any(not part for part in relative_path.parts):
        raise ValueError("ZIP contains an invalid path")
    return Path(*relative_path.parts)


def _is_accepted(path: Path, size: int) -> bool:
    return (
        size <= MAX_FILE_SIZE
        and not any(part.lower() in IGNORED_DIRECTORIES for part in path.parts)
        and path.suffix.lower() in LANGUAGES
    )


def _set_failed(repo_id: int) -> None:
    with SessionLocal() as session:
        repo = session.get(Repo, repo_id)
        if repo is not None:
            repo.status = "failed"
            session.commit()


def _python_chunks(content: bytes) -> list[ChunkData]:
    try:
        source = content.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError, ValueError):
        return []

    lines = source.splitlines(keepends=True)
    chunks: list[ChunkData] = []

    def add_node(node: ast.AST, symbol_name: str) -> None:
        start_line = getattr(node, "lineno", None)
        end_line = getattr(node, "end_lineno", None)
        if start_line is None or end_line is None:
            return
        decorator_lines = [
            decorator.lineno
            for decorator in getattr(node, "decorator_list", [])
            if hasattr(decorator, "lineno")
        ]
        start_line = min([start_line, *decorator_lines])
        chunks.append(
            (
                symbol_name,
                start_line,
                end_line,
                "".join(lines[start_line - 1 : end_line]),
            )
        )

    def visit_body(body: list[ast.stmt], parent_name: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol_name = f"{parent_name}.{node.name}" if parent_name else node.name
                add_node(node, symbol_name)
                if isinstance(node, ast.ClassDef):
                    visit_body(node.body, symbol_name)

    visit_body(tree.body)
    return chunks


def _chunks_for_file(language: str, content: bytes) -> list[ChunkData]:
    if language == "python":
        return _python_chunks(content)
    return []


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _store_embeddings(session, chunks: list[Chunk]) -> None:
    if not chunks:
        return

    existing_chunk_ids = set(
        session.scalars(
            select(Embedding.chunk_id).where(
                Embedding.chunk_id.in_(chunk.id for chunk in chunks)
            )
        )
    )
    chunks_to_embed = [chunk for chunk in chunks if chunk.id not in existing_chunk_ids]
    if not chunks_to_embed:
        return

    vectors = _get_embedding_model().encode(
        [chunk.content for chunk in chunks_to_embed],
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    if len(vectors) != len(chunks_to_embed):
        raise RuntimeError("Embedding count does not match chunk count")

    for chunk, vector in zip(chunks_to_embed, vectors):
        values = vector.tolist()
        if len(values) != EMBEDDING_DIMENSION:
            raise RuntimeError("Embedding dimension does not match schema")
        session.add(Embedding(chunk_id=chunk.id, vector=values))


def _create_repo(*, source_url: str | None = None, zip_name: str | None = None) -> int:
    with SessionLocal() as session:
        repo = Repo(source_url=source_url, zip_name=zip_name, status="pending")
        session.add(repo)
        session.commit()
        repo_id = repo.id
        repo.status = "indexing"
        session.commit()
    return repo_id


def _save_ingested_files(
    repo_id: int, accepted_files: list[AcceptedFile]
) -> None:
    with SessionLocal() as session:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise RuntimeError("Repository record disappeared")
        chunks: list[Chunk] = []
        for path, language, content_hash, content in accepted_files:
            repo_file = RepoFile(
                repo_id=repo_id,
                path=path.as_posix(),
                language=language,
                content_hash=content_hash,
            )
            session.add(repo_file)
            session.flush()
            file_chunks = [
                Chunk(
                    file_id=repo_file.id,
                    symbol_name=symbol_name,
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_content,
                )
                for symbol_name, start_line, end_line, chunk_content in _chunks_for_file(
                    language, content
                )
            ]
            session.add_all(file_chunks)
            session.flush()
            chunks.extend(file_chunks)
        _store_embeddings(session, chunks)
        repo.status = "ready"
        session.commit()


def _accepted_files_from_archive(archive: zipfile.ZipFile) -> list[AcceptedFile]:
    accepted_files: list[AcceptedFile] = []
    with TemporaryDirectory() as temp_dir:
        extraction_root = Path(temp_dir).resolve()
        for member in archive.infolist():
            if member.is_dir():
                _safe_relative_path(member.filename)
                continue

            relative_path = _safe_relative_path(member.filename)
            if not _is_accepted(relative_path, member.file_size):
                continue

            destination = (extraction_root / relative_path).resolve()
            if extraction_root not in destination.parents:
                raise ValueError("ZIP contains an unsafe path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as target:
                content = source.read(MAX_FILE_SIZE + 1)
                if len(content) > MAX_FILE_SIZE:
                    continue
                target.write(content)
            accepted_files.append(
                (
                    relative_path,
                    LANGUAGES[relative_path.suffix.lower()],
                    hashlib.sha256(content).hexdigest(),
                    content,
                )
            )
    return accepted_files


def _github_repository_parts(source_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(source_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid GitHub repository URL")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise ValueError("Invalid GitHub repository URL")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    name_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    if not name_pattern.fullmatch(owner) or not name_pattern.fullmatch(repository):
        raise ValueError("Invalid GitHub repository URL")
    return owner, repository


def _download_github_archive(owner: str, repository: str) -> zipfile.ZipFile:
    api_url = f"https://api.github.com/repos/{owner}/{repository}"
    request = urllib.request.Request(
        api_url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "codebase-rag"},
    )
    with urllib.request.urlopen(request) as response:
        metadata = json.load(response)
    default_branch = metadata.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise ValueError("GitHub repository has no default branch")

    archive_url = (
        f"https://codeload.github.com/{urllib.parse.quote(owner)}/"
        f"{urllib.parse.quote(repository)}/zip/refs/heads/"
        f"{urllib.parse.quote(default_branch, safe='')}"
    )
    archive_request = urllib.request.Request(
        archive_url, headers={"User-Agent": "codebase-rag"}
    )
    with urllib.request.urlopen(archive_request) as response:
        return zipfile.ZipFile(io.BytesIO(response.read()))


@router.post("/zip")
def ingest_zip(file: UploadFile = UploadFileField(...)) -> dict[str, int | str]:
    try:
        archive_bytes = file.file.read()
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
        archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid ZIP file") from exc

    repo_id: int | None = None
    try:
        repo_id = _create_repo(zip_name=file.filename)
        accepted_files = _accepted_files_from_archive(archive)
        _save_ingested_files(repo_id, accepted_files)

        return {"repo_id": repo_id, "status": "ready", "file_count": len(accepted_files)}
    except ValueError as exc:
        if repo_id is not None:
            _set_failed(repo_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if repo_id is not None:
            _set_failed(repo_id)
        raise HTTPException(status_code=500, detail="ZIP ingestion failed") from exc
    finally:
        archive.close()
        file.file.close()


@router.post("/github")
def ingest_github(request: GithubIngestRequest) -> dict[str, int | str]:
    source_url = request.url or request.source_url
    if source_url is None:
        raise HTTPException(status_code=400, detail="GitHub repository URL is required")
    try:
        owner, repository = _github_repository_parts(source_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo_id: int | None = None
    try:
        repo_id = _create_repo(source_url=source_url)
        archive = _download_github_archive(owner, repository)
        try:
            accepted_files = _accepted_files_from_archive(archive)
        finally:
            archive.close()
        _save_ingested_files(repo_id, accepted_files)
        return {"repo_id": repo_id, "status": "ready", "file_count": len(accepted_files)}
    except urllib.error.HTTPError as exc:
        if repo_id is not None:
            _set_failed(repo_id)
        if exc.code == 404:
            raise HTTPException(status_code=404, detail="GitHub repository not found") from exc
        raise HTTPException(status_code=502, detail="GitHub download failed") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        if repo_id is not None:
            _set_failed(repo_id)
        raise HTTPException(status_code=502, detail="GitHub download failed") from exc
    except ValueError as exc:
        if repo_id is not None:
            _set_failed(repo_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if repo_id is not None:
            _set_failed(repo_id)
        raise HTTPException(status_code=500, detail="GitHub ingestion failed") from exc


@router.get("/status/{repo_id}")
def ingestion_status(repo_id: int) -> dict[str, int | str]:
    with SessionLocal() as session:
        result = session.execute(
            select(Repo.status, func.count(RepoFile.id))
            .outerjoin(RepoFile, RepoFile.repo_id == Repo.id)
            .where(Repo.id == repo_id)
            .group_by(Repo.id, Repo.status)
        ).one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    status, file_count = result
    return {"repo_id": repo_id, "status": status, "file_count": file_count}