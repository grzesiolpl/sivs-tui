"""
SIVS-TUI - Main TUI Application using Textual.
"""
import os
import asyncio
import subprocess
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, Static, DataTable, Input, Button,
    Label, Select, ProgressBar, TabbedContent, TabPane,
    RichLog, Collapsible, Tree, Sparkline, TextArea
)
from textual.widgets._header import HeaderIcon
from textual.binding import Binding
from textual.screen import Screen
from textual.message import Message
from textual.events import FileDrop
from rich.console import Console
from rich.table import Table
from rich.text import Text

from sivs_tui.config import settings
from sivs_tui.models import (
    MediaFile, EditPlan, EditOperation, OperationType,
    ExportTarget, ExportMode, QCStage, ProjectState,
    MediaType, get_media_type, next_edit_filename, find_existing_edits
)
from sivs_tui.core.analyzer import MediaAnalyzer, SilenceDetector
from sivs_tui.preview import PreviewManager, ASCIITimelineRenderer
from sivs_tui.exporters import ExportManager, open_in_finder, open_with_default_app
from sivs_tui.utils.ai_brief import generate_edit_plan, refine_edit_plan


@dataclass
class ProjectContext:
    """Context for the current project being edited."""
    input_file: Path
    media_file: MediaFile
    manifest_dir: Path
    edit_plan: Optional[EditPlan] = None
    project_state: Optional[ProjectState] = None
    edit_number: int = 1


class WelcomeWidget(Static):
    """Welcome screen with workflow guide when no file is loaded."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loading_file = None

    def show_loading(self, filename: str):
        """Show loading state."""
        self._loading_file = filename
        self.refresh()

    def hide_loading(self):
        """Clear loading state."""
        self._loading_file = None
        self.refresh()

    def render(self) -> str:
        if self._loading_file:
            return f"""\\
[bold cyan]SIVS[/bold cyan]
[dim]Terminal UI for video editing[/dim]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[bold yellow]⏳ Loading {self._loading_file}...[/bold yellow]
[dim]Analyzing media, detecting silence, transcribing audio...[/dim]
[dim]This may take a few seconds for large files.[/dim]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        return """\\
[bold cyan]SIVS[/bold cyan]
[dim]Terminal UI for video editing[/dim]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[bold]Quick Start:[/bold]

  [bold]1. Load[/bold]  →  [cyan]sivs video.mp4[/cyan]  or drag & drop
  [bold]2. Brief[/bold] →  Type in bottom box, press [bold]Enter[/bold]
  [bold]3. Review[/bold] →  Tab [bold]Timeline[/bold] / [bold]Edit Plan[/bold]
  [bold]4. Preview[/bold] →  [bold]P[/bold] = mpv EDL (instant!)
  [bold]5. Export[/bold]  →  [bold]T[/bold] = XML/EDL  |  [bold]R[/bold] = render
  [bold]6. Find[/bold]    →  [bold]O[/bold] = Finder → edit_01_name.ext

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[bold]Keys:[/bold]  [bold]P[/bold] Preview  [bold]B[/bold] Brief  [bold]E[/bold] Edit Plan  [bold]R[/bold] Render  [bold]T[/bold] Export  [bold]O[/bold] Finder  [bold]W[/bold] Web UI  [bold]Q[/bold] Quit
[bold]C[/bold] Clear    [bold]L[/bold] Load Another  [bold]S[/bold] Save Plan  [bold]Esc[/bold] Cancel Plan

[dim]Run [cyan]sivs --help[/cyan] for full guide  •  [cyan]sivs --setup[/cyan] for first-time config  •  [cyan]sivs --doctor[/cyan] for system check
"""


