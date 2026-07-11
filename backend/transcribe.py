"""Transcription (NVIDIA Riva hosted whisper-large-v3) + ffprobe duration
+ deterministic transcript stats computed BEFORE any LLM sees the text.

NOTE: transcription was switched from local faster-whisper to the hosted
NVIDIA Riva NVCF API as a workaround. The old faster-whisper code is left
commented out below (search for "DISABLED") so it can be restored verbatim.
The public interface is unchanged: transcribe(path) -> str, and the module
global last_gaps is still populated for compute_stats()."""
import os
import re
import subprocess

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

# DISABLED — switched to NVIDIA Riva hosted API, see below — revert by uncommenting
# (model_size, device) in preference order per PROJECT_CONTEXT: small on the
# GTX 1650, base if VRAM errors, CPU as last resort. All int8. CUDA failures
# surface lazily at transcription time (e.g. missing libcublas), so a config
# counts as working only after it has actually transcribed something.
# _ATTEMPTS = [("small", "cuda"), ("base", "cuda"), ("small", "cpu")]


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


def detect_silences(path: str, noise_db: float = -30.0,
                    min_silence_sec: float = 0.5) -> list[float]:
    """Whisper-independent pause detection, feeding last_gaps -> longest_silence_sec.
    The old faster-whisper path derived silences from segment timings; the hosted
    Riva ASR returns no word/segment times, so measure silence straight off the
    audio with ffmpeg's energy-based silencedetect filter (no new audio library —
    same ffmpeg used for probing/conversion). Returns the duration of every silent
    stretch >= min_silence_sec; compute_stats() takes the max. Empty -> None."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_sec}",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    # silencedetect logs one "silence_duration: <seconds>" line per gap to stderr
    return [float(m) for m in
            re.findall(r"silence_duration:\s*([0-9.]+)", out.stderr)]


# DISABLED — switched to NVIDIA Riva hosted API, see below — revert by uncommenting
# def _run(model, path: str) -> str:
#     global last_gaps
#     segments, _info = model.transcribe(path, language="en", vad_filter=True)
#     texts, gaps, prev_end = [], [], None
#     for s in segments:
#         if prev_end is not None:
#             gaps.append(max(0.0, s.start - prev_end))
#         prev_end = s.end
#         texts.append(s.text.strip())
#     last_gaps = gaps
#     return " ".join(texts).strip()
#
#
# def transcribe(path: str) -> str:
#     global _model
#     if _model is not None:
#         return _run(_model, path)
#     from faster_whisper import WhisperModel
#     last = None
#     attempts = list(_ATTEMPTS)
#     while attempts:
#         size, device = attempts.pop(0)
#         try:
#             model = WhisperModel(size, device=device, compute_type="int8")
#             text = _run(model, path)
#             _model = model
#             return text
#         except Exception as e:
#             last = e
#             # base-on-cuda only exists for the VRAM case; a missing-library
#             # failure means every cuda config is dead — go straight to CPU.
#             if device == "cuda" and "memory" not in str(e).lower():
#                 attempts = [a for a in attempts if a[1] != "cuda"]
#     raise RuntimeError(f"transcription failed with every model config: {last}")


# ---------- NVIDIA Riva hosted ASR (whisper-large-v3) ----------
# Drop-in replacement for the faster-whisper transcribe() above. Adapted from
# nvidia-riva/python-clients scripts/asr/transcribe_file_offline.py. The NVCF
# endpoint is reached over SSL gRPC with the function-id + bearer-token metadata
# headers; NVIDIA_API_KEY is read from the environment (already set).
_RIVA_URI = "grpc.nvcf.nvidia.com:443"
_RIVA_FUNCTION_ID = "b702f636-f60c-4a3d-a6f4-f3568c13bd7d"
_RIVA_SAMPLE_RATE = 16000  # mono 16-bit PCM we transcode to below
_riva_asr = None  # cached ASRService after the first successful connect


def _to_riva_wav(path: str) -> str:
    """Riva requires mono 16-bit audio (WAV/OPUS/FLAC); MediaRecorder gives us
    webm/opus. Transcode to mono 16-bit PCM WAV with the ffmpeg already used for
    probing. Returns a temp path the caller must delete."""
    import tempfile
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    out = subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", str(_RIVA_SAMPLE_RATE),
         "-sample_fmt", "s16", "-f", "wav", wav],
        capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg wav conversion failed: {out.stderr.strip()[:200]}")
    return wav


def _riva_service():
    global _riva_asr
    if _riva_asr is not None:
        return _riva_asr
    import riva.client
    key = os.environ["NVIDIA_API_KEY"]
    auth = riva.client.Auth(
        uri=_RIVA_URI, use_ssl=True,
        metadata_args=[["function-id", _RIVA_FUNCTION_ID],
                       ["authorization", f"Bearer {key}"]])
    _riva_asr = riva.client.ASRService(auth)
    return _riva_asr


def transcribe(path: str) -> str:
    global last_gaps
    import riva.client
    wav = _to_riva_wav(path)
    try:
        with open(wav, "rb") as fh:
            data = fh.read()
        config = riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=_RIVA_SAMPLE_RATE,
            audio_channel_count=1,
            language_code="en",
            max_alternatives=1,
            enable_automatic_punctuation=True,
        )
        response = _riva_service().offline_recognize(data, config)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
    # Riva walks the file sequentially and returns one result per ~30s window;
    # concatenate them in order (same shape the old _run produced). The hosted
    # endpoint returns no word timings, so silences come from detect_silences()
    # run on the original audio rather than from segment gaps.
    texts = [res.alternatives[0].transcript.strip()
             for res in response.results if res.alternatives]
    last_gaps = detect_silences(path)
    return " ".join(t for t in texts if t).strip()
