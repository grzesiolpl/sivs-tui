"""SIVS-TUI - Super Intelligence Video Studio (Terminal UI)"""
from .config import settings
from .models import (
    MediaFile, EditPlan, EditOperation, OperationType,
    ExportTarget, ExportMode, QCStage, MediaType,
    ProjectState, AudioTrack, QCReport,
    next_edit_filename, find_existing_edits
)
from .core.analyzer import MediaAnalyzer, SilenceDetector
from .preview import PreviewManager, ASCIITimelineRenderer, FFplayPreview, QuickLookPreview
from .exporters import ExportManager, open_in_finder, open_with_default_app
from .utils.ai_brief import generate_edit_plan, refine_edit_plan, validate_plan_against_media

__version__ = "1.0.0"
__all__ = [
    "settings",
    "MediaFile", "EditPlan", "EditOperation", "OperationType",
    "ExportTarget", "ExportMode", "QCStage", "MediaType",
    "ProjectState", "AudioTrack", "QCReport",
    "next_edit_filename", "find_existing_edits",
    "MediaAnalyzer", "SilenceDetector",
    "PreviewManager", "ASCIITimelineRenderer",
    "FFplayPreview", "QuickLookPreview",
    "ExportManager", "open_in_finder", "open_with_default_app",
    "generate_edit_plan", "refine_edit_plan", "validate_plan_against_media",
]