class TimelineWidget(Static):
    """Widget for displaying ASCII timeline visualization."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.renderer = ASCIITimelineRenderer(console=None)
        self.plan = None
        self.media_files = []

    def update_timeline(self, plan: EditPlan, media_files: List[MediaFile]):
        self.plan = plan
        self.media_files = media_files
        self.refresh()

    def render(self) -> str:
        if not self.plan:
            return "[dim]No edit plan loaded. Enter a brief to generate one.[/dim]"

        from rich.console import Console
        from io import StringIO

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=self.size.width or 120)
        renderer = ASCIITimelineRenderer(console=console, max_width=self.max_width)
        renderer.render(self.plan, self.media_files)
        return output.getvalue()


class MediaInfoWidget(Static):
    """Widget for displaying media file information."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.media_file = None

    def update_media(self, media: MediaFile):
        self.media_file = media
        self.refresh()

    def render(self) -> str:
        if not self.media_file:
            return "[dim]No media loaded[/dim]"

        m = self.media_file
        lines = [
            f"[bold cyan]📁 {m.name}[/bold cyan]",
            f"  Type: [cyan]{m.type.value}[/cyan]  |  Size: [green]{m.formatted_size}[/green]  |  Duration: [yellow]{m.formatted_duration}[/yellow]",
        ]
        if m.width and m.height:
            lines.append(f"  Resolution: [cyan]{m.width}x{m.height}[/cyan]  |  FPS: [yellow]{m.fps:.2f}[/yellow]  |  Codec: [magenta]{m.video_codec or 'N/A'}[/magenta]")
        if m.audio_tracks:
            for at in m.audio_tracks:
                lines.append(f"  Audio: [cyan]{at.codec}[/cyan] {at.channels}ch @ {at.sample_rate}Hz")

        return "\n".join(lines)


