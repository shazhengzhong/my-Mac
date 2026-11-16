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
    fade = int(SAMPLE_RATE * 0.012)
    total = len(buffer)
    faded: list[float] = []
    for index, value in enumerate(buffer):
        envelope = 1.0
        if index < fade:
            envelope = index / fade
        elif index >= total - fade:
            envelope = (total - index) / fade
        faded.append((value - mean) * envelope)
    highest = max(abs(value) for value in faded)
    if highest <= 0:
        return faded
    scale = (32767 * peak) / highest
    return [value * scale for value in faded]


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


def guitar_note(frequency: float, seed: int, duration: float = 0.95) -> list[float]:
    rng = random.Random(seed)
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        attack = min(1.0, time / 0.0015)
        noise = rng.uniform(-1.0, 1.0) * math.exp(-60.0 * time)
        value = 0.18 * noise
        for harmonic in range(1, 8):
            value += (
                (1.0 / harmonic)
                * math.sin(2 * math.pi * frequency * harmonic * time)
                * math.exp(-(1.4 + 0.55 * harmonic) * time)
            )
        result.append(value * attack)
    return result


def guitar(first: float, second: float, seed: int) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.10)
    add_note(buffer, 0.0, guitar_note(first, seed))
    add_note(buffer, 0.22, guitar_note(second, seed + 1))
    return buffer


def handpan_note(frequency: float, duration: float = 1.45) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    partials = ((1.0, 1.00, 1.4), (2.0, 0.48, 2.0), (2.9, 0.24, 2.8), (4.2, 0.12, 3.8))
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.012)) * math.exp(-1.7 * time)
        value = 0.0
        for ratio, amplitude, decay in partials:
            value += amplitude * math.sin(
                2 * math.pi * frequency * ratio * time
            ) * math.exp(-decay * time)
        result.append(value * envelope)
    return result


def singing_bowl(frequency: float, duration: float = 1.65) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    partials = ((1.0, 1.0, 1.1), (1.5, 0.35, 1.5), (2.0, 0.18, 2.0), (2.7, 0.08, 2.6))
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.05)) * math.exp(-1.6 * time)
        value = 0.0
        for ratio, amplitude, decay in partials:
            beat = 0.35 * math.sin(2 * math.pi * 0.7 * time)
            value += amplitude * math.sin(
                2 * math.pi * frequency * ratio * time + beat
            ) * math.exp(-decay * time)
        result.append(value * envelope)
    return result


def bubble_drop(start: float, end: float, duration: float = 0.42) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    phase = 0.0
    for index in range(count):
        time = index / SAMPLE_RATE
        frequency = start + (end - start) * (1.0 - math.exp(-time / 0.04))
        phase += 2 * math.pi * frequency / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.003)) * math.exp(-8.5 * time)
        result.append(
            (math.sin(phase) + 0.04 * math.sin(2 * phase)) * envelope
        )
    return result


def bubbles(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 0.90)
    if high:
        add_note(buffer, 0.0, bubble_drop(220.0, 540.0))
        add_note(buffer, 0.28, bubble_drop(250.0, 580.0))
    else:
        add_note(buffer, 0.0, bubble_drop(150.0, 380.0, duration=0.52))
    return buffer


def shaker_hit(seed: int, duration: float = 0.22) -> list[float]:
    rng = random.Random(seed)
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    previous = 0.0
    for index in range(count):
        time = index / SAMPLE_RATE
        noise = rng.uniform(-1.0, 1.0)
        high_pass = noise - previous * 0.92
        previous = noise
        envelope = (1.0 - math.exp(-time / 0.0015)) * math.exp(-30.0 * time)
        result.append(high_pass * envelope)
    return result


def shaker(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 0.60)
    if high:
        add_note(buffer, 0.0, shaker_hit(31))
        add_note(buffer, 0.18, shaker_hit(32))
    else:
        add_note(buffer, 0.0, shaker_hit(33, duration=0.30))
    return buffer


def soft_drum(frequency: float, duration: float = 0.45) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    phase = 0.0
    for index in range(count):
        time = index / SAMPLE_RATE
        phase += 2 * math.pi * (frequency * math.exp(-1.8 * time)) / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.002)) * math.exp(-9.0 * time)
        result.append(math.sin(phase) * envelope)
    return result


