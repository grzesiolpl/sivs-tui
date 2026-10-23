"""
SIVS-TUI - AI-powered edit plan generation from natural language briefs.
"""
import json
import os
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from openai import OpenAI
from sivs_tui.config import settings
from sivs_tui.models import EditPlan, EditOperation, OperationType, MediaFile


SYSTEM_PROMPT = """You are an expert video editor creating edit plans for SIVS (Super Intelligence Video Studio).

Your task: Convert a natural language brief into a structured JSON edit plan.

AVAILABLE OPERATIONS:
1. keep_range - Keep a specific time range from a file
2. remove_range - Remove a specific time range from a file  
3. slow_motion - Apply slow motion to a range (requires speed factor: 0.5 = 2x slower, 0.33 = 3x slower)
4. concat - Concatenate multiple files/ranges (handled implicitly by ordering)

OUTPUT FORMAT (JSON):
{
  "project": "project_name",
  "output": {
    "container": "mp4",
    "video_codec": "libx264",
    "audio_codec": "aac",
    "crf": 20,
    "preset": "medium",
    "resolution": "1920x1080",
    "framerate": 30
  },
  "operations": [
    {"action": "keep_range", "file": "clip.mp4", "start": 0, "end": 10, "description": "Opening shot"},
    {"action": "remove_range", "file": "clip.mp4", "start": 10, "end": 15, "description": "Remove shaky part"},
    {"action": "slow_motion", "file": "clip.mp4", "start": 30, "end": 35, "speed": 0.33, "description": "Slow-mo explosion"}
  ],
  "approval_required": true,
  "post_processing": {"face_blur": {"enabled": false}, "upscale": {"enabled": false}}
}

RULES:
1. All times in SECONDS (float), not HH:MM:SS
2. File names must match exactly the source filenames provided
3. Operations execute in order - they define the FINAL timeline sequence
4. remove_range = cut OUT that range (keep before AND after)
4. slow_motion speed: 0.5 = 2x slower, 0.33 = 3x slower, 0.25 = 4x slower
5. Only use file names from the provided source list
6. Times must be within the source file duration
7. Include descriptive "description" field for each operation
8. Default output: 1920x1080, 30fps, libx264, CRF 20

EXAMPLES:

Brief: "Cut 0-10s from intro.mp4, remove 5-8s from broll.mp4, slow-mo 20-25s at 0.5x in action.mp4"
→ Operations:
  keep_range: intro.mp4 0-10
  keep_range: broll.mp4 0-5, keep_range: broll.mp4 8-end (remove_range creates two keep ranges)
  slow_motion: action.mp4 20-25 speed=0.5

Brief: "Make a 30s trailer from movie.mp4: 0-5, 10-15, 30-35, slow-mo at 0.33x for 40-45"
→ Operations:
  keep_range: movie.mp4 0-5
  keep_range: movie.mp4 10-15
  keep_range: movie.mp4 30-35
  slow_motion: movie.mp4 40-45 speed=0.33
"""


def create_openai_client() -> OpenAI:
    """Create OpenAI client with OpenRouter configuration."""
    api_key = settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not configured. Set in ~/.config/sivs/.env or environment.")
    
    return OpenAI(
        api_key=api_key,
        base_url=settings.openrouter_base_url,
    )