class BriefInputWidget(Static):
    """Widget for entering/editing the brief."""

    class BriefSubmitted(Message):
        def __init__(self, brief: str) -> None:
            self.brief = brief
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_brief = ""

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Describe your edit... e.g. 'Cut 0:10-0:20, slow-mo 0:30-0:35 at 0.33x, export for FCP'",
            id="brief_input",
        )

    def on_mount(self) -> None:
        """Focus the input when widget is shown."""
        self.query_one("#brief_input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.current_brief = event.value.strip()
            self.post_message(self.BriefSubmitted(event.value.strip()))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Track current brief as user types."""
        self.current_brief = event.value


class ExportConfigWidget(Static):
    """Widget for configuring export target and mode."""

    class ConfigChanged(Message):
        def __init__(self, target: ExportTarget, mode: ExportMode) -> None:
            self.target = target
            self.mode = mode
            super().__init__()

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Select(
                [(t.value.upper(), t) for t in ExportTarget],
                value=ExportTarget.FCP,
                id="target_select",
                prompt="Target",
            )
            yield Select(
                [(m.value.title(), m) for m in ExportMode],
                value=ExportMode.TIMELINE,
                id="mode_select",
                prompt="Mode",
            )

    def on_select_changed(self, event: Select.Changed) -> None:
        target = self.query_one("#target_select", Select).value
        mode = self.query_one("#mode_select", Select).value
        self.post_message(self.ConfigChanged(target, mode))


class KeyBindingsWidget(Static):
    """Display available key bindings."""

    def render(self) -> str:
        bindings = [
            ("[bold]P[/bold]", "▶ Live Preview (mpv EDL)"),
            ("[bold]B[/bold]", "💬 Refine Brief / AI Edit"),
            ("[bold]E[/bold]", "✏️ Edit Plan JSON ($EDITOR)"),
            ("[bold]R[/bold]", "🚀 Render Output"),
            ("[bold]T[/bold]", "🎞️ Export Timeline (XML/EDL)"),
            ("[bold]O[/bold]", "📂 Show in Finder"),
            ("[bold]Q[/bold]", "❌ Quit"),
            ("[bold]C[/bold]", "🗑️ Clear File"),
            ("[bold]L[/bold]", "📁 Load Another"),
            ("[bold]S[/bold]", "💾 Save Plan"),
            ("[bold]Esc[/bold]", "↩️ Cancel Plan"),
        ]
        return "\n".join(f"  {k:<12} {v}" for k, v in bindings)


class SIVSApp(App):
    """Main SIVS TUI Application."""

    CSS = """
    Screen {
        background: $surface;
    }

    #main_container {
        layout: horizontal;
        height: 100%;
    }

    #left_panel {
        width: 40%;
        min-width: 50;
        border-right: solid $primary;
        padding: 1;
        height: 100%;
        overflow-y: auto;
    }

    #right_panel {
        width: 60%;
        padding: 1;
        height: 100%;
    }

    #timeline_widget {
        height: 1fr;
        border: solid $secondary;
        padding: 1;
        overflow-y: auto;
    }

    #media_info {
        height: auto;
        min-height: 10;
        border: solid $secondary;
        padding: 1;
        margin-top: 1;
    }

    #brief_widget {
        height: 3;
        border: solid $primary;
        padding: 1;
    }

    #export_config {
        height: 3;
        border: solid $accent;
        padding: 1;
    }

    #key_bindings {
        height: 10;
        border: solid $secondary;
        padding: 1;
        background: $surface-darken-1;
    }

    #status_bar {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        height: 1fr;
    }

    .plan_table {
        height: 1fr;
    }

    .info_box {
        border: solid $secondary;
        padding: 1;
        margin: 1 0;
    }

    Button {
        margin: 0 1;
    }

    .button_row {
        height: auto;
        margin: 1 0;
    }

    /* Edit Plan Editor */
    #plan_editor_text {
        height: 1fr;
    }
    
    /* Ensure QC table fills its tab */
    #qc_table {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("p", "preview", "▶ Preview"),
        Binding("b", "brief", "💬 Brief"),
        Binding("e", "edit_plan", "✏️ Edit Plan"),
        Binding("r", "render", "🚀 Render"),
        Binding("t", "export_timeline", "🎞️ Export"),
        Binding("o", "open_finder", "📂 Finder"),
        Binding("w", "launch_web", "🌐 Web UI"),
        Binding("q", "quit", "❌ Quit"),
        Binding("c", "clear_file", "🗑️ Clear"),
        Binding("l", "load_another", "📁 Load"),
        Binding("s", "save_plan", "💾 Save"),
        Binding("escape", "cancel_plan", "↩️ Cancel"),
        Binding("ctrl+z", "undo", "↶ Undo"),
        Binding("ctrl+shift+z", "redo", "↷ Redo"),
    ]

    def __init__(self, input_file: Optional[Path] = None, **kwargs):
        super().__init__(**kwargs)
        self.input_file = input_file
        self.project_context: Optional[ProjectContext] = None
        self.preview_manager = PreviewManager()
        self.export_manager = ExportManager()
        self.analyzer = MediaAnalyzer()
        self.silence_detector = SilenceDetector()
        self.console = Console()

        # State
        self.current_brief = ""
        self.export_target = ExportTarget.FCP
        self.export_mode = ExportMode.TIMELINE
        self.active_preview = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="🎬")

        with Horizontal(id="main_container"):
            # Left panel - Media info, Brief, Export config
            with Vertical(id="left_panel"):
                yield WelcomeWidget(id="welcome_widget")
                yield MediaInfoWidget(id="media_info")
                yield Static("", classes="info_box", id="silence_info")
                yield BriefInputWidget(id="brief_widget")
                yield ExportConfigWidget(id="export_config")
                yield KeyBindingsWidget(id="key_bindings")

            # Right panel - Timeline, Plan, Actions
            with Vertical(id="right_panel"):
                with TabbedContent(initial="timeline_tab"):
                    with TabPane("📊 Timeline", id="timeline_tab"):
                        yield Static(id="timeline_widget", classes="plan_table")
                    with TabPane("📝 Edit Plan", id="plan_tab"):
                        yield TextArea(id="plan_editor_text", read_only=False)
                    with TabPane("🔍 QC Reports", id="qc_tab"):
                        yield DataTable(id="qc_table")

                # Action buttons
                with Horizontal(classes="button_row"):
                    yield Button("▶ Preview [P]", id="btn_preview", variant="primary")
                    yield Button("💬 Brief [B]", id="btn_brief", variant="default")
                    yield Button("✏️ Edit Plan [E]", id="btn_edit_plan", variant="default")
                    yield Button("🚀 Render [R]", id="btn_render", variant="success")
                    yield Button("🎞️ Export [T]", id="btn_export", variant="default")
                    yield Button("📂 Finder [O]", id="btn_finder", variant="default")
                    yield Button("🌐 Web UI [W]", id="btn_web", variant="default")

                # Main input for file paths (when no file) or brief (when file loaded)
                yield Input(
                    placeholder="Drag & drop video file here, or paste path, or type brief and press Enter...",
                    id="main_input",
                )

        yield Static("", id="status_bar")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the app."""
        # Initialize QC table
        self.query_one("#qc_table", DataTable).add_columns(
            "Stage", "Passed", "Checks", "Issues", "Time"
        )

        # Initially hide media-related widgets
        self.query_one("#media_info", MediaInfoWidget).display = False
        self.query_one("#silence_info", Static).display = False
        self.query_one("#brief_widget", BriefInputWidget).display = False
        self.query_one("#export_config", ExportConfigWidget).display = False
        self.query_one("#key_bindings", KeyBindingsWidget).display = False
        self.query_one("#timeline_widget", Static).display = False
        self.query_one("#qc_table", DataTable).display = False
        self.query_one("#plan_editor_text", TextArea).display = False

        # Load initial file if provided
        if self.input_file:
            self.call_later(self.load_file, self.input_file)
        else:
            self.update_status("Welcome to SIVS! Drag a video file here or run: sivs video.mp4")

    def on_file_drop(self, event: FileDrop) -> None:
        """Handle file drag & drop."""
        if event.files:
            for file_path in event.files:
                path = Path(file_path)
                if path.suffix.lower() in ('.mp4', '.mov', '.mkv', '.avi', '.m4v', '.mpg', '.mpeg', '.webm', '.mts', '.m2ts'):
                    self.call_later(self.load_file, path)
                    self.update_status(f"Loading {path.name}...")
                    self.notify(f"📁 Loading: {path.name}", severity="information")
                    return
            self.notify("No valid video file dropped. Supported: mp4, mov, mkv, avi, m4v, mpg, webm, mts, m2ts", severity="warning")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle main input submission - file path or brief."""
        if event.input.id != "main_input":
            return
        
        value = event.value.strip()
        if not value:
            return
        
        # Clean up path from macOS drag & drop (remove quotes and backslashes)
        cleaned = value.strip('"\'').replace("\\ ", " ").replace("\\", "")
        
        # Check if it's a file path
        path = Path(cleaned).expanduser()
        if path.exists() and path.suffix.lower() in ('.mp4', '.mov', '.mkv', '.avi', '.m4v', '.mpg', '.mpeg', '.webm', '.mts', '.m2ts'):
            self.call_later(self.load_file, path)
            self.update_status(f"Loading {path.name}...")
            self.notify(f"📁 Loading: {path.name}", severity="information")
            # Clear input after loading
            event.input.value = ""
        elif self.project_context and self.project_context.edit_plan is not None:
            # Treat as brief - generate edit plan
            self.current_brief = value
            self.update_status("Generating edit plan with AI...")
            self.call_later(self._generate_plan_from_brief, value)
            event.input.value = ""
        else:
            self.notify("No video loaded. Drag a file or paste a valid path first.", severity="warning")

    async def _generate_plan_from_brief(self, brief: str) -> None:
        """Generate edit plan from brief using AI."""
        try:
            from sivs_tui.utils.ai_brief import generate_edit_plan
            plan = await self.run_worker(
                generate_edit_plan,
                brief,
                [self.project_context.media_file],
                thread=True
            )
            self.project_context.edit_plan = plan
            self.update_timeline_display()
            self.update_plan_display()
            self._update_plan_management_buttons()
            self.update_status("Edit plan generated!")
            self.notify("Edit plan generated!")
        except Exception as e:
            self.notify(f"AI generation failed: {e}", severity="error")
            self.update_status(f"AI error: {e}")

    async def load_file(self, file_path: Path) -> None:
        """Load a media file and initialize the project."""
        # Validate file
        if not file_path.exists():
            self.notify(f"File not found: {file_path}", severity="error")
            return

        valid_extensions = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.mpg', '.mpeg', '.webm', '.mts', '.m2ts'}
        if file_path.suffix.lower() not in valid_extensions:
            self.notify(f"Unsupported format: {file_path.suffix}. Supported: mp4, mov, mkv, avi, m4v, mpg, webm, mts, m2ts", severity="error")
            return

        # Show file info notification
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        self.notify(f"Loading: {file_path.name} ({file_size_mb:.1f} MB)", severity="information")

        try:
            # Show loading state in welcome widget
            welcome_widget = self.query_one("#welcome_widget", WelcomeWidget)
            welcome_widget.show_loading(file_path.name)

            self.update_status(f"Analyzing {file_path.name}...")

            # Analyze media
            media_file = await self.run_worker(
                lambda: self.analyzer.analyze(file_path), thread=True
            )

            # Detect silence AND speech segments
            silence_segments = await self.run_worker(
                lambda: self.silence_detector.detect(file_path), thread=True
            )
            speech_segments = await self.run_worker(
                lambda: self.silence_detector.get_speech_segments(file_path), thread=True
            )

            # Try Whisper transcription (optional, runs in background)
            transcript_segments = await self.run_worker(
                self._transcribe_audio, file_path, thread=True
            )

            # Determine manifest directory
            manifest_dir = file_path.parent / ".sivs"
            manifest_dir.mkdir(exist_ok=True)

            # Save media manifest with all analysis data
            await self._save_media_manifest(
                manifest_dir, media_file, silence_segments, speech_segments, transcript_segments
            )

            # Find next edit number
            edit_number = find_existing_edits(file_path.parent, file_path.stem) + 1

            # Create project context
            self.project_context = ProjectContext(
                input_file=file_path,
                media_file=media_file,
                manifest_dir=manifest_dir,
                edit_number=edit_number,
            )

            # Clear loading state and switch UI
            welcome_widget = self.query_one("#welcome_widget", WelcomeWidget)
            welcome_widget.hide_loading()

            # Switch UI: hide welcome, show media widgets
            self.query_one("#welcome_widget", WelcomeWidget).display = False
            self.query_one("#media_info", MediaInfoWidget).display = True
            self.query_one("#silence_info", Static).display = True
            self.query_one("#brief_widget", BriefInputWidget).display = True
            self.query_one("#export_config", ExportConfigWidget).display = True
            self.query_one("#key_bindings", KeyBindingsWidget).display = True
            self.query_one("#timeline_widget", Static).display = True
            self.query_one("#qc_table", DataTable).display = True
            self.query_one("#plan_editor_text", TextArea).display = True

            # Add file management buttons
            self._add_file_management_buttons()

            # Update UI
            self.query_one("#media_info", MediaInfoWidget).update_media(media_file)
            self.update_timeline_display()
            self.update_plan_display()
            self.update_silence_info(silence_segments)

            self.update_status(f"✅ Loaded: {file_path.name} ({media_file.formatted_duration}) — Enter brief below")
            self.notify(f"✅ Loaded: {file_path.name} ({media_file.formatted_duration})", severity="information")

            # Focus brief input
            self.query_one("#brief_widget #brief_input", Input).focus()

        except Exception as e:
            welcome_widget = self.query_one("#welcome_widget", WelcomeWidget)
            welcome_widget.hide_loading()
            self.notify(f"Failed to load: {e}", severity="error")
            self.update_status(f"Error: {e}")

    async def _transcribe_audio(self, file_path: Path) -> List[Dict[str, Any]]:
        """Run Whisper transcription if available."""
        from sivs_tui.core.analyzer import WhisperTranscriber
        transcriber = WhisperTranscriber()
        if transcriber.is_available():
            return transcriber.get_sentence_segments(file_path) or []
        return []

    async def _save_media_manifest(self, manifest_dir: Path, media_file,
                                   silence_segments: List[tuple],
                                   speech_segments: List[tuple],
                                   transcript_segments: List[Dict[str, Any]]) -> None:
        """Save comprehensive media manifest for the planner."""
        import json
        from datetime import datetime

        manifest = {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "source_file": {
                "name": media_file.name,
                "path": str(media_file.path),
                "duration": media_file.duration,
                "width": media_file.width,
                "height": media_file.height,
                "fps": media_file.fps,
                "video_codec": media_file.video_codec,
                "audio_codec": media_file.audio_codec,
                "size": media_file.size,
            },
            "analysis": {
                "silence_segments": [
                    {"start": s, "end": e, "duration": e - s}
                    for s, e in silence_segments
                ],
                "speech_segments": [
                    {"start": s, "end": e, "duration": e - s}
                    for s, e in speech_segments
                ],
                "transcript_segments": transcript_segments,
            }
        }

        manifest_path = manifest_dir / "media_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        # Also save transcript separately for easy access
        if transcript_segments:
            transcript_path = manifest_dir / "transcript.json"
            with open(transcript_path, "w") as f:
                json.dump({
                    "segments": transcript_segments,
                    "full_text": " ".join([s.get("text", "") for s in transcript_segments])
                }, f, indent=2, ensure_ascii=False)

    def update_timeline_display(self):
        """Update the timeline visualization."""
        if not self.project_context or not self.project_context.edit_plan:
            self.query_one("#timeline_widget", Static).update(
                "[dim]No edit plan yet. Enter a brief below and press Enter to generate one.[/dim]"
            )
            return

        plan = self.project_context.edit_plan
        media_files = [self.project_context.media_file]

        from io import StringIO
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        renderer = ASCIITimelineRenderer(console=console)
        renderer.render(plan, media_files)

        self.query_one("#timeline_widget", Static).update(output.getvalue())

    def update_plan_display(self):
        """Update the edit plan TextArea."""
        text_area = self.query_one("#plan_editor_text", TextArea)

        if not self.project_context or not self.project_context.edit_plan:
            text_area.text = "[dim]No edit plan yet. Enter a brief below and press Enter to generate one.[/dim]"
            return

        plan = self.project_context.edit_plan
        lines = []
        for i, op in enumerate(plan.operations, 1):
            tc_start = self._format_tc(op.start)
            tc_end = self._format_tc(op.end)
            duration = op.end - op.start
            speed = f"{op.speed}×" if op.speed else "1×"

            op_style = {
                OperationType.KEEP_RANGE: "KEEP",
                OperationType.REMOVE_RANGE: "CUT",
                OperationType.SLOW_MOTION: f"SLOW {op.speed}×",
                OperationType.CONCAT: "JOIN",
            }.get(op.action, op.action.value)

            lines.append(f"{i:2d}  {op_style:12s}  {op.file:<20s}  {tc_start} → {tc_end}  ({duration:.2f}s)  {speed:>5s}  {op.description or ''}")

        text_area.text = "\n".join(lines) if lines else "[dim]No edit plan yet. Enter a brief below and press Enter to generate one.[/dim]"

    def update_silence_info(self, silences: List[tuple]):
        """Update silence detection info."""
        widget = self.query_one("#silence_info", Static)
        if not silences:
            widget.update("[dim]No silence detected[/dim]")
            return

        lines = ["[bold]🔇 Silence Detected:[/bold]"]
        for start, end in silences[:10]:
            dur = end - start
            lines.append(f"  {self._format_tc(start)} → {self._format_tc(end)}  ({dur:.1f}s)")

        if len(silences) > 10:
            lines.append(f"  … and {len(silences) - 10} more")

        widget.update("\n".join(lines))

    def _format_tc(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"

    def update_status(self, message: str):
        self.query_one("#status_bar", Static).update(f"  {message}")

    # Action handlers
    async def action_preview(self) -> None:
        """Start live preview (Level 2: mpv EDL)."""
        if not self.project_context or not self.project_context.edit_plan:
            self.notify("No edit plan loaded", severity="warning")
            return

        try:
            self.update_status("Starting live preview (mpv EDL)...")
            plan = self.project_context.edit_plan
            media_files = [self.project_context.media_file]

            preview, level = self.preview_manager.start_best_preview(plan, [self.project_context.media_file])
            self.active_preview = preview
            self.update_status(f"Live preview started (Level {level}: {'mpv EDL' if level==2 else 'ffplay'})")
            self.notify(f"Preview started (Level {level})")
        except Exception as e:
            self.notify(f"Preview failed: {e}", severity="error")
            self.update_status(f"Preview failed: {e}")

    async def action_brief(self) -> None:
        """Focus brief input for refinement."""
        self.query_one("#brief_widget #brief_input", Input).focus()

    async def action_edit_plan(self) -> None:
        """Open edit plan in $EDITOR."""
        if not self.project_context or not self.project_context.edit_plan:
            self.notify("No edit plan to edit", severity="warning")
            return

        import tempfile
        import os
        import json

        plan = self.project_context.edit_plan
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(plan.model_dump(mode='json'), f, indent=2, default=str)
            temp_path = f.name

        editor = os.environ.get("EDITOR", "code")
        try:
            subprocess.run([editor, temp_path], check=True)
            with open(temp_path) as f:
                new_plan_data = json.load(f)
            self.project_context.edit_plan = EditPlan.model_validate(new_plan_data)
            self.update_timeline_display()
            self.update_plan_display()
            self.notify("Plan updated from editor")
        except subprocess.CalledProcessError:
            self.notify("Editor cancelled", severity="warning")
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass

    async def action_render(self) -> None:
        """Render the final output."""
        if not self.project_context or not self.project_context.edit_plan:
            self.notify("No edit plan to render", severity="warning")
            return

        self.update_status("Rendering...")
        self.notify("Render started...")
        # TODO: Implement actual render
        self.update_status("Render complete!")
        self.notify("Render complete!")

    async def action_export_timeline(self) -> None:
        """Export timeline (XML/EDL) for NLE."""
        if not self.project_context or not self.project_context.edit_plan:
            self.notify("No edit plan to export", severity="warning")
            return

        try:
            plan = self.project_context.edit_plan
            media_files = [self.project_context.media_file]

            output_path = self.export_manager.generate_output_path(
                self.project_context.input_file.parent,
                self.project_context.input_file.stem,
                self.export_target,
                self.export_mode
            )

            if self.export_mode == ExportMode.TIMELINE:
                output_path = self.export_manager.export_timeline(
                    self.project_context.edit_plan,
                    [self.project_context.media_file],
                    self.export_target,
                    output_path
                )
                self.notify(f"Timeline exported: {output_path.name}")
                open_with_default_app(output_path)
            else:
                self.notify("Render mode not fully implemented yet", severity="warning")

            self.update_status(f"Exported: {output_path.name}")
        except Exception as e:
            self.notify(f"Export failed: {e}", severity="error")

    async def action_open_finder(self) -> None:
        """Show file in Finder."""
        if self.project_context:
            open_in_finder(self.project_context.input_file)
            self.notify("Opened in Finder")

    async def action_launch_web(self) -> None:
        """Launch the Web UI."""
        self.notify("Starting Web UI at http://localhost:3000...", severity="information")
        import subprocess
        import sys
        web_dir = Path(__file__).parent.parent.parent / "AI-Video-Studio-UI"
        if not web_dir.exists():
            web_dir = Path("/Users/mac/AI-Video-Studio-UI")
        if web_dir.exists():
            threading.Thread(
                target=lambda: subprocess.run(
                    ["npm", "run", "dev"],
                    cwd=web_dir,
                    capture_output=True
                ),
                daemon=True
            ).start()
        else:
            self.notify("Web UI not found. Run from main repo.", severity="warning")

    async def on_brief_widget_brief_submitted(self, event: BriefInputWidget.BriefSubmitted) -> None:
        """Handle brief submission - generate edit plan via AI."""
        self.current_brief = event.brief
        self.update_status("Generating edit plan with AI...")

        try:
            plan = await self.run_worker(
                generate_edit_plan,
                event.brief,
                [self.project_context.media_file],
                thread=True
            )

            self.project_context.edit_plan = plan
            self.update_timeline_display()
            self.update_plan_display()
            self._update_plan_management_buttons()
            self.update_status("Edit plan generated!")
            self.notify("Edit plan generated!")
        except Exception as e:
            self.notify(f"AI generation failed: {e}", severity="error")
            self.update_status(f"AI error: {e}")

    async def on_export_config_config_changed(self, event: ExportConfigWidget.ConfigChanged) -> None:
        self.export_target = event.target
        self.export_mode = event.mode
        self.update_status(f"Export: {event.target.value.upper()} / {event.mode.value}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        actions = {
            "btn_preview": self.action_preview,
            "btn_brief": self.action_brief,
            "btn_edit_plan": self.action_edit_plan,
            "btn_render": self.action_render,
            "btn_export": self.action_export_timeline,
            "btn_finder": self.action_open_finder,
            "btn_web": self.action_launch_web,
            "btn_clear_file": self.action_clear_file,
            "btn_load_another": self.action_load_another,
            "btn_save_plan": self.action_save_plan,
            "btn_cancel_plan": self.action_cancel_plan,
        }
        if button_id in actions:
            self.call_later(actions[button_id])

    def _add_file_management_buttons(self) -> None:
        """Add file management buttons to the button row."""
        button_row = self.query_one(".button_row", Horizontal)

        # Remove existing file management buttons if they exist
        for btn_id in ["btn_clear_file", "btn_load_another", "btn_save_plan", "btn_cancel_plan"]:
            try:
                existing = self.query_one(f"#{btn_id}", Button)
                existing.remove()
            except:
                pass

        # Add new buttons
        button_row.mount(
            Button("🗑️ Clear [C]", id="btn_clear_file", variant="error"),
            Button("📁 Load Another [L]", id="btn_load_another", variant="primary"),
        )

        # Add plan management buttons (shown when plan exists)
        if self.project_context and self.project_context.edit_plan:
            button_row.mount(
                Button("💾 Save Plan [S]", id="btn_save_plan", variant="success"),
                Button("↩️ Cancel [Esc]", id="btn_cancel_plan", variant="default"),
            )

    def _remove_file_management_buttons(self) -> None:
        """Remove file management buttons."""
        for btn_id in ["btn_clear_file", "btn_load_another", "btn_save_plan", "btn_cancel_plan"]:
            try:
                existing = self.query_one(f"#{btn_id}", Button)
                existing.remove()
            except:
                pass

    def _update_plan_management_buttons(self) -> None:
        """Show/hide plan management buttons based on whether plan exists."""
        try:
            button_row = self.query_one(".button_row", Horizontal)
            has_plan = self.project_context and self.project_context.edit_plan

            for btn_id in ["btn_save_plan", "btn_cancel_plan"]:
                try:
                    btn = self.query_one(f"#{btn_id}", Button)
                    btn.display = has_plan
                except:
                    if has_plan:
                        if btn_id == "btn_save_plan":
                            button_row.mount(Button("💾 Save Plan [S]", id="btn_save_plan", variant="success"))
                        elif btn_id == "btn_cancel_plan":
                            button_row.mount(Button("↩️ Cancel [Esc]", id="btn_cancel_plan", variant="default"))
        except:
            pass

    # === File Management Actions ===
    async def action_clear_file(self) -> None:
        """Clear current file and return to welcome screen."""
        self._remove_file_management_buttons()

        # Reset project context
        self.project_context = None
        self.current_brief = ""

        # Hide media widgets, show welcome
        self.query_one("#welcome_widget", WelcomeWidget).display = True
        self.query_one("#media_info", MediaInfoWidget).display = False
        self.query_one("#silence_info", Static).display = False
        self.query_one("#brief_widget", BriefInputWidget).display = False
        self.query_one("#export_config", ExportConfigWidget).display = False
        self.query_one("#key_bindings", KeyBindingsWidget).display = False
        self.query_one("#timeline_widget", Static).display = False
        self.query_one("#qc_table", DataTable).display = False
        self.query_one("#plan_editor_text", TextArea).display = False

        # Clear brief input
        brief_input = self.query_one("#brief_widget #brief_input", Input)
        brief_input.value = ""

        # Clear timeline and plan display
        self.query_one("#timeline_widget", Static).update(
            "[dim]No edit plan yet. Enter a brief below and press Enter to generate one.[/dim]"
        )
        self.query_one("#plan_editor_text", TextArea).text = "[dim]No edit plan yet. Enter a brief below and press Enter to generate one.[/dim]"
        self.query_one("#silence_info", Static).update("[dim]No silence detected[/dim]")

        self.update_status("Welcome to SIVS! Drag a video file here or run: sivs video.mp4")
        self.notify("File cleared. Ready for new file.", severity="information")

    async def action_load_another(self) -> None:
        """Load another file (clears current first)."""
        await self.action_clear_file()

    async def action_save_plan(self) -> None:
        """Save current edit plan to manifest."""
        if not self.project_context or not self.project_context.edit_plan:
            self.notify("No plan to save", severity="warning")
            return

        try:
            import json
            from datetime import datetime

            plan = self.project_context.edit_plan
            manifest_dir = self.project_context.manifest_dir

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            plan_path = manifest_dir / f"edit_plan_{self.project_context.edit_number:02d}_{timestamp}.json"

            with open(plan_path, "w") as f:
                json.dump(plan.model_dump(mode='json'), f, indent=2, default=str)

            self.notify(f"Plan saved: {plan_path.name}", severity="information")
            self.update_status(f"Plan saved: {plan_path.name}")

        except Exception as e:
            self.notify(f"Failed to save plan: {e}", severity="error")

    async def action_cancel_plan(self) -> None:
        """Cancel current plan edits, revert to last saved."""
        if not self.project_context or not self.project_context.edit_plan:
            return

        manifest_dir = self.project_context.manifest_dir
        plan_files = sorted(manifest_dir.glob("edit_plan_*.json"), reverse=True)

        if len(plan_files) > 1:
            latest = plan_files[1]
            try:
                import json
                with open(latest) as f:
                    plan_data = json.load(f)
                self.project_context.edit_plan = EditPlan.model_validate(plan_data)
                self.update_timeline_display()
                self.update_plan_display()
                self.notify(f"Reverted to {latest.name}", severity="information")
            except Exception as e:
                self.notify(f"Failed to revert: {e}", severity="error")
        else:
            self.notify("No previous version to revert to", severity="warning")

    # === Key Bindings for New Actions ===
    async def on_key(self, event: events.Key) -> None:
        """Handle key events."""
        if event.key == "c":
            await self.action_clear_file()
        elif event.key == "l":
            await self.action_load_another()
        elif event.key == "s" and self.project_context and self.project_context.edit_plan:
            await self.action_save_plan()
        elif event.key == "escape" and self.project_context and self.project_context.edit_plan:
            await self.action_cancel_plan()


def run_sivs_tui(input_file: Optional[Path] = None):
    """Entry point for the TUI application."""
    app = SIVSApp(input_file=input_file)
    app.run()


if __name__ == "__main__":
    import sys
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    run_sivs_tui(input_file=input_path)