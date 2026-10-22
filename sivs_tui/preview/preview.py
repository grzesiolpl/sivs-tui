"""Preview modules - 3-level zero-render live preview system"""
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

from sivs_tui.models import EditPlan, EditOperation, OperationType, MediaFile
from sivs_tui.config import settings
from rich.console import Console
from rich.table import Table
from rich.text import Text


@dataclass
class TimelineSegment:
    """A single segment in the timeline visualization."""
    start: float
    end: float
    operation: OperationType
    filename: str
    description: Optional[str] = None
    speed: Optional[float] = None


class ASCIITimelineRenderer:
    """Level 1: Render ASCII timeline visualization using Rich."""
    
    def __init__(self, console: Console = None, max_width: int = 120):
        self.console = console or Console()
        self.max_width = max_width
    
    def render(self, plan: EditPlan, media_files: List[MediaFile]) -> None:
        """Render the complete timeline visualization."""
        segments = self._build_segments(plan, media_files)
        total_duration = sum(s.end - s.start for s in segments)
        
        # Header
        self._render_header(plan, total_duration)
        
        # Timeline bar
        self._render_timeline_bar(segments, total_duration)
        
        # Details table
        self._render_details_table(segments, media_files)
        
        # Transcript snippets
        self._render_transcript_snippets(segments)
    
    def _build_segments(self, plan: EditPlan, media_files: List[MediaFile]) -> List[TimelineSegment]:
        """Build timeline segments from edit plan."""
        segments = []
        media_map = {m.name: m for m in media_files}
        
        for op in plan.operations:
            media = media_map.get(op.file)
            if not media:
                continue
            
            segments.append(TimelineSegment(
                start=op.start,
                end=op.end,
                operation=op.action,
                filename=op.file,
                description=op.description,
                speed=op.speed,
            ))
        
        return sorted(segments, key=lambda s: s.start)
    
    def _render_header(self, plan: EditPlan, total_duration: float) -> None:
        """Render plan header info."""
        self.console.print()
        self.console.rule(f"[bold cyan]📋 Edit Plan: {plan.project}[/bold cyan]")
        
        info_text = Text()
        info_text.append(f"📁 Source files: ", style="dim")
        info_text.append(f"{len(plan.source_files)}", style="cyan")
        info_text.append(f"  |  ⏱️  Expected duration: ", style="dim")
        info_text.append(f"{total_duration:.2f}s", style="green")
        info_text.append(f"  |  📐 Output: ", style="dim")
        out = plan.output
        info_text.append(f"{out.get('resolution', '1920x1080')} @ {out.get('framerate', 30)}fps", style="yellow")
        
        self.console.print(info_text)
        self.console.print()
    
    def _render_timeline_bar(self, segments: List[TimelineSegment], total_duration: float) -> None:
        """Render visual timeline bar with colored blocks."""
        if total_duration <= 0:
            return
        
        # Color mapping for operations
        op_colors = {
            OperationType.KEEP_RANGE: ("green", "█", "KEEP"),
            OperationType.REMOVE_RANGE: ("red", "░", "CUT"),
            OperationType.SLOW_MOTION: ("yellow", "▓", "SLOW"),
            OperationType.CONCAT: ("blue", "▓", "JOIN"),
        }
        
        self.console.print("[bold]Timeline:[/bold]")
        
        # Build the timeline bar
        bar_parts = []
        for seg in segments:
            color, char, label = op_colors.get(seg.operation, ("white", "·", "???"))
            duration = seg.end - seg.start
            # Calculate width proportional to duration
            width = max(1, int((duration / total_duration) * (self.max_width - 10)))
            bar_parts.append(f"[{color}]{char * width}[/{color}]")
        
        bar = "".join(bar_parts)
        self.console.print(f"  {bar}")
        
        # Legend
        legend_parts = []
        for op_type, (color, char, label) in op_colors.items():
            if any(s.operation == op_type for s in segments):
                legend_parts.append(f"[{color}]{char}[/{color}] {label}")
        self.console.print(f"  {'  '.join(legend_parts)}")
        self.console.print()
    
    def _render_details_table(self, segments: List[TimelineSegment], media_files: List[MediaFile]) -> None:
        """Render detailed segment table."""
        media_map = {m.name: m for m in media_files}
        
        table = Table(title="Segment Details", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=3)
        table.add_column("Operation", style="bold", width=12)
        table.add_column("File", style="cyan", width=25)
        table.add_column("Timecode", style="yellow", width=20)
        table.add_column("Duration", style="green", width=10)
        table.add_column("Speed", style="magenta", width=8)
        table.add_column("Description", style="white")
        
        for i, seg in enumerate(segments, 1):
            media = media_map.get(seg.filename)
            tc_start = self._format_timecode(seg.start)
            tc_end = self._format_timecode(seg.end)
            duration = seg.end - seg.start
            
            op_display = {
                OperationType.KEEP_RANGE: "[green]KEEP[/green]",
                OperationType.REMOVE_RANGE: "[red]CUT[/red]",
                OperationType.SLOW_MOTION: f"[yellow]SLOW {seg.speed}×[/yellow]",
                OperationType.CONCAT: "[blue]JOIN[/blue]",
            }.get(seg.operation, seg.operation.value)
            
            table.add_row(
                str(i),
                op_display,
                seg.filename[:24] + "…" if len(seg.filename) > 24 else seg.filename,
                f"{tc_start} → {tc_end}",
                f"{duration:.2f}s",
                f"{seg.speed}×" if seg.speed else "1×",
                seg.description or "",
            )
        
        self.console.print(table)
        self.console.print()
    
    def _render_transcript_snippets(self, segments: List[TimelineSegment]) -> None:
        """Render transcript snippets if available (placeholder)."""
        # This would integrate with transcript data if available
        self.console.print("[dim]💡 Tip: Press [P] for live preview, [B] to refine brief, [R] to render[/dim]")
        self.console.print()
    
    def _format_timecode(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS.mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


@dataclass
class PreviewProcess:
    """Manages a preview subprocess."""
    process: subprocess.Popen
    temp_files: List[Path] = None
    
    def __post_init__(self):
        if self.temp_files is None:
            self.temp_files = []
    
    def terminate(self):
        """Clean up process and temp files."""
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        
        for f in self.temp_files:
            try:
                f.unlink(missing_ok=True)
            except:
                pass


class MPVEDLPreview:
    """Level 2: Zero-render preview using mpv with EDL."""
    
    def __init__(self, mpv_path: str = None):
        self.mvp_path = mpv_path or settings.mpv_path
        self.current_preview: Optional[PreviewProcess] = None
    
    def generate_edl(self, plan: EditPlan, media_files: List[MediaFile]) -> str:
        """Generate EDL content for mpv."""
        media_map = {m.name: m for m in media_files}
        edl_lines = ["# mpv EDL v0"]
        
        for op in plan.operations:
            if op.action not in (OperationType.KEEP_RANGE, OperationType.SLOW_MOTION):
                continue
            
            media = media_map.get(op.file)
            if not media or not media.path:
                continue
            
            # mpv EDL format: start end length
            start = op.start
            end = op.end
            length = end - start
            
            if op.action == OperationType.SLOW_MOTION and op.speed:
                # For slow motion, mpv can handle speed via EDL
                edl_lines.append(f"{media.path} {start} {length} speed={op.speed}")
            else:
                edl_lines.append(f"{media.path} {start} {length}")
        
        return "\n".join(edl_lines)
    
    def start_preview(self, plan: EditPlan, media_files: List[MediaFile]) -> PreviewProcess:
        """Start mpv preview with EDL."""
        edl_content = self.generate_edl(plan, media_files)
        
        # Write EDL to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.edl', delete=False) as f:
            f.write(edl_content)
            edl_path = Path(f.name)
        
        # Build mpv command
        cmd = [
            self.mvp_path,
            f"edl://{edl_path}",
            "--ontop",
            f"--geometry={settings.preview_geometry}",
            "--no-terminal",
            "--force-window=immediate",
        ]
        
        if settings.preview_ontop:
            cmd.append("--ontop")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        preview = PreviewProcess(process=process, temp_files=[edl_path])
        self.current_preview = preview
        return preview
    
    def stop_preview(self):
        if self.current_preview:
            self.current_preview.terminate()
            self.current_preview = None


class FFplayPreview:
    """Level 3: Fallback preview using ffplay (always available with ffmpeg)."""
    
    def __init__(self, ffplay_path: str = None):
        self.ffplay_path = ffplay_path or settings.ffplay_path
        self.current_preview: Optional[PreviewProcess] = None
    
    def start_preview(self, plan: EditPlan, media_files: List[MediaFile]) -> PreviewProcess:
        """Start ffplay preview with filter_complex for cuts."""
        media_map = {m.name: m for m in media_files}
        
        # Build filter_complex for cuts
        filter_parts = []
        input_files = []
        
        for i, op in enumerate(plan.operations):
            if op.action not in (OperationType.KEEP_RANGE, OperationType.SLOW_MOTION):
                continue
            
            media = media_map.get(op.file)
            if not media or not media.path:
                continue
            
            input_files.append(str(media.path))
            # Will use trim filter
        
        # For simplicity, use concat with trim filters
        # This is a simplified version - full implementation would be more complex
        
        cmd = [
            self.ffplay_path,
            "-autoexit",
            "-window_title", "SIVS Preview",
        ] + input_files
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        preview = PreviewProcess(process=process)
        self.current_preview = preview
        return preview
    
    def stop_preview(self):
        if self.current_preview:
            self.current_preview.terminate()
            self.current_preview = None


class QuickLookPreview:
    """Level 3b: macOS QuickLook fallback."""
    
    def __init__(self):
        self.current_preview: Optional[PreviewProcess] = None
    
    def start_preview(self, file_path: Path) -> PreviewProcess:
        """Open file in QuickLook."""
        cmd = ["qlmanage", "-p", str(file_path)]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        preview = PreviewProcess(process=process)
        self.current_preview = preview
        return preview
    
    def stop_preview(self):
        if self.current_preview:
            self.current_preview.terminate()
            self.current_preview = None


class PreviewManager:
    """Manages all preview levels and auto-selects best available."""
    
    def __init__(self):
        self.mpv_preview = MPVEDLPreview()
        self.ffplay_preview = FFplayPreview()
        self.quicklook_preview = QuickLookPreview()
        self.active_preview: Optional[PreviewProcess] = None
        self.active_level: int = 0
    
    def check_availability(self) -> dict:
        """Check which preview methods are available."""
        return {
            "mpv": self._check_command(settings.mpv_path),
            "ffplay": self._check_command(settings.ffplay_path),
            "quicklook": self._check_command("qlmanage"),
        }
    
    def _check_command(self, cmd: str) -> bool:
        try:
            subprocess.run([cmd, "-version"], capture_output=True, timeout=2)
            return True
        except:
            return False
    
    def start_best_preview(self, plan: EditPlan, media_files: List[MediaFile]) -> Tuple[PreviewProcess, int]:
        """Start the best available preview."""
        availability = self.check_availability()
        
        # Level 2: mpv with EDL (best for instant preview)
        if availability["mpv"]:
            self.active_preview = self.mpv_preview.start_preview(plan, media_files)
            self.active_level = 2
            return self.active_preview, 2
        
        # Level 3: ffplay
        if availability["ffplay"]:
            self.active_preview = self.ffplay_preview.start_preview(plan, media_files)
            self.active_level = 3
            return self.active_preview, 3
        
        # Level 3b: QuickLook (macOS only) - needs a rendered file
        if availability["quicklook"]:
            # Would need a temp render first - skip for now
            pass
        
        raise RuntimeError("No preview method available. Install mpv or ffplay.")
    
    def stop_all(self):
        self.mpv_preview.stop_preview()
        self.ffplay_preview.stop_preview()
        self.quicklook_preview.stop_preview()
        self.active_preview = None
        self.active_level = 0


# Export the classes
__all__ = [
    "PreviewManager", "ASCIITimelineRenderer",
    "MPVEDLPreview", "FFplayPreview", "QuickLookPreview",
    "PreviewProcess", "TimelineSegment",
]