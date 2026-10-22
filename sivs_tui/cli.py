#!/usr/bin/env python3
"""
SIVS CLI - Command line interface for SIVS TUI.
"""
import sys
import argparse
from pathlib import Path


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sivs",
        description="SIVS - Super Intelligence Video Studio (Terminal UI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sivs                          # Start TUI, select file interactively
  sivs video.mp4                # Open video.mp4 directly
  sivs ~/Videos/project.mov     # Open with full path
  sivs --config                 # Show configuration
  sivs --doctor                 # Check system dependencies
        """
    )
    
    parser.add_argument(
        "input_file", 
        nargs="?", 
        type=Path,
        help="Video file to edit (optional - can select in TUI)"
    )
    
    parser.add_argument(
        "--config", 
        action="store_true",
        help="Show current configuration"
    )
    
    parser.add_argument(
        "--doctor",
        action="store_true", 
        help="Check system dependencies (ffmpeg, mpv, etc.)"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="SIVS-TUI 1.0.0"
    )
    
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run in development mode with debug logging"
    )
    
    return parser


def show_config():
    """Display current configuration."""
    from rich.console import Console
    from rich.table import Table
    from sivs_tui.config import settings
    
    console = Console()
    table = Table(title="SIVS Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    config_items = [
        ("Workspace", settings.workspace_dir),
        ("Config Dir", settings.config_dir),
        ("Cache Dir", settings.cache_dir),
        ("FFmpeg", settings.ffmpeg_path),
        ("FFprobe", settings.ffprobe_path),
        ("MPV", settings.mpv_path),
        ("FFplay", settings.ffplay_path),
        ("Default Model", settings.default_model),
        ("Cheap Model", settings.cheap_model),
        ("OpenRouter Key", "***" if settings.openrouter_api_key else "NOT SET"),
    ]
    
    for key, value in config_items:
        table.add_row(key, str(value))
    
    console.print(table)


async def run_doctor():
    """Check system dependencies."""
    from rich.console import Console
    from rich.table import Table
    import subprocess
    from sivs_tui.config import settings
    
    console = Console()
    table = Table(title="SIVS System Check")
    table.add_column("Tool", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Version", style="yellow")
    
    checks = [
        ("ffmpeg", "ffmpeg", ["-version"]),
        ("ffprobe", "ffprobe", ["-version"]),
        ("mpv", "mpv", ["--version"]),
        ("ffplay", "ffplay", ["-version"]),
        ("qlmanage", "qlmanage", ["-h"]),
        ("python", sys.executable, ["--version"]),
        ("textual", "python", ["-c", "import textual; print(textual.__version__)"]),
        ("rich", "python", ["-c", "import rich; print(rich.__version__)"]),
    ]
    
    for name, cmd, args in checks:
        try:
            result = subprocess.run([cmd] + args, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                version = result.stdout.strip().split('\n')[0]
                table.add_row(name, "✅ OK", version[:50])
            else:
                table.add_row(name, "❌ FAIL", result.stderr[:50])
        except Exception as e:
            table.add_row(name, "❌ ERROR", str(e)[:50])
    
    console.print(table)
    
    # Check API key
    from sivs_tui.config import settings
    if settings.openrouter_api_key:
        console.print("\n[green]✅ OPENROUTER_API_KEY configured[/green]")
    else:
        console.print("\n[yellow]⚠️  OPENROUTER_API_KEY not set (AI features disabled)[/yellow]")
        console.print("  Set via: export OPENROUTER_API_KEY=your_key")
        console.print("  Or add to ~/.config/sivs/.env")


def main():
    parser = create_parser()
    args = parser.parse_args()
    
    if args.config:
        show_config()
        return 0
    
    if args.doctor:
        import asyncio
        asyncio.run(run_doctor())
        return 0
    
    input_file = None
    if args.input_file:
        input_file = args.input_file.expanduser().resolve()
        if not input_file.exists():
            print(f"Error: File not found: {input_file}", file=sys.stderr)
            return 1
    
    # Run TUI - import here to avoid circular imports
    try:
        from sivs_tui.app import run_sivs_tui
        run_sivs_tui(input_file=input_file)
        return 0
    except KeyboardInterrupt:
        print("\nExiting...")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.dev:
            import traceback
            traceback.print_exc()
        return 1