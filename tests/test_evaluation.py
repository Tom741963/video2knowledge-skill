import json
import tempfile
import unittest
from pathlib import Path

from video2knowledge.evaluation import evaluate_cases
from video2knowledge.pipeline import ingest


class EvaluationTests(unittest.TestCase):
    def test_evaluation_reports_retrieval_and_citation_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.md"
            source.write_text(
                "RAG 通过检索外部知识降低幻觉。视频知识库应保留时间戳，方便回看原始视频。",
                encoding="utf-8",
            )
            knowledge_dir = ingest(source, root / "run")
            cases = root / "cases.jsonl"
            cases.write_text(
                json.dumps(
                    {
                        "id": "case-1",
                        "question": "RAG 如何降低幻觉？",
                        "expected_terms": ["检索", "降低幻觉"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            result = evaluate_cases(knowledge_dir, cases, mode="vector")
            self.assertTrue(result["overall_pass"])
            self.assertEqual(result["retrieval_pass_rate"], 1.0)
            self.assertEqual(result["citation_pass_rate"], 1.0)
