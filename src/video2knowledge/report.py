from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .inspection import inspect_knowledge


def build_report(knowledge_dir: str | Path, max_points: int = 12) -> dict[str, Any]:
    """Build a deterministic Markdown study report from a knowledge pack."""
    root = Path(knowledge_dir)
    inspection = inspect_knowledge(root)
    chunks_path = root / "chunks.jsonl"
    chunks = [
        json.loads(line)
        for line in chunks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if chunks_path.exists() else []
    lines = [
        "# 学习报告",
        "",
        f"- 知识包：`{root}`",
        f"- 输入数量：{inspection.get('input_count', 1)}",
        f"- 知识分块：{inspection.get('chunk_count', 0)}",
        f"- 模态：{', '.join(f'{key}={value}' for key, value in inspection.get('modalities', {}).items()) or '无'}",
        "",
        "## 关键内容",
        "",
    ]
    if not chunks:
        lines.append("当前知识包没有可用于整理的内容。")
    else:
        for index, chunk in enumerate(chunks[:max_points], start=1):
            source = chunk.get("source") or "unknown"
            collection = f" / {chunk['collection']}" if chunk.get("collection") else ""
            location = chunk.get("location") or "unknown"
            modality = chunk.get("modality", "text")
            lines.append(f"### {index}. [{modality}] {source}{collection} · {location}")
            lines.append("")
            lines.append(chunk.get("text", "").strip())
            lines.append("")
    lines.extend(["## 处理警告", ""])
    warnings = inspection.get("warnings", [])
    if warnings:
        lines.extend(f"- `{warning}`" for warning in warnings)
    else:
        lines.append("暂无处理警告。")
    lines.extend([
        "",
        "## 使用说明",
        "",
        "以上内容由知识包中的检索分块整理而成。引用结论时请回看对应的来源、页码、时间戳或帧位置。",
        "",
    ])
    return {
        "knowledge_dir": str(root.resolve()),
        "key_point_count": min(len(chunks), max_points),
        "warnings": warnings,
        "markdown": "\n".join(lines),
    }


def write_report(knowledge_dir: str | Path, output_path: str | Path, max_points: int = 12) -> dict[str, Any]:
    result = build_report(knowledge_dir, max_points=max_points)
    output = Path(output_path)
    output.write_text(result["markdown"], encoding="utf-8")
    result["output"] = str(output.resolve())
    result.pop("markdown", None)
    return result
