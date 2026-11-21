"""Automated quality control for finished Rushmark clips.
Checks duration, loudness (-14 LUFS), black frames, frozen screens, and opening/closing cards.
"""
import json
import re
import subprocess
from pathlib import Path

# Thresholds
T_MIN_DUR = 3.0
T_MAX_DUR = 90.0
T_TARGET_LUFS = -14.0
T_LUFS_TOLERANCE = 3.0


def check_clip(path: str | Path, min_dur: float = T_MIN_DUR, max_dur: float = T_MAX_DUR) -> dict:
    """Run QC checks on a rendered video file. Returns status (PASS, WARN, FAIL) and details."""
    p = Path(path)
    if not p.is_file():
        return {"status": "FAIL", "errors": ["File not found"], "duration": 0, "lufs": None}

    errors = []
    warnings = []

    # 1. Duration check
    dur = 0.0
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
            capture_output=True, text=True, timeout=30
        )
        dur = round(float(r.stdout.strip()), 2)
    except Exception as e:
        errors.append(f"Could not read duration: {e}")

    if dur > 0:
        if dur < min_dur:
            errors.append(f"Too short ({dur}s < {min_dur}s)")
        elif dur > max_dur:
            errors.append(f"Too long ({dur}s > {max_dur}s)")
        elif dur > 60.0:
            warnings.append(f"Long clip ({dur}s, over 60s standard Shorts threshold)")

    # 2. Integrated loudness check (EBU R128)
    lufs = None
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-af", "ebur128", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60
        )
        matches = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr or "")
        if matches:
            lufs = round(float(matches[-1]), 1)
            if abs(lufs - T_TARGET_LUFS) > T_LUFS_TOLERANCE:
                warnings.append(f"Loudness {lufs} LUFS differs from target -14 LUFS")
    except Exception:
        pass

    # 3. Black frame and freeze frame detection
    black_spans = []
    freeze_spans = []
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-an",
             "-vf", "blackdetect=d=0.4:pix_th=0.10,freezedetect=n=-60dB:d=2.0",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=60
        )
        black_spans = [float(x) for x in re.findall(r"black_duration:([\d.]+)", r.stderr or "")]
        freeze_spans = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", r.stderr or "")]
    except Exception:
        pass

    if black_spans and max(black_spans) >= 1.0:
        errors.append(f"Black frames detected ({max(black_spans):.1f}s)")
    elif black_spans and max(black_spans) >= 0.4:
        warnings.append(f"Short black transition ({max(black_spans):.1f}s)")

    if freeze_spans and max(freeze_spans) >= 3.0:
        warnings.append(f"Frozen video detected ({max(freeze_spans):.1f}s)")

    # 4. Opening and ending frame brightness check
    try:
        for label, offset in [("Opening", 0.4), ("Ending", max(0.5, dur - 0.4))]:
            out = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{offset:.2f}", "-i", str(p),
                 "-frames:v", "1", "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"],
                capture_output=True, timeout=20
            ).stdout
            if out:
                mean_luma = sum(out) / len(out)
                if mean_luma < 6:
                    warnings.append(f"{label} frame is dark (luma {mean_luma:.1f})")
    except Exception:
        pass

    status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "status": status,
        "duration": dur,
        "lufs": lufs,
        "errors": errors,
        "warnings": warnings
    }
