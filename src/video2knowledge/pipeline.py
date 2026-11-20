from __future__ import annotations

import hashlib
import json
import csv
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .frames import extract_keyframes, write_keyframe_manifest
from .vision import describe_keyframes
from .retrieval import VectorIndexUnavailable, build_vector_index

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".srt", ".vtt"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

@dataclass
class Source:
    file: str
    location: str
    text: str
    modality: str = "text"
    start_seconds: float | None = None
    end_seconds: float | None = None

@dataclass
class Chunk:
    id: str
    text: str
    source: str
    location: str
    modality: str = "text"
    start_seconds: float | None = None
    end_seconds: float | None = None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_csv(path: Path) -> list[Source]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return [Source(path.name, "document", "")]
    headers = rows[0]
    sources: list[Source] = []
    for number, row in enumerate(rows[1:] if len(rows) > 1 else rows, start=2 if len(rows) > 1 else 1):
        values = [value.strip() for value in row]
        if not any(values):
            continue
        if len(rows) > 1 and any(headers):
            content = "\n".join(f"{header.strip()}: {value}" for header, value in zip(headers, values) if header.strip() or value)
        else:
            content = ", ".join(values)
        sources.append(Source(path.name, f"row:{number}", content))
    return sources or [Source(path.name, "document", "")]


def _extract_xlsx(path: Path) -> list[Source]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("处理 XLSX 需要安装可选依赖：pip install -e '.[documents]'") from exc
    workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    sources: list[Source] = []
    for sheet in workbook.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue
        headers = ["" if value is None else str(value) for value in rows[0]]
        for number, row in enumerate(rows[1:] if len(rows) > 1 else rows, start=2 if len(rows) > 1 else 1):
            values = ["" if value is None else str(value).strip() for value in row]
            if not any(values):
                continue
            if len(rows) > 1 and any(headers):
                content = "\n".join(f"{header.strip()}: {value}" for header, value in zip(headers, values) if header.strip() or value)
            else:
                content = ", ".join(values)
            sources.append(Source(path.name, f"sheet:{sheet.title}/row:{number}", content))
    return sources or [Source(path.name, "document", "")]


def _extract_json(path: Path) -> list[Source]:
    try:
        payload = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 文件格式错误：{exc}") from exc
    sources: list[Source] = []

    def walk(value: object, location: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_location = f"{location}.{key}" if location else str(key)
                walk(child, child_location)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                child_location = f"{location}[{index}]" if location else f"[{index}]"
                walk(child, child_location)
            return
        text = "" if value is None else str(value).strip()
        if text:
            sources.append(Source(path.name, f"json:{location or '$'}", text))

    walk(payload, "")
    return sources or [Source(path.name, "document", "")]


def _parse_timestamp(value: str) -> float | None:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return float(minutes) * 60 + float(seconds)
        return float(value.rstrip("s"))
    except ValueError:
        return None


def _parse_location_range(location: str) -> tuple[float | None, float | None]:
    if "-->" in location:
        left, right = [part.strip().split()[0] for part in location.split("-->", 1)]
        return _parse_timestamp(left), _parse_timestamp(right)
    if location.endswith("s") and "-" in location:
        left, right = location[:-1].split("-", 1)
        return _parse_timestamp(left), _parse_timestamp(right)
    if location.startswith("frame:") and location.endswith("s"):
        value = _parse_timestamp(location[6:])
        return value, value
    return None, None


def _parse_srt_vtt(text: str) -> list[Source]:
    blocks = re.split(r"\n\s*\n", text.strip())
    output: list[Source] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_line = next((line for line in lines if "-->" in line), "")
        if time_line:
            payload = [line for line in lines if "-->" not in line and not line.isdigit()]
            start, end = _parse_location_range(time_line)
            output.append(Source("", time_line, " ".join(payload), modality="audio", start_seconds=start, end_seconds=end))
    return output


def _parse_markdown_sections(path: Path, text: str) -> list[Source]:
    sections: list[Source] = []
    current_title = "document"
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(Source(path.name, current_title if current_title == "document" else f"section:{current_title}", content))

    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading:
            flush()
            current_title = heading.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)
    flush()
    return sections or [Source(path.name, "document", text)]


