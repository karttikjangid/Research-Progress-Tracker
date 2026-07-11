"""faster-whisper transcription (small/int8, CPU fallback) + ffprobe duration
+ deterministic transcript stats computed BEFORE any LLM sees the text."""
import re
import subprocess

_model = None  # set only after a config has produced a successful transcription
last_gaps: list[float] = []  # inter-segment silences of the most recent real run

FILLERS = ("um", "uh", "like", "basically", "you know", "actually")


def compute_stats(text: str, duration_sec: float) -> dict:
    """Hard numbers the LLM audit must argue from. longest_silence_sec is None
    when no segment timing is available (e.g. mocked transcription)."""
    words = re.findall(r"[a-zA-Z']+", text.lower())
    minutes = max(duration_sec, 1) / 60
    low = text.lower()
    fillers = sum(len(re.findall(rf"\b{re.escape(f)}\b", low)) for f in FILLERS)
    return {
        "wpm": round(len(words) / minutes, 1),
        "fillers_per_min": round(fillers / minutes, 2),
        "unique_ratio": round(len(set(words)) / max(len(words), 1), 3),
        "longest_silence_sec": round(max(last_gaps), 1) if last_gaps else None,
    }

# (model_size, device) in preference order per PROJECT_CONTEXT: small on the
# GTX 1650, base if VRAM errors, CPU as last resort. All int8. CUDA failures
# surface lazily at transcription time (e.g. missing libcublas), so a config
# counts as working only after it has actually transcribed something.
_ATTEMPTS = [("small", "cuda"), ("base", "cuda"), ("small", "cpu")]


def _ffprobe(args: list[str], path: str) -> str:
    out = subprocess.run(["ffprobe", "-v", "error", *args, path],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise ValueError(f"ffprobe failed: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


def probe_duration(path: str) -> float:
    """Server-side truth for recording length — the client is never trusted.
    MediaRecorder webm often lacks a duration header, so when the container
    reports nothing we take the last audio packet's pts from a full scan."""
    try:
        d = float(_ffprobe(["-show_entries", "format=duration",
                            "-of", "csv=p=0"], path))
        if d > 0:
            return d
    except ValueError:
        pass
    packets = _ffprobe(["-select_streams", "a:0", "-show_entries",
                        "packet=pts_time,duration_time", "-of", "csv=p=0"], path)
    lines = [ln for ln in packets.splitlines() if ln.strip(",")]
    if not lines:
        raise ValueError("no decodable audio packets")
    fields = lines[-1].split(",")
    pts = float(fields[0])
    dur = float(fields[1]) if len(fields) > 1 and fields[1] not in ("", "N/A") else 0.0
    return pts + dur


def _run(model, path: str) -> str:
    global last_gaps
    segments, _info = model.transcribe(path, language="en", vad_filter=True)
    texts, gaps, prev_end = [], [], None
    for s in segments:
        if prev_end is not None:
            gaps.append(max(0.0, s.start - prev_end))
        prev_end = s.end
        texts.append(s.text.strip())
    last_gaps = gaps
    return " ".join(texts).strip()


def transcribe(path: str) -> str:
    global _model
    if _model is not None:
        return _run(_model, path)
    from faster_whisper import WhisperModel
    last = None
    attempts = list(_ATTEMPTS)
    while attempts:
        size, device = attempts.pop(0)
        try:
            model = WhisperModel(size, device=device, compute_type="int8")
            text = _run(model, path)
            _model = model
            return text
        except Exception as e:
            last = e
            # base-on-cuda only exists for the VRAM case; a missing-library
            # failure means every cuda config is dead — go straight to CPU.
            if device == "cuda" and "memory" not in str(e).lower():
                attempts = [a for a in attempts if a[1] != "cuda"]
    raise RuntimeError(f"transcription failed with every model config: {last}")
