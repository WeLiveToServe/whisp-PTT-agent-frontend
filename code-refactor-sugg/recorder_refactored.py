"""Audio recording module with push-to-talk support."""
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import keyboard
import sounddevice as sd
import soundfile as sf
import numpy as np

logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
BUFFER_FLUSH_SECONDS = 0.05
POLL_SLEEP_SECONDS = 0.05
RECORDER_DIR = Path("sessions")
FILE_PREFIX = "snippet"


class RecordingError(Exception):
    """Raised when recording fails."""
    pass


def record_push_to_talk(
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    output_dir: Path | str = RECORDER_DIR,
    frame_consumer: Optional[Callable[[np.ndarray], None]] = None,
    indicator_callback: Optional[Callable[[bool], None]] = None,
) -> str:
    """
    Record audio while space bar is pressed, save to WAV file.
    
    Args:
        sample_rate: Audio sample rate in Hz
        channels: Number of audio channels (1 for mono)
        output_dir: Directory to save recordings
        frame_consumer: Optional callback for real-time frame processing
        indicator_callback: Optional callback for UI indicator (True=start, False=stop)
    
    Returns:
        Path to saved audio file
    
    Raises:
        RecordingError: If recording fails
    """
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    
    target_path = _generate_output_path(base_dir)
    audio_queue: "queue.Queue[np.ndarray]" = queue.Queue()
    
    def audio_callback(indata, _frames, _time_info, status):
        if status:
            logger.warning("Audio stream status: %s", status)
        audio_queue.put(indata.copy())
    
    # Wait for space bar press
    logger.info("Waiting for space bar...")
    while not keyboard.is_pressed("space"):
        time.sleep(POLL_SLEEP_SECONDS)
    
    # Start indicator if provided
    if indicator_callback:
        threading.Thread(
            target=indicator_callback,
            args=(True,),
            daemon=True
        ).start()
    
    logger.info("Recording started -> %s", target_path)
    stop_requested = False
    
    try:
        with sf.SoundFile(
            target_path,
            mode="w",
            samplerate=sample_rate,
            channels=channels,
        ) as wav_file:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=channels,
                callback=audio_callback,
            ):
                while True:
                    # Check for stop conditions
                    if not stop_requested:
                        if keyboard.is_pressed("backspace") or not keyboard.is_pressed("space"):
                            stop_requested = True
                    
                    # Process audio chunks
                    try:
                        chunk = audio_queue.get(timeout=BUFFER_FLUSH_SECONDS)
                    except queue.Empty:
                        if stop_requested:
                            break
                        continue
                    
                    # Downmix to mono if needed
                    if channels == 1 and chunk.ndim > 1:
                        chunk = chunk.mean(axis=1)
                    
                    # Send to consumer if provided
                    if frame_consumer:
                        frame_consumer(chunk)
                    
                    wav_file.write(chunk)
                    
                    if stop_requested and audio_queue.empty():
                        break
                
                # Flush remaining audio
                while not audio_queue.empty():
                    chunk = audio_queue.get()
                    if channels == 1 and chunk.ndim > 1:
                        chunk = chunk.mean(axis=1)
                    if frame_consumer:
                        frame_consumer(chunk)
                    wav_file.write(chunk)
    
    except Exception as e:
        logger.exception("Recording failed")
        raise RecordingError(f"Failed to record audio: {e}") from e
    
    finally:
        # Stop indicator if provided
        if indicator_callback:
            indicator_callback(False)
    
    logger.info("Recording finished -> %s", target_path)
    return str(target_path)


def _generate_output_path(base_dir: Path) -> Path:
    """Generate unique output path with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = base_dir / f"{FILE_PREFIX}-{timestamp}.wav"
    counter = 1
    while candidate.exists():
        candidate = base_dir / f"{FILE_PREFIX}-{timestamp}-{counter}.wav"
        counter += 1
    return candidate
