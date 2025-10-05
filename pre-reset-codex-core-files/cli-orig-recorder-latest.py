import os
import queue
import sounddevice as sd
import soundfile as sf
import keyboard
import io
from datetime import datetime
from pydub import AudioSegment
import threading
import ui  # add near top with your other imports


def record_push_to_talk():
    q = queue.Queue()
    samplerate = 44100
    channels = 1

    def callback(indata, frames, time, status):
        if status:
            print(status)
        q.put(indata.copy())

    os.makedirs("sessions", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%Hh-%Mm-recording")
    wav_outpath = os.path.join("sessions", f"{timestamp}.wav")

    ui.print_status("Press SPACE to record, BACKSPACE to stop.")

    last_state = None  # track last state for printing
    run_flag = [False]  # used for spinner/timer thread
    indicator_thread = None

    with sf.SoundFile(wav_outpath, mode="w", samplerate=samplerate, channels=channels) as file:
        with sd.InputStream(samplerate=samplerate, channels=channels, callback=callback):
            while True:
                if keyboard.is_pressed("backspace"):
                    ui.print_recording_finished()
                    if run_flag[0]:
                        run_flag[0] = False
                        if indicator_thread:
                            indicator_thread.join()
                    break

                elif keyboard.is_pressed("space"):
                    if last_state != "recording":
                        last_state = "recording"
                        # start spinner/timer if not already running
                        if not run_flag[0]:
                            run_flag[0] = True
                            indicator_thread = threading.Thread(target=ui.record_indicator, args=(run_flag,))
                            indicator_thread.start()
                    file.write(q.get())

                else:
                    if last_state != "paused":
                        last_state = "paused"
                        ui.print_status("⏸️  Paused")
                        # stop spinner/timer while paused
                        if run_flag[0]:
                            run_flag[0] = False
                            if indicator_thread:
                                indicator_thread.join()
                    sd.sleep(200)  # throttle loop

    # after finishing recording, convert to mp3
    mp3_outpath = wav_outpath.replace(".wav", ".mp3")
    try:
        AudioSegment.from_wav(wav_outpath).export(mp3_outpath, format="mp3")
        ui.print_success(f"✓ Compressed recording saved as {mp3_outpath}")
        return mp3_outpath
    except Exception as e:
        ui.print_error(f"MP3 conversion failed: {e}")
        return wav_outpath

# ===============================
# Experimental Chunked Recorder
# ===============================

def record_chunks_push_to_talk(chunk_seconds=1, samplerate=44100, channels=1):
    """
    Generator that yields audio chunks while SPACE is held down.
    Stops when BACKSPACE is pressed.
    """

    q = queue.Queue()

    def callback(indata, frames, time, status):
        if status:
            print(status)
        q.put(indata.copy())

    print("Recording (live mode)... Hold SPACE, BACKSPACE to stop.")

    last_state = None
    frames_per_chunk = int(samplerate * chunk_seconds)
    buffer = []

    with sd.InputStream(samplerate=samplerate, channels=channels, callback=callback):
        while True:
            if keyboard.is_pressed("backspace"):
                print("⌫ Finished live recording.")
                if buffer:
                    yield _frames_to_wav(buffer, samplerate, channels)
                break
            elif keyboard.is_pressed("space"):
                if last_state != "recording":
                    print("🎙️  Recording...")
                    last_state = "recording"
                buffer.extend(q.get())
                if len(buffer) >= frames_per_chunk:
                    yield _frames_to_wav(buffer, samplerate, channels)
                    buffer = []
            else:
                if last_state != "paused":
                    print("⏸️  Paused")
                    last_state = "paused"
                sd.sleep(200)


def _frames_to_wav(frames, samplerate, channels):
    """
    Helper: convert numpy frames to an in-memory WAV bytes object.
    """
    import soundfile as sf
    import numpy as np
    import io

    wav_bytes = io.BytesIO()
    wav_bytes.name = "chunk.wav"
    data = np.vstack(frames)
    sf.write(wav_bytes, data, samplerate, format="WAV", subtype="PCM_16")
    wav_bytes.seek(0)
    return wav_bytes.read()

