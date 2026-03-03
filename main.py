import logging
from rich.console import Console
from rich.logging import RichHandler
from dotenv import load_dotenv

load_dotenv(override=True)

console = Console()
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True)]
)

import os
import argparse
from loom.core.overseer import Overseer
from loom.core.cleaner import clean_slate
from loom.core.state import ConductorState
import threading
import http.server
import socketserver
from datetime import datetime

logger = logging.getLogger("loom")

def git_doctor():
    """Ensures git is configured for commits."""
    import subprocess
    logger.info("Configuring Git identity...")
    try:
        subprocess.run(["git", "config", "--global", "user.email", "loom@example.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "Loom Bot"], check=True)
        # Prevent "dubious ownership" errors in Docker volumes
        subprocess.run(["git", "config", "--global", "safe.directory", "*"], check=True)
        return True
    except Exception as e:
        logger.error(f"Failed to configure git: {e}")
        return False

def doctor():
    """Validates the environment before starting."""
    logger.info("Running system check...")
    required_keys = ["GEMINI_API_KEY", "STITCH_API_KEY", "STITCH_PROJECT_ID"]
    
    # Jules is only required if not mocking
    if os.getenv("USE_MOCK_JULES", "").lower() != "true":
        required_keys.append("JULES_API_KEY")
        
    missing = [key for key in required_keys if not os.getenv(key)]
    
    if missing:
        logger.error(f"[bold red]System Check Failed! Missing API Keys: {', '.join(missing)}[/bold red]", extra={"markup": True})
        logger.error("Please check your .env file.")
        return False
    
    logger.info("[bold green]System Check Passed.[/bold green]", extra={"markup": True})
    return True

class StateLogHandler(logging.Handler):
    def emit(self, record):
        try:
            import re
            msg = self.format(record)
            # Strip Rich markup tags so they don't show up literally in the web dashboard
            msg = re.sub(r'\[/?bold.*?\]', '', msg)
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_line = f"[{timestamp}] {record.levelname}: {msg}"
            
            # This is a bit hacky, but lets us grab the active state
            state = ConductorState.load()
            state.add_log(log_line)
        except Exception:
            pass

def start_viewer_server():
    PORT = 8080
    
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

    class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
            
    with ThreadingTCPServer(("", PORT), QuietHandler) as httpd:
        httpd.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the Loom autonomous software factory.")
    parser.add_argument("--clean", action="store_true", help="Perform a full system clean slate before starting.")
    parser.add_argument("--mock", action="store_true", help="Use local Mock Jules (Gemini) instead of official API.")
    args = parser.parse_args()

    if args.mock:
        os.environ["USE_MOCK_JULES"] = "true"

    logger = logging.getLogger("loom")
    state_handler = StateLogHandler()
    logger.addHandler(state_handler)
    
    # Doctor check before anything else
    if not git_doctor() or not doctor():
        import sys
        sys.exit(1)
        
    if args.clean:
        clean_slate()
    
    # Start the Dashboard Viewer server in the background
    viewer_thread = threading.Thread(target=start_viewer_server, daemon=True)
    viewer_thread.start()
    logger.info("[bold green]Observer Dashboard running at http://localhost:8080/viewer/[/bold green]", extra={"markup": True})
    
    conductor = Overseer()
    try:
        conductor.loop()
    except KeyboardInterrupt:
        logger.info("Loom stopped by user.")
        conductor.phoenix.kill()
