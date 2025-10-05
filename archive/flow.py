# flow.py
# Orchestrates dictation flow using ui.py for all presentation

import os
import datetime
import pyperclip
import recorder_latest
import transcripter_latest
import ui
import my_agents as agents

LOG_FILE = "debug_log.txt"

def log_debug(message: str, mode: str = "a"):
    """Write debug messages to debug_log.txt in repo root."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, mode, encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

# marker on startup
log_debug(">>> flow.py started", mode="w")

def run_recording_loop(session_file: str, new_session=True):
    """Main record-transcribe-append loop for a session."""
    ui.snippet_recording_banner()
    recording_path = recorder_latest.record_push_to_talk()
    print("⌫ Finished.\n")

    try:
        transcript_raw, transcript_enhanced = transcripter_latest.transcribe_and_enhance(recording_path)
        ui.show_transcript(transcript_enhanced)

        txt_path = session_file + ".txt"
        md_path = session_file + ".md"

        with open(txt_path, "a", encoding="utf-8") as f:
            f.write(transcript_raw.strip() + "\n---\n")

        with open(md_path, "a", encoding="utf-8") as f:
            f.write("## Raw Transcript\n")
            f.write(transcript_raw.strip() + "\n\n")
            f.write("## Enhanced Transcript\n")
            f.write(transcript_enhanced.strip() + "\n")
            f.write("---\n")

    except Exception as e:
        log_debug(f"Error during transcription: {e}")
        print("✗ Error transcribing audio. See debug_log.txt for details.")
        return

    # Post-record menu
    choice = ui.menu_post_record()
    print(f"User Selection: [{choice}]\n")

    if choice == "4":
        pyperclip.copy(transcript_enhanced)
        print("✓ Copied last snippet to clipboard. Exiting.")
    elif choice == "5":
        pyperclip.copy(transcript_enhanced)
        print("✓ Copied last snippet to clipboard. You can record another.\n")
        run_recording_loop(session_file, new_session=False)
    elif choice == "1":
        print("Re-recording...")
        run_recording_loop(session_file, new_session=True)
    elif choice == "2":
        print("Session closed.")
    elif choice == "3":
        run_recording_loop(session_file, new_session=False)
    elif choice == "6":
        print("→ Sending to Agent Moneypenny...")
        reply = agents.agent_moneypenny(transcript_raw)

        # Log into .md file
        md_path = session_file + ".md"
        with open(md_path, "a", encoding="utf-8") as f:
            f.write("## Agent Moneypenny\n")
            f.write("### User Transcript\n")
            f.write(transcript_raw.strip() + "\n\n")
            f.write("### Agent Reply\n")
            f.write(reply + "\n")
            f.write("---\n")

        print("✓ Response from Agent Moneypenny:")
        ui.pretty_print_response(reply)
    else:
        print("Invalid choice, please try again.")

def main():
    selection = ui.menu_start()
    print(f"User Selection: [{selection}]\n")

    if selection == "1":
        name = input("Enter a session name (leave blank to use timestamp): ").strip()
        if not name:
            name = datetime.datetime.now().strftime("%Y-%m-%d-%Hh-%Mm-session")
        os.makedirs("sessions", exist_ok=True)
        session_base = os.path.join("sessions", name)
        run_recording_loop(session_file=session_base, new_session=True)

    elif selection == "2":
        sessions_dir = "sessions"
        if not os.path.isdir(sessions_dir):
            print("No existing sessions found.")
            return

        files = [f for f in os.listdir(sessions_dir) if f.lower().endswith(".txt")]
        if not files:
            print("No existing sessions found.")
            return

        files = sorted(
            files,
            key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)),
            reverse=True
        )
        recent = files[:5]

        print("\nRecent Sessions:")
        for i, fname in enumerate(recent, 1):
            print(f"[{i}] {fname}")
        ui.divider()

        sel = input("User Selection: ").strip()
        print(f"User Selection: [{sel}]\n")

        try:
            idx = int(sel) - 1
            assert 0 <= idx < len(recent)
        except Exception:
            print("Invalid selection.")
            return

        chosen_txt = os.path.join(sessions_dir, recent[idx])

        # Preview last ~50 words
        try:
            with open(chosen_txt, "r", encoding="utf-8") as f:
                words = f.read().split()
            preview = " ".join(words[-50:]) if words else "(empty file)"
            ui.show_preview(preview)
        except Exception:
            print("\n(Preview unavailable)\n")

        base_no_ext = os.path.splitext(recent[idx])[0]
        session_base = os.path.join(sessions_dir, base_no_ext)
        run_recording_loop(session_file=session_base, new_session=False)

    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()
    ui.print_session_concluded()
