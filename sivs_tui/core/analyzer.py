"""
SIVS-TUI - Media analysis and metadata extraction using ffprobe.
"""
import json
import subprocess
from pathlib import Path
from typing import List, Optional
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
    
    def detect(self, path: Path, noise_db: float = -30, min_duration: float = 0.5) -> List[tuple]:
        """Detect silence segments, returns list of (start, end) in seconds."""
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


async def analyze_media_file(path: Path) -> MediaFile:
    """Convenience function for async analysis."""
    import asyncio
    loop = asyncio.get_event_loop()
    analyzer = MediaAnalyzer()
    return await loop.run_in_executor(None, analyzer.analyze, path)