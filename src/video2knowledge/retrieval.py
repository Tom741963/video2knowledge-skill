from __future__ import annotations

import json
from pathlib import Path


class VectorIndexUnavailable(RuntimeError):
    """Raised when the optional vector retrieval dependencies are unavailable."""


def _dependencies():
    try:
        import joblib
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        return joblib, TfidfVectorizer, cosine_similarity
    except ImportError as exc:
        raise VectorIndexUnavailable(
            '向量检索需要安装可选依赖：pip install -e ".[retrieval]"。'
        ) from exc


def _load_chunks(knowledge_dir: Path) -> list[dict]:
    path = knowledge_dir / "chunks.jsonl"
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_vector_index(knowledge_dir: str | Path) -> dict:
    knowledge_dir = Path(knowledge_dir)
    chunks = _load_chunks(knowledge_dir)
    if not chunks:
        return {"status": "empty", "count": 0}
    joblib, TfidfVectorizer, _ = _dependencies()
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1, sublinear_tf=True)
    matrix = vectorizer.fit_transform([chunk["text"] for chunk in chunks])
    joblib.dump({"vectorizer": vectorizer, "matrix": matrix, "chunks": chunks}, knowledge_dir / "vector_index.joblib")
    return {"status": "ready", "count": len(chunks), "features": int(matrix.shape[1]), "backend": "tfidf-char"}


def vector_search(knowledge_dir: str | Path, query: str, limit: int = 5, min_score: float = 0.05) -> list[dict]:
    knowledge_dir = Path(knowledge_dir)
    index_path = knowledge_dir / "vector_index.joblib"
    if not index_path.exists():
        build_vector_index(knowledge_dir)
    joblib, _, cosine_similarity = _dependencies()
    bundle = joblib.load(index_path)
    query_vector = bundle["vectorizer"].transform([query])
    scores = cosine_similarity(query_vector, bundle["matrix"])[0]
    ranked = sorted(enumerate(scores.tolist()), key=lambda item: (-item[1], item[0]))
    hits = []
    for index, score in ranked[:limit]:
        if score < min_score:
            continue
        item = dict(bundle["chunks"][index])
        item["score"] = round(float(score), 6)
        item["retrieval"] = "vector"
        hits.append(item)
    return hits
