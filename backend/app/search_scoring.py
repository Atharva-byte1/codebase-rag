import math
import re
from collections import Counter


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
BM25_K1 = 1.5
BM25_B = 0.75


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.replace("_", " ").casefold())


def bm25_scores(query: str, documents: list[str]) -> list[float]:
    """Return Okapi BM25 scores for query against the supplied corpus."""
    query_terms = tokenize(query)
    document_terms = [tokenize(document) for document in documents]
    if not query_terms or not document_terms:
        return [0.0] * len(documents)

    document_frequencies = Counter(
        term for terms in document_terms for term in set(terms)
    )
    average_length = sum(map(len, document_terms)) / len(document_terms)
    if average_length == 0:
        return [0.0] * len(documents)

    document_count = len(document_terms)
    scores: list[float] = []
    for terms in document_terms:
        term_counts = Counter(terms)
        document_length = len(terms)
        score = 0.0
        for term in query_terms:
            document_frequency = document_frequencies.get(term, 0)
            if document_frequency == 0:
                continue
            inverse_document_frequency = math.log(
                1 + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            term_frequency = term_counts[term]
            denominator = term_frequency + BM25_K1 * (
                1 - BM25_B + BM25_B * document_length / average_length
            )
            score += inverse_document_frequency * (
                term_frequency * (BM25_K1 + 1) / denominator
            )
        scores.append(score)
    return scores


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def hybrid_scores(
    bm25_values: list[float], vector_values: list[float]
) -> list[float]:
    """Combine normalized BM25 and cosine scores with equal weighting."""
    if len(bm25_values) != len(vector_values):
        raise ValueError("Score lists must have the same length")
    if not bm25_values:
        return []

    maximum_bm25 = max(bm25_values)
    normalized_bm25 = [
        value / maximum_bm25 if maximum_bm25 > 0 else 0.0
        for value in bm25_values
    ]
    normalized_vector = [
        max(0.0, min(1.0, (value + 1.0) / 2.0)) for value in vector_values
    ]
    return [
        (bm25_value + vector_value) / 2
        for bm25_value, vector_value in zip(normalized_bm25, normalized_vector)
    ]