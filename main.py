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

def db_doctor(pb_host="loom-pocketbase"):
    """Ensures PocketBase superuser exists, waiting for container to be ready."""
    import subprocess
    import time
    logger.info(f"Configuring PocketBase Superuser on {pb_host}...")
    
    max_retries = 15
    for i in range(max_retries):
        try:
            # First, check if the container is even running and responding to CLI
            check_cmd = ["docker", "exec", pb_host, "pocketbase", "--version"]
            result = subprocess.run(check_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                # Container is ready for CLI commands
                # Try modern v0.23+ superuser upsert
                cmd_new = ["docker", "exec", pb_host, "pocketbase", "superuser", "upsert", "admin@loom.local", "loom_secure_password"]
                # Try legacy v0.22 and below admin upsert
                cmd_old = ["docker", "exec", pb_host, "pocketbase", "admin", "create", "admin@loom.local", "loom_secure_password"]
                
                try:
                    subprocess.run(cmd_new, check=True, capture_output=True)
                    logger.info(f"PocketBase Superuser configured successfully via 'superuser upsert' on {pb_host}.")
                    return True
                except subprocess.CalledProcessError:
                    try:
                        subprocess.run(cmd_old, check=True, capture_output=True)
                        logger.info(f"PocketBase Superuser configured successfully via 'admin create' on {pb_host}.")
                        return True
                    except subprocess.CalledProcessError as e:
                        logger.warning(f"Both superuser/admin creation methods failed: {e.stderr}")
                        # If both fail, maybe the account already exists and 'create' won't overwrite it
                        return True 
        except Exception as e:
            if i == max_retries - 1:
                logger.error(f"Failed to configure PocketBase superuser on {pb_host} after {max_retries} attempts: {e}")
                return False
        
        logger.info(f"Waiting for {pb_host} container to stabilize (Attempt {i+1}/{max_retries})...")
        time.sleep(2)
    return False

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
            
        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            if self.path == "/api/steer":
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                try:
                    import json
                    data = json.loads(post_data)
                    note = data.get("note")
                    if note:
                        state = ConductorState.load()
                        state.pending_steer.append(note)
                        state.save()
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "ok"}).encode())
                        return
                except Exception as e:
                    logger.error(f"Failed to process steering POST: {e}")
            
            self.send_response(400)
            self.end_headers()

    class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
            
    with ThreadingTCPServer(("", PORT), QuietHandler) as httpd:
        httpd.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the Loom autonomous software factory.")
    parser.add_argument("--clean", action="store_true", help="Perform a full system clean slate before starting.")
    parser.add_argument("--mock", action="store_true", help="Use local Mock Jules (Gemini) instead of official API.")
    
    # Seeding arguments
    parser.add_argument("--name", type=str, help="Initial project name.")
    parser.add_argument("--goal", type=str, help="Initial inspiration goal.")
    parser.add_argument("--data-model", type=str, help="Initial PocketBase data model.")
    
    args = parser.parse_args()

    if args.mock:
        os.environ["USE_MOCK_JULES"] = "true"

    logger = logging.getLogger("loom")
    state_handler = StateLogHandler()
    logger.addHandler(state_handler)
    
    # Perform clean slate BEFORE doctor checks if requested
    if args.clean:
        clean_slate()
    
    # PocketBase hostname from environment
    pb_host = os.getenv("PB_HOSTNAME", "loom-pocketbase")
    
    # Doctor check after potential clean
    if not git_doctor() or not db_doctor(pb_host) or not doctor():
        import sys
        sys.exit(1)
    
    # Seed the state if arguments provided
    if args.name or args.goal or args.data_model:
        state = ConductorState.load()
        if args.name: state.project_name = args.name
        if args.goal: state.inspiration_goal = args.goal
        if args.data_model: state.inspiration_data_model = args.data_model
        state.save()
        logger.info(f"Seeded project state: Name={args.name}, Goal={args.goal}")

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
