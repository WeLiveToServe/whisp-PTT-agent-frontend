import recorder_latest
import transcripter_latest
import ui

if __name__ == "__main__":
    print("=== Live Transcription Test ===")
    chunks = recorder_latest.record_chunks_push_to_talk(chunk_seconds=1)
    for text in transcripter_latest.live_transcribe(chunks):
        pass
    ui.print_session_concluded()
