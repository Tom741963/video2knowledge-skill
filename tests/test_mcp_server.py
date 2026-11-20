import asyncio
import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP optional dependency is not installed")
class MCPServerTests(unittest.TestCase):
    def test_registers_expected_tools(self):
        from video2knowledge.mcp_server import create_server

        tools = asyncio.run(create_server().list_tools())
        names = {tool.name for tool in tools}
        self.assertEqual(
            names,
            {
                "ingest_file",
                "ingest_files",
                "ask_knowledge",
                "inspect_knowledge_pack",
                "diagnose_environment",
                "generate_report",
                "answer_with_evidence",
                "evaluate_knowledge",
                "describe_frames",
            },
        )
