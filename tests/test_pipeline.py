import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from video2knowledge.pipeline import Source, chunk_sources, ingest, ingest_many, search
from video2knowledge.frames import extract_keyframes
from video2knowledge.vision import describe_keyframes
from video2knowledge.retrieval import build_vector_index, vector_search
from video2knowledge.qa import answer_question
from video2knowledge.transcribe import transcribe_video
from video2knowledge.inspection import inspect_knowledge
from video2knowledge.diagnostics import doctor
from video2knowledge.report import build_report


class PipelineTests(unittest.TestCase):
    def test_ingest_and_search(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.md"
            source.write_text("RAG 通过检索外部知识降低幻觉。视频还需要时间戳证据。", encoding="utf-8")
            output = ingest(source, root / "run")
            self.assertTrue((output / "manifest.json").exists())
            self.assertTrue((output / "chunks.jsonl").exists())
            hits = search(output, "时间戳证据")
            self.assertTrue(hits)
            self.assertIn("时间戳", hits[0]["text"])

    def test_manifest_is_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.txt"
            source.write_text("hello world", encoding="utf-8")
            output = ingest(source, root / "run")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["chunk_count"], 1)

    def test_multimodal_chunk_keeps_modality_and_time(self):
        chunks = chunk_sources([
            Source("demo.mp4", "0.00-2.00s", "说话内容", modality="audio", start_seconds=0, end_seconds=2),
            Source("demo.mp4", "frame:3s", "画面内容", modality="vision", start_seconds=3, end_seconds=3),
        ])
        self.assertEqual([chunk.modality for chunk in chunks], ["audio", "vision"])
        self.assertEqual(chunks[1].start_seconds, 3)

    def test_keyframes_extract_from_sample_video(self):
        sample = Path(r"D:\wedding-invitation-h5\小鸡项目_破壳过程视频附件.mp4")
        if not sample.exists():
            self.skipTest("sample video not present")
        with tempfile.TemporaryDirectory() as directory:
            metadata = extract_keyframes(sample, Path(directory) / "frames", interval_seconds=5)
            self.assertEqual(metadata["status"], "extracted")
            self.assertGreaterEqual(metadata["count"], 1)
            self.assertTrue((Path(directory) / "frames" / "frame_0001.jpg").exists() or (Path(directory) / "frames" / "frame_0000.jpg").exists())

    def test_answer_includes_evidence_without_llm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.md"
            source.write_text("RAG 通过检索外部知识降低大模型幻觉。", encoding="utf-8")
            output = ingest(source, root / "run")
            result = answer_question(output, "如何减少模型幻觉", mode="vector")
            self.assertEqual(result["mode"], "extractive")
            self.assertTrue(result["citations"])
            self.assertIn("[1]", result["answer"])

    def test_answer_refuses_when_evidence_score_is_below_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.md"
            source.write_text("RAG 通过检索外部知识降低大模型幻觉。", encoding="utf-8")
            output = ingest(source, root / "run")
            result = answer_question(output, "完全无关的量子电池制造流程", mode="vector", min_score=0.5)
            self.assertEqual(result["evidence_status"], "insufficient")
            self.assertEqual(result["confidence"], "none")
            self.assertFalse(result["citations"])
            self.assertIn("无法回答", result["answer"])

    def test_ingest_many_searches_across_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.md"
            second = root / "second.md"
            first.write_text("第一份资料介绍检索。", encoding="utf-8")
            second.write_text("第二份资料介绍时间戳证据。", encoding="utf-8")
            output = ingest_many([first, second], root / "collection")
            hits = search(output, "时间戳证据", mode="vector")
            self.assertTrue(hits)
            self.assertEqual(hits[0]["source"], "second.md")
            self.assertIn("002-second", hits[0]["collection"])

    def test_inspect_reports_modalities_and_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.md"
            source.write_text("只有文字证据。", encoding="utf-8")
            output = ingest(source, root / "run")
            report = inspect_knowledge(output)
            self.assertEqual(report["chunk_count"], 1)
            self.assertEqual(report["modalities"], {"text": 1})
            self.assertEqual(report["warnings"], [])

    def test_doctor_reports_capability_checks_without_secrets(self):
        report = doctor()
        self.assertTrue(report["ready"])
        self.assertIn("retrieval", report["checks"])
        self.assertIn("vision_api_key", report["checks"])
        self.assertNotIn("key", report["checks"]["vision_api_key"])

    def test_report_contains_source_location_and_warning_section(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.md"
            source.write_text("报告内容必须保留来源定位。", encoding="utf-8")
            output = ingest(source, root / "run")
            report = build_report(output)
            self.assertEqual(report["key_point_count"], 1)
            self.assertIn("demo.md", report["markdown"])
            self.assertIn("document", report["markdown"])
            self.assertIn("处理警告", report["markdown"])

    def test_markdown_sections_preserve_heading_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "guide.md"
            source.write_text("# 安装\n安装步骤。\n\n## 验证\n验证步骤。", encoding="utf-8")
            output = ingest(source, root / "run")
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            locations = {chunk["location"] for chunk in chunks}
            self.assertIn("section:安装", locations)
            self.assertIn("section:验证", locations)

    def test_docx_sections_preserve_heading_locations_when_dependency_is_available(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "guide.docx"
            document = Document()
            document.add_heading("安装", level=1)
            document.add_paragraph("安装步骤。")
            document.add_heading("验证", level=1)
            document.add_paragraph("验证步骤。")
            document.save(source)
            output = ingest(source, root / "run")
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            locations = {chunk["location"] for chunk in chunks}
            self.assertIn("section:安装", locations)
            self.assertIn("section:验证", locations)

    def test_pptx_slides_preserve_slide_locations_when_dependency_is_available(self):
        try:
            from pptx import Presentation
        except ImportError:
            self.skipTest("python-pptx not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "guide.pptx"
            presentation = Presentation()
            first = presentation.slides.add_slide(presentation.slide_layouts[6])
            first.shapes.add_textbox(0, 0, 100, 100).text = "安装步骤"
            second = presentation.slides.add_slide(presentation.slide_layouts[6])
            second.shapes.add_textbox(0, 0, 100, 100).text = "验证步骤"
            presentation.save(source)
            output = ingest(source, root / "run")
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            locations = {chunk["location"] for chunk in chunks}
            self.assertIn("slide:1", locations)
            self.assertIn("slide:2", locations)

    def test_csv_rows_preserve_row_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "guide.csv"
            source.write_text("topic,detail\n安装,安装步骤\n验证,验证步骤\n", encoding="utf-8")
            output = ingest(source, root / "run")
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            locations = {chunk["location"] for chunk in chunks}
            self.assertIn("row:2", locations)
            self.assertIn("row:3", locations)
            self.assertTrue(any("安装步骤" in chunk["text"] for chunk in chunks))

    def test_xlsx_rows_preserve_sheet_and_row_locations_when_dependency_is_available(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "guide.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "教程"
            sheet.append(["topic", "detail"])
            sheet.append(["安装", "安装步骤"])
            workbook.save(source)
            output = ingest(source, root / "run")
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            locations = {chunk["location"] for chunk in chunks}
            self.assertIn("sheet:教程/row:2", locations)

    def test_json_nested_values_preserve_json_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "guide.json"
            source.write_text(json.dumps({"course": {"title": "检索课程", "steps": ["安装", "验证"]}}, ensure_ascii=False), encoding="utf-8")
            output = ingest(source, root / "run")
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            locations = {chunk["location"] for chunk in chunks}
            self.assertIn("json:course.title", locations)
            self.assertIn("json:course.steps[0]", locations)
            self.assertTrue(any("检索课程" in chunk["text"] for chunk in chunks))

    def test_vector_search_returns_semantic_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.md"
            source.write_text("RAG 通过检索外部知识降低大模型幻觉。", encoding="utf-8")
            output = ingest(source, root / "run")
            self.assertEqual(build_vector_index(output)["status"], "ready")
            hits = vector_search(output, "如何减少模型胡编", limit=3)
            self.assertTrue(hits)
            self.assertEqual(hits[0]["retrieval"], "vector")

    def test_hybrid_search_combines_vector_and_keyword_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.md"
            source.write_text("RAG 通过检索外部知识降低大模型幻觉。", encoding="utf-8")
            output = ingest(source, root / "run")
            hits = search(output, "如何降低幻觉", mode="hybrid")
            self.assertTrue(hits)
            self.assertEqual(hits[0]["retrieval"], "hybrid")

    def test_vision_unavailable_is_explicit(self):
        sample = Path(r"D:\wedding-invitation-h5\video2knowledge-skill\runs\video-keyframes-final\frames")
        if not sample.exists():
            self.skipTest("keyframe sample not present")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "descriptions.json"
            result = describe_keyframes(sample, output, api_key="")
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["described_count"], 0)
            self.assertTrue(output.exists())

    def test_transcription_adapter_preserves_timestamps(self):
        class FakeSegment:
            def __init__(self, start, end, text):
                self.start = start
                self.end = end
                self.text = text

        class FakeModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, *args, **kwargs):
                return iter([FakeSegment(1.2, 3.4, " 第一段 ")]), None

        class FakeContainer:
            streams = types.SimpleNamespace(audio=[object()])

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        fake_module = types.SimpleNamespace(WhisperModel=FakeModel)
        fake_av = types.SimpleNamespace(open=lambda *args, **kwargs: FakeContainer())
        original_whisper = sys.modules.get("faster_whisper")
        original_av = sys.modules.get("av")
        sys.modules["faster_whisper"] = fake_module
        sys.modules["av"] = fake_av
        try:
            sources = transcribe_video(Path("demo.mp4"), model_size="tiny", language="zh")
        finally:
            if original_whisper is None:
                sys.modules.pop("faster_whisper", None)
            else:
                sys.modules["faster_whisper"] = original_whisper
            if original_av is None:
                sys.modules.pop("av", None)
            else:
                sys.modules["av"] = original_av
        self.assertEqual(sources[0].location, "1.20-3.40s")
        self.assertEqual(sources[0].text, "第一段")

    def test_transcription_unavailable_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "demo.mp4"
            source.write_bytes(b"not-a-real-video")
            output = ingest(source, root / "run", transcribe=True)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn(manifest["metadata"]["status"], {"transcription_unavailable", "transcription_failed", "no_audio_track"})

    def test_video_uses_matching_sidecar_subtitle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "lesson.mp4"
            video.write_bytes(b"not-a-real-video")
            (root / "lesson.srt").write_text(
                "1\n00:00:01,000 --> 00:00:03,000\n旁车字幕提供证据。\n",
                encoding="utf-8",
            )
            output = ingest(video, root / "run")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["metadata"]["status"], "subtitle_sidecar")
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(chunks[0]["source"], "lesson.srt")
            self.assertEqual(chunks[0]["modality"], "audio")


if __name__ == "__main__":
    unittest.main()
