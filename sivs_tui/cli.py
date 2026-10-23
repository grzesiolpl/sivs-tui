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
  sivs --setup                  # Run first-time setup wizard
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

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run first-time setup wizard"
    )

    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch web UI (Next.js) instead of TUI"
    )
    
    return parser


async def run_setup_wizard():
    """Interactive first-time setup wizard."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from sivs_tui.config import settings, CONFIG_FILE
    import subprocess
    
    console = Console()
    
    console.print(Panel.fit(
        "[bold cyan]🎬 SIVS - Super Intelligence Video Studio[/bold cyan]\n"
        "[dim]First-time Setup Wizard[/dim]",
        border_style="cyan"
    ))
    
    console.print("\n[bold]Welcome to SIVS![/bold] Let's get you set up in a few steps.\n")
    
    # Step 1: Check dependencies
    console.print("[bold cyan]Step 1/4: System Check[/bold cyan]")
    
    checks = [
        ("ffmpeg", "ffmpeg", ["-version"]),
        ("ffprobe", "ffprobe", ["-version"]),
        ("mpv", "mpv", ["--version"]),
        ("ffplay", "ffplay", ["-version"]),
        ("qlmanage", "qlmanage", ["-h"]),
    ]
    
    table = Table(title="Dependencies")
    table.add_column("Tool", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Note", style="yellow")
    
    missing = []
    for name, cmd, args in checks:
        try:
            result = subprocess.run([cmd] + args, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version = result.stdout.strip().split('\n')[0][:40]
                table.add_row(name, "✅ OK", version)
            else:
                table.add_row(name, "❌ MISSING", "Install required")
                missing.append(name)
        except Exception:
            table.add_row(name, "❌ MISSING", "Install required")
            missing.append(name)
    
    console.print(table)
    
    if missing:
        console.print(f"\n[yellow]Missing tools: {', '.join(missing)}[/yellow]")
        console.print("Install with: [bold]brew install " + " ".join(missing) + "[/bold]")
        if "mpv" in missing:
            console.print("\n[dim]Note: mpv enables instant Level 2 preview (0s render).[/dim]")
            console.print("[dim]Without mpv, fallback is ffplay (works but slower).[/dim]")
        if not Confirm.ask("\nContinue anyway?", default=True):
            return 0
    
    # Step 2: API Key
    console.print("\n[bold cyan]Step 2/4: OpenRouter API Key[/bold cyan]")
    console.print("SIVS uses LLMs via OpenRouter to generate edit plans from your brief.")
    console.print("Get a free key at: [link]https://openrouter.ai/keys[/link]")
    console.print("Recommended models: [bold]anthropic/claude-3.5-sonnet[/bold] or [bold]openai/gpt-4o-mini[/bold] (cheaper)")
    
    current_key = settings.openrouter_api_key
    if current_key:
        console.print(f"\n[green]✅ Already configured: {current_key[:8]}...{current_key[-4:]}[/green]")
        if not Confirm.ask("Update API key?", default=False):
            pass
        else:
            new_key = Prompt.ask("Enter OpenRouter API Key", password=True)
            if new_key:
                settings.openrouter_api_key = new_key.strip()
    else:
        console.print("\n[yellow]No API key configured yet.[/yellow]")
        new_key = Prompt.ask("Enter OpenRouter API Key (or press Enter to skip)", password=True, default="")
        if new_key.strip():
            settings.openrouter_api_key = new_key.strip()
            console.print("[green]✅ API key saved![/green]")
        else:
            console.print("[yellow]⚠️  Skipped - AI features will be disabled[/yellow]")
            console.print("[dim]You can add it later with: sivs --setup[/dim]")
    
    # Step 3: Model selection
    console.print("\n[bold cyan]Step 3/4: Model Selection[/bold cyan]")
    console.print(f"Current model: [bold]{settings.default_model}[/bold]")
    
    models = [
        ("anthropic/claude-3.5-sonnet", "Best quality, best JSON output"),
        ("openai/gpt-4o-mini", "10x cheaper, good for simple edits"),
        ("anthropic/claude-3-haiku", "Fast & cheap, decent quality"),
    ]
    
    table = Table()
    table.add_column("#", style="cyan")
    table.add_column("Model", style="green")
    table.add_column("Description", style="dim")
    for i, (model, desc) in enumerate(models, 1):
        current = " ← current" if model == settings.default_model else ""
        table.add_row(str(i), model + current, desc)
    console.print(table)
    
    choice = Prompt.ask("Select model (1-3) or press Enter to keep current", choices=["1", "2", "3", ""], default="")
    if choice:
        settings.default_model = models[int(choice) - 1][0]
        console.print(f"[green]✅ Model set to: {settings.default_model}[/green]")
    
    # Step 4: Workspace
    console.print("\n[bold cyan]Step 4/4: Workspace Directory[/bold cyan]")
    console.print(f"Current workspace: [bold]{settings.workspace_dir}[/bold]")
    console.print("[dim]This is where SIVS will store projects if you don't specify a file path.[/dim]")
    
    new_ws = Prompt.ask("Change workspace? (Enter path or press Enter to keep)", default="")
    if new_ws.strip():
        ws_path = Path(new_ws.strip()).expanduser()
        ws_path.mkdir(parents=True, exist_ok=True)
        settings.workspace_dir = str(ws_path)
        console.print(f"[green]✅ Workspace set to: {settings.workspace_dir}[/green]")
    
    # Save config
    settings.save()
    console.print(f"\n[green]✅ Configuration saved to: {CONFIG_FILE}[/green]")
    
    # Final summary
    console.print(Panel.fit(
        "[bold green]🎉 Setup Complete![/bold green]\n\n"
        "You're ready to use SIVS:\n"
        "  • [bold]sivs video.mp4[/bold] - Open a video file\n"
        "  • [bold]sivs[/bold] - Start TUI, select file in UI\n"
        "  • [bold]sivs --doctor[/bold] - Re-run system check\n"
        "  • [bold]sivs --setup[/bold] - Re-run this wizard",
        border_style="green"
    ))
    
    return 0


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
    if settings.openrouter_api_key:
        console.print("\n[green]✅ OPENROUTER_API_KEY configured[/green]")
    else:
        console.print("\n[yellow]⚠️  OPENROUTER_API_KEY not set (AI features disabled)[/yellow]")
        console.print("  Run [bold]sivs --setup[/bold] to configure it")


def launch_web_ui():
    """Launch the SIVS Web UI (Next.js)."""
    import subprocess
    import os
    from pathlib import Path
    
    # Try to find the web UI directory
    possible_paths = [
        Path.home() / "AI-Video-Studio-UI",
        Path("/Users/mac/AI-Video-Studio-UI"),
        Path.cwd() / "AI-Video-Studio-UI",
        Path(__file__).parent.parent / "AI-Video-Studio-UI",
    ]
    
    web_ui_dir = None
    for p in possible_paths:
        if (p / "package.json").exists():
            web_ui_dir = p
            break
    
    if not web_ui_dir:
        print("Error: SIVS Web UI not found.", file=sys.stderr)
        print("Expected at ~/AI-Video-Studio-UI or /Users/mac/AI-Video-Studio-UI", file=sys.stderr)
        print("Clone from: https://github.com/grzesiolpl/sivs", file=sys.stderr)
        return 1
    
    print(f"🌐 Starting SIVS Web UI from {web_ui_dir}...")
    print("   Opening http://localhost:3000 in your browser...")
    
    # Check if node_modules exists
    if not (web_ui_dir / "node_modules").exists():
        print("   Installing dependencies (first run)...")
        subprocess.run(["npm", "install"], cwd=web_ui_dir, check=True)
    
    # Start the dev server
    try:
        # Open browser after a short delay
        import threading
        import time
        import webbrowser
        
        def open_browser():
            time.sleep(3)
            webbrowser.open("http://localhost:3000")
        
        threading.Thread(target=open_browser, daemon=True).start()
        
        # Run next dev server
        subprocess.run(["npm", "run", "dev"], cwd=web_ui_dir, check=True)
    except KeyboardInterrupt:
        print("\n👋 Web UI stopped")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error starting web UI: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("Error: npm not found. Install Node.js first.", file=sys.stderr)
        return 1
    
    return 0


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
    
    if args.setup:
        import asyncio
        asyncio.run(run_setup_wizard())
        return 0
    
    if args.web:
        return launch_web_ui()
    
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