#!/usr/bin/env python3
"""
Frame rate normalization utilities for phone recordings (VFR, HEVC/HDR).
Handles VFR -> CFR conversion, frame boundary precision, and NLE-compatible timecodes.
"""
import math
from fractions import Fraction
from typing import Tuple, Optional


# Industry standard frame rates (exact fractions)
STANDARD_FRAMERATES = {
    "23.976": Fraction(24000, 1001),   # 23.976023976...
    "24": Fraction(24, 1),
    "25": Fraction(25, 1),
    "29.97": Fraction(30000, 1001),    # 29.97002997...
    "30": Fraction(30, 1),
    "50": Fraction(50, 1),
    "59.94": Fraction(60000, 1001),    # 59.94005994...
    "60": Fraction(60, 1),
}

# Common phone VFR frame rates that need normalization
PHONE_VFR_RATES = {
    29.83: "30",
    29.9: "30", 
    29.97: "29.97",
    30.0: "30",
    59.88: "60",
    59.9: "60",
    59.94: "59.94",
    60.0: "60",
    23.98: "23.976",
    24.0: "24",
    25.0: "25",
    23.976: "23.976",
}


def normalize_framerate(detected_fps: float, tolerance: float = 0.15) -> str:
    """
    Normalize detected VFR frame rate to nearest industry standard.
    
    Args:
        detected_fps: Detected frame rate (e.g., 29.83, 59.88)
        tolerance: Max difference to consider a match
        
    Returns:
        Standard frame rate key (e.g., "30", "29.97", "23.976")
    """
    # Check phone VFR mappings first
    for vfr, standard in PHONE_VFR_RATES.items():
        if abs(detected_fps - vfr) <= tolerance:
            return standard
    
    # Check exact standard rates
    for standard, frac in STANDARD_FRAMERATES.items():
        if abs(detected_fps - float(frac)) <= tolerance:
            return standard
    
    # Fallback: find closest standard
    closest = min(STANDARD_FRAMERATES.keys(), 
                  key=lambda k: abs(detected_fps - float(STANDARD_FRAMERATES[k])))
    return closest


def get_framerate_fraction(framerate_key: str) -> Fraction:
    """Get exact Fraction for a standard frame rate key."""
    if framerate_key in STANDARD_FRAMERATES:
        return STANDARD_FRAMERATES[framerate_key]
    # Try to parse as float and find closest
    try:
        fps = float(framerate_key)
        return Fraction(fps).limit_denominator(100000)
    except (ValueError, TypeError):
        return Fraction(30, 1)  # Default to 30fps


def seconds_to_frames(seconds: float, framerate_key: str) -> int:
    """Convert seconds to exact frame count using standard frame rate."""
    frac = get_framerate_fraction(framerate_key)
    return int(round(seconds * float(frac)))


def frames_to_seconds(frames: int, framerate_key: str) -> float:
    """Convert frame count to seconds using standard frame rate."""
    frac = get_framerate_fraction(framerate_key)
    return frames / float(frac)


def format_fcp_time(seconds: float, framerate_key: str) -> str:
    """
    Format time for FCPXML as exact frame fraction.
    
    FCPXML expects format: "frames/framerate" (e.g., "100/30000" for 30fps)
    """
    frac = get_framerate_fraction(framerate_key)
    frames = int(round(seconds * float(frac)))
    return f"{frames}/{frac.denominator}"


def format_fcp_duration(seconds: float, framerate_key: str) -> str:
    """Format duration for FCPXML as exact frame fraction."""
    return format_fcp_time(seconds, framerate_key)


