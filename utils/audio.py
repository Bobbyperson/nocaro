import threading
import uuid

import discord
import numpy as np


class MixerAudioSource(discord.AudioSource):
    def __init__(self):
        self.sources = {}
        self.lock = threading.Lock()
        self.frame_size = 3840  # stereo, 20ms at 48kHz

    def add_source(self, source_id, source):
        with self.lock:
            self.sources[source_id] = source

    def remove_source(self, source_id):
        with self.lock:
            if source_id in self.sources:
                del self.sources[source_id]

    def read(self):
        with self.lock:
            if not self.sources:
                return bytes([0] * self.frame_size)

            frames = []
            remove_list = []
            for source_id, source in list(self.sources.items()):
                try:
                    data = source.read()
                    if data:
                        # Ensure data is the correct length
                        if len(data) < self.frame_size:
                            data += bytes([0] * (self.frame_size - len(data)))
                        # Convert data to numpy array
                        audio_frame = np.frombuffer(data, dtype=np.int16)
                        frames.append(audio_frame)
                    else:
                        remove_list.append(source_id)
                except Exception as e:
                    print(f"Error reading from source {source_id}: {e}")
                    remove_list.append(source_id)

            for source_id in remove_list:
                del self.sources[source_id]

            if not frames:
                return bytes([0] * self.frame_size)

            # Sum the frames
            mixed_frame = np.sum(frames, axis=0)

            # Avoid clipping by normalizing the mixed audio
            max_int16 = np.iinfo(np.int16).max
            min_int16 = np.iinfo(np.int16).min
            mixed_frame = np.clip(mixed_frame, min_int16, max_int16).astype(np.int16)

            return mixed_frame.tobytes()

    def is_opus(self):
        return False


async def join(ctx) -> bool:
    """Join the voice channel of the user."""
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        return True
    return False


async def leave(ctx) -> bool:
    """Disconnect from the voice channel."""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        return True
    return False


async def play(ctx, filename) -> str | None:
    """Play an audio file in the voice channel."""
    if ctx.voice_client:
        if not hasattr(ctx.voice_client, "mixer"):
            ctx.voice_client.mixer = MixerAudioSource()
            ctx.voice_client.play(ctx.voice_client.mixer)
        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(filename, options="-vn")  # No video
            )
            source_id = str(uuid.uuid4())
            ctx.voice_client.mixer.add_source(source_id, source)
            return source_id
        except Exception as e:
            await ctx.send(f"Error playing `{filename}`: {e}")
            return None
    return None


async def stop(ctx, source_id) -> bool:
    """Stop an audio source by its ID."""
    if ctx.voice_client and hasattr(ctx.voice_client, "mixer"):
        ctx.voice_client.mixer.remove_source(source_id)
        return True
    return False
