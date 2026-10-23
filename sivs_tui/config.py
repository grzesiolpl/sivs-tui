"""
SIVS-TUI - Core configuration and settings management.
"""
import os
import json
from pathlib import Path
from typing import Optional, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


CONFIG_FILE = Path.home() / ".config" / "sivs" / "settings.json"


class SIVSSettings(BaseSettings):
    """Global SIVS configuration loaded from environment and config files."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Core paths
    workspace_dir: Path = Field(default_factory=lambda: Path.home() / "AI-Video-Studio-Workspace")
    config_dir: Path = Field(default_factory=lambda: Path.home() / ".config" / "sivs")
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "sivs")
    
    # External tools (auto-detected if not set)
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    mpv_path: str = "mpv"
    ffplay_path: str = "ffplay"
    qlmanage_path: str = "qlmanage"
    davinci_path: Optional[str] = None
    
    # AI / LLM
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "anthropic/claude-3.5-sonnet"
    cheap_model: str = "openai/gpt-4o-mini"
    
    # Video processing defaults
    default_framerate: int = 30
    default_resolution: str = "1920x1080"
    default_video_codec: str = "libx264"
    default_audio_codec: str = "aac"
    default_crf: int = 20
    default_preset: str = "medium"
    
    # Preview settings
    preview_geometry: str = "960x540"
    preview_ontop: bool = True
    
    # Export targets
    enabled_targets: List[str] = ["fcp", "davinci", "after_effects", "daw_audio", "universal"]
    
    # UI
    theme: str = "sivs_dark"
    show_ascii_timeline: bool = True
    max_timeline_width: int = 120
    
    @field_validator("workspace_dir", "config_dir", "cache_dir", mode="before")
    @classmethod
    def expand_path(cls, v):
        if isinstance(v, str):
            return Path(v).expanduser().resolve()
        return v
    
    def get_studio_scripts_dir(self) -> Path:
        """Get path to CLI scripts (exported from Obsidian)."""
        # First check config_dir, then workspace, then package resources
        for base in [self.config_dir, self.workspace_dir]:
            scripts = base / "scripts"
            if scripts.exists():
                return scripts
        # Fallback to package resources
        import sivs_tui
        return Path(sivs_tui.__file__).parent / "resources" / "scripts"
    
    def get_templates_dir(self) -> Path:
        for base in [self.config_dir, self.workspace_dir]:
            templates = base / "templates"
            if templates.exists():
                return templates
        import sivs_tui
        return Path(sivs_tui.__file__).parent / "resources" / "templates"
    
    def save(self) -> None:
        """Save settings to JSON config file."""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Only save user-modifiable settings
        data = {
            "workspace_dir": str(self.workspace_dir),
            "config_dir": str(self.config_dir),
            "cache_dir": str(self.cache_dir),
            "ffmpeg_path": self.ffmpeg_path,
            "ffprobe_path": self.ffprobe_path,
            "mpv_path": self.mpv_path,
            "ffplay_path": self.ffplay_path,
            "qlmanage_path": self.qlmanage_path,
            "davinci_path": self.davinci_path,
            "openrouter_api_key": self.openrouter_api_key,
            "openrouter_base_url": self.openrouter_base_url,
            "default_model": self.default_model,
            "cheap_model": self.cheap_model,
            "default_framerate": self.default_framerate,
            "default_resolution": self.default_resolution,
            "default_video_codec": self.default_video_codec,
            "default_audio_codec": self.default_audio_codec,
            "default_crf": self.default_crf,
            "default_preset": self.default_preset,
            "preview_geometry": self.preview_geometry,
            "preview_ontop": self.preview_ontop,
            "enabled_targets": self.enabled_targets,
            "theme": self.theme,
            "show_ascii_timeline": self.show_ascii_timeline,
            "max_timeline_width": self.max_timeline_width,
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)


# Global settings instance
settings = SIVSSettings()

# Load saved config if exists
if CONFIG_FILE.exists():
    try:
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
        for key, value in saved.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
    except Exception:
        pass  # Ignore corrupt config