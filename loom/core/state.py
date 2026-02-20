import logging
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel

logger = logging.getLogger("loom")
STATE_FILE = Path("session_state.json")

class LoopIteration(BaseModel):
    id: int
    timestamp: str
    goal: str
    happiness_score: int = 0
    git_commit: Optional[str] = None
    critiques: List[str] = []

class ConductorState(BaseModel):
    project_name: str = "Loom Experiment"
    current_iteration: int = 0
    active_branch: str = "main"
    inspiration_goal: str = ""
    history: List[LoopIteration] = []
    
    def save(self):
        with open(STATE_FILE, "w") as f:
            f.write(self.model_dump_json(indent=2))
    
    @classmethod
    def load(cls) -> 'ConductorState':
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r") as f:
                    return cls.model_validate_json(f.read())
            except Exception as e:
                logger.error(f"Failed to load state: {e}. Starting fresh.")
        return cls()
