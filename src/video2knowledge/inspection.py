from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def inspect_knowledge(knowledge_dir: str | Path) -> dict[str, Any]:
    """Summarize the available evidence and processing warnings in a knowledge pack."""
    root = Path(knowledge_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks_path = root / "chunks.jsonl"
    chunks = [
        json.loads(line)
        for line in chunks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if chunks_path.exists() else []
    modalities = Counter(chunk.get("modality", "text") for chunk in chunks)
    metadata = manifest.get("metadata", {})
    warnings: list[str] = []
    for status in ("status", "transcription", "vision", "keyframes"):
        value = metadata.get(status)
        if isinstance(value, dict):
            nested_status = value.get("status")
            if nested_status in {"no_audio_track", "transcription_unavailable", "transcription_failed", "unavailable", "failed"}:
                warnings.append(f"{status}:{nested_status}")
        elif value in {"no_audio_track", "transcription_unavailable", "transcription_failed", "unavailable", "failed"}:
            warnings.append(f"{status}:{value}")
    if not chunks:
        warnings.append("no_knowledge_chunks")
    retrieval = metadata.get("retrieval", {})
    if isinstance(retrieval, dict) and retrieval.get("status") == "unavailable":
        warnings.append("vector_retrieval_unavailable")
    return {
        "knowledge_dir": str(root.resolve()),
        "input": manifest.get("input"),
        "input_count": manifest.get("input_count", 1),
        "chunk_count": len(chunks),
        "modalities": dict(sorted(modalities.items())),
        "retrieval": retrieval,
        "warnings": warnings,
        "manifest": manifest,
    }
