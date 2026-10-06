import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.routes.search import SearchResult

MAX_CONTEXT_CHARS = 12000
INSUFFICIENT_CONTEXT_MESSAGE = (
    "I could not find enough relevant repository context to answer that reliably."
)
CITATION_PATTERN = re.compile(r"(?<!\w)\[(\d+)\]")


@dataclass(frozen=True)
class ContextSource:
    citation_id: int
    file_path: str
    symbol_name: str | None
    start_line: int | None
    end_line: int | None


def build_context(
    results: Sequence[SearchResult], max_chars: int = MAX_CONTEXT_CHARS
) -> tuple[str, list[ContextSource]]:
    parts: list[str] = []
    sources: list[ContextSource] = []
    characters = 0
    for index, result in enumerate(results, start=1):
        location = result.file_path
        if result.start_line is not None:
            location += f":{result.start_line}"
            if result.end_line is not None:
                location += f"-{result.end_line}"
        block = f"Repository excerpt {index}: {location}"
        if result.symbol_name:
            block += f" ({result.symbol_name})"
        block += f"\n{result.content.strip()}"
        if len(block) > max_chars or characters + len(block) > max_chars:
            continue
        parts.append(block)
        sources.append(
            ContextSource(
                citation_id=index,
                file_path=result.file_path,
                symbol_name=result.symbol_name,
                start_line=result.start_line,
                end_line=result.end_line,
            )
        )
        characters += len(block)
    return "\n\n".join(parts), sources


def cited_sources(answer: str, sources: Sequence[ContextSource]) -> list[ContextSource]:
    sources_by_id = {source.citation_id: source for source in sources}
    cited_ids = dict.fromkeys(
        int(match.group(1)) for match in CITATION_PATTERN.finditer(answer)
    )
    return [source for citation_id in cited_ids if (source := sources_by_id.get(citation_id))]


def build_prompt(message: str, context: str) -> str:
    return f"""You are a repository-grounded code assistant.

Retrieved repository context is the source of truth. Use only facts supported by it.
Never invent repository files, functions, APIs, or behavior. If the context is insufficient,
say so clearly. Distinguish existing repository behavior from suggestions or generated code.
Every repository-grounded factual claim must include an immediate citation in the form [1], [2],
and so on. Do not state repository facts without a citation. Use only citation numbers that
exist in the supplied context; never invent citation numbers. Before finalizing, check that
every repository fact has at least one valid citation.
Use only bare numbered citations in the exact form [1], [2], [3], and so on. Never output "[Context N]" or expose internal context, chunk, retrieval, or indexing labels in your answer. For longer answers, use clear headings when they genuinely aid readability, and keep the response concise. Use tables only when they genuinely clarify a comparison or structured result — do not default to large tables or code blocks when prose or a short list would be clearer.
You can explain code, architecture and execution flow, component relationships, debugging,
repository-specific modifications, code generation following repository patterns, and
implementation questions.

Repository context:
{context}

User question:
{message}
"""