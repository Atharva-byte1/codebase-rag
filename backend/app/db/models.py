from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    zip_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    files: Mapped[list["File"]] = relationship(back_populates="repo")


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    repo: Mapped[Repo] = relationship(back_populates="files")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="file")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(String, nullable=True)
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    file: Mapped[File] = relationship(back_populates="chunks")
    embedding: Mapped["Embedding | None"] = relationship(back_populates="chunk")


class Embedding(Base):
    __tablename__ = "embeddings"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id"), primary_key=True
    )
    vector: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    chunk: Mapped[Chunk] = relationship(back_populates="embedding")
