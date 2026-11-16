"""Generate candidate assessment feedback tones for the audition page."""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 24_000
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "static" / "tone-options"


def add_note(buffer: list[float], start: float, note: list[float]) -> None:
    offset = int(start * SAMPLE_RATE)
    for index, value in enumerate(note):
        target = offset + index
        if 0 <= target < len(buffer):
            buffer[target] += value


def normalize(buffer: list[float], peak: float = 0.90) -> list[float]:
    if not buffer:
        return buffer
    mean = sum(buffer) / len(buffer)
    buffer = [value - mean for value in buffer]
    highest = max(abs(value) for value in buffer)
    if highest <= 0:
        return buffer
    scale = (32767 * peak) / highest
    fade = int(SAMPLE_RATE * 0.012)
    result: list[float] = []
    total = len(buffer)
    for index, value in enumerate(buffer):
        envelope = 1.0
        if index < fade:
            envelope = index / fade
        elif index >= total - fade:
            envelope = (total - index) / fade
        result.append(value * scale * envelope)
    return result


def write_wav(name: str, buffer: list[float]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    samples = [max(-32768, min(32767, round(value))) for value in buffer]
    with wave.open(str(OUTPUT_DIR / name), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    duration = len(samples) / SAMPLE_RATE
    peak = max(abs(value) for value in samples) if samples else 0
    print(f"{name:26s} {duration:4.2f}s peak={peak}")


def marimba_note(frequency: float, duration: float = 0.80) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.0015)) * math.exp(-7.0 * time)
        value = (
            math.sin(2 * math.pi * frequency * time)
            + 0.22
            * math.sin(2 * math.pi * frequency * 4 * time)
            * math.exp(-18.0 * time)
            + 0.04
            * math.sin(2 * math.pi * frequency * 7 * time)
            * math.exp(-26.0 * time)
        )
        result.append(value * envelope)
    return result


def marimba(first: float, second: float) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.05)
    add_note(buffer, 0.0, marimba_note(first))
    add_note(buffer, 0.22, marimba_note(second))
    return buffer


def pluck_note(frequency: float, duration: float = 1.05) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = min(1.0, time / 0.0025) * math.exp(-2.1 * time)
        value = 0.0
        for harmonic in range(1, 7):
            value += (
                (1.0 / harmonic**1.1)
                * math.sin(2 * math.pi * frequency * harmonic * time)
                * math.exp(-(0.65 + 0.45 * harmonic) * time)
            )
        result.append(value * envelope)
    return result


def harp(first: float, second: float) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.05)
    add_note(buffer, 0.0, pluck_note(first))
    add_note(buffer, 0.22, pluck_note(second))
    return buffer


def piano_note(
    frequency: float, duration: float = 1.55, level: float = 1.0
) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        attack = min(1.0, time / 0.004)
        value = 0.0
        for harmonic in range(1, 9):
            harmonic_frequency = frequency * harmonic * math.sqrt(
                1.0 + 0.0004 * harmonic * harmonic
            )
            value += (
                (1.0 / harmonic**1.6)
                * math.sin(2 * math.pi * harmonic_frequency * time)
                * math.exp(-(1.0 + 0.55 * harmonic) * time)
            )
        result.append(value * attack * level)
    return result


def piano_chord(frequencies: tuple[float, ...]) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.60)
    for frequency in frequencies:
        add_note(buffer, 0.0, piano_note(frequency, level=0.9))
    return buffer


def pad_note(
    frequency: float, duration: float = 1.40, detune: float = 0.0
) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    actual = frequency * (1.0 + detune)
    for index in range(count):
        time = index / SAMPLE_RATE
        attack = min(1.0, time / 0.18)
        if time < 0.72:
            release = 1.0
        else:
            release = max(0.0, 1.0 - (time - 0.72) / 0.58)
        envelope = attack * release
        value = (
            math.sin(2 * math.pi * actual * time)
            + 0.08 * math.sin(2 * math.pi * actual * 2 * time)
        )
        result.append(value * envelope)
    return result


def pad_chord(frequencies: tuple[float, ...]) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.45)
    for index, frequency in enumerate(frequencies):
        add_note(buffer, 0.0, pad_note(frequency, detune=0.0015 * (index - 1)))
    return buffer


def water_drop(
    start_frequency: float,
    end_frequency: float,
    duration: float = 0.50,
) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    phase = 0.0
    for index in range(count):
        time = index / SAMPLE_RATE
        frequency = end_frequency + (
            start_frequency - end_frequency
        ) * math.exp(-time / 0.045)
        phase += 2 * math.pi * frequency / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.003)) * math.exp(-9.0 * time)
        value = (
            math.sin(phase) + 0.04 * math.sin(2 * phase)
        ) * envelope
        result.append(value)
    return result