def _ffprobe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"available": False, "reason": "ffprobe not found"}
    command = [ffprobe, "-v", "error", "-show_entries", "format=duration,format_name", "-of", "json", str(path)]
    try:
        raw = subprocess.check_output(command, text=True)
        data = json.loads(raw)
        fmt = data.get("format", {})
        duration = float(fmt["duration"]) if fmt.get("duration") else None
        return {"available": True, "format": fmt.get("format_name"), "duration_seconds": duration}
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def _extract_pdf(path: Path) -> list[Source]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("处理 PDF 需要安装可选依赖：pip install -e '.[documents]'") from exc
    result = []
    for index, page in enumerate(PdfReader(str(path)).pages, start=1):
        result.append(Source(path.name, f"page:{index}", page.extract_text() or ""))
    return result


def _extract_docx(path: Path) -> list[Source]:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("处理 DOCX 需要安装可选依赖：pip install -e '.[documents]'") from exc
    paragraphs = [paragraph for paragraph in Document(str(path)).paragraphs if paragraph.text.strip()]
    if not paragraphs:
        return [Source(path.name, "document", "")]
    has_headings = any(
        getattr(getattr(paragraph, "style", None), "name", "").lower().startswith("heading")
        for paragraph in paragraphs
    )
    if not has_headings:
        return [Source(path.name, "document", "\n".join(paragraph.text for paragraph in paragraphs))]

    sections: list[Source] = []
    current_title = "document"
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            location = current_title if current_title == "document" else f"section:{current_title}"
            sections.append(Source(path.name, location, content))

    for paragraph in paragraphs:
        style_name = getattr(getattr(paragraph, "style", None), "name", "").lower()
        if style_name.startswith("heading"):
            flush()
            current_title = paragraph.text.strip()
            current_lines = [paragraph.text.strip()]
        else:
            current_lines.append(paragraph.text.strip())
    flush()
    return sections


def _extract_pptx(path: Path) -> list[Source]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise RuntimeError("处理 PPTX 需要安装可选依赖：pip install -e '.[documents]'") from exc
    sources: list[Source] = []
    presentation = Presentation(str(path))
    for number, slide in enumerate(presentation.slides, start=1):
        texts = [
            shape.text.strip()
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text.strip()
        ]
        content = "\n".join(texts).strip()
        if content:
            sources.append(Source(path.name, f"slide:{number}", content))
    return sources or [Source(path.name, "document", "")]


def load_sources(path: Path, transcribe: bool = False, transcribe_options: dict | None = None) -> tuple[list[Source], dict]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _extract_csv(path), {"kind": "csv", "status": "parsed"}
    if suffix == ".xlsx":
        return _extract_xlsx(path), {"kind": "xlsx", "status": "parsed"}
    if suffix == ".json":
        return _extract_json(path), {"kind": "json", "status": "parsed"}
    if suffix in TEXT_EXTENSIONS:
        raw = _read_text(path)
        if suffix in {".srt", ".vtt"}:
            sources = _parse_srt_vtt(raw)
            for item in sources:
                item.file = path.name
            return sources, {"kind": "subtitle", "status": "parsed"}
        if suffix in {".md", ".markdown"}:
            return _parse_markdown_sections(path, raw), {"kind": "markdown", "status": "parsed"}
        return [Source(path.name, "document", raw)], {"kind": "text", "status": "parsed"}
    if suffix == ".pdf":
        return _extract_pdf(path), {"kind": "pdf", "status": "parsed"}
    if suffix == ".docx":
        return _extract_docx(path), {"kind": "docx", "status": "parsed"}
    if suffix == ".pptx":
        return _extract_pptx(path), {"kind": "pptx", "status": "parsed"}
    if suffix in VIDEO_EXTENSIONS:
        media = _ffprobe(path)
        for sidecar_suffix in (".srt", ".vtt"):
            sidecar = path.with_suffix(sidecar_suffix)
            if not sidecar.exists():
                continue
            sources = _parse_srt_vtt(_read_text(sidecar))
            for item in sources:
                item.file = sidecar.name
            return sources, {
                "kind": "video",
                "status": "subtitle_sidecar",
                "media": media,
                "subtitle": str(sidecar.resolve()),
            }
        if transcribe:
            try:
                from .transcribe import TranscriptionUnavailable, transcribe_video
                sources = transcribe_video(path, **(transcribe_options or {}))
                return sources, {"kind": "video", "status": "transcribed", "media": media, "transcription": transcribe_options or {}}
            except TranscriptionUnavailable as exc:
                status = "no_audio_track" if "没有音频轨" in str(exc) else "transcription_unavailable"
                return [], {"kind": "video", "status": status, "error": str(exc), "media": media}
            except Exception as exc:
                return [], {"kind": "video", "status": "transcription_failed", "error": str(exc), "media": media}
        return [], {"kind": "video", "status": "metadata_only", "media": media, "hint": "提供 .srt/.vtt 或安装 video extras 后使用 --transcribe"}
    raise ValueError(f"暂不支持的文件类型：{path.suffix}")


