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

import argparse
from loom.core.overseer import Overseer
from loom.core.cleaner import clean_slate
from loom.core.state import ConductorState
import threading
import http.server
import socketserver
from datetime import datetime

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
    args = parser.parse_args()

    logger = logging.getLogger("loom")
    state_handler = StateLogHandler()
    logger.addHandler(state_handler)
    
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