async def generate_edit_plan(brief: str, media_files: List[MediaFile]) -> 'EditPlan':
    """Generate edit plan from brief using LLM."""
    from sivs_tui.models import EditPlan
    
    # Prepare media info for the prompt
    media_info = []
    for m in media_files:
        media_info.append({
            "filename": m.name,
            "duration": m.duration,
            "duration_str": f"{m.duration:.1f}s",
            "type": m.type.value,
        })
    
    # Build user prompt
    user_prompt = f"""BRIEF:
{brief}

SOURCE FILES:
{json.dumps(media_info, indent=2)}

Generate the edit plan JSON. Return ONLY the JSON, no markdown or explanation."""
    
    client = create_openai_client()
    
    response = await client.chat.completions.create(
        model=settings.default_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    plan_data = json.loads(content)
    
    # Validate and create EditPlan
    plan = EditPlan.model_validate(plan_data)
    
    # Set source files
    plan.source_files = [m.name for m in media_files]
    
    return plan


async def refine_edit_plan(current_plan: 'EditPlan', refinement_brief: str, 
                          media_files: List[MediaFile]) -> 'EditPlan':
    """Refine an existing plan based on user feedback."""
    from sivs_tui.models import EditPlan
    
    media_info = []
    for m in media_files:
        media_info.append({
            "filename": m.name,
            "duration": m.duration,
        })
    
    # Build refinement prompt
    current_plan_json = current_plan.model_dump(mode='json')
    
    user_prompt = f"""CURRENT PLAN:
{json.dumps(current_plan_json, indent=2, default=str)}

SOURCE FILES:
{json.dumps([{"filename": m.name, "duration": m.duration} for m in media_files], indent=2)}

REFINEMENT REQUEST:
{refinement_brief}

Update the plan accordingly. Return ONLY the updated JSON."""
    
    client = create_openai_client()
    
    response = await client.chat.completions.create(
        model=settings.default_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    plan_data = json.loads(content)
    
    # Preserve project name and version
    plan_data["project"] = current_plan.project
    plan_data["version"] = current_plan.version + 1
    
    return EditPlan.model_validate(plan_data)


def validate_plan_against_media(plan: 'EditPlan', media_files: List[MediaFile]) -> List[str]:
    """Validate plan operations against actual media files."""
    errors = []
    media_map = {m.name: m for m in media_files}
    
    for i, op in enumerate(plan.operations):
        # Check file exists
        if op.file not in media_map:
            errors.append(f"Operation {i}: File '{op.file}' not found in source files")
            continue
        
        media = media_map[op.file]
        
        # Check time bounds
        if op.start < 0:
            errors.append(f"Operation {i}: start time cannot be negative")
        if op.end > media.duration:
            errors.append(f"Operation {i}: end time {op.end}s exceeds file duration {media.duration:.1f}s")
        if op.start >= op.end:
            errors.append(f"Operation {i}: start time must be < end time")
        
        # Check slow_motion speed
        if op.action == OperationType.SLOW_MOTION:
            if not op.speed or op.speed <= 0 or op.speed >= 1:
                errors.append(f"Operation {i}: slow_motion requires speed between 0 and 1")
    
    return errors


def auto_generate_plan_from_silence(media_files: List[MediaFile], 
                                    silence_threshold_db: float = -30,
                                    min_silence_duration: float = 0.5) -> 'EditPlan':
    """Auto-generate a plan by removing silence from media files."""
    from sivs_tui.core.analyzer import SilenceDetector
    from sivs_tui.config import settings
    
    detector = SilenceDetector()
    all_operations = []
    
    for media in media_files:
        if media.type != "video" and media.type != "audio":
            continue
        
        silences = detector.detect(
            media.path, 
            noise_db=silence_threshold_db, 
            min_duration=min_silence_duration
        )
        
        if not silences:
            # No silence - keep entire file
            all_operations.append(EditOperation(
                action=OperationType.KEEP_RANGE,
                file=media.name,
                start=0,
                end=media.duration,
                description=f"Full file (no silence detected)"
            ))
        else:
            # Build keep ranges around silences
            last_end = 0
            for silence_start, silence_end in silences:
                if silence_start > last_end:
                    all_operations.append(EditOperation(
                        action=OperationType.KEEP_RANGE,
                        file=media.name,
                        start=last_end,
                        end=silence_start,
                        description=f"Content before silence at {silence_start:.1f}s"
                    ))
                last_end = silence_end
            
            # Final segment after last silence
            if last_end < media.duration:
                all_operations.append(EditOperation(
                    action=OperationType.KEEP_RANGE,
                    file=media.name,
                    start=last_end,
                    end=media.duration,
                    description=f"Content after last silence"
                ))
    
    from sivs_tui.models import EditPlan
    return EditPlan(
        project="auto_silence_removal",
        operations=all_operations,
        source_files=[m.name for m in media_files],
    )