from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .pipeline import search


class QAUnavailable(RuntimeError):
    """Raised when optional LLM answering cannot run."""


def _citation(hit: dict, index: int) -> dict:
    return {
        "id": index,
        "source": hit.get("source"),
        "collection": hit.get("collection"),
        "location": hit.get("location"),
        "modality": hit.get("modality", "text"),
        "start_seconds": hit.get("start_seconds"),
        "end_seconds": hit.get("end_seconds"),
        "chunk_id": hit.get("id"),
    }


def _extractive_answer(question: str, hits: list[dict]) -> str:
    if not hits:
        return "没有检索到足够的资料证据，暂时无法回答。"
    lines = [f"根据资料中与“{question}”最相关的内容："]
    for index, hit in enumerate(hits, start=1):
        lines.append(f"{index}. {hit['text']} [{index}]")
    lines.append("以上内容是基于检索片段的整理，具体结论请回看对应来源。")
    return "\n".join(lines)


def _llm_answer(question: str, hits: list[dict], *, api_key: str | None = None, base_url: str | None = None, model: str | None = None, timeout: int = 60) -> str:
    api_key = api_key or os.getenv("QA_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise QAUnavailable("未配置问答模型 API Key。")
    base_url = (base_url or os.getenv("QA_API_BASE") or "https://api.openai.com/v1").rstrip("/")
    model = model or os.getenv("QA_MODEL") or "gpt-4o-mini"
    context = "\n".join(
        f"[{index}] 来源={hit.get('source')} 位置={hit.get('location')} 类型={hit.get('modality', 'text')}\n{hit['text']}"
        for index, hit in enumerate(hits, start=1)
    )
    prompt = (
        "你是一个有证据约束的资料问答 Agent。只能根据给出的资料回答。"
        "每个关键结论后必须标注对应的 [编号]；资料不足时明确说不知道。\n\n"
        f"问题：{question}\n\n资料：\n{context}"
    )
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "回答简洁、准确，并保留证据编号。"},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise QAUnavailable(f"问答模型请求失败或返回格式无法解析：{exc}") from exc


def answer_question(
    knowledge_dir: str | Path,
    question: str,
    *,
    limit: int = 5,
    mode: str = "auto",
    min_score: float = 0.05,
    use_llm: bool = False,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict:
    hits = search(knowledge_dir, question, limit=limit, mode=mode, min_score=min_score)
    citations = [_citation(hit, index) for index, hit in enumerate(hits, start=1)]
    top_score = max((float(hit.get("score", 0)) for hit in hits), default=0.0)
    confidence = "high" if top_score >= 0.35 else ("medium" if top_score >= 0.15 else ("low" if hits else "none"))
    evidence_status = "sufficient" if hits else "insufficient"
    answer_mode = "extractive"
    if use_llm and hits:
        try:
            answer = _llm_answer(question, hits, api_key=api_key, base_url=base_url, model=model)
            answer_mode = "llm"
        except QAUnavailable:
            answer = _extractive_answer(question, hits)
            answer_mode = "extractive_fallback"
    else:
        answer = _extractive_answer(question, hits)
    return {
        "question": question,
        "answer": answer,
        "mode": answer_mode,
        "retrieval": mode,
        "min_score": min_score,
        "confidence": confidence,
        "evidence_status": evidence_status,
        "citations": citations,
        "matches": hits,
    }


def save_answer(result: dict, output_path: str | Path) -> None:
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
