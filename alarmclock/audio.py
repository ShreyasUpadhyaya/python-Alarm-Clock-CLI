"""Tone synthesis and playback, standard library only.

Four named tones are generated at runtime into a temp WAV; none is bundled.
Playback goes through a ``Player`` protocol backed by a chain that degrades
from ``simpleaudio`` to an OS command-line player to a terminal bell plus a
printed banner, so the alarm always signals even with no audio stack at all.
"""

from __future__ import annotations

import array
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass, field
from typing import Protocol

_SAMPLE_RATE = 44_100
_AMPLITUDE = 0.62
_ATTACK = 0.008
_RELEASE = 0.040


@dataclass(frozen=True, slots=True)
class ToneSpec:
    """Parameters that make one tone audibly distinct from the others.

    ``freqs`` is the sequence of pitches stepped through within a single
    segment; ``segment`` is that segment's length in seconds; ``gap`` is the
    silence after it; ``repeat`` is how many times the segment+gap plays.
    ``tremolo_hz`` amplitude-modulates the whole segment when non-zero.
    """

    freqs: tuple[float, ...]
    segment: float
    gap: float
    repeat: int
    tremolo_hz: float = 0.0


TONES: dict[str, ToneSpec] = {
    "beep": ToneSpec(freqs=(880.0,), segment=0.18, gap=0.12, repeat=3),
    "chirp": ToneSpec(freqs=(1200.0, 1700.0), segment=0.09, gap=0.05, repeat=6),
    "rising": ToneSpec(
        freqs=(440.0, 554.37, 659.25, 880.0), segment=1.1, gap=0.25, repeat=2
    ),
    "pulse": ToneSpec(freqs=(660.0,), segment=1.4, gap=0.2, repeat=2, tremolo_hz=11.0),
}


def tone_names() -> list[str]:
    return list(TONES)


def render_tone(name: str, path: str) -> str:
    """Write tone ``name`` to ``path`` as a 16-bit mono WAV and return ``path``."""
    try:
        spec = TONES[name]
    except KeyError:
        raise ValueError(f"unknown tone {name!r}; choices: {', '.join(TONES)}") from None

    samples = _synthesize(spec)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(_pack(samples))
    return path


def render_tone_to_temp(name: str) -> str:
    fd, path = tempfile.mkstemp(prefix=f"alarmclock-{name}-", suffix=".wav")
    os.close(fd)
    try:
        return render_tone(name, path)
    except Exception:
        _unlink_quiet(path)
        raise


def _synthesize(spec: ToneSpec) -> array.array:
    seg = _segment(spec)
    gap = array.array("d", bytes(8 * int(_SAMPLE_RATE * spec.gap)))
    out = array.array("d")
    for _ in range(max(1, spec.repeat)):
        out.extend(seg)
        out.extend(gap)
    return out


