import logging
import os
import shutil
import threading
import time
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
    data_model: Optional[str] = None
    requires_design: bool = True
    test_scenario: Optional[str] = None
    negative_history: List[str] = []
    brainstorming_output: Optional[str] = None
    base_briefs: List[str] = []
    base_seed_paths: List[Optional[str]] = []
    base_variants_data: Optional[List[dict]] = None
    seed_review_critique: Optional[str] = None
    design_screenshot_path: Optional[str] = None
    design_variants_paths: List[Optional[str]] = []
    layout_review_critique: Optional[str] = None
    chosen_design_path: Optional[str] = None
    design_review_critique: Optional[str] = None
    theme_variants_paths: List[Optional[str]] = []
    chosen_theme_path: Optional[str] = None
    theme_review_critique: Optional[str] = None
    attempts: List[AttemptRecord] = []
    happiness_score: int = 0  # Final score of this iteration
    architectural_critique: Optional[str] = None
    git_commit: Optional[str] = None

_global_state = None
_state_lock = threading.RLock()

class ConductorState(BaseModel):
    project_name: str = "Loom Experiment"
    app_meta: str = ""
    product_phase: str = "Phase 1: Core Loop MVP"
    product_roadmap: str = ""
    repo_memory: dict = {}
    current_iteration: int = 0
    active_branch: str = "main"
    inspiration_goal: str = ""
    inspiration_target_route: str = "/"
    inspiration_data_model: Optional[str] = None
    inspiration_requires_design: bool = True
    inspiration_mode: str = "design"  # "design", "refinement", "logic"
    inspiration_test_scenario: str = ""
    history: List[LoopIteration] = []
    stitch_project_id: Optional[str] = None
    stitch_screen_id: Optional[str] = None
    active_jules_prompt: Optional[str] = None
    active_jules_url: Optional[str] = None
    active_jules_action: Optional[str] = None
    current_status: str = "Idle"
    current_phase: str = "Inspiration"
    pending_steer: List[str] = []
    steering_history: List[dict] = []
    live_logs: List[str] = []
    
    def save(self):
        with _state_lock:
            # Use a thread-specific temp file to prevent multiple threads from writing to the same file before replacing
            tmp_file = STATE_FILE.with_suffix(f'.tmp.{threading.get_ident()}.json')
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    f.write(self.model_dump_json(indent=2))
                
                # Windows specific: retry replace if file is locked
                max_retries = 20
                for i in range(max_retries):
                    try:
                        os.replace(tmp_file, STATE_FILE)
                        break
                    except OSError as e:
                        if i == max_retries - 1:
                            raise e
                        # Gradually increase sleep time
                        time.sleep(0.05 * (i + 1))
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
    def reset(cls):
        """Wipes the in-memory global state."""
        global _global_state
        with _state_lock:
            _global_state = cls(live_logs=[])
            return _global_state

    @classmethod
    def load(cls) -> 'ConductorState':
        global _global_state
        with _state_lock:
            if _global_state is not None:
                return _global_state
            
            # Robust initialization to prevent directory-mount errors
            if STATE_FILE.exists() and STATE_FILE.is_dir():
                import shutil
                shutil.rmtree(STATE_FILE)
            
            if STATE_FILE.exists():
                # Retry load if file is temporarily locked (e.g. by save process rename)
                max_retries = 10
                for i in range(max_retries):
                    try:
                        with open(STATE_FILE, "r", encoding="utf-8") as f:
                            _global_state = cls.model_validate_json(f.read())
                            return _global_state
                    except (OSError, Exception) as e:
                        if i == max_retries - 1:
                            print(f"Warning: Failed to load state after {max_retries} attempts: {e}. Starting fresh.")
                            break
                        time.sleep(0.05 * (i + 1))
            _global_state = cls()
            return _global_state
