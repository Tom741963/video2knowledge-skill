from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evaluation import evaluate_cases
from .inspection import inspect_knowledge
from .diagnostics import doctor
from .report import build_report
from .pipeline import ingest, ingest_many, search
from .qa import answer_question
from .vision import describe_keyframes

try:
    from mcp.server import MCPServer
except ImportError:  # pragma: no cover - exercised only without the optional extra
    MCPServer = None  # type: ignore[assignment,misc]


def create_server() -> Any:
    if MCPServer is None:
        raise RuntimeError('MCP 支持需要安装可选依赖：pip install -e ".[mcp]"')

    server = MCPServer(
        name="video2knowledge",
        description="Ingest multimedia files and answer questions with source-grounded evidence.",
        version="0.2.0",
    )

    @server.tool(description="Ingest one supported file into a searchable knowledge pack.")
    def ingest_file(input: str, output: str, transcribe: bool = False, language: str | None = None) -> dict[str, Any]:
        target = ingest(
            input,
            output,
            transcribe=transcribe,
            transcribe_options={"model_size": "small", "language": language, "device": "auto", "compute_type": "int8"},
        )
        return {
            "knowledge_dir": str(target.resolve()),
            "manifest": json.loads((target / "manifest.json").read_text(encoding="utf-8")),
        }

    @server.tool(description="Ingest several supported files into one cross-source collection.")
    def ingest_files(inputs: list[str], output: str, transcribe: bool = False, language: str | None = None) -> dict[str, Any]:
        target = ingest_many(
            inputs,
            output,
            transcribe=transcribe,
            transcribe_options={"model_size": "small", "language": language, "device": "auto", "compute_type": "int8"},
        )
        return {
            "knowledge_dir": str(target.resolve()),
            "manifest": json.loads((target / "manifest.json").read_text(encoding="utf-8")),
        }

    @server.tool(description="Retrieve evidence chunks without generating an answer.")
    def ask_knowledge(knowledge_dir: str, question: str, limit: int = 5, mode: str = "auto", min_score: float = 0.05) -> list[dict[str, Any]]:
        return search(knowledge_dir, question, limit=limit, mode=mode, min_score=min_score)

    @server.tool(description="Inspect available modalities, retrieval status, and processing warnings.")
    def inspect_knowledge_pack(knowledge_dir: str) -> dict[str, Any]:
        return inspect_knowledge(knowledge_dir)

    @server.tool(description="Check local dependencies, binaries, API configuration, and optional capabilities.")
    def diagnose_environment() -> dict[str, Any]:
        return doctor()

    @server.tool(description="Build a Markdown study report with source locations and processing warnings.")
    def generate_report(knowledge_dir: str, max_points: int = 12) -> dict[str, Any]:
        return build_report(knowledge_dir, max_points=max_points)

    @server.tool(description="Answer a question with citations and evidence status.")
    def answer_with_evidence(knowledge_dir: str, question: str, limit: int = 5, mode: str = "auto", min_score: float = 0.05) -> dict[str, Any]:
        return answer_question(knowledge_dir, question, limit=limit, mode=mode, min_score=min_score)

    @server.tool(description="Evaluate retrieval coverage and citation presence from a JSONL case file.")
    def evaluate_knowledge(knowledge_dir: str, cases: str, limit: int = 5, mode: str = "auto", min_score: float = 0.05) -> dict[str, Any]:
        return evaluate_cases(knowledge_dir, cases, limit=limit, mode=mode, min_score=min_score)

    @server.tool(description="Describe extracted keyframes with the configured vision model.")
    def describe_frames(frames_dir: str, output: str, model: str | None = None) -> dict[str, Any]:
        return describe_keyframes(Path(frames_dir), Path(output), model=model)

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