def _segment(spec: ToneSpec) -> array.array:
    total = max(1, int(_SAMPLE_RATE * spec.segment))
    steps = len(spec.freqs)
    step_len = max(1, total // steps)
    buf = array.array("d", bytes(8 * total))

    phase = 0.0
    for i in range(total):
        freq = spec.freqs[min(i // step_len, steps - 1)]
        phase += 2.0 * math.pi * freq / _SAMPLE_RATE
        value = math.sin(phase)
        if spec.tremolo_hz:
            value *= 0.5 + 0.5 * math.sin(2.0 * math.pi * spec.tremolo_hz * i / _SAMPLE_RATE)
        buf[i] = value * _AMPLITUDE * _envelope(i, total)
    return buf


def _envelope(i: int, total: int) -> float:
    attack = max(1, int(_SAMPLE_RATE * _ATTACK))
    release = max(1, int(_SAMPLE_RATE * _RELEASE))
    if i < attack:
        return i / attack
    if i > total - release:
        return max(0.0, (total - i) / release)
    return 1.0


def _pack(samples: array.array) -> bytes:
    clamped = bytearray()
    for value in samples:
        v = int(max(-1.0, min(1.0, value)) * 32767)
        clamped += struct.pack("<h", v)
    return bytes(clamped)


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


class Player(Protocol):
    def play(self, path: str) -> None:
        """Start playing the WAV at ``path``. May return before it finishes."""
        ...

    def stop(self) -> None:
        """Stop any playback started by this player. A no-op if nothing plays."""
        ...


class SimpleAudioPlayer:
    name = "simpleaudio"

    def __init__(self) -> None:
        import simpleaudio  # noqa: F401  (probe; raises ImportError if absent)

        self._simpleaudio = simpleaudio
        self._play_obj = None

    def play(self, path: str) -> None:
        wave_obj = self._simpleaudio.WaveObject.from_wave_file(path)
        self._play_obj = wave_obj.play()

    def stop(self) -> None:
        if self._play_obj is not None:
            self._play_obj.stop()
            self._play_obj = None


class CommandLinePlayer:
    """Plays via whichever of ``afplay`` / ``paplay`` / ``aplay`` / ``winsound``
    is available on this OS."""

    name = "os-player"

    def __init__(self) -> None:
        self._winsound = None
        self._cmd: list[str] | None = None

        if sys.platform == "darwin" and shutil.which("afplay"):
            self._cmd = ["afplay"]
        elif sys.platform.startswith("linux"):
            for candidate in ("paplay", "aplay"):
                if shutil.which(candidate):
                    self._cmd = [candidate]
                    break
        elif sys.platform == "win32":
            import winsound

            self._winsound = winsound

        if self._cmd is None and self._winsound is None:
            raise BackendUnavailable("no command-line audio player found")

        self._proc: subprocess.Popen | None = None

    def play(self, path: str) -> None:
        if self._winsound is not None:
            self._winsound.PlaySound(
                path, self._winsound.SND_FILENAME | self._winsound.SND_ASYNC
            )
            return
        assert self._cmd is not None
        self._proc = subprocess.Popen(
            [*self._cmd, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self._winsound is not None:
            self._winsound.PlaySound(None, self._winsound.SND_PURGE)
            return
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None


class BannerPlayer:
    """Last resort: ring the terminal bell and print a visible banner. Always
    available, so the alarm never fails silently."""

    name = "banner"

    def play(self, path: str) -> None:
        sys.stderr.write("\a")
        sys.stderr.write("\n" + "=" * 44 + "\n")
        sys.stderr.write("  ALARM  (no audio backend; visual only)\n")
        sys.stderr.write("=" * 44 + "\n")
        sys.stderr.flush()

    def stop(self) -> None:
        return None


class NullPlayer:
    """Records calls, produces no sound. For tests only."""

    name = "null"

    def __init__(self) -> None:
        self.played: list[str] = []
        self.stops = 0

    def play(self, path: str) -> None:
        self.played.append(path)

    def stop(self) -> None:
        self.stops += 1


class BackendUnavailable(Exception):
    """A backend cannot run in this environment."""


_BACKEND_CHAIN = (SimpleAudioPlayer, CommandLinePlayer, BannerPlayer)


def select_player(
    chain: tuple[type, ...] = _BACKEND_CHAIN,
) -> Player:
    """Return the first backend in ``chain`` that constructs cleanly.

    ``ImportError`` (module missing) and ``BackendUnavailable`` (binary
    missing) fall through to the next; anything else propagates.
    """
    last_error: Exception | None = None
    for backend in chain:
        try:
            return backend()
        except (ImportError, BackendUnavailable) as exc:
            last_error = exc
    raise RuntimeError(f"no audio backend available: {last_error}")


@dataclass
class Speaker:
    """Binds a chosen ``Player`` to a tone source: a named built-in tone or a
    user-supplied WAV file."""

    player: Player
    _temp_paths: list[str] = field(default_factory=list)

    def play_tone(self, name: str) -> None:
        path = render_tone_to_temp(name)
        self._temp_paths.append(path)
        self.player.play(path)

    def play_file(self, path: str) -> None:
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        self.player.play(path)

    def stop(self) -> None:
        self.player.stop()

    def cleanup(self) -> None:
        while self._temp_paths:
            _unlink_quiet(self._temp_paths.pop())
