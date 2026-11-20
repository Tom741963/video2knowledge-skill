from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class VisionUnavailable(RuntimeError):
    """Raised when no vision provider is configured."""


def _data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def describe_image(
    image_path: Path,
    prompt: str = "请用中文描述这张图片中与知识理解有关的主要内容，区分可见事实和不确定推断。",
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: int = 60,
    opener=urllib.request.urlopen,
) -> str:
    """Describe an image through an OpenAI-compatible chat completions endpoint."""
    api_key = api_key or os.getenv("VISION_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise VisionUnavailable("未配置视觉模型 API Key，请设置 VISION_API_KEY。")
    base_url = (base_url or os.getenv("VISION_API_BASE") or "https://api.openai.com/v1").rstrip("/")
    model = model or os.getenv("VISION_MODEL") or "gpt-4o-mini"
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 500,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
            ],
        }],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise VisionUnavailable(f"视觉模型请求失败：{exc}") from exc
    try:
        return result["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionUnavailable("视觉模型返回格式无法解析。") from exc


def describe_keyframes(
    frames_dir: str | Path,
    output_path: str | Path,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict:
    frames_dir = Path(frames_dir)
    output_path = Path(output_path)
    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    records = []
    for index, frame in enumerate(frame_files):
        record = {"index": index, "file": frame.name}
        try:
            record["description"] = describe_image(
                frame, api_key=api_key, base_url=base_url, model=model
            )
            record["status"] = "described"
        except VisionUnavailable as exc:
            record["status"] = "unavailable"
            record["error"] = str(exc)
        records.append(record)
    described = sum(1 for record in records if record["status"] == "described")
    result = {
        "status": "described" if described else ("unavailable" if records else "no_frames"),
        "model": model or os.getenv("VISION_MODEL") or "gpt-4o-mini",
        "count": len(records),
        "described_count": described,
        "frames": records,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
