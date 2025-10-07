"""Terminal UI utilities for recording indicators and status messages."""
import itertools
import sys
import time
from rich.console import Console
from rich.text import Text

console = Console()


def record_indicator(run_flag_or_active: object) -> None:
    """
    Display animated recording indicator with timer.
    
    Args:
        run_flag_or_active: Either a list [bool] or bool indicating if recording is active.
                           Use list for thread-safe flag: [True] to start, set [0] = False to stop.
                           Use bool True for single display, False to skip.
    """
    # Handle both [bool] list and direct bool
    def is_active():
        if isinstance(run_flag_or_active, list):
            return run_flag_or_active[0]
        return run_flag_or_active
    
    spinner = itertools.cycle(["|", "/", "-", "\\"])
    start_time = time.time()
    
    while is_active():
        elapsed = time.time() - start_time
        mins, secs = divmod(elapsed, 60)
        ms = int((secs - int(secs)) * 100)
        timer = f"{int(mins)}:{int(secs):02}.{ms:02}"
        spin = next(spinner)
        
        msg = f"🎙️  Recording... {spin}   {timer}"
        console.print(Text(msg, style="bold green"), end="\r")
        time.sleep(0.1)
    
    # Clear line and show completion
    console.print(Text("✓ Recording complete" + " " * 20, style="bold green"))


def print_status(message: str, style: str = "bold white") -> None:
    """
    Print a status message.
    
    Args:
        message: Status message text
        style: Rich style string (default: "bold white")
    """
    console.print(Text(message, style=style))


def print_success(message: str) -> None:
    """Print a success message in green."""
    console.print(Text(f"✓ {message}", style="bold green"))


def print_error(message: str) -> None:
    """Print an error message in red."""
    console.print(Text(f"✗ {message}", style="bold red"))


def print_info(message: str) -> None:
    """Print an info message in cyan."""
    console.print(Text(f"ℹ {message}", style="bold cyan"))


def divider(width: int = 45, char: str = "-", style: str = "green") -> None:
    """Print a horizontal divider line."""
    console.print(Text(char * width, style=style))


def banner(title: str = "WhisPTT", width: int = 45) -> None:
    """Print a centered banner title."""
    console.print(Text(title.center(width), style="bold green"))
    divider(width)
