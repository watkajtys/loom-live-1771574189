import os
import shutil
import subprocess
import logging

logger = logging.getLogger("loom")

def clean_slate():
    """
    Performs a completely destructive reset of the Loom environment to ensure 
    a 100% fresh start. This includes resetting git state, deleting session 
    state files, and wiping all generated artifacts.
    """
    # 0. Prevent state resurrection by resetting the singleton before logging
    try:
        from loom.core.state import ConductorState
        ConductorState.reset()
    except Exception as e:
        logger.warning(f"Failed to reset in-memory state: {e}")

    logger.info("[bold red]INITIATING FULL SYSTEM CLEAN SLATE...[/bold red]", extra={"markup": True})
    
    # 1. Reset Git State in the app submodule
    try:
        if os.path.exists("app/.git"):
            logger.info("Resetting app repository to origin/main...")
            subprocess.run(["git", "reset", "--hard"], cwd="app", check=True, stdout=subprocess.DEVNULL, shell=(os.name == 'nt'))
            subprocess.run(["git", "clean", "-xfd"], cwd="app", check=True, stdout=subprocess.DEVNULL, shell=(os.name == 'nt'))
            subprocess.run(["git", "checkout", "main"], cwd="app", check=True, stdout=subprocess.DEVNULL, shell=(os.name == 'nt'))
            
            # Delete any left-over iter- branches
            try:
                branches = subprocess.check_output(["git", "branch"], cwd="app", text=True, shell=(os.name == 'nt'))
                for branch in branches.splitlines():
                    branch_name = branch.strip().replace("* ", "")
                    if branch_name.startswith("iter-"):
                        subprocess.run(["git", "branch", "-D", branch_name], cwd="app", check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=(os.name == 'nt'))
            except Exception as e:
                logger.warning(f"Error deleting old branches: {e}")
            
            # If origin exists, hard reset to it. If it fails, that's okay (e.g. no origin yet).
            try:
                subprocess.run(["git", "reset", "--hard", "origin/main"], cwd="app", check=True, stdout=subprocess.DEVNULL, shell=(os.name == 'nt'))
            except subprocess.CalledProcessError:
                pass
            
            # Attempt to remove any origin remote so ensure_remote() creates a fresh one
            try:
                subprocess.run(["git", "remote", "remove", "origin"], cwd="app", check=True, stdout=subprocess.DEVNULL, shell=(os.name == 'nt'))
            except subprocess.CalledProcessError:
                pass
    except Exception as e:
        logger.warning(f"Error during git reset (this is usually fine if it's the first run): {e}")

    # 2. Delete Session State Files
    import glob
    state_files = glob.glob("session_state*.json")
    for file in state_files:
        if os.path.exists(file):
            logger.info(f"Deleting {file}...")
            try:
                os.remove(file)
            except Exception as e:
                logger.error(f"Failed to delete {file}: {e}")

    # 3. Wipe Artifacts Directory
    artifacts_dir = os.path.join("viewer", "public", "artifacts")
    if os.path.exists(artifacts_dir):
        logger.info(f"Wiping artifacts directory: {artifacts_dir}...")
        try:
            for filename in os.listdir(artifacts_dir):
                file_path = os.path.join(artifacts_dir, filename)
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
        except Exception as e:
            logger.error(f"Failed to wipe artifacts: {e}")
            
    # 4. Wipe PocketBase Data
    pb_data_dir = "pb_data"
    if os.path.exists(pb_data_dir):
        logger.info(f"Wiping PocketBase data directory: {pb_data_dir}...")
        try:
            shutil.rmtree(pb_data_dir)
        except Exception as e:
            logger.error(f"Failed to wipe pb_data: {e}")

    logger.info("[bold green]CLEAN SLATE COMPLETE. Ready to initialize new project.[/bold green]", extra={"markup": True})