def soft_drums(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 0.65)
    if high:
        add_note(buffer, 0.0, soft_drum(180.0))
        add_note(buffer, 0.20, soft_drum(155.0))
    else:
        add_note(buffer, 0.0, soft_drum(120.0, duration=0.55))
    return buffer


def wind_chime_note(frequency: float, seed: int, duration: float = 1.35) -> list[float]:
    rng = random.Random(seed)
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    partials = ((1.0, 1.0, 1.2), (2.4, 0.30, 2.2), (3.7, 0.12, 3.0), (5.1, 0.05, 3.8))
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.008)) * math.exp(-2.0 * time)
        value = 0.0
        for ratio, amplitude, decay in partials:
            value += amplitude * math.sin(
                2 * math.pi * frequency * ratio * time
            ) * math.exp(-decay * time)
        result.append(value * envelope)
    return result


def wind_chime(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.45)
    if high:
        add_note(buffer, 0.0, wind_chime_note(392.0, 41))
        add_note(buffer, 0.20, wind_chime_note(329.63, 42))
    else:
        add_note(buffer, 0.0, wind_chime_note(329.63, 43))
    return buffer


def whistle(frequency: float, duration: float = 0.80) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        vibrato = 0.012 * math.sin(2 * math.pi * 4.8 * time)
        envelope = min(1.0, time / 0.04) * math.exp(-2.8 * time)
        value = math.sin(2 * math.pi * frequency * (1 + vibrato) * time)
        result.append(value * envelope)
    return result


def whistles(first: float, second: float) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.10)
    add_note(buffer, 0.0, whistle(first))
    add_note(buffer, 0.28, whistle(second))
    return buffer


def music_box_arpeggio(notes: tuple[float, float, float]) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.25)
    for start, frequency in zip((0.0, 0.13, 0.26), notes):
        add_note(buffer, start, music_box_note(frequency, duration=0.95))
    return buffer


def single_note(note: list[float], duration: float) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * duration)
    add_note(buffer, 0.0, note)
    return buffer


def harp_arpeggio(notes: tuple[float, float, float]) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.20)
    for start, frequency in zip((0.0, 0.10, 0.20), notes):
        add_note(buffer, start, pluck_note(frequency, duration=1.0))
    return buffer


def synth_note(frequency: float, duration: float = 0.55) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = min(1.0, time / 0.03) * math.exp(-3.5 * time)
        result.append(
            (
                math.sin(2 * math.pi * frequency * time)
                + 0.06 * math.sin(2 * math.pi * frequency * 2 * time)
            )
            * envelope
        )
    return result


def synth_arpeggio(notes: tuple[float, float, float]) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.05)
    for start, frequency in zip((0.0, 0.12, 0.24), notes):
        add_note(buffer, start, synth_note(frequency))
    return buffer


def service_bell_note(frequency: float, duration: float = 0.58) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = (1.0 - math.exp(-time / 0.0015)) * math.exp(-9.0 * time)
        value = (
            math.sin(2 * math.pi * frequency * time)
            + 0.18
            * math.sin(2 * math.pi * frequency * 2.7 * time)
            * math.exp(-14.0 * time)
            + 0.06
            * math.sin(2 * math.pi * frequency * 4.2 * time)
            * math.exp(-20.0 * time)
        )
        result.append(value * envelope)
    return result


def service_bell(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 0.72)
    if high:
        add_note(buffer, 0.0, service_bell_note(392.00))
        add_note(buffer, 0.13, service_bell_note(392.00))
    else:
        add_note(buffer, 0.0, service_bell_note(329.63, duration=0.68))
    return buffer


def wooden_fish(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 0.62)
    if high:
        add_note(buffer, 0.0, woodblock_tap(480.0, 61))
        add_note(buffer, 0.16, woodblock_tap(540.0, 62))
    else:
        add_note(buffer, 0.0, woodblock_tap(330.0, 63))
    return buffer


def doorbell_note(frequency: float, duration: float = 0.82) -> list[float]:
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = min(1.0, time / 0.015) * math.exp(-2.8 * time)
        value = (
            math.sin(2 * math.pi * frequency * time)
            + 0.05 * math.sin(2 * math.pi * frequency * 2 * time)
        )
        result.append(value * envelope)
    return result


def doorbell(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.15)
    first, second = (
        (220.00, 293.66) if high else (293.66, 220.00)
    )
    add_note(buffer, 0.0, doorbell_note(first))
    add_note(buffer, 0.30, doorbell_note(second))
    return buffer


