"""
SIVS-TUI - Main TUI Application using Textual.
"""
import os
import asyncio
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, Static, DataTable, Input, Button, 
    Label, Select, ProgressBar, TabbedContent, TabPane,
    RichLog, Collapsible, Tree, Sparkline
)
from textual.widgets._header import HeaderIcon
from textual.binding import Binding
from textual.screen import Screen
from textual.message import Message
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


class TimelineWidget(Static):
    """Widget for displaying ASCII timeline visualization."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.renderer = ASCIITimelineRenderer(console=None)  # Will use Rich render
        self.plan = None
        self.media_files = []
    
    def update_timeline(self, plan: EditPlan, media_files: List[MediaFile]):
        self.plan = plan
        self.media_files = media_files
        self.refresh()
    
    def render(self) -> str:
        if not self.plan:
            return "[dim]No edit plan loaded. Enter a brief to generate one.[/dim]"
        
        # Use Rich to render
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
    
    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Describe your edit... e.g. 'Cut 0:10-0:20, slow-mo 0:30-0:35 at 0.33x, export for FCP'",
            id="brief_input",
        )
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.post_message(self.BriefSubmitted(event.value.strip()))


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
    }
    
    #right_panel {
        width: 60%;
        padding: 1;
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
    
    #brief_input {
        dock: bottom;
        height: 3;
        border: solid $primary;
        padding: 1;
    }
    
    #export_config {
        dock: bottom;
        height: 3;
        border: solid $accent;
        padding: 1;
    }
    
    #key_bindings {
        dock: bottom;
        height: 8;
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
    """
    
    BINDINGS = [
        Binding("p", "preview", "▶ Preview"),
        Binding("b", "brief", "💬 Brief"),
        Binding("e", "edit_plan", "✏️ Edit Plan"),
        Binding("r", "render", "🚀 Render"),
        Binding("t", "export_timeline", "🎞️ Export"),
        Binding("o", "open_finder", "📂 Finder"),
        Binding("q", "quit", "❌ Quit"),
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
                        yield DataTable(id="plan_table", classes="plan_table")
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
        
        yield Static("", id="status_bar")
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize the app."""
        self.query_one("#plan_table", DataTable).add_columns(
            "#", "Operation", "File", "Start", "End", "Duration", "Speed", "Description"
        )
        self.query_one("#qc_table", DataTable).add_columns(
            "Stage", "Passed", "Checks", "Issues", "Time"
        )
        
        # Load initial file if provided
        if self.input_file:
            await self.load_file(self.input_file)
        else:
            self.update_status("Welcome to SIVS! Drag a video file here or use the CLI.")
    
    async def load_file(self, file_path: Path) -> None:
        """Load a media file and initialize the project."""
        try:
            self.update_status(f"Analyzing {file_path.name}...")
            
            # Analyze media
            media_file = await self.run_worker(
                self.analyzer.analyze, file_path, thread=True
            )
            
            # Detect silence
            silence_segments = await self.run_worker(
                self.silence_detector.detect, file_path, thread=True
            )
            
            # Determine manifest directory
            manifest_dir = file_path.parent / ".sivs"
            manifest_dir.mkdir(exist_ok=True)
            
            # Find next edit number
            edit_number = find_existing_edits(file_path.parent, file_path.stem) + 1
            
            # Create project context
            self.project_context = ProjectContext(
                input_file=file_path,
                media_file=media_file,
                manifest_dir=manifest_dir,
                edit_number=1,  # Will be updated
            )
            
            # Update UI
            self.query_one("#media_info", MediaInfoWidget).update_media(media_file)
            self.update_timeline_display()
            self.update_plan_table()
            self.update_silence_info(silence_segments)
            
            self.update_status(f"Loaded {file_path.name} ({media_file.formatted_duration})")
            
            # Auto-generate initial plan if we have a brief
            # (would need brief first)
            
        except Exception as e:
            self.notify(f"Failed to load file: {e}", severity="error")
            self.update_status(f"Error: {e}")
    
    def update_timeline_display(self):
        """Update the timeline visualization."""
        if not self.project_context or not self.project_context.edit_plan:
            return
        
        plan = self.project_context.edit_plan
        media_files = [self.project_context.media_file]
        
        # Use rich to render timeline
        from io import StringIO
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        renderer = ASCIITimelineRenderer(console=console)
        renderer.render(plan, media_files)
        
        self.query_one("#timeline_widget", Static).update(output.getvalue())
    
    def update_plan_table(self):
        """Update the edit plan data table."""
        table = self.query_one("#plan_table", DataTable)
        table.clear()
        
        if not self.project_context or not self.project_context.edit_plan:
            return
        
        plan = self.project_context.edit_plan
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
            
            table.add_row(
                str(i), op_style, op.file, tc_start, tc_end,
                f"{duration:.2f}s", speed, op.description or ""
            )
    
    def update_silence_info(self, silences: List[tuple]):
        """Update silence detection info."""
        widget = self.query_one("#silence_info", Static)
        if not silences:
            widget.update("[dim]No silence detected[/dim]")
            return
        
        lines = ["[bold]🔇 Silence Detected:[/bold]"]
        for start, end in silences[:10]:  # Show first 10
            dur = end - start
            lines.append(f"  {self._format_tc(start)} → {self._format_tc(end)}  ({dur:.1f}s)")
        
        if len(silences) > 10:
            lines.append(f"  … and {len(silences) - 10} more")
        
        widget.update("\n".join(lines))
    
    def update_plan_table(self):
        pass  # Placeholder
    
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
        
        # Write plan to temp file and open in editor
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
            # Reload plan
            with open(temp_path) as f:
                new_plan_data = json.load(f)
            self.project_context.edit_plan = EditPlan.model_validate(new_plan_data)
            self.update_timeline_display()
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
            
            # Generate output path
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
                # Render mode
                self.notify("Render mode not fully implemented yet", severity="warning")
            
            self.update_status(f"Exported: {output_path.name}")
        except Exception as e:
            self.notify(f"Export failed: {e}", severity="error")
    
    async def action_open_finder(self) -> None:
        """Show file in Finder."""
        if self.project_context:
            open_in_finder(self.project_context.input_file)
            self.notify("Opened in Finder")
    
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
            self.update_plan_table()
            self.update_status("Edit plan generated!")
            self.notify("Edit plan generated!")
        except Exception as e:
            self.notify(f"AI generation failed: {e}", severity="error")
            self.update_status(f"AI error: {e}")
    
    async def on_export_config_config_changed(self, event: ExportConfigWidget.ConfigChanged) -> None:
        self.export_target = event.target
        self.export_mode = event.mode
        self.update_status(f"Export: {event.target.value.upper()} / {event.mode.value}")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        actions = {
            "btn_preview": self.action_preview,
            "btn_brief": self.action_brief,
            "btn_edit_plan": self.action_edit_plan,
            "btn_render": self.action_render,
            "btn_export": self.action_export_timeline,
            "btn_finder": self.action_open_finder,
        }
        if button_id in actions:
            self.call_later(actions[button_id])
    
    async def on_key(self, event: events.Key) -> None:
        """Handle key events."""
        # Prevent default for our bindings
        pass


def run_sivs_tui(input_file: Optional[Path] = None):
    """Entry point for the TUI application."""
    app = SIVSApp(input_file=input_file)
    app.run()


if __name__ == "__main__":
    import sys
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    run_sivs_tui(input_file=input_path)