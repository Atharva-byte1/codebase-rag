import json
import io
import urllib.error
import unittest
from unittest.mock import patch

from app.chat import INSUFFICIENT_CONTEXT_MESSAGE, build_context, build_prompt
from app.llm_service import OpenRouterError, OpenRouterService
from app.routes.search import SearchResult


def result(content: str, path: str = "app/main.py") -> SearchResult:
    return SearchResult(
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
        context = build_context([result("def app(): pass")], max_chars=1000)
        self.assertIn("app/main.py:1-3 (app)", context)
        self.assertIn("def app(): pass", context)
        self.assertEqual(build_context([result("too long")], max_chars=1), "")

    def test_prompt_building_requires_grounded_answers(self) -> None:
        prompt = build_prompt("How does this work?", "[Context 1] app/main.py\ncode")
        self.assertIn("source of truth", prompt)
        self.assertIn("Never invent", prompt)
        self.assertIn("How does this work?", prompt)

    def test_insufficient_context_is_explicit(self) -> None:
        self.assertEqual(build_context([]), "")
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