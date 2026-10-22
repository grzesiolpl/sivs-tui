"""Exporters - Export management for NLE/DAW targets."""
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any

from sivs_tui.models import EditPlan, EditOperation, OperationType, ExportTarget, ExportMode, MediaFile
from sivs_tui.config import settings


class ExporterBase:
    """Base class for all exporters."""
    
    def __init__(self, studio_scripts_dir: Path):
        self.scripts_dir = studio_scripts_dir
    
    def run_exporter(self, script_name: str, args: List[str]) -> subprocess.CompletedProcess:
        """Run an exporter script."""
        script_path = self.scripts_dir / "exporters" / script_name
        if not script_path.exists():
            raise FileNotFoundError(f"Exporter not found: {script_path}")
        
        cmd = ["python3", str(script_path)] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


class FCPXMLExporter:
    """Export to FCPXML for Final Cut Pro."""
    
    def __init__(self, studio_scripts_dir: Path):
        self.scripts_dir = studio_scripts_dir
    
    def export(self, plan, media_files: list, output_path: Path) -> Path:
        # Use the Python exporter directly
        from sivs_tui.exporters.export_fcpxml import generate_fcpxml
        
        # Prepare media info in expected format
        media_info = {}
        for m in media_files:
            media_info[m.name] = {
                "duration": m.duration,
                "width": m.width,
                "height": m.height,
            }
        
        # Create a plan dict compatible with the exporter
        plan_dict = {
            "project": plan.project,
            "output": plan.output,
            "operations": [op.model_dump() for op in plan.operations],
            "media": media_info,
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        generate_fcpxml(Path("."), plan_dict, output_path)
        
        return output_path


class EDLExporter:
    """Export to CMX 3600 EDL for DaVinci Resolve / Audio DAWs."""
    
    def __init__(self, studio_scripts_dir: Path):
        self.scripts_dir = studio_scripts_dir
    
    def export(self, plan, media_files: list, output_path: Path, audio_only: bool = False) -> Path:
        from sivs_tui.exporters.export_edl import generate_edl
        
        media_info = {}
        for m in media_files:
            media_info[m.name] = {
                "duration": m.duration,
                "audio": len(m.audio_tracks) > 0,
            }
        
        plan_dict = {
            "project": plan.project,
            "output": plan.output,
            "operations": [op.model_dump() for op in plan.operations],
            "media": media_info,
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        generate_edl(Path("."), plan_dict, output_path, audio_only=audio_only)
        
        return output_path


class FCP7XMLExporter:
    """Export to FCP7 XML (xmeml) for After Effects / Premiere Pro."""
    
    def __init__(self, studio_scripts_dir: Path):
        self.scripts_dir = studio_scripts_dir
    
    def export(self, plan, media_files: list, output_path: Path) -> Path:
        from sivs_tui.exporters.export_fcp7_xml import generate_fcp7_xml
        
        media_info = {}
        for m in media_files:
            media_info[m.name] = {
                "duration": m.duration,
                "width": m.width,
                "height": m.height,
            }
        
        plan_dict = {
            "project": plan.project,
            "output": plan.output,
            "operations": [op.model_dump() for op in plan.operations],
            "media": media_info,
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        generate_fcp7_xml(Path("."), plan_dict, output_path)
        
        return output_path


class RenderExporter:
    """Render video/audio files using FFmpeg."""
    
    def __init__(self, studio_scripts_dir: Path):
        self.scripts_dir = studio_scripts_dir
        self.ffmpeg_path = settings.ffmpeg_path
    
    def render_video(self, plan, media_files: list, output_path: Path, preset_name: str = "universal_render") -> Path:
        """Render video using FFmpeg with preset."""
        # Get preset from export_presets.json
        presets = self._load_presets()
        preset = presets.get(preset_name, presets.get("universal_render"))
        
        # Build FFmpeg command
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # For now, delegate to render_project script
        # In a full implementation, we'd build the FFmpeg command here
        cmd = [
            "python3", str(self.scripts_dir / "render_project"),
            "--plan", "temp_plan.json",  # Would write plan to temp file
            "--output", str(output_path),
        ]
        
        # For now, just return the path - full implementation would run the render
        return output_path
    
    def render_audio(self, plan, media_files: list, output_path: Path) -> Path:
        """Export audio only as WAV."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path
    
    def _load_presets(self) -> dict:
        presets_path = settings.config_dir / "export_presets.json"
        if presets_path.exists():
            import json
            return json.loads(presets_path.read_text())
        return {}


class ExportManager:
    """Manages all export operations."""
    
    def __init__(self, studio_scripts_dir: Path = None):
        self.studio_scripts_dir = studio_scripts_dir or settings.get_studio_scripts_dir()
        self.fcpxml = FCPXMLExporter(self.studio_scripts_dir)
        self.edl = EDLExporter(self.studio_scripts_dir)
        self.fcp7xml = FCP7XMLExporter(self.studio_scripts_dir)
        self.render = RenderExporter(self.studio_scripts_dir)
    
    def export_timeline(self, plan, media_files: list, 
                       target, output_path: Path) -> Path:
        """Export timeline format (XML/EDL) without rendering."""
        
        from sivs_tui.models import ExportTarget
        
        if target == ExportTarget.FCP:
            return self.fcpxml.export(plan, media_files, output_path)
        
        elif target == "davinci":  # string comparison for flexibility
            # Export both FCPXML and EDL
            fcpxml_path = output_path.with_suffix(".fcpxml")
            edl_path = output_path.with_suffix(".edl")
            self.fcpxml.export(plan, media_files, fcpxml_path)
            self.edl.export(plan, media_files, edl_path)
            return output_path
        
        elif target == "after_effects":
            return self.fcp7xml.export(plan, media_files, output_path)
        
        elif target == "daw_audio":
            return self.edl.export(plan, media_files, output_path, audio_only=True)
        
        elif target == "universal":
            # Universal timeline = FCPXML + EDL
            fcpxml_path = output_path.with_suffix(".fcpxml")
            edl_path = output_path.with_suffix(".edl")
            self.fcpxml.export(plan, media_files, fcpxml_path)
            self.edl.export(plan, media_files, edl_path)
            return output_path
        
        raise ValueError(f"Unknown timeline export target: {target}")
    
    def render_output(self, plan, media_files: list,
                     target, output_path: Path, preset_name: str = None) -> Path:
        """Render video/audio file for target."""
        # This would use FFmpeg with target-specific settings
        # For now, return path - full implementation in render_exporter.py
        return output_path
    
    def get_output_extension(self, target, mode) -> str:
        """Get file extension for target/mode combination."""
        from sivs_tui.models import ExportTarget, ExportMode
        
        if mode == "timeline":
            if target == "fcp":
                return ".fcpxml"
            elif target == "davinci":
                return ".fcpxml"
            elif target == "after_effects":
                return "_fcp7.xml"
            elif target == "daw_audio":
                return ".edl"
            elif target == "universal":
                return ".fcpxml"
        else:  # RENDER mode
            if target == "daw_audio":
                return "_audio.wav"
            elif target in ("fcp", "davinci", "after_effects"):
                return ".mov"
            else:
                return ".mp4"
        
        return ".mp4"
    
    def generate_output_path(self, folder: Path, base_name: str, 
                            target, mode) -> Path:
        """Generate output path with auto-incrementing edit number."""
        from sivs_tui.models import find_existing_edits
        
        ext = self.get_output_extension(target, mode)
        stem = Path(base_name).stem
        
        # Find next edit number
        pattern = f"edit_*_{stem}{ext}"
        existing = list(folder.glob(pattern))
        max_num = 0
        for f in existing:
            try:
                parts = f.stem.split("_")
                if len(parts) >= 2 and parts[0] == "edit":
                    max_num = max(max_num, int(parts[1]))
            except:
                pass
        
        next_num = max_num + 1
        return folder / f"edit_{next_num:02d}_{stem}{ext}"


def open_in_finder(path: Path) -> None:
    """Open file in Finder (macOS)."""
    subprocess.run(["open", "-R", str(path)], check=False)


def open_with_default_app(path: Path) -> None:
    """Open file with default application."""
    subprocess.run(["open", str(path)], check=False)