from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import ingest, ingest_many, search
from .vision import describe_keyframes
from .retrieval import build_vector_index
from .qa import answer_question, save_answer
from .evaluation import evaluate_cases, save_evaluation
from .inspection import inspect_knowledge
from .diagnostics import doctor
from .report import write_report


def main() -> None:
    parser = argparse.ArgumentParser(prog="video2knowledge")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser("ingest", help="ingest a video or document")
    ingest_parser.add_argument("input", type=Path)
    ingest_parser.add_argument("--output", type=Path, required=True)
    ingest_parser.add_argument("--transcribe", action="store_true")
    ingest_parser.add_argument("--model-size", default="small", help="Whisper 模型：tiny/base/small/medium/large-v3")
    ingest_parser.add_argument("--language", default=None, help="可选语言代码，例如 zh 或 en")
    ingest_parser.add_argument("--device", default="auto", help="auto/cpu/cuda")
    ingest_parser.add_argument("--compute-type", default="int8", help="例如 int8、float16")
    ingest_parser.add_argument("--frame-interval", type=float, default=5.0, help="视频关键帧间隔（秒）")
    ingest_parser.add_argument("--describe-frames", action="store_true", help="调用视觉模型描述关键帧")

    ingest_many_parser = sub.add_parser("ingest-many", help="ingest several files into one collection")
    ingest_many_parser.add_argument("inputs", nargs="+", type=Path)
    ingest_many_parser.add_argument("--output", type=Path, required=True)
    ingest_many_parser.add_argument("--transcribe", action="store_true")
    ingest_many_parser.add_argument("--model-size", default="small")
    ingest_many_parser.add_argument("--language", default=None)
    ingest_many_parser.add_argument("--device", default="auto")
    ingest_many_parser.add_argument("--compute-type", default="int8")
    ingest_many_parser.add_argument("--frame-interval", type=float, default=5.0)
    ingest_many_parser.add_argument("--describe-frames", action="store_true")

    describe_parser = sub.add_parser("describe", help="describe extracted keyframes")
    describe_parser.add_argument("frames_dir", type=Path)
    describe_parser.add_argument("--output", type=Path, required=True)
    describe_parser.add_argument("--model", default=None)

    ask_parser = sub.add_parser("ask", help="keyword search in a knowledge pack")
    ask_parser.add_argument("knowledge_dir", type=Path)
    ask_parser.add_argument("question")
    ask_parser.add_argument("--limit", type=int, default=5)
    ask_parser.add_argument("--mode", choices=["auto", "vector", "lexical", "hybrid"], default="auto")
    ask_parser.add_argument("--min-score", type=float, default=0.05)

    answer_parser = sub.add_parser("answer", help="answer a question with evidence")
    answer_parser.add_argument("knowledge_dir", type=Path)
    answer_parser.add_argument("question")
    answer_parser.add_argument("--limit", type=int, default=5)
    answer_parser.add_argument("--mode", choices=["auto", "vector", "lexical", "hybrid"], default="auto")
    answer_parser.add_argument("--min-score", type=float, default=0.05)
    answer_parser.add_argument("--llm", action="store_true", help="调用兼容 Chat Completions 的问答模型")
    answer_parser.add_argument("--output", type=Path, default=None)

    index_parser = sub.add_parser("index", help="build a local vector index")
    index_parser.add_argument("knowledge_dir", type=Path)

    inspect_parser = sub.add_parser("inspect", help="inspect knowledge pack status")
    inspect_parser.add_argument("knowledge_dir", type=Path)

    sub.add_parser("doctor", help="check local dependencies and optional capabilities")

    report_parser = sub.add_parser("report", help="write a source-grounded Markdown study report")
    report_parser.add_argument("knowledge_dir", type=Path)
    report_parser.add_argument("--output", type=Path, default=None)
    report_parser.add_argument("--max-points", type=int, default=12)

    evaluate_parser = sub.add_parser("evaluate", help="evaluate retrieval and citations")
    evaluate_parser.add_argument("knowledge_dir", type=Path)
    evaluate_parser.add_argument("cases", type=Path)
    evaluate_parser.add_argument("--limit", type=int, default=5)
    evaluate_parser.add_argument("--mode", choices=["auto", "vector", "lexical", "hybrid"], default="auto")
    evaluate_parser.add_argument("--min-score", type=float, default=0.05)
    evaluate_parser.add_argument("--output", type=Path, default=None)

    args = parser.parse_args()
    if args.command == "ingest":
        options = {
            "model_size": args.model_size,
            "language": args.language,
            "device": args.device,
            "compute_type": args.compute_type,
        }
        target = ingest(args.input, args.output, transcribe=args.transcribe, transcribe_options=options, frame_interval=args.frame_interval, describe_frames=args.describe_frames)
        print(json.dumps({"knowledge_dir": str(target.resolve())}, ensure_ascii=False, indent=2))
    elif args.command == "ingest-many":
        options = {
            "model_size": args.model_size,
            "language": args.language,
            "device": args.device,
            "compute_type": args.compute_type,
        }
        target = ingest_many(args.inputs, args.output, transcribe=args.transcribe, transcribe_options=options, frame_interval=args.frame_interval, describe_frames=args.describe_frames)
        print(json.dumps({"knowledge_dir": str(target.resolve())}, ensure_ascii=False, indent=2))
    elif args.command == "answer":
        result = answer_question(args.knowledge_dir, args.question, limit=args.limit, mode=args.mode, min_score=args.min_score, use_llm=args.llm)
        if args.output:
            save_answer(result, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "index":
        print(json.dumps(build_vector_index(args.knowledge_dir), ensure_ascii=False, indent=2))
    elif args.command == "inspect":
        print(json.dumps(inspect_knowledge(args.knowledge_dir), ensure_ascii=False, indent=2))
    elif args.command == "doctor":
        print(json.dumps(doctor(), ensure_ascii=False, indent=2))
    elif args.command == "report":
        output = args.output or (args.knowledge_dir / "report.md")
        print(json.dumps(write_report(args.knowledge_dir, output, max_points=args.max_points), ensure_ascii=False, indent=2))
    elif args.command == "describe":
        result = describe_keyframes(args.frames_dir, args.output, model=args.model)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "ask":
        hits = search(args.knowledge_dir, args.question, limit=args.limit, mode=args.mode, min_score=args.min_score)
        if not hits:
            print("没有找到匹配证据。")
            return
        for index, hit in enumerate(hits, start=1):
            print(f"[{index}] {hit['text']}\n来源：{hit['source']} / {hit['location']}\n检索：{hit.get('retrieval', 'unknown')}，得分：{hit.get('score', 0)}\n")
    elif args.command == "evaluate":
        result = evaluate_cases(args.knowledge_dir, args.cases, mode=args.mode, limit=args.limit, min_score=args.min_score)
        if args.output:
            save_evaluation(result, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