def chunk_sources(sources: Iterable[Source], max_chars: int = 900, overlap: int = 120) -> list[Chunk]:
    chunks: list[Chunk] = []
    for source in sources:
        text = re.sub(r"\s+", " ", source.text).strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            end = min(len(text), start + max_chars)
            if end < len(text):
                boundary = text.rfind("。", start, end)
                boundary = max(boundary, text.rfind(".", start, end), text.rfind(" ", start, end))
                if boundary > start + max_chars // 2:
                    end = boundary + 1
            piece = text[start:end].strip()
            digest = hashlib.sha1(f"{source.file}|{source.location}|{start}|{piece}".encode()).hexdigest()[:12]
            chunks.append(Chunk(f"chunk-{digest}", piece, source.file, source.location, source.modality, source.start_seconds, source.end_seconds))
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
    return chunks


def extract_keywords(chunks: list[Chunk], limit: int = 20) -> list[str]:
    stopwords = set("的 了 和 是 在 对 与 及 一个 这个 主要 可以 进行 通过 使用 以及 用户 内容 需要 如果 into the and is are of to in for a an".split())
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", " ".join(c.text for c in chunks).lower())
    counts: dict[str, int] = {}
    for word in words:
        if word not in stopwords:
            counts[word] = counts.get(word, 0) + 1
    return [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def build_summary(chunks: list[Chunk], keywords: list[str]) -> str:
    lines = ["# 内容摘要", "", f"共生成 {len(chunks)} 个知识分块。", "", "## 关键词", "", ", ".join(keywords) if keywords else "暂无足够文本提取关键词。", "", "## 内容片段", ""]
    for chunk in chunks[:8]:
        lines.append(f"- [{chunk.location}] {chunk.text[:180]}")
    return "\n".join(lines) + "\n"


def ingest(input_path: str | Path, output_dir: str | Path, transcribe: bool = False, transcribe_options: dict | None = None, frame_interval: float = 5.0, describe_frames: bool = False) -> Path:
    source_path = Path(input_path)
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    sources, metadata = load_sources(source_path, transcribe=transcribe, transcribe_options=transcribe_options)
    frame_sources: list[Source] = []
    if source_path.suffix.lower() in VIDEO_EXTENSIONS:
        keyframe_metadata = extract_keyframes(source_path, target / "frames", interval_seconds=frame_interval)
        metadata["keyframes"] = {
            "status": keyframe_metadata.get("status"),
            "count": keyframe_metadata.get("count", 0),
            "interval_seconds": keyframe_metadata.get("interval_seconds", frame_interval),
        }
        write_keyframe_manifest(target, keyframe_metadata)
        if describe_frames and keyframe_metadata.get("status") == "extracted":
            descriptions = describe_keyframes(target / "frames", target / "frame_descriptions.json")
            metadata["vision"] = {
                "status": descriptions.get("status"),
                "count": descriptions.get("count", 0),
                "described_count": descriptions.get("described_count", 0),
            }
            frame_times = {item["index"]: item.get("timestamp_seconds") for item in keyframe_metadata.get("frames", [])}
            for record in descriptions.get("frames", []):
                if record.get("status") != "described":
                    continue
                timestamp = frame_times.get(record.get("index"))
                frame_sources.append(Source(
                    source_path.name,
                    f"frame:{timestamp:g}s" if timestamp is not None else f"frame:{record.get('file')}",
                    record["description"],
                    modality="vision",
                    start_seconds=timestamp,
                    end_seconds=timestamp,
                ))
    all_sources = sources + frame_sources
    chunks = chunk_sources(all_sources)
    keywords = extract_keywords(chunks)

    manifest = {"input": str(source_path.resolve()), "filename": source_path.name, "metadata": metadata, "chunk_count": len(chunks), "keywords": keywords}
    with (target / "chunks.jsonl").open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    try:
        metadata["retrieval"] = build_vector_index(target)
    except VectorIndexUnavailable as exc:
        metadata["retrieval"] = {"status": "unavailable", "error": str(exc)}
    manifest["metadata"] = metadata
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "transcript.md").write_text("\n\n".join(f"## {s.location}\n{s.text}" for s in sources), encoding="utf-8")
    (target / "multimodal.md").write_text("\n\n".join(f"## [{s.modality}] {s.location}\n{s.text}" for s in all_sources), encoding="utf-8")
    (target / "summary.md").write_text(build_summary(chunks, keywords), encoding="utf-8")
    timeline = [{"location": c.location, "chunk_id": c.id, "preview": c.text[:120], "modality": c.modality, "start_seconds": c.start_seconds, "end_seconds": c.end_seconds} for c in chunks]
    (target / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    source_timeline = [{"source": s.file, "location": s.location, "modality": s.modality, "start_seconds": s.start_seconds, "end_seconds": s.end_seconds, "text": s.text} for s in all_sources]
    (target / "source_timeline.json").write_text(json.dumps(source_timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence = [{"claim": c.text[:180], "source": c.source, "location": c.location, "modality": c.modality, "start_seconds": c.start_seconds, "end_seconds": c.end_seconds, "chunk_id": c.id} for c in chunks]
    (target / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def ingest_many(
    input_paths: Iterable[str | Path],
    output_dir: str | Path,
    transcribe: bool = False,
    transcribe_options: dict | None = None,
    frame_interval: float = 5.0,
    describe_frames: bool = False,
) -> Path:
    """Create one searchable collection from several independent knowledge packs."""
    paths = [Path(path) for path in input_paths]
    if not paths:
        raise ValueError("至少需要一个输入文件")
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    source_root = target / "sources"
    source_root.mkdir(parents=True, exist_ok=True)
    child_dirs: list[Path] = []
    for index, path in enumerate(paths, start=1):
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-") or "source"
        child = source_root / f"{index:03d}-{safe_stem}"
        child_dirs.append(ingest(
            path,
            child,
            transcribe=transcribe,
            transcribe_options=transcribe_options,
            frame_interval=frame_interval,
            describe_frames=describe_frames,
        ))

    combined_chunks: list[dict] = []
    source_manifests: list[dict] = []
    combined_keywords: list[str] = []
    transcript_parts: list[str] = []
    multimodal_parts: list[str] = []
    for child in child_dirs:
        manifest = json.loads((child / "manifest.json").read_text(encoding="utf-8"))
        source_manifests.append(manifest)
        combined_keywords.extend(manifest.get("keywords", []))
        for line in (child / "chunks.jsonl").read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            item["collection"] = child.name
            item["id"] = f"{child.name}:{item['id']}"
            combined_chunks.append(item)
        transcript_parts.append(f"# {child.name}\n{(child / 'transcript.md').read_text(encoding='utf-8')}")
        multimodal_parts.append(f"# {child.name}\n{(child / 'multimodal.md').read_text(encoding='utf-8')}")

    unique_keywords = sorted(set(combined_keywords))
    with (target / "chunks.jsonl").open("w", encoding="utf-8") as handle:
        for chunk in combined_chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    (target / "transcript.md").write_text("\n\n".join(transcript_parts), encoding="utf-8")
    (target / "multimodal.md").write_text("\n\n".join(multimodal_parts), encoding="utf-8")
    (target / "summary.md").write_text(
        "# 内容摘要\n\n"
        f"共收录 {len(paths)} 个文件，生成 {len(combined_chunks)} 个知识分块。\n\n"
        "## 关键词\n\n"
        + (", ".join(unique_keywords) if unique_keywords else "暂无足够文本提取关键词。")
        + "\n",
        encoding="utf-8",
    )
    timeline = [
        {
            "location": chunk.get("location"),
            "chunk_id": chunk.get("id"),
            "preview": chunk.get("text", "")[:120],
            "modality": chunk.get("modality", "text"),
            "start_seconds": chunk.get("start_seconds"),
            "end_seconds": chunk.get("end_seconds"),
            "collection": chunk.get("collection"),
        }
        for chunk in combined_chunks
    ]
    (target / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "source_timeline.json").write_text(
        json.dumps(
            [
                {
                    "source": chunk.get("source"),
                    "location": chunk.get("location"),
                    "modality": chunk.get("modality", "text"),
                    "start_seconds": chunk.get("start_seconds"),
                    "end_seconds": chunk.get("end_seconds"),
                    "text": chunk.get("text", ""),
                    "collection": chunk.get("collection"),
                }
                for chunk in combined_chunks
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (target / "evidence.json").write_text(
        json.dumps(
            [
                {
                    "claim": chunk.get("text", "")[:180],
                    "source": chunk.get("source"),
                    "location": chunk.get("location"),
                    "modality": chunk.get("modality", "text"),
                    "start_seconds": chunk.get("start_seconds"),
                    "end_seconds": chunk.get("end_seconds"),
                    "chunk_id": chunk.get("id"),
                    "collection": chunk.get("collection"),
                }
                for chunk in combined_chunks
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    metadata = {
        "kind": "collection",
        "status": "ready",
        "source_count": len(paths),
        "sources": source_manifests,
    }
    try:
        metadata["retrieval"] = build_vector_index(target)
    except VectorIndexUnavailable as exc:
        metadata["retrieval"] = {"status": "unavailable", "error": str(exc)}
    manifest = {
        "input_count": len(paths),
        "inputs": [str(path.resolve()) for path in paths],
        "metadata": metadata,
        "chunk_count": len(combined_chunks),
        "keywords": unique_keywords,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def lexical_search(knowledge_dir: str | Path, query: str, limit: int = 5, min_score: float = 0.05) -> list[dict]:
    path = Path(knowledge_dir) / "chunks.jsonl"
    if not path.exists():
        raise FileNotFoundError(path)
    terms = {term.lower() for term in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", query) if term.strip()}
    hits = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        text = item["text"].lower()
        score = sum(text.count(term) for term in terms)
        if score >= min_score:
            item["score"] = score
            hits.append(item)
    return sorted(hits, key=lambda item: (-item["score"], item["id"]))[:limit]


def hybrid_search(knowledge_dir: str | Path, query: str, limit: int = 5, min_score: float = 0.05) -> list[dict]:
    """Combine vector similarity and lexical term matching into one ranked list."""
    vector_hits: list[dict] = []
    try:
        from .retrieval import vector_search
        vector_hits = vector_search(knowledge_dir, query, limit=max(limit * 3, 10), min_score=min_score)
    except (VectorIndexUnavailable, FileNotFoundError):
        vector_hits = []
    lexical_hits = lexical_search(knowledge_dir, query, limit=max(limit * 3, 10), min_score=min_score)
    vector_max = max((float(item.get("score", 0)) for item in vector_hits), default=0.0)
    lexical_max = max((float(item.get("score", 0)) for item in lexical_hits), default=0.0)
    merged: dict[str, dict] = {}
    for item in vector_hits:
        key = item["id"]
        merged[key] = dict(item)
        merged[key]["_vector_score"] = float(item.get("score", 0))
    for item in lexical_hits:
        key = item["id"]
        merged.setdefault(key, dict(item))
        merged[key]["_lexical_score"] = float(item.get("score", 0))
    ranked: list[dict] = []
    for item in merged.values():
        vector_part = item.get("_vector_score", 0.0) / vector_max if vector_max else 0.0
        lexical_part = item.get("_lexical_score", 0.0) / lexical_max if lexical_max else 0.0
        item["score"] = round(0.7 * vector_part + 0.3 * lexical_part, 6)
        item["retrieval"] = "hybrid"
        item.pop("_vector_score", None)
        item.pop("_lexical_score", None)
        if item["score"] >= min_score:
            ranked.append(item)
    return sorted(ranked, key=lambda item: (-item["score"], item["id"]))[:limit]



def search(knowledge_dir: str | Path, query: str, limit: int = 5, mode: str = "auto", min_score: float = 0.05) -> list[dict]:
    if mode == "hybrid":
        return hybrid_search(knowledge_dir, query, limit=limit, min_score=min_score)
    if mode in {"vector", "auto"}:
        try:
            from .retrieval import vector_search
            hits = vector_search(knowledge_dir, query, limit=limit, min_score=min_score)
            if hits or mode == "vector":
                return hits
        except (VectorIndexUnavailable, FileNotFoundError):
            if mode == "vector":
                raise
    hits = lexical_search(knowledge_dir, query, limit=limit, min_score=min_score)
    for item in hits:
        item["retrieval"] = "lexical"
    return hits
