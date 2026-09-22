import unittest

from app.search_scoring import bm25_scores, hybrid_scores


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


if __name__ == "__main__":
    unittest.main()