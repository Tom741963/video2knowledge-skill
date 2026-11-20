from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def extract_keyframes(video_path: Path, output_dir: Path, interval_seconds: float = 5.0) -> dict:
    """Extract representative JPEG frames and return timestamp metadata."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds 必须大于 0")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "unavailable", "reason": "ffmpeg not found", "frames": []}

    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame_%04d.jpg"
    command = [
        ffmpeg, "-y", "-i", str(video_path),
        "-vf", f"fps=1/{interval_seconds:g}",
        "-q:v", "2", "-fps_mode", "vfr",
        str(pattern),
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except subprocess.CalledProcessError as exc:
        return {"status": "failed", "reason": exc.stderr[-1000:], "frames": []}

    files = sorted(output_dir.glob("frame_*.jpg"))
    records = []
    for index, path in enumerate(files):
        records.append({
            "index": index,
            "timestamp_seconds": round(index * interval_seconds, 3),
            "path": str(path.name),
        })
    return {
        "status": "extracted",
        "interval_seconds": interval_seconds,
        "count": len(records),
        "frames": records,
    }


def write_keyframe_manifest(output_dir: Path, metadata: dict) -> None:
    (output_dir / "keyframes.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


