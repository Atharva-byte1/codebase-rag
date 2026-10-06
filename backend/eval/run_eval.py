"""Run the fixed Flask repository evaluation against the live backend.

From the repository root, run ``python backend/eval/run_eval.py``. From the
backend directory, run ``python eval/run_eval.py``. Use ``--include-empty-question``
to verify that one invalid question is recorded without stopping the run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = SCRIPT_DIR / "questions.json"
RESULTS_DIR = SCRIPT_DIR / "results"
CITATION_PATTERN = re.compile(r"\[\d+\]")
SOURCE_FIELDS = (
    "citation_id",
    "file_path",
    "symbol_name",
    "start_line",
    "end_line",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=None,
        help="Backend URL; defaults to EVAL_BASE_URL or http://localhost:8000.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-question HTTP timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--include-empty-question",
        action="store_true",
        help="Append an empty question to exercise graceful invalid-request handling.",
    )
    return parser.parse_args()


def load_questions(include_empty_question: bool) -> list[str]:
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not all(
        isinstance(question, str) for question in questions
    ):
        raise ValueError("questions.json must contain a list of strings")
    if include_empty_question:
        questions.append("")
    return questions


def request_chat(base_url: str, question: str, timeout: float) -> dict[str, Any]:
    payload = json.dumps({"message": question, "repo_id": 16}).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    result: dict[str, Any] = {
        "question": question,
        "http_status": None,
        "response_time_ms": None,
        "answer": "",
        "citation_marker_count": 0,
        "sources": [],
        "error": None,
    }
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            result["http_status"] = response.status
    except HTTPError as exc:
        result["http_status"] = exc.code
        try:
            body = exc.read().decode("utf-8")
        except OSError:
            body = ""
        result["error"] = f"HTTP {exc.code}"
    except (TimeoutError, URLError, OSError) as exc:
        body = ""
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["response_time_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )

    try:
        response_data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        response_data = {}
        result["error"] = result["error"] or "Invalid JSON response"

    answer = response_data.get("answer", "")
    if isinstance(answer, str):
        result["answer"] = answer
        result["citation_marker_count"] = len(CITATION_PATTERN.findall(answer))

    sources = response_data.get("sources", [])
    if isinstance(sources, list):
        result["sources"] = [
            {field: source.get(field) for field in SOURCE_FIELDS}
            for source in sources
            if isinstance(source, dict)
        ]
    return result


def is_pass(result: dict[str, Any]) -> bool:
    return result["http_status"] == 200 and len(result["sources"]) > 0


def markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def build_markdown(results: list[dict[str, Any]], timestamp: str) -> str:
    passed = sum(is_pass(result) for result in results)
    failed = len(results) - passed
    measured_times = [
        result["response_time_ms"]
        for result in results
        if isinstance(result["response_time_ms"], (int, float))
    ]
    average = sum(measured_times) / len(measured_times) if measured_times else 0

    lines = [
        "# Flask Repository Evaluation",
        "",
        f"Generated: `{timestamp}`",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total questions | {len(results)} |",
        f"| Pass (HTTP 200 and at least one citation) | {passed} |",
        f"| Fail | {failed} |",
        f"| Average response time (ms) | {average:.2f} |",
        "",
    ]

    for index, result in enumerate(results, start=1):
        status = result["http_status"] if result["http_status"] is not None else "request failed"
        lines.extend(
            [
                f"## Question {index}",
                "",
                f"**Question:** {result['question'] or '(empty question)'}  ",
                f"**HTTP status:** {status}  ",
                f"**Response time:** {result['response_time_ms']:.2f} ms  ",
                f"**Citation markers:** {result['citation_marker_count']}  ",
                f"**Returned citations:** {len(result['sources'])}",
                "",
                "### Answer",
                "",
                result["answer"] or f"_No answer returned. {result['error'] or ''}_",
                "",
                "### Citations",
                "",
                "| File path | Symbol | Lines |",
                "| --- | --- | --- |",
            ]
        )
        if result["sources"]:
            for source in result["sources"]:
                start = source["start_line"]
                end = source["end_line"]
                lines.append(
                    f"| {markdown_cell(source['file_path'])} | "
                    f"{markdown_cell(source['symbol_name'])} | "
                    f"{markdown_cell(f'{start}-{end}' if start is not None or end is not None else '')} |"
                )
        else:
            lines.append("| _none_ |  |  |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    base_url = args.base_url or os.environ.get("EVAL_BASE_URL", "http://localhost:8000")
    try:
        questions = load_questions(args.include_empty_question)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Unable to load questions: {exc}", file=sys.stderr)
        return 1

    results = [request_chat(base_url, question, args.timeout) for question in questions]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"results_{timestamp}.json"
    markdown_path = RESULTS_DIR / f"results_{timestamp}.md"
    payload = {
        "generated_at": timestamp,
        "base_url": base_url,
        "repo_id": 16,
        "results": results,
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(
        build_markdown(results, timestamp), encoding="utf-8"
    )
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    print(f"Questions: {len(results)}")
    print(f"Pass: {sum(is_pass(result) for result in results)}")
    print(f"Fail: {sum(not is_pass(result) for result in results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())