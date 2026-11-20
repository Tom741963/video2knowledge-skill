from __future__ import annotations

import importlib.util
import os
import shutil
from typing import Any


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def doctor() -> dict[str, Any]:
    """Report local dependencies and configured optional capabilities without exposing secrets."""
    checks = {
        "ffmpeg": {"available": shutil.which("ffmpeg") is not None},
        "ffprobe": {"available": shutil.which("ffprobe") is not None},
        "documents": {
            "available": _module_available("pypdf") and _module_available("docx") and _module_available("pptx") and _module_available("openpyxl"),
            "dependencies": {
                "pypdf": _module_available("pypdf"),
                "docx": _module_available("docx"),
                "pptx": _module_available("pptx"),
                "openpyxl": _module_available("openpyxl"),
            },
        },
        "video": {
            "available": _module_available("faster_whisper") and _module_available("av"),
            "dependencies": {"faster_whisper": _module_available("faster_whisper"), "av": _module_available("av")},
        },
        "retrieval": {
            "available": _module_available("sklearn") and _module_available("joblib"),
            "dependencies": {"sklearn": _module_available("sklearn"), "joblib": _module_available("joblib")},
        },
        "mcp": {"available": _module_available("mcp")},
        "vision_api_key": {"configured": bool(os.getenv("VISION_API_KEY"))},
        "qa_api_key": {"configured": bool(os.getenv("QA_API_KEY") or os.getenv("OPENAI_API_KEY"))},
    }
    capabilities = [name for name, result in checks.items() if result.get("available") or result.get("configured")]
    return {
        "ready": True,
        "checks": checks,
        "capabilities": capabilities,
        "hint": "缺少可选能力时，请按 README 安装对应 extra；API Key 只报告是否配置，不会返回密钥内容。",
    }