def soft_click_tap(frequency: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    duration = 0.12
    result: list[float] = []
    count = int(SAMPLE_RATE * duration)
    for index in range(count):
        time = index / SAMPLE_RATE
        noise = rng.uniform(-1.0, 1.0)
        envelope = (1.0 - math.exp(-time / 0.001)) * math.exp(-55.0 * time)
        body = math.sin(2 * math.pi * frequency * time) * math.exp(-38.0 * time)
        result.append((0.22 * noise + body) * envelope)
    return result


def soft_clicks(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 0.45)
    if high:
        add_note(buffer, 0.0, soft_click_tap(820.0, 71))
        add_note(buffer, 0.13, soft_click_tap(920.0, 72))
    else:
        add_note(buffer, 0.0, soft_click_tap(520.0, 73))
    return buffer


def water_marimba(high: bool) -> list[float]:
    buffer = [0.0] * int(SAMPLE_RATE * 1.10)
    if high:
        add_note(buffer, 0.0, water_drop(620.0, 310.0))
        add_note(buffer, 0.08, marimba_note(392.00))
    else:
        add_note(buffer, 0.0, water_drop(330.0, 165.0, duration=0.60))
        add_note(buffer, 0.10, marimba_note(261.63))
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
        "13-guitar": (
            guitar(261.63, 392.00, 51),
            guitar(392.00, 261.63, 53),
        ),
        "14-piano-single": (
            piano_note(261.63, duration=1.55, level=1.0),
            piano_note(220.00, duration=1.65, level=1.0),
        ),
        "15-handpan": (
            handpan_note(392.00),
            handpan_note(329.63),
        ),
        "16-singing-bowl": (
            singing_bowl(329.63),
            singing_bowl(261.63),
        ),
        "17-bubble": (bubbles(True), bubbles(False)),
        "18-shaker": (shaker(True), shaker(False)),
        "19-soft-drum": (soft_drums(True), soft_drums(False)),
        "20-wind-chime": (wind_chime(True), wind_chime(False)),
        "21-whistle": (
            whistles(261.63, 329.63),
            whistles(329.63, 261.63),
        ),
        "22-music-box-arpeggio": (
            music_box_arpeggio((261.63, 329.63, 392.00)),
            music_box_arpeggio((392.00, 329.63, 261.63)),
        ),
        "23-marimba-third": (
            marimba(261.63, 329.63),
            marimba(329.63, 261.63),
        ),
        "24-marimba-fifth": (
            marimba(220.00, 329.63),
            marimba(329.63, 220.00),
        ),
        "25-music-box-single": (
            single_note(music_box_note(329.63), 0.95),
            single_note(music_box_note(261.63), 0.95),
        ),
        "26-piano-double": (
            piano_chord((261.63, 329.63)),
            piano_chord((220.00, 261.63)),
        ),
        "27-harp-pentatonic": (
            harp_arpeggio((261.63, 293.66, 392.00)),
            harp_arpeggio((392.00, 293.66, 261.63)),
        ),
        "28-kalimba-fifth": (
            kalimba(261.63, 392.00),
            kalimba(392.00, 261.63),
        ),
        "29-vibraphone-short": (
            single_note(vibraphone_note(392.00, duration=0.70), 0.80),
            single_note(vibraphone_note(329.63, duration=0.75), 0.85),
        ),
        "30-synth-arpeggio": (
            synth_arpeggio((261.63, 329.63, 392.00)),
            synth_arpeggio((392.00, 329.63, 261.63)),
        ),
        "31-service-bell": (service_bell(True), service_bell(False)),
        "32-wooden-fish": (wooden_fish(True), wooden_fish(False)),
        "33-doorbell": (doorbell(True), doorbell(False)),
        "34-soft-woodblock": (
            single_note(woodblock_tap(560.0, 81), 0.55),
            single_note(woodblock_tap(380.0, 82), 0.55),
        ),
        "35-soft-click": (soft_clicks(True), soft_clicks(False)),
        "36-water-marimba": (water_marimba(True), water_marimba(False)),
    }
    for name, (high, low) in candidates.items():
        write_wav(f"{name}-high.wav", normalize(high))
        write_wav(f"{name}-low.wav", normalize(low))


if __name__ == "__main__":
    main()