def water(first_high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 0.95)
    if first_high:
        add_note(buffer, 0.0, water_drop(560.0, 280.0))
        add_note(buffer, 0.28, water_drop(500.0, 250.0))
    else:
        add_note(buffer, 0.0, water_drop(360.0, 180.0, duration=0.62))
    return buffer


def kalimba_note(frequency: float, duration: float = 0.95) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = min(1.0, time / 0.005) * math.exp(-4.2 * time)
        value = (
            math.sin(2 * math.pi * frequency * time)
            + 0.18
            * math.sin(2 * math.pi * frequency * 3 * time)
            * math.exp(-7.0 * time)
            + 0.06
            * math.sin(2 * math.pi * frequency * 5 * time)
            * math.exp(-10.0 * time)
        )
        result.append(value * envelope)
    return result


def kalimba(first: float, second: float) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.10)
    add_note(buffer, 0.0, kalimba_note(first))
    add_note(buffer, 0.24, kalimba_note(second))
    return buffer


def music_box_note(frequency: float, duration: float = 0.90) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.0012)) * math.exp(-6.5 * time)
        value = (
            math.sin(2 * math.pi * frequency * time)
            + 0.30
            * math.sin(2 * math.pi * frequency * 3 * time)
            * math.exp(-14.0 * time)
            + 0.10
            * math.sin(2 * math.pi * frequency * 5 * time)
            * math.exp(-20.0 * time)
        )
        result.append(value * envelope)
    return result


def music_box(first: float, second: float) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.05)
    add_note(buffer, 0.0, music_box_note(first))
    add_note(buffer, 0.24, music_box_note(second))
    return buffer


def vibraphone_note(frequency: float, duration: float = 1.25) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        tremolo = 0.78 + 0.22 * math.sin(2 * math.pi * 5.5 * time)
        envelope = (1.0 - math.exp(-time / 0.006)) * math.exp(-2.2 * time)
        value = (
            math.sin(2 * math.pi * frequency * time)
            + 0.12
            * math.sin(2 * math.pi * frequency * 4 * time)
            * math.exp(-7.0 * time)
        )
        result.append(value * envelope * tremolo)
    return result


def arpeggio(notes: tuple[float, float, float]) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.20)
    for start, frequency in zip((0.0, 0.13, 0.26), notes):
        add_note(buffer, start, marimba_note(frequency, duration=0.85))
    return buffer


def woodblock_tap(frequency: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    duration = 0.22
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        attack = 1.0 - math.exp(-time / 0.001)
        noise = rng.uniform(-1.0, 1.0) * math.exp(-55.0 * time)
        body = (
            math.sin(2 * math.pi * frequency * time)
            + 0.35 * math.sin(2 * math.pi * frequency * 1.8 * time)
        ) * math.exp(-28.0 * time)
        result.append((0.35 * noise + body) * attack)
    return result


def woodblock(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 0.55)
    if high:
        add_note(buffer, 0.0, woodblock_tap(720.0, 21))
        add_note(buffer, 0.16, woodblock_tap(820.0, 22))
    else:
        add_note(buffer, 0.0, woodblock_tap(480.0, 23))
    return buffer


def main() -> None:
    candidates = {
        "01-marimba": (marimba(261.63, 392.00), marimba(392.00, 261.63)),
        "02-harp": (
            harp(261.63, 392.00),
            harp(392.00, 261.63),
        ),
        "03-piano": (
            piano_chord((261.63, 329.63, 392.00)),
            piano_chord((220.00, 261.63, 329.63)),
        ),
        "04-pad": (
            pad_chord((261.63, 329.63, 392.00)),
            pad_chord((220.00, 261.63, 329.63)),
        ),
        "05-water": (water(True), water(False)),
        "06-kalimba": (
            kalimba(329.63, 392.00),
            kalimba(392.00, 329.63),
        ),
        "07-music-box": (
            music_box(329.63, 392.00),
            music_box(392.00, 329.63),
        ),
        "08-vibraphone": (
            vibraphone_note(392.00),
            vibraphone_note(329.63),
        ),
        "09-arpeggio": (
            arpeggio((261.63, 329.63, 392.00)),
            arpeggio((392.00, 329.63, 261.63)),
        ),
        "10-woodblock": (woodblock(True), woodblock(False)),
    }
    for name, (high, low) in candidates.items():
        write_wav(f"{name}-high.wav", normalize(high))
        write_wav(f"{name}-low.wav", normalize(low))


if __name__ == "__main__":
    main()
