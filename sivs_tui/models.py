"""
SIVS-TUI - Core data models for projects, media, and edit plans.
"""
from __future__ import annotations
import json
import hashlib
import xxhash
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
import humanize


class MediaType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    UNKNOWN = "unknown"


class OperationType(str, Enum):
    KEEP_RANGE = "keep_range"
    REMOVE_RANGE = "remove_range"
    SLOW_MOTION = "slow_motion"
    CONCAT = "concat"


class ExportTarget(str, Enum):
    FCP = "fcp"
    DAVINCI = "davinci"
    AFTER_EFFECTS = "after_effects"
    DAW_AUDIO = "daw_audio"
    UNIVERSAL = "universal"


class ExportMode(str, Enum):
    TIMELINE = "timeline"
    RENDER = "render"


class QCStage(str, Enum):
    PREVIEW = "preview"
    FINAL = "final"


@dataclass
class AudioTrack:
    index: int
    codec: str
    channels: int
    sample_rate: int
    language: Optional[str] = None
    bitrate: Optional[int] = None


@dataclass
class MediaFile:
    """Metadata for a single media file."""
    id: str
    path: Path
    name: str
    type: MediaType
    size: int
    duration: float
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    bitrate: Optional[int] = None
    audio_tracks: List[AudioTrack] = field(default_factory=list)
    file_hash: Optional[str] = None  # xxhash for quick identification
    
    @property
    def formatted_duration(self) -> str:
        return humanize.precisedelta(self.duration, format="%0.3f")
    
    @property
    def formatted_size(self) -> str:
        return humanize.naturalsize(self.size)
    
    @property
    def resolution_str(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "unknown"


class EditOperation(BaseModel):
    """Single edit operation in the plan."""
    action: OperationType
    file: str  # filename (not path)
    start: float  # seconds
    end: float  # seconds
    speed: Optional[float] = None  # for slow_motion
    description: Optional[str] = None
    
    @property
    def duration(self) -> float:
        return self.end - self.start
    
    @model_validator(mode="after")
    def validate_times(self):
        if self.start >= self.end:
            raise ValueError(f"start ({self.start}) must be < end ({self.end})")
        if self.action == OperationType.SLOW_MOTION and not self.speed:
            raise ValueError("slow_motion requires speed parameter")
        return self


class EditPlan(BaseModel):
    """Complete edit plan for a project."""
    project: str
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    source_files: List[str] = Field(default_factory=list)  # filenames
    output: Dict[str, Any] = Field(default_factory=lambda: {
        "container": "mp4",
        "video_codec": "libx264",
        "audio_codec": "aac",
        "crf": 20,
        "preset": "medium",
        "resolution": "1920x1080",
        "framerate": 30,
    })
    operations: List[EditOperation] = Field(default_factory=list)
    approval_required: bool = True
    post_processing: Dict[str, Any] = Field(default_factory=lambda: {
        "face_blur": {"enabled": False, "note": ""},
        "upscale": {"enabled": False, "note": ""},
    })
    
    def get_total_duration(self) -> float:
        """Calculate expected output duration from operations."""
        total = 0.0
        for op in self.operations:
            if op.action in (OperationType.KEEP_RANGE, OperationType.REMOVE_RANGE):
                total += op.duration
            elif op.action == OperationType.SLOW_MOTION:
                total += op.duration / op.speed if op.speed else op.duration
        return total
    
    def get_operations_for_file(self, filename: str) -> List[EditOperation]:
        return [op for op in self.operations if op.file == filename]


class QCReport(BaseModel):
    """Quality control report for a rendered file."""
    id: str
    stage: QCStage
    created_at: datetime = Field(default_factory=datetime.now)
    file_path: Path
    checks: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    passed: bool = False
    target_nle: Optional[str] = None


class ProjectState(BaseModel):
    """Runtime state for a project being edited."""
    input_file: Path
    media_info: MediaFile
    manifest_dir: Path  # .sivs/ or cache dir
    edit_plan: EditPlan
    edit_number: int = 1
    history: List[EditPlan] = Field(default_factory=list)  # for undo/redo
    current_history_index: int = -1
    
    class Config:
        arbitrary_types_allowed = True


def compute_file_hash(path: Path, algorithm: str = "xxh64") -> str:
    """Compute hash of a file for identification."""
    if algorithm == "xxh64":
        h = xxhash.xxh64()
    else:
        h = hashlib.new(algorithm)
    
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_media_type(path: Path) -> MediaType:
    """Determine media type from file extension."""
    ext = path.suffix.lower()
    video_exts = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mxf", ".mpg", ".mpeg"}
    audio_exts = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma", ".aiff"}
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic"}
    
    if ext in video_exts:
        return MediaType.VIDEO
    elif ext in audio_exts:
        return MediaType.AUDIO
    elif ext in image_exts:
        return MediaType.IMAGE
    return MediaType.UNKNOWN


def find_existing_edits(folder: Path, base_name: str) -> int:
    """Find the highest edit number for a given base filename."""
    pattern = f"edit_*_{base_name}"
    existing = list(folder.glob(pattern))
    max_num = 0
    for f in existing:
        try:
            # extract number from edit_XX_name
            parts = f.stem.split("_")
            if len(parts) >= 2 and parts[0] == "edit":
                num = int(parts[1])
                max_num = max(max_num, num)
        except (ValueError, IndexError):
            continue
    return max_num


def next_edit_filename(folder: Path, base_name: str, extension: str = ".mp4") -> Path:
    """Generate next edit filename with auto-increment."""
    next_num = find_existing_edits(folder, base_name) + 1
    stem = Path(base_name).stem
    return folder / f"edit_{next_num:02d}_{stem}{extension}"