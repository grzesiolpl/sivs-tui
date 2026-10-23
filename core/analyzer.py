#!/usr/bin/env python3
"""
SIVS-TUI - Media analysis and metadata extraction using ffprobe.
Enhanced with silence detection, speech segments, and Whisper transcription.
"""
import json
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import asdict

from sivs_tui.models import MediaFile, AudioTrack, MediaType, get_media_type
from sivs_tui.config import settings


class MediaAnalyzer:
    """Analyze media files using ffprobe."""

    def __init__(self, ffprobe_path: str = None):
        self.ffprobe_path = ffprobe_path or settings.ffprobe_path

    def analyze(self, path: Path) -> MediaFile:
        """Run ffprobe and extract metadata."""
        if not path.exists():
            raise FileNotFoundError(f"Media file not found: {path}")

        # Run ffprobe
        cmd = [
            self.ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)

        # Parse format info
        fmt = data.get("format", {})
        duration = float(fmt.get("duration", 0))
        size = int(fmt.get("size", 0))
        bitrate = int(fmt.get("bit_rate", 0)) if fmt.get("bit_rate") else None

        # Parse streams
        video_stream = None
        audio_streams = []

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and video_stream is None:
                video_stream = stream
            elif stream.get("codec_type") == "audio":
                audio_streams.append(stream)

        # Build MediaFile
        media_type = get_media_type(path)

        audio_tracks = []
        for i, a_stream in enumerate(audio_streams):
            audio_tracks.append(AudioTrack(
                index=a_stream.get("index", i),
                codec=a_stream.get("codec_name", "unknown"),
                channels=a_stream.get("channels", 0),
                sample_rate=int(a_stream.get("sample_rate", 0)),
                language=a_stream.get("tags", {}).get("language"),
                bitrate=int(a_stream.get("bit_rate", 0)) if a_stream.get("bit_rate") else None,
            ))

        return MediaFile(
            id=path.stem,
            path=path,
            name=path.name,
            type=MediaType.VIDEO if video_stream else MediaType.AUDIO if audio_streams else MediaType.UNKNOWN,
            size=int(fmt.get("size", 0)),
            duration=duration,
            width=video_stream.get("width") if video_stream else None,
            height=video_stream.get("height") if video_stream else None,
            fps=self._parse_framerate(video_stream.get("r_frame_rate")) if video_stream else None,
            video_codec=video_stream.get("codec_name") if video_stream else None,
            audio_codec=audio_streams[0].get("codec_name") if audio_streams else None,
            bitrate=bitrate,
            audio_tracks=audio_tracks,
        )

    def _parse_framerate(self, rate_str: str) -> Optional[float]:
        """Parse framerate string like '30000/1001' to float."""
        if not rate_str:
            return None
        try:
            if "/" in rate_str:
                num, den = rate_str.split("/")
                return float(num) / float(den)
            return float(rate_str)
        except (ValueError, ZeroDivisionError):
            return None

    def analyze_batch(self, paths: List[Path]) -> List[MediaFile]:
        """Analyze multiple files."""
        results = []
        for path in paths:
            try:
                results.append(self.analyze(path))
            except Exception as e:
                print(f"[WARN] Failed to analyze {path}: {e}")
        return results


