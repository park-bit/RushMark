"""Generates high-quality sound effects (whoosh, impact, pop, ding) for Rushmark clips."""
import numpy as np
import soundfile as sf
from pathlib import Path

SFX_DIR = Path(__file__).resolve().parent / "sfx"
SAMPLE_RATE = 48000


def generate_all():
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    _make_whoosh(SFX_DIR / "whoosh.wav")
    _make_impact(SFX_DIR / "impact.wav")
    _make_pop(SFX_DIR / "pop.wav")
    _make_ding(SFX_DIR / "ding.wav")
    print(f"Generated sound effects in {SFX_DIR}")


def _make_whoosh(path: Path):
    """Cinematic air whoosh: filtered noise sweep + subtle low air tone."""
    dur = 0.38
    n = int(dur * SAMPLE_RATE)
    t = np.linspace(0, dur, n, endpoint=False)

    # Filtered noise with rising then falling envelope
    noise = np.random.uniform(-1, 1, n)
    # Pitch/cutoff sweep envelope: peak around 60% of duration
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2.5
    noise = noise * env

    # Simple moving average lowpass that moves over time
    sweep = 80 + 700 * np.sin(np.pi * t / dur)
    tone = np.sin(2 * np.pi * sweep * t) * env * 0.4

    mixed = (noise * 0.6 + tone) * 0.75
    # Smooth fade out
    fade_len = int(0.04 * SAMPLE_RATE)
    mixed[-fade_len:] *= np.linspace(1, 0, fade_len)
    sf.write(str(path), mixed.astype(np.float32), SAMPLE_RATE)


def _make_impact(path: Path):
    """Cinematic punchy bass impact/boom for climax moments."""
    dur = 0.55
    n = int(dur * SAMPLE_RATE)
    t = np.linspace(0, dur, n, endpoint=False)

    # Fast pitch drop: 110Hz -> 38Hz
    freq = 38 + 72 * np.exp(-t * 14)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    sub = np.sin(phase) * np.exp(-t * 6.5)

    # Click/punch at start (transient)
    click_t = t[:int(0.02 * SAMPLE_RATE)]
    click = np.sin(2 * np.pi * 180 * click_t) * np.exp(-click_t * 200)
    sub[:len(click)] += click * 0.5

    # Subtle rumble noise
    noise = np.random.uniform(-0.15, 0.15, n) * np.exp(-t * 10)
    mixed = (sub * 0.8 + noise) * 0.85
    sf.write(str(path), mixed.astype(np.float32), SAMPLE_RATE)


def _make_pop(path: Path):
    """Clean bubble / wooden pop sound for punchy words."""
    dur = 0.12
    n = int(dur * SAMPLE_RATE)
    t = np.linspace(0, dur, n, endpoint=False)

    freq = 140 + 380 * np.exp(-t * 45)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    pop = np.sin(phase) * np.exp(-t * 30)

    # Soft click transient
    mixed = pop * 0.8
    sf.write(str(path), mixed.astype(np.float32), SAMPLE_RATE)


def _make_ding(path: Path):
    """Pleasant metallic chime / bell for payoffs."""
    dur = 0.45
    n = int(dur * SAMPLE_RATE)
    t = np.linspace(0, dur, n, endpoint=False)

    # Bell with harmonics (1046Hz, 2093Hz, 3139Hz)
    f0 = 1046.5
    bell = (np.sin(2 * np.pi * f0 * t) * 0.6 * np.exp(-t * 5) +
            np.sin(2 * np.pi * f0 * 2.02 * t) * 0.25 * np.exp(-t * 8) +
            np.sin(2 * np.pi * f0 * 3.01 * t) * 0.15 * np.exp(-t * 12))

    mixed = bell * 0.75
    sf.write(str(path), mixed.astype(np.float32), SAMPLE_RATE)


if __name__ == "__main__":
    generate_all()
