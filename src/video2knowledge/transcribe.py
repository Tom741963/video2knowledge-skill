from __future__ import annotations

from pathlib import Path

from .pipeline import Source


class TranscriptionUnavailable(RuntimeError):
    """Raised when local transcription cannot run for the current input."""


def _ensure_audio_track(path: Path) -> None:
    try:
        import av
        with av.open(str(path), mode="r") as container:
            if not container.streams.audio:
                raise TranscriptionUnavailable("视频没有音频轨，无法进行语音转录。")
    except TranscriptionUnavailable:
        raise
    except Exception as exc:
        raise TranscriptionUnavailable(f"无法读取视频音频轨：{exc}") from exc


def transcribe_video(
    path: Path,
    model_size: str = "small",
    language: str | None = None,
    device: str = "auto",
    compute_type: str = "int8",
) -> list[Source]:
    """Transcribe a video with the optional faster-whisper backend."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionUnavailable(
            '本地视频转录需要安装可选依赖：pip install -e ".[video]"；首次运行还会下载 Whisper 模型。'
        ) from exc

    _ensure_audio_track(path)
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(
        str(path),
        language=language or None,
        vad_filter=True,
        beam_size=5,
    )
    return [
        Source(path.name, f"{segment.start:.2f}-{segment.end:.2f}s", segment.text.strip(), modality="audio", start_seconds=segment.start, end_seconds=segment.end)
        for segment in segments
        if segment.text.strip()
    ]
