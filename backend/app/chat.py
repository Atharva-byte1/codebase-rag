from collections.abc import Sequence

from app.routes.search import SearchResult

MAX_CONTEXT_CHARS = 12000
INSUFFICIENT_CONTEXT_MESSAGE = (
    "I could not find enough relevant repository context to answer that reliably."
)


def build_context(results: Sequence[SearchResult], max_chars: int = MAX_CONTEXT_CHARS) -> str:
    parts: list[str] = []
    characters = 0
    for index, result in enumerate(results, start=1):
        location = result.file_path
        if result.start_line is not None:
            location += f":{result.start_line}"
            if result.end_line is not None:
                location += f"-{result.end_line}"
        block = f"[Context {index}] {location}"
        if result.symbol_name:
            block += f" ({result.symbol_name})"
        block += f"\n{result.content.strip()}"
        if characters + len(block) > max_chars:
            break
        parts.append(block)
        characters += len(block)
    return "\n\n".join(parts)


def build_prompt(message: str, context: str) -> str:
    return f"""You are a repository-grounded code assistant.

Retrieved repository context is the source of truth. Use only facts supported by it.
Never invent repository files, functions, APIs, or behavior. If the context is insufficient,
say so clearly. Distinguish existing repository behavior from suggestions or generated code.
You can explain code, architecture and execution flow, component relationships, debugging,
repository-specific modifications, code generation following repository patterns, and
implementation questions.

Repository context:
{context}

User question:
{message}
"""