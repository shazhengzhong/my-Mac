"""Import CC0 interface sounds from Kenney for the tone audition page.

Source: https://kenney.nl/assets/interface-sounds (CC0 1.0).
The source directory path can be passed as the first argument; it defaults to
the extraction directory used during the initial audition build.
"""

from __future__ import annotations

import shutil
import struct
import sys
import wave
from pathlib import Path

SAMPLE_RATE = 24_000
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "static" / "tone-options"
DEFAULT_SOURCE = Path(
    "/tmp/kenney-interface-sounds/addons/kenney_interface_sounds"
)

PAIRS = [
    ("43", "confirmation_001", "error_001"),
    ("44", "confirmation_002", "error_002"),
    ("45", "confirmation_003", "error_003"),
    ("46", "confirmation_004", "error_004"),
    ("47", "glass_001", "error_005"),
    ("48", "glass_002", "error_006"),
    ("49", "glass_003", "error_007"),
    ("50", "glass_004", "error_008"),
    ("51", "glass_005", "LOW:glass_005"),
    ("52", "glass_006", "LOW:glass_006"),
    ("53", "pluck_001", "LOW:pluck_001"),
    ("54", "pluck_002", "LOW:pluck_002"),
    ("55", "select_003", "LOW:select_003"),
    ("56", "select_004", "LOW:select_004"),
    ("57", "select_005", "LOW:select_005"),
    ("58", "switch_001", "LOW:switch_001"),
    ("59", "switch_002", "LOW:switch_002"),
    ("60", "bong_001", "LOW:bong_001"),
    ("61", "drop_001", "LOW:drop_001"),
    ("62", "drop_002", "LOW:drop_002"),
]


def read_wav(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(f"{path} is not 16-bit PCM")
        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
        values = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    if channels == 1:
        return [float(value) for value in values], sample_rate
    mono: list[float] = []
    for index in range(0, len(values), channels):
        frame = values[index : index + channels]
        mono.append(sum(frame) / len(frame))
    return mono, sample_rate


def resample(
    values: list[float], source_rate: int, speed: float = 1.0
) -> list[float]:
    source_step = source_rate / SAMPLE_RATE * speed
    count = int(len(values) / source_step)
    result: list[float] = []
    for index in range(count):
        position = index * source_step
        base = int(position)
        fraction = position - base
        left = values[base]
        right = values[min(base + 1, len(values) - 1)]
        result.append(left * (1 - fraction) + right * fraction)
    return result


def write_wav(path: Path, values: list[float], fade_ms: float = 2.0) -> None:
    fade = max(1, int(SAMPLE_RATE * fade_ms / 1000))
    for index in range(min(fade, len(values))):
        values[index] *= index / fade
    for index in range(min(fade, len(values))):
        values[len(values) - 1 - index] *= index / fade
    peak = max(abs(value) for value in values) or 1.0
    scale = (32767 * 0.90) / peak
    samples = [
        max(-32768, min(32767, round(value * scale))) for value in values
    ]
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.is_dir():
        raise SystemExit(f"Kenney source directory not found: {source}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for number, high_name, low_name in PAIRS:
        high_values, high_rate = read_wav(source / f"{high_name}.wav")
        write_wav(
            OUTPUT_DIR
            / f"{number}-kenney-{high_name.replace('_', '-')}-high.wav",
            resample(high_values, high_rate),
        )
        is_low = low_name.startswith("LOW:")
        base_name = low_name[4:] if is_low else low_name
        low_values, low_rate = read_wav(source / f"{base_name}.wav")
        speed = 2 ** (6 / 12) if is_low else 1.0
        write_wav(
            OUTPUT_DIR
            / f"{number}-kenney-{base_name.replace('_', '-')}-low.wav",
            resample(low_values, low_rate, speed=speed),
        )
    license_path = source.parent.parent / "LICENSE.txt"
    if license_path.exists():
        shutil.copyfile(license_path, OUTPUT_DIR / "KENNEY-LICENSE.txt")
    print(f"Imported {len(PAIRS)} Kenney pairs into {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