class SilenceDetector:
    """Detect silence segments in audio using ffmpeg."""

    def __init__(self, ffmpeg_path: str = None):
        self.ffmpeg_path = ffmpeg_path or settings.ffmpeg_path

    def detect(self, path: Path, noise_db: float = -35, min_duration: float = 0.35) -> List[tuple]:
        """Detect silence segments, returns list of (start, end) in seconds.
        
        Uses stricter defaults: -35dB noise floor, 0.35s minimum duration
        to catch natural pauses between sentences/words.
        """
        cmd = [
            self.ffmpeg_path,
            "-i", str(path),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
            "-f", "null", "-"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        # Parse stderr for silence detection
        silences = []
        for line in result.stderr.split("\n"):
            if "silence_start" in line:
                parts = line.split()
                start = float(parts[parts.index("silence_start") + 1])
                silences.append([start, None])
            elif "silence_end" in line:
                parts = line.split()
                end = float(parts[parts.index("silence_end") + 1])
                if silences and silences[-1][1] is None:
                    silences[-1][1] = end

        return [(s[0], s[1]) for s in silences if s[1] is not None]

    def get_speech_segments(self, path: Path, noise_db: float = -35, min_duration: float = 0.35) -> List[tuple]:
        """Get speech segments (inverse of silence) with padding.
        
        Returns list of (start, end) where speech occurs.
        Adds 0.15s padding before first word, 0.20s after last word.
        """
        silences = self.detect(path, noise_db, min_duration)
        if not silences:
            return [(0, self._get_duration(path))]

        duration = self._get_duration(path)
        speech_segments = []
        
        # Start from beginning to first silence
        first_silence_start = silences[0][0]
        if first_silence_start > 0:
            speech_segments.append((0, first_silence_start))
        
        # Between silences
        for i in range(len(silences) - 1):
            speech_start = silences[i][1]
            speech_end = silences[i + 1][0]
            if speech_end > speech_start:
                speech_segments.append((speech_start, speech_end))
        
        # After last silence to end
        last_silence_end = silences[-1][1]
        if last_silence_end < duration:
            speech_segments.append((last_silence_end, duration))
        
        # Apply padding: +0.15s before, +0.20s after (but don't overlap)
        padded = []
        for i, (start, end) in enumerate(speech_segments):
            pad_start = max(0, start - 0.15)
            pad_end = min(duration, end + 0.20)
            
            # Don't overlap with previous/next
            if i > 0:
                pad_start = max(pad_start, padded[-1][1])
            if i < len(speech_segments) - 1:
                next_start = speech_segments[i + 1][0]
                pad_end = min(pad_end, next_start - 0.15)
            
            if pad_end > pad_start:
                padded.append((pad_start, pad_end))
        
        return padded

    def _get_duration(self, path: Path) -> float:
        """Get media duration using ffprobe."""
        cmd = [
            self.ffprobe_path, "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except (ValueError, IndexError):
            return 0.0


class WhisperTranscriber:
    """Transcribe audio using whisper-cpp (local, fast)."""

    def __init__(self, whisper_path: str = None, model_path: str = None):
        self.whisper_path = whisper_path or "whisper-cli"
        # Default to base model for speed/accuracy balance
        self.model_path = model_path or "/opt/homebrew/share/whisper-cpp/ggml-base.bin"
        
    def is_available(self) -> bool:
        """Check if whisper-cli is available."""
        try:
            subprocess.run([self.whisper_path, "-h"], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def transcribe(self, path: Path, language: str = "pl") -> Optional[Dict[str, Any]]:
        """Transcribe audio file, returns dict with segments and full text."""
        if not self.is_available():
            return None
        
        # Check model exists
        if not Path(self.model_path).exists():
            # Try to find model
            possible_models = [
                "/opt/homebrew/share/whisper-cpp/ggml-base.bin",
                "/usr/local/share/whisper-cpp/ggml-base.bin",
                str(Path.home() / ".cache/whisper-cpp/ggml-base.bin"),
            ]
            for m in possible_models:
                if Path(m).exists():
                    self.model_path = m
                    break
            else:
                return None
        
        cmd = [
            self.whisper_path,
            "-m", self.model_path,
            "-l", language,
            "-oj",  # JSON output
            "-f", str(path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                return None
            
            # Parse JSON output
            # whisper-cli outputs JSON to stdout when -oj is used
            data = json.loads(result.stdout)
            return data
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return None

    def get_sentence_segments(self, path: Path, language: str = "pl") -> List[Dict[str, Any]]:
        """Extract sentence-level segments with precise timestamps.
        
        Returns list of dicts: {"start": float, "end": float, "text": str}
        """
        data = self.transcribe(path, language)
        if not data:
            return []
        
        segments = []
        for seg in data.get("segments", []):
            # whisper-cpp segments have start/end in seconds
            segments.append({
                "start": float(seg.get("start", 0)),
                "end": float(seg.get("end", 0)),
                "text": seg.get("text", "").strip()
            })
        return segments


async def analyze_media_file(path: Path) -> MediaFile:
    """Convenience function for async analysis."""
    import asyncio
    loop = asyncio.get_event_loop()
    analyzer = MediaAnalyzer()
    return await loop.run_in_executor(None, analyzer.analyze, path)