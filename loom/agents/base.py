import logging
import subprocess
from typing import List

logger = logging.getLogger("loom")

class AgentProxy:
    def _run(self, command: List[str], cwd: str = ".") -> str:
        logger.info(f"Running: {' '.join(command)}")
        try:
            result = subprocess.run(
                command, 
                cwd=cwd, 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=300 # 5 minute timeout
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e.stderr}")
            raise
        except subprocess.TimeoutExpired:
            logger.error("Command timed out!")
            raise
