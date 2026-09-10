from __future__ import annotations

import wave

import pytest

from alarmclock import audio
from alarmclock.audio import (
    BackendUnavailable,
    BannerPlayer,
    NullPlayer,
    Speaker,
    render_tone,
    select_player,
    tone_names,
)


# --- tone generation (no playback) -----------------------------------------

def test_four_named_tones_exist() -> None:
    assert set(tone_names()) == {"beep", "chirp", "rising", "pulse"}


def test_render_tone_writes_a_valid_wav(tmp_path) -> None:
    path = tmp_path / "beep.wav"
    render_tone("beep", str(path))

    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 44_100
        assert wav.getnframes() > 0


def test_tones_are_genuinely_different(tmp_path) -> None:
    frames = {}
    for name in tone_names():
        path = tmp_path / f"{name}.wav"
        render_tone(name, str(path))
        with wave.open(str(path), "rb") as wav:
            frames[name] = (wav.getnframes(), wav.readframes(wav.getnframes()))

    payloads = [payload for _n, payload in frames.values()]
    assert len(set(payloads)) == len(payloads)


def test_envelope_ramps_from_silence(tmp_path) -> None:
    path = tmp_path / "beep.wav"
    render_tone("beep", str(path))
    with wave.open(str(path), "rb") as wav:
        head = wav.readframes(4)
    assert head[:2] == b"\x00\x00"  # first sample sits at zero, no click


def test_unknown_tone_raises() -> None:
    with pytest.raises(ValueError):
        render_tone("foghorn", "unused.wav")


# --- backend selection and fallthrough (no playback) ----------------------

class _OKBackend:
    name = "ok"

    def __init__(self) -> None:
        self.name = "ok"

    def play(self, path: str) -> None: ...
    def stop(self) -> None: ...


class _ImportErrorBackend:
    def __init__(self) -> None:
        raise ImportError("no such module")

    def play(self, path: str) -> None: ...
    def stop(self) -> None: ...


class _UnavailableBackend:
    def __init__(self) -> None:
        raise BackendUnavailable("binary missing")

    def play(self, path: str) -> None: ...
    def stop(self) -> None: ...


def test_selects_first_constructible_backend() -> None:
    player = select_player((_OKBackend, BannerPlayer))
    assert player.name == "ok"


def test_falls_through_import_error_then_backend_unavailable() -> None:
    player = select_player(
        (_ImportErrorBackend, _UnavailableBackend, _OKBackend)
    )
    assert player.name == "ok"


def test_banner_is_the_guaranteed_tail() -> None:
    player = select_player((_ImportErrorBackend, _UnavailableBackend, BannerPlayer))
    assert isinstance(player, BannerPlayer)


def test_no_backend_at_all_raises_runtimeerror() -> None:
    with pytest.raises(RuntimeError):
        select_player((_ImportErrorBackend, _UnavailableBackend))


def test_unexpected_construction_error_propagates() -> None:
    class _Boom:
        def __init__(self) -> None:
            raise KeyError("not an ImportError or BackendUnavailable")

        def play(self, path: str) -> None: ...
        def stop(self) -> None: ...

    with pytest.raises(KeyError):
        select_player((_Boom, BannerPlayer))


# --- Speaker with NullPlayer (no playback) --------------------------------

def test_speaker_plays_a_tone_through_the_player(tmp_path) -> None:
    null = NullPlayer()
    speaker = Speaker(null)

    speaker.play_tone("chirp")

    assert len(null.played) == 1
    assert null.played[0].endswith(".wav")
    speaker.cleanup()


def test_speaker_rejects_a_missing_sound_file() -> None:
    speaker = Speaker(NullPlayer())
    with pytest.raises(FileNotFoundError):
        speaker.play_file("/no/such/file.wav")


def test_speaker_plays_a_user_wav(tmp_path) -> None:
    path = tmp_path / "custom.wav"
    render_tone("beep", str(path))
    null = NullPlayer()
    speaker = Speaker(null)

    speaker.play_file(str(path))

    assert null.played == [str(path)]


def test_speaker_stop_delegates_to_player() -> None:
    null = NullPlayer()
    Speaker(null).stop()
    assert null.stops == 1


def test_real_chain_resolves_to_something_on_this_host() -> None:
    player = select_player()
    assert player.name in {"simpleaudio", "os-player", "banner"}
