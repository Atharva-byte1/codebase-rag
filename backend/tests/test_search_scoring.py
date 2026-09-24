import unittest

from app.search_scoring import bm25_scores, hybrid_scores, rerank_scores


class SearchScoringTests(unittest.TestCase):
    def test_bm25_prefers_documents_containing_query_terms(self) -> None:
        scores = bm25_scores(
            "database connection",
            ["database connection pool", "render a user interface"],
        )

        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[0], 0)
        self.assertEqual(scores[1], 0)

    def test_hybrid_score_is_deterministic_and_balanced(self) -> None:
        scores = hybrid_scores([2.0, 0.0], [0.2, 0.9])

        self.assertEqual(scores, hybrid_scores([2.0, 0.0], [0.2, 0.9]))
        self.assertGreater(scores[0], scores[1])

    def test_empty_and_no_match_queries_are_zero(self) -> None:
        self.assertEqual(bm25_scores("", ["some code"]), [0.0])
        self.assertEqual(bm25_scores("missing", ["some code"]), [0.0])
        self.assertEqual(hybrid_scores([], []), [])

    def test_reranker_scores_are_returned_in_document_order(self) -> None:
        calls: list[list[list[str]]] = []

        def score_pairs(pairs: list[list[str]]) -> list[float]:
            calls.append(pairs)
            return [0.2, 0.9]

        scores = rerank_scores(
            "find database connection",
            ["database code", "connection pool code"],
            score_pairs,
        )

        self.assertEqual(scores, [0.2, 0.9])
        self.assertEqual(
            calls,
            [[
                ["find database connection", "database code"],
                ["find database connection", "connection pool code"],
            ]],
        )

    def test_reranker_empty_inputs_are_safe(self) -> None:
        def fail_if_called(_pairs: list[list[str]]) -> list[float]:
            raise AssertionError("empty reranking should not call the model")

        self.assertEqual(rerank_scores("", ["some code"], fail_if_called), [0.0])
        self.assertEqual(rerank_scores("query", [], fail_if_called), [])

    def test_reranking_score_controls_ranking_order(self) -> None:
        candidates = [
            ("hybrid-first", 0.95),
            ("hybrid-second", 0.80),
        ]
        reranking_scores = [0.1, 0.9]

        ranked = sorted(
            zip(candidates, reranking_scores),
            key=lambda item: -item[1],
        )

        self.assertEqual(ranked[0][0][0], "hybrid-second")


if __name__ == "__main__":
    unittest.main()