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

import ui

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
BUFFER_FLUSH_SECONDS = 0.05
POLL_SLEEP_SECONDS = 0.05
RECORDER_DIR = Path("sessions")
FILE_PREFIX = "snippet"


def _ensure_output_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)


def _next_output_path(base_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = base_dir / f"{FILE_PREFIX}-{timestamp}.wav"
    counter = 1
    while candidate.exists():
        candidate = base_dir / f"{FILE_PREFIX}-{timestamp}-{counter}.wav"
        counter += 1
    return candidate


def record_push_to_talk(
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    output_dir: Path | str = RECORDER_DIR,
    frame_consumer: Optional[Callable[[np.ndarray], None]] = None,
) -> str:
    """Record while the space bar is pressed and persist audio to disk."""

    base_dir = Path(output_dir)
    _ensure_output_dir(base_dir)
    target_path = _next_output_path(base_dir)

    audio_queue: "queue.Queue[object]" = queue.Queue()
    indicator_flag = [True]

    def callback(indata, _frames, _time_info, status):
        if status:
            logger.warning("Input stream status: %s", status)
        audio_queue.put(indata.copy())

    indicator_thread = threading.Thread(
        target=ui.record_indicator,
        args=(indicator_flag,),
        daemon=True,
    )

    logger.info("Waiting for push-to-talk gesture")
    while not keyboard.is_pressed("space"):
        time.sleep(POLL_SLEEP_SECONDS)

    indicator_thread.start()

    logger.info("Recording started -> %s", target_path)
    stop_requested = False

    with sf.SoundFile(
        target_path,
        mode="w",
        samplerate=sample_rate,
        channels=channels,
    ) as wav_file:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            callback=callback,
        ):
            while True:
                if not stop_requested:
                    if keyboard.is_pressed("backspace") or not keyboard.is_pressed("space"):
                        stop_requested = True

                try:
                    chunk = audio_queue.get(timeout=BUFFER_FLUSH_SECONDS)
                except queue.Empty:
                    if stop_requested:
                        break
                    continue

                if frame_consumer is not None:
                    frame_consumer(chunk)

                wav_file.write(chunk)

                if stop_requested and audio_queue.empty():
                    break

            while not audio_queue.empty():
                chunk = audio_queue.get()
                if frame_consumer is not None:
                    frame_consumer(chunk)
                wav_file.write(chunk)

    indicator_flag[0] = False
    indicator_thread.join(timeout=1)
    logger.info("Recording finished -> %s", target_path)

    return str(target_path)