def format_tc(seconds: float, framerate_key: str, drop_frame: bool = False) -> str:
    """
    Format timecode as HH:MM:SS:FF for EDL/FCP7.
    
    Uses exact frame counting for frame-accurate boundaries.
    """
    frac = get_framerate_fraction(framerate_key)
    total_frames = int(round(seconds * float(frac)))
    fps = int(frac) if frac.denominator == 1 else float(frac)
    
    # Use integer math for exact boundaries
    if isinstance(frac, Fraction):
        fps_int = frac.numerator // frac.denominator if frac.denominator > 1 else frac.numerator
        if frac == Fraction(30000, 1001):  # 29.97
            fps_int = 30  # NDF timecode uses 30
        elif frac == Fraction(60000, 1001):  # 59.94
            fps_int = 60
        else:
            fps_int = frac.numerator // frac.denominator
    else:
        fps_int = 30
    
    hours = total_frames // (3600 * fps_int)
    minutes = (total_frames % (3600 * fps_int)) // (60 * fps_int)
    secs = (total_frames % (60 * fps_int)) // fps_int
    frames = total_frames % fps_int
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def get_media_framerate(path: str) -> Tuple[float, str]:
    """
    Get media frame rate using ffprobe, returns (raw_fps, normalized_key).
    
    Uses ffprobe to get exact frame rate from media file.
    """
    import subprocess
    import json
    
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-select_streams", "v:0",
        path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return 30.0, "30"
        
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            return 30.0, "30"
        
        stream = streams[0]
        # Get r_frame_rate (average frame rate) or avg_frame_rate
        rate_str = stream.get("r_frame_rate") or stream.get("avg_frame_rate")
        
        if rate_str and "/" in rate_str:
            num, den = rate_str.split("/")
            raw_fps = float(num) / float(den)
        else:
            raw_fps = float(rate_str) if rate_str else 30.0
        
        normalized = normalize_framerate(raw_fps)
        return raw_fps, normalized
        
    except Exception:
        return 30.0, "30"


def validate_frame_boundary(seconds: float, framerate_key: str, tolerance_frames: float = 0.5) -> bool:
    """
    Check if a time value falls on a valid frame boundary.
    
    Returns True if the time aligns with frame boundaries within tolerance.
    """
    frac = get_framerate_fraction(framerate_key)
    frames = seconds * float(frac)
    nearest_frame = round(frames)
    return abs(frames - nearest_frame) <= tolerance_frames / float(frac)


def snap_to_frame_boundary(seconds: float, framerate_key: str) -> float:
    """Snap time to nearest valid frame boundary."""
    frac = get_framerate_fraction(framerate_key)
    frames = round(seconds * float(frac))
    return frames / float(frac)


# Color space / HDR handling for phone recordings
def get_color_space_info(path: str) -> dict:
    """Extract color space info from media file."""
    import subprocess
    import json
    
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-select_streams", "v:0",
        path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {"color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709", "is_hdr": False}
        
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            return {"color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709", "is_hdr": False}
        
        stream = streams[0]
        color_space = stream.get("color_space", "bt709")
        color_transfer = stream.get("color_transfer", "bt709") 
        color_primaries = stream.get("color_primaries", "bt709")
        
        # Detect HDR
        is_hdr = color_transfer in ("bt2020", "smpte2084", "arib-std-b67") or \
                 color_space in ("bt2020nc", "bt2020c")
        
        return {
            "color_space": color_space,
            "color_transfer": color_transfer,
            "color_primaries": color_primaries,
            "is_hdr": is_hdr
        }
    except Exception:
        return {"color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709", "is_hdr": False}


def get_ffmpeg_colorspace_args(path: str) -> list:
    """Get FFmpeg args to normalize color space for SDR delivery."""
    info = get_color_space_info(path)
    
    if info["is_hdr"]:
        # HDR -> SDR conversion with tone mapping
        return [
            "-vf", "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709:t=bt709:m=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:p=bt709,format=yuv420p",
            "-color_primaries", "1",
            "-color_trc", "1", 
            "-colorspace", "1"
        ]
    else:
        # Already SDR, just ensure bt709
        return [
            "-color_primaries", "1",
            "-color_trc", "1",
            "-colorspace", "1"
        ]


if __name__ == "__main__":
    # Test
    test_rates = [29.83, 29.97, 59.88, 59.94, 23.976, 30.0, 60.0]
    for r in test_rates:
        norm = normalize_framerate(r)
        print(f"{r:>6} fps -> {norm} (exact: {float(get_framerate_fraction(norm)):.6f})")
    
    print("\nFCP time format tests:")
    for sec in [0.5, 1.0, 10.5, 30.125]:
        print(f"  {sec}s @ 29.97 = {format_fcp_time(sec, '29.97')}")
        print(f"  {sec}s @ 30 = {format_fcp_time(sec, '30')}")