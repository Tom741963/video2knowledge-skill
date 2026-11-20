from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .qa import answer_question


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load newline-delimited JSON evaluation cases."""
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"评测用例第 {line_number} 行不是有效 JSON：{exc}") from exc
        if not case.get("id") or not case.get("question"):
            raise ValueError(f"评测用例第 {line_number} 行缺少 id 或 question")
        case.setdefault("expected_terms", [])
        cases.append(case)
    return cases


def evaluate_cases(
    knowledge_dir: str | Path,
    cases_path: str | Path,
    *,
    mode: str = "auto",
    limit: int = 5,
    min_score: float = 0.05,
) -> dict[str, Any]:
    """Evaluate retrieval coverage and citation presence for a knowledge pack."""
    case_results: list[dict[str, Any]] = []
    for case in load_cases(cases_path):
        result = answer_question(knowledge_dir, case["question"], limit=limit, mode=mode, min_score=min_score)
        texts = "\n".join(match.get("text", "") for match in result.get("matches", [])).casefold()
        expected_terms = [str(term) for term in case.get("expected_terms", [])]
        term_hits = {term: term.casefold() in texts for term in expected_terms}
        retrieval_pass = all(term_hits.values()) if term_hits else bool(result.get("matches"))
        citation_pass = any(
            citation.get("source") and citation.get("location")
            for citation in result.get("citations", [])
        )
        case_results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "retrieval_pass": retrieval_pass,
                "citation_pass": citation_pass,
                "expected_terms": expected_terms,
                "term_hits": term_hits,
                "match_count": len(result.get("matches", [])),
                "citation_count": len(result.get("citations", [])),
                "answer_mode": result.get("mode"),
                "answer": result.get("answer", ""),
            }
        )

    total = len(case_results)
    retrieval_passed = sum(item["retrieval_pass"] for item in case_results)
    citation_passed = sum(item["citation_pass"] for item in case_results)
    return {
        "knowledge_dir": str(Path(knowledge_dir)),
        "cases": str(Path(cases_path)),
        "mode": mode,
        "min_score": min_score,
        "case_count": total,
        "retrieval_pass_count": retrieval_passed,
        "citation_pass_count": citation_passed,
        "retrieval_pass_rate": retrieval_passed / total if total else 0.0,
        "citation_pass_rate": citation_passed / total if total else 0.0,
        "overall_pass": bool(case_results) and all(
            item["retrieval_pass"] and item["citation_pass"] for item in case_results
        ),
        "results": case_results,
    }


def save_evaluation(result: dict[str, Any], output_path: str | Path) -> None:
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
