import json
import io
import urllib.error
import unittest
from unittest.mock import patch

from app.chat import (
    CITATION_PATTERN,
    INSUFFICIENT_CONTEXT_MESSAGE,
    build_context,
    build_prompt,
    cited_sources,
)
from app.llm_service import OpenRouterError, OpenRouterService
from app.routes.search import SearchResult


def result(content: str, path: str = "app/main.py") -> SearchResult:
    return SearchResult(
        chunk_id=7,
        file_path=path,
        symbol_name="app",
        start_line=1,
        end_line=3,
        content=content,
        similarity=1.0,
        bm25_score=1.0,
        vector_score=1.0,
        hybrid_score=1.0,
        reranking_score=1.0,
    )


class ChatTests(unittest.TestCase):
    def test_context_building_includes_locations_and_respects_limit(self) -> None:
        context, sources = build_context([result("def app(): pass")], max_chars=1000)
        self.assertIn("Repository excerpt 1:", context)
        self.assertIn("app/main.py:1-3 (app)", context)
        self.assertIn("def app(): pass", context)
        self.assertEqual(sources[0].citation_id, 1)
        self.assertEqual(sources[0].file_path, "app/main.py")
        self.assertEqual(build_context([result("too long")], max_chars=1), ("", []))

    def test_search_result_preserves_chunk_id_without_exposing_it(self) -> None:
        search_result = result("code")
        self.assertEqual(search_result.chunk_id, 7)
        self.assertNotIn("chunk_id", search_result.model_dump())

    def test_context_truncation_excludes_sources_for_unsent_chunks(self) -> None:
        first = result("first", "app/first.py")
        second = result("second", "app/second.py")
        context, sources = build_context([first, second], max_chars=80)

        self.assertIn("app/first.py", context)
        self.assertNotIn("app/second.py", context)
        self.assertEqual([source.file_path for source in sources], ["app/first.py"])

    def test_prompt_building_requires_grounded_answers(self) -> None:
        prompt = build_prompt("How does this work?", "Repository excerpt 1: app/main.py\ncode")
        self.assertIn("source of truth", prompt)
        self.assertIn("Never invent", prompt)
        self.assertIn("Every repository-grounded factual claim must include an immediate citation", prompt)
        self.assertIn("Do not state repository facts without a citation", prompt)
        self.assertIn("never invent citation numbers", prompt)
        self.assertIn("every repository fact has at least one valid citation", prompt)
        self.assertIn("Use only bare numbered citations in the exact form [1], [2], [3], and so on.", prompt)
        self.assertIn('Never output "[Context N]" or expose internal context, chunk, retrieval, or indexing labels in your answer.', prompt)
        self.assertIn("For longer answers, use clear headings when they genuinely aid readability, and keep the response concise.", prompt)
        self.assertIn("Use tables only when they genuinely clarify a comparison or structured result", prompt)
        self.assertIn("How does this work?", prompt)

    def test_context_label_does_not_match_citation_pattern(self) -> None:
        context, _ = build_context([result("code")])

        self.assertIn("Repository excerpt 1:", context)
        self.assertEqual(CITATION_PATTERN.findall(context), [])
        self.assertEqual(CITATION_PATTERN.findall("The answer cites [1]."), ["1"])

    def test_valid_citations_return_matching_sources(self) -> None:
        _, sources = build_context([result("code")])

        cited = cited_sources("The answer uses [1].", sources)

        self.assertEqual([source.citation_id for source in cited], [1])
        self.assertEqual(cited[0].file_path, "app/main.py")

    def test_invalid_citations_are_ignored(self) -> None:
        _, sources = build_context([result("code")])

        cited = cited_sources("The answer uses [1], [99], and [not-a-citation].", sources)

        self.assertEqual([source.citation_id for source in cited], [1])

    def test_duplicate_citations_are_returned_once(self) -> None:
        _, sources = build_context([result("code")])

        cited = cited_sources("The answer uses [1] twice: [1].", sources)

        self.assertEqual([source.citation_id for source in cited], [1])

    def test_insufficient_context_is_explicit(self) -> None:
        self.assertEqual(build_context([]), ("", []))
        self.assertIn("enough relevant", INSUFFICIENT_CONTEXT_MESSAGE)

    def test_openrouter_response_parsing(self) -> None:
        body = {"choices": [{"message": {"content": "  grounded answer  "}}]}
        self.assertEqual(OpenRouterService._parse_response(body), "grounded answer")
        with self.assertRaises(OpenRouterError):
            OpenRouterService._parse_response({"choices": []})

    @patch("app.llm_service.urllib.request.urlopen")
    def test_mocked_openrouter_http_response(self, urlopen) -> None:
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        response.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "answer"}}]}
        ).encode()
        urlopen.return_value = response
        with patch("app.llm_service.json.load", return_value={
            "choices": [{"message": {"content": "answer"}}]
        }):
            service = OpenRouterService(api_key="test-key", model="test-model")
            self.assertEqual(service.complete("prompt"), "answer")
        request = urlopen.call_args.args[0]
        self.assertIn("Bearer test-key", request.headers["Authorization"])
        self.assertEqual(json.loads(request.data)["model"], "test-model")

    @patch("app.llm_service.urllib.request.urlopen")
    def test_mocked_openrouter_http_error_is_logged(self, urlopen) -> None:
        error_body = b'{"error":{"message":"model is unavailable"}}'
        urlopen.side_effect = urllib.error.HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(error_body),
        )
        service = OpenRouterService(api_key="test-key", model="test-model")

        with self.assertLogs("app.llm_service", level="ERROR") as logs:
            with self.assertRaisesRegex(OpenRouterError, "OpenRouter request failed"):
                service.complete("prompt")

        self.assertIn(
            'OpenRouter request failed with HTTP 429: {"error":{"message":"model is unavailable"}}',
            logs.output[0],
        )
        self.assertNotIn("test-key", logs.output[0])


if __name__ == "__main__":
    unittest.main()