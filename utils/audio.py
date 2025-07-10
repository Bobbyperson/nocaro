import threading
import time
import uuid

import discord
import numpy as np
from mutagen import File as MutagenFile


class MixerAudioSource(discord.AudioSource):
    FRAME_SIZE = 3840  # 20 ms of 48 kHz stereo, 16-bit signed
    FRAMES_PER_SEC = 1000 // 20  # 50 packets per second

    def __init__(self, master_volume: float = 1.0):
        self.sources: dict[str, discord.PCMVolumeTransformer] = {}
        # Track meta: {id: {"start": float, "duration": float}}
        self._track_meta: dict[str, dict[str, float]] = {}
        self.lock = threading.Lock()

        self.master_volume: float = master_volume
        self._m_target: float = master_volume
        self._m_step: float = 0.0
        self._m_steps_left: int = 0

    # fading helpers
    @staticmethod
    def _init_fade_attrs(src: discord.PCMVolumeTransformer, volume: float):
        src.volume = volume
        src._t_target = volume
        src._t_step = 0.0
        src._t_steps_left = 0

    @staticmethod
    def _advance_track_fade(src: discord.PCMVolumeTransformer):
        if getattr(src, "_t_steps_left", 0):
            src.volume += src._t_step
            src._t_steps_left -= 1
            if src._t_steps_left == 0:
                src.volume = src._t_target

    def _advance_master_fade(self):
        if self._m_steps_left:
            self.master_volume += self._m_step
            self._m_steps_left -= 1
            if self._m_steps_left == 0:
                self.master_volume = self._m_target

    # track controls
    def add_source(
        self,
        source_id: str,
        source: discord.AudioSource,
        *,
        volume: float = 1.0,
        duration: float | None = None,
    ) -> None:
        if not isinstance(source, discord.PCMVolumeTransformer):
            source = discord.PCMVolumeTransformer(source, volume=volume)
        self._init_fade_attrs(source, volume)
        with self.lock:
            self.sources[source_id] = source
            self._track_meta[source_id] = {
                "start": time.monotonic(),
                "duration": float("inf") if duration is None else duration,
            }

    def remove_source(self, source_id: str) -> None:
        with self.lock:
            self.sources.pop(source_id, None)
            self._track_meta.pop(source_id, None)

    def set_source_volume(
        self, source_id: str, volume: float, *, ramp_sec: float = 0.0
    ) -> bool:
        with self.lock:
            src = self.sources.get(source_id)
            if src is None:
                return False
            if ramp_sec <= 0:
                self._init_fade_attrs(src, volume)
                return True
            steps = max(1, int(ramp_sec * self.FRAMES_PER_SEC))
            src._t_target = volume
            src._t_step = (volume - src.volume) / steps
            src._t_steps_left = steps
            return True

    # master controls
    def set_master_volume(self, volume: float, *, ramp_sec: float = 0.0):
        volume = max(0.0, volume)
        if ramp_sec <= 0:
            self.master_volume = volume
            self._m_steps_left = 0
            self._m_target = volume
            return
        steps = max(1, int(ramp_sec * self.FRAMES_PER_SEC))
        self._m_target = volume
        self._m_step = (volume - self.master_volume) / steps
        self._m_steps_left = steps

    def get_time_left(self, source_id: str) -> float | None:
        with self.lock:
            meta = self._track_meta.get(source_id)
            if not meta:
                return None
            dur = meta["duration"]
            if dur == float("inf"):
                return None
            elapsed = time.monotonic() - meta["start"]
            return max(0.0, dur - elapsed)

    def read(self) -> bytes:
        with self.lock:
            self._advance_master_fade()
            if not self.sources:
                return bytes(self.FRAME_SIZE)

            frames: list[np.ndarray] = []
            dead: list[str] = []

            for sid, src in tuple(self.sources.items()):
                self._advance_track_fade(src)
                try:
                    data = src.read()
                    if not data:
                        dead.append(sid)
                        continue
                    if len(data) < self.FRAME_SIZE:
                        data += bytes(self.FRAME_SIZE - len(data))
                    frames.append(np.frombuffer(data, dtype=np.int16))
                except Exception as exc:
                    print(f"Source {sid} error: {exc}")
                    dead.append(sid)

            for sid in dead:
                self.sources.pop(sid, None)
                self._track_meta.pop(sid, None)

            if not frames:
                return bytes(self.FRAME_SIZE)

            mixed = np.sum(frames, axis=0, dtype=np.int32)
            mixed = (mixed * self.master_volume).astype(np.int32)
            mixed = np.clip(
                mixed, np.iinfo(np.int16).min, np.iinfo(np.int16).max
            ).astype(np.int16)
            return mixed.tobytes()

    def is_opus(self) -> bool:
        return False


async def join(ctx) -> bool:
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()
        return True
    return False


async def leave(ctx) -> bool:
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        return True
    return False


async def _ensure_mixer(ctx) -> MixerAudioSource:
    if not hasattr(ctx.voice_client, "mixer"):
        ctx.voice_client.mixer = MixerAudioSource()
        ctx.voice_client.play(ctx.voice_client.mixer)
    return ctx.voice_client.mixer


def _probe_duration(filename: str) -> float | None:
    m = MutagenFile(filename)
    if m is not None and getattr(m, "info", None) and hasattr(m.info, "length"):
        return float(m.info.length)
    return None


async def play(
    ctx,
    filename: str,
    *,
    vol: float = 1.0,
    repeat: bool = False,
) -> tuple[str, float | None] | tuple[None, None]:
    if not ctx.voice_client:
        return None, None
    try:
        duration = None if repeat else _probe_duration(filename)
        before_opts = "-stream_loop -1" if repeat else None
        ffmpeg = discord.FFmpegPCMAudio(
            filename,
            before_options=before_opts,
            options="-vn",
        )
        source_id = str(uuid.uuid4())
        mixer = await _ensure_mixer(ctx)
        mixer.add_source(source_id, ffmpeg, volume=vol, duration=duration)
        return source_id, duration
    except Exception as exc:
        await ctx.send(f"Error playing `{filename}`: {exc}")
        return None, None


async def stop(ctx, source_id: str) -> bool:
    if ctx.voice_client and hasattr(ctx.voice_client, "mixer"):
        ctx.voice_client.mixer.remove_source(source_id)
        return True
    return False


async def set_track_volume(
    ctx, source_id: str, volume: float, *, ramp_sec: float = 0.0
) -> bool:
    if ctx.voice_client and hasattr(ctx.voice_client, "mixer"):
        return ctx.voice_client.mixer.set_source_volume(
            source_id, volume, ramp_sec=ramp_sec
        )
    return False


async def set_master_volume(ctx, volume: float, *, ramp_sec: float = 0.0) -> bool:
    if ctx.voice_client and hasattr(ctx.voice_client, "mixer"):
        ctx.voice_client.mixer.set_master_volume(volume, ramp_sec=ramp_sec)
        return True
    return False


async def time_left(ctx, source_id: str) -> float | None:
    if ctx.voice_client and hasattr(ctx.voice_client, "mixer"):
        return ctx.voice_client.mixer.get_time_left(source_id)
    return None
