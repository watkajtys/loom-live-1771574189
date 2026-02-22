import logging
import os
import shutil
import threading
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel

logger = logging.getLogger("loom")
STATE_FILE = Path("session_state.json")

class AttemptRecord(BaseModel):
    attempt_number: int
    prompt_used: str
    app_screenshot_path: Optional[str] = None
    jules_patch_path: Optional[str] = None
    score: int
    critique: str

class LoopIteration(BaseModel):
    id: int
    timestamp: str
    goal: str
    target_route: str = "/"
    brainstorming_output: Optional[str] = None
    design_screenshot_path: Optional[str] = None
    design_variants_paths: List[str] = []
    chosen_design_path: Optional[str] = None
    design_review_critique: Optional[str] = None
    attempts: List[AttemptRecord] = []
    happiness_score: int = 0  # Final score of this iteration
    architectural_critique: Optional[str] = None
    git_commit: Optional[str] = None

_global_state = None
_state_lock = threading.RLock()

class ConductorState(BaseModel):
    project_name: str = "Loom Experiment"
    app_meta: str = ""
    current_iteration: int = 0
    active_branch: str = "main"
    inspiration_goal: str = ""
    history: List[LoopIteration] = []
    stitch_project_id: Optional[str] = None
    stitch_screen_id: Optional[str] = None
    active_jules_prompt: Optional[str] = None
    active_jules_url: Optional[str] = None
    active_jules_action: Optional[str] = None
    current_status: str = "Idle"
    live_logs: List[str] = []
    
    def save(self):
        with _state_lock:
            # Use a thread-specific temp file to prevent multiple threads from writing to the same file before replacing
            tmp_file = STATE_FILE.with_suffix(f'.tmp.{threading.get_ident()}.json')
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    f.write(self.model_dump_json(indent=2))
                os.replace(tmp_file, STATE_FILE)
            except Exception as e:
                # Using print instead of logger to prevent infinite recursion with StateLogHandler
                print(f"Warning: Failed to save state to disk (likely locked by viewer): {e}")
            finally:
                if tmp_file.exists():
                    try:
                        os.remove(tmp_file)
                    except:
                        pass
    
    def add_log(self, log_line: str):
        with _state_lock:
            self.live_logs.append(log_line)
            if len(self.live_logs) > 500:
                self.live_logs = self.live_logs[-500:]
            self.save()

    @classmethod
    def load(cls) -> 'ConductorState':
        global _global_state
        with _state_lock:
            if _global_state is not None:
                return _global_state
            if STATE_FILE.exists():
                try:
                    with open(STATE_FILE, "r", encoding="utf-8") as f:
                        _global_state = cls.model_validate_json(f.read())
                        return _global_state
                except Exception as e:
                    print(f"Warning: Failed to load state: {e}. Starting fresh.")
            _global_state = cls()
            return _global_state
