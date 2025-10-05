import os
import queue
import sounddevice as sd
import soundfile as sf
import keyboard
import io
from datetime import datetime
import threading
import ui  # add near top with your other imports
import logging

# <span style="color: blue;">
# ADDED: Configure module-level logger for debugging recorder issues
# </span>
logger = logging.getLogger(__name__)

# <span style="color: blue;">
# ADDED: Named constants for magic numbers throughout the file
# </span>
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
POLL_SLEEP_MS = 200  # Milliseconds to sleep when paused, reduces CPU usage


def record_push_to_talk():
    q = queue.Queue()
    # <span style="color: red;">
    # samplerate = 44100
    # channels = 1
    # </span>
    # <span style="color: blue;">
    # CHANGED: Magic numbers replaced with named constants for clarity and maintainability
    # </span>
    samplerate = DEFAULT_SAMPLE_RATE
    channels = DEFAULT_CHANNELS

    def callback(indata