import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from shutil import which

import numpy as np


FINDER_SAFE_BINARY_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


def _existing_binary_dirs(binary_dirs):
    return tuple(directory for directory in binary_dirs if directory.is_dir())


def _bundled_binary_dirs():
    candidates = []
    env_dir = os.environ.get("HALA_FFMPEG_BIN_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        bundle_root = Path(getattr(sys, "_MEIPASS", executable_dir))
        candidates.append(bundle_root / "bin")
        candidates.append(executable_dir / "bin")

        # macOS .app layout: Contents/MacOS/<exe> -> Contents/Resources/bin.
        contents_dir = executable_dir.parent
        candidates.append(contents_dir / "Resources" / "bin")

    return tuple(candidates)


def _executable_candidates(executable):
    names = [executable]
    if not executable.lower().endswith(".exe"):
        names.append(f"{executable}.exe")
    return tuple(dict.fromkeys(names))


def _prepend_existing_binary_dirs_to_path(
    preferred_dirs=(),
    fallback_dirs=FINDER_SAFE_BINARY_DIRS,
):
    path_dirs = [directory for directory in os.environ.get("PATH", "").split(os.pathsep) if directory]
    front_additions = [
        str(directory)
        for directory in _existing_binary_dirs(preferred_dirs)
        if str(directory) not in path_dirs
    ]
    back_additions = [
        str(directory)
        for directory in _existing_binary_dirs(fallback_dirs)
        if str(directory) not in path_dirs and str(directory) not in front_additions
    ]

    updated_path = front_additions + path_dirs + back_additions
    if updated_path != path_dirs:
        os.environ["PATH"] = os.pathsep.join(updated_path)


def _find_executable(
    executable,
    preferred_dirs=(),
    fallback_dirs=FINDER_SAFE_BINARY_DIRS,
):
    for directory in _existing_binary_dirs(preferred_dirs):
        for executable_name in _executable_candidates(executable):
            candidate = directory / executable_name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

    found = which(executable)
    if found:
        return found

    for directory in _existing_binary_dirs(fallback_dirs):
        for executable_name in _executable_candidates(executable):
            candidate = directory / executable_name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

    return None


_prepend_existing_binary_dirs_to_path(_bundled_binary_dirs())


try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("WARNING: pydub not installed. MP3 support disabled.")
    print("Install: pip install pydub")

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False
    print("WARNING: soundfile not installed. WAV/FLAC reading disabled.")
    print("Install: pip install soundfile")

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    print("WARNING: sounddevice not installed. Audio playback disabled.")
    print("Install: pip install sounddevice")


class AudioManager:
    """
    Manages audio file loading, format conversion, and playback.
    Supports WAV, MP3, FLAC, and M4A formats.
    """
    
    def __init__(self):
        self.audio_data = None          # Numpy array of audio samples
        self.sample_rate = None          # Sample rate (Hz)
        self.duration = 0.0              # Duration in seconds
        self.num_channels = 1            # Number of channels
        self.file_path = None            # Original file path
        self.file_format = None          # Original format
        
        # Playback state
        self.is_playing = False
        self.playback_start_time = None  # Wall clock time when playback started
        self.playback_start_sample = 0   # Audio sample where playback started
        self.playback_end_sample = None  # Audio sample where bounded playback should stop
        self.stream = None               # sounddevice stream
        
        bundled_binary_dirs = _bundled_binary_dirs()
        # Finder-launched .app bundles do not reliably inherit the user's shell PATH.
        _prepend_existing_binary_dirs_to_path(bundled_binary_dirs)

        # Check FFmpeg availability for M4A support
        self.ffmpeg_path = _find_executable("ffmpeg", bundled_binary_dirs)
        self.ffprobe_path = _find_executable("ffprobe", bundled_binary_dirs)
        self.ffmpeg_available = self.ffmpeg_path is not None

        if PYDUB_AVAILABLE and self.ffmpeg_path:
            AudioSegment.converter = self.ffmpeg_path

        if not self.ffmpeg_available:
            print("WARNING: FFmpeg not found. M4A conversion will not work.")

    @staticmethod
    def _update_progress(progress_callback, value, message):
        if progress_callback:
            progress_callback(value, message)

    @staticmethod
    def _log_exception(prefix, error):
        print(f"ERROR {prefix}: {error}")
        traceback.print_exc()

    @staticmethod
    def _audiosegment_to_mono_float32(audio_segment):
        raw_samples = np.array(audio_segment.get_array_of_samples())
        channels = max(1, int(audio_segment.channels))
        sample_width = max(1, int(audio_segment.sample_width))

        if raw_samples.size == 0:
            return np.array([], dtype=np.float32), audio_segment.frame_rate, 1

        scale = float(1 << (8 * sample_width - 1))
        samples = raw_samples.astype(np.float32) / scale

        if channels > 1:
            frame_count = samples.size // channels
            samples = samples[:frame_count * channels].reshape((-1, channels))
            samples = samples.mean(axis=1)

        samples = np.clip(samples, -1.0, 1.0).astype(np.float32, copy=False)
        return samples, audio_segment.frame_rate, 1

    def _probe_audio_sample_rate(self, file_path):
        if not self.ffprobe_path:
            raise RuntimeError("ffprobe not found. Cannot determine audio sample rate.")

        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate",
            "-of",
            "json",
            str(file_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")

        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams or "sample_rate" not in streams[0]:
            raise RuntimeError("No audio stream sample rate found.")

        return int(streams[0]["sample_rate"])

    def _decode_audio_with_ffmpeg(self, file_path):
        sample_rate = self._probe_audio_sample_rate(file_path)
        command = [
            self.ffmpeg_path,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(file_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "pipe:1",
        ]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or "FFmpeg failed to decode audio")

        sample_width = np.dtype(np.float32).itemsize
        usable_bytes = len(result.stdout) - (len(result.stdout) % sample_width)
        samples = np.frombuffer(result.stdout[:usable_bytes], dtype=np.float32).copy()
        if samples.size == 0:
            raise RuntimeError("FFmpeg decoded no audio samples.")

        samples = np.clip(samples, -1.0, 1.0).astype(np.float32, copy=False)
        return samples, sample_rate, 1

    def _set_loaded_audio(self, samples, sample_rate, num_channels):
        self.audio_data = samples
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.duration = len(samples) / sample_rate

    def _print_load_stats(self, label, elapsed, samples):
        print(f"✓ {label} in {elapsed:.2f}s")
        print(f"  Sample rate: {self.sample_rate} Hz")
        print(f"  Duration: {self.duration:.2f} seconds")
        print(f"  Samples: {len(samples):,}")

    def _finalize_load(self, samples, sample_rate, num_channels, elapsed, label, progress_callback):
        self._set_loaded_audio(samples, sample_rate, num_channels)
        self._print_load_stats(label, elapsed, samples)
        self._update_progress(progress_callback, 100, "Audio loaded successfully")
        return True
    
    def load_audio(self, file_path, progress_callback=None):
        """
        Load audio file and convert to standard format.
        
        Args:
            file_path: Path to audio file
            progress_callback: Function to call with progress updates (0-100)
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.file_path = file_path
            file_ext = Path(file_path).suffix.lower()
            self.file_format = file_ext
            
            print(f"\n{'='*60}")
            print(f"Loading audio file: {Path(file_path).name}")
            print(f"Format: {file_ext}")
            print(f"{'='*60}")
            
            self._update_progress(progress_callback, 10, "Detecting format...")

            loaders = {
                '.m4a': self._load_m4a,
                '.m4v': self._load_m4v,
                '.wav': self._load_with_soundfile,
                '.flac': self._load_with_soundfile,
                '.mp3': self._load_with_pydub,
            }
            loader = loaders.get(file_ext)
            if loader is None:
                print(f"ERROR: Unsupported format: {file_ext}")
                return False
            return loader(file_path, progress_callback)

        except Exception as e:
            self._log_exception("loading audio", e)
            return False
    
    def _load_audio_source(
        self,
        file_path,
        progress_callback,
        decode,
        label,
        error_prefix,
        available=True,
        unavailable_message=None,
        on_error=None,
    ):
        """Run one decode strategy with shared timing, finalize, and error handling.

        ``decode(file_path, progress_callback)`` returns
        ``(samples, sample_rate, num_channels)``. Everything around it -- the
        availability guard, wall-clock timing, finalize, and exception logging --
        is identical across formats and lives here once.
        """
        if not available:
            print(f"ERROR: {unavailable_message}")
            return False

        try:
            start_time = time.time()
            samples, sample_rate, num_channels = decode(file_path, progress_callback)
            elapsed = time.time() - start_time
            return self._finalize_load(
                samples, sample_rate, num_channels, elapsed, label, progress_callback
            )
        except Exception as error:
            if on_error is not None:
                return on_error(error)
            self._log_exception(error_prefix, error)
            return False

    def _decode_via_ffmpeg(self, file_path, progress_callback, format_label):
        self._update_progress(progress_callback, 20, f"Decoding {format_label}...")
        print(f"Decoding {format_label} audio to mono float32 (in memory)...")
        samples, sample_rate, num_channels = self._decode_audio_with_ffmpeg(file_path)
        self._update_progress(progress_callback, 50, "Extracting audio data...")
        return samples, sample_rate, num_channels

    def _decode_m4a_with_pydub(self, file_path, progress_callback):
        self._update_progress(progress_callback, 20, "Converting M4A to WAV...")
        print("Converting M4A to WAV with pydub (in memory)...")
        audio_segment = AudioSegment.from_file(file_path, format='m4a')
        self._update_progress(progress_callback, 50, "Extracting audio data...")
        return self._audiosegment_to_mono_float32(audio_segment)

    def _decode_with_soundfile(self, file_path, progress_callback):
        self._update_progress(progress_callback, 30, "Reading audio file...")
        print("Loading audio with soundfile...")
        data, sample_rate = sf.read(file_path, dtype='float32')
        self._update_progress(progress_callback, 70, "Processing audio data...")
        # Convert stereo to mono if needed
        if len(data.shape) > 1 and data.shape[1] == 2:
            data = data.mean(axis=1)
            num_channels = 1
        else:
            num_channels = 1 if len(data.shape) == 1 else data.shape[1]
        return data, sample_rate, num_channels

    def _decode_mp3_with_pydub(self, file_path, progress_callback):
        self._update_progress(progress_callback, 30, "Loading MP3...")
        print("Loading MP3 with pydub...")
        audio_segment = AudioSegment.from_mp3(file_path)
        self._update_progress(progress_callback, 70, "Converting to numpy array...")
        return self._audiosegment_to_mono_float32(audio_segment)

    def _load_ffmpeg_stream(self, file_path, format_label, progress_callback=None):
        on_error = None
        if format_label == "M4A" and PYDUB_AVAILABLE:
            def on_error(error):
                print(f"FFmpeg float32 decode failed, falling back to pydub: {error}")
                return self._load_m4a_with_pydub(file_path, progress_callback)

        return self._load_audio_source(
            file_path,
            progress_callback,
            decode=lambda path, progress: self._decode_via_ffmpeg(path, progress, format_label),
            label="Conversion complete",
            error_prefix=f"decoding {format_label}",
            available=self.ffmpeg_available,
            unavailable_message=f"FFmpeg not found. Cannot decode {format_label}.",
            on_error=on_error,
        )

    def _load_m4a(self, file_path, progress_callback=None):
        """Load M4A by decoding to mono float32 with FFmpeg (pydub fallback)."""
        return self._load_ffmpeg_stream(file_path, "M4A", progress_callback)

    def _load_m4v(self, file_path, progress_callback=None):
        """Load the first audio stream from an M4V file using FFmpeg."""
        return self._load_ffmpeg_stream(file_path, "M4V", progress_callback)

    def _load_m4a_with_pydub(self, file_path, progress_callback=None):
        return self._load_audio_source(
            file_path,
            progress_callback,
            decode=self._decode_m4a_with_pydub,
            label="Conversion complete",
            error_prefix="converting M4A",
        )

    def _load_with_soundfile(self, file_path, progress_callback=None):
        """Load WAV/FLAC file using soundfile."""
        return self._load_audio_source(
            file_path,
            progress_callback,
            decode=self._decode_with_soundfile,
            label="Audio loaded",
            error_prefix="loading with soundfile",
            available=SOUNDFILE_AVAILABLE,
            unavailable_message="soundfile not installed. Cannot load WAV/FLAC.",
        )

    def _load_with_pydub(self, file_path, progress_callback=None):
        """Load MP3 file using pydub."""
        return self._load_audio_source(
            file_path,
            progress_callback,
            decode=self._decode_mp3_with_pydub,
            label="MP3 loaded",
            error_prefix="loading MP3",
            available=PYDUB_AVAILABLE,
            unavailable_message="pydub not installed. Cannot load MP3.",
        )
    
    def play(self, start_time=0.0, end_time=None):
        """
        Start audio playback from specified time.
        
        Args:
            start_time: Start time in seconds
            end_time: End time in seconds (None = play to end)
        """
        if not SOUNDDEVICE_AVAILABLE:
            print("ERROR: sounddevice not installed. Cannot play audio.")
            return False
        
        if self.audio_data is None:
            print("ERROR: No audio loaded.")
            return False
        
        try:
            # Stop any existing playback
            self.stop()
            
            # Calculate sample range
            start_time = min(max(float(start_time), 0.0), self.duration)
            if end_time is None:
                end_time = self.duration
            else:
                end_time = min(max(float(end_time), 0.0), self.duration)

            if end_time <= start_time:
                print("ERROR: Playback end time must be after start time.")
                return False

            start_sample = min(len(self.audio_data), max(0, int(start_time * self.sample_rate)))
            end_sample = min(len(self.audio_data), max(start_sample, int(end_time * self.sample_rate)))
            if end_sample <= start_sample:
                print("ERROR: Playback range is empty.")
                return False
            
            # Extract segment
            audio_segment = self.audio_data[start_sample:end_sample]
            
            print(f"\n▶ Playing audio: {start_time:.2f}s - {end_time:.2f}s")
            
            # Play audio
            sd.play(audio_segment, self.sample_rate)
            
            self.is_playing = True
            self.playback_start_time = time.time()
            self.playback_start_sample = start_sample
            self.playback_end_sample = end_sample
            
            return True
            
        except Exception as e:
            print(f"ERROR during playback: {e}")
            return False
    
    def pause(self):
        """Pause audio playback"""
        if SOUNDDEVICE_AVAILABLE:
            sd.stop()
        self.is_playing = False
        self.playback_end_sample = None
        print("⏸ Paused")
    
    def stop(self):
        """Stop audio playback"""
        if SOUNDDEVICE_AVAILABLE:
            sd.stop()
        self.is_playing = False
        self.playback_start_time = None
        self.playback_end_sample = None
        print("⏹ Stopped")
    
    def get_playback_position(self):
        """
        Get current playback position in seconds.
        
        Returns:
            float: Current position in seconds, or 0.0 if not playing
        """
        if not self.is_playing or self.playback_start_time is None:
            return 0.0
        
        elapsed = time.time() - self.playback_start_time
        position = (self.playback_start_sample / self.sample_rate) + elapsed

        if self.playback_end_sample is not None:
            end_position = self.playback_end_sample / self.sample_rate
            position = min(position, end_position)
        
        return min(position, self.duration)

    def get_playback_end_time(self):
        """Get the bounded playback end time in seconds, if playback is range-limited."""
        if self.playback_end_sample is None or not self.sample_rate:
            return None
        return min(self.playback_end_sample / self.sample_rate, self.duration)
    
    def is_playback_active(self):
        """Check if audio is currently playing"""
        if not SOUNDDEVICE_AVAILABLE:
            return False
        
        # Check if sounddevice stream is active
        if self.is_playing:
            try:
                return sd.get_stream().active
            except:
                return False
        return False
