import logging
import subprocess
import psutil
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential
import requests

logger = logging.getLogger("loom")
VITE_PORT = 5173

class PhoenixServer:
    """Manages the lifecycle of the Vite dev server."""
    
    def __init__(self, port: int = VITE_PORT):
        self.port = port
        self.process: Optional[subprocess.Popen] = None

    def kill(self):
        """Kills any process listening on the target port."""
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for conn in proc.connections(kind='inet'):
                    if conn.laddr.port == self.port:
                        logger.warning(f"Killing zombie process {proc.name()} (PID: {proc.pid}) on port {self.port}")
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    def spawn(self):
        """Starts the Vite server in the background."""
        self.kill() # Ensure clean slate
        logger.info("Spawning Phoenix Server (Vite)...")
        try:
            # Using shell=True for Windows compatibility with npm
            self.process = subprocess.Popen(
                ["npm", "run", "dev"], 
                cwd="app",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )
        except Exception as e:
            logger.error(f"Failed to spawn Vite: {e}")
            raise

    @retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=2, max=10))
    def wait_for_ready(self):
        """Polls localhost until it returns 200 OK."""
        url = f"http://localhost:{self.port}"
        logger.info(f"Waiting for {url}...")
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            logger.info("Phoenix Server is READY.")
            return True
        raise Exception("Server not ready")
