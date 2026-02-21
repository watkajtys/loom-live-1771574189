import os
import json
import logging
import requests
from typing import Optional, Tuple
from pathlib import Path
from loom.agents.base import AgentProxy

logger = logging.getLogger("loom")
DESIGN_DIR = Path("app/design")

class StitchClient(AgentProxy):
    """
    Direct client for the Stitch MCP HTTP API.
    Uses 'gcloud auth print-access-token' for authentication or API key.
    """
    BASE_URL = "https://stitch.googleapis.com/mcp"

    def _get_access_token(self) -> str:
        try:
            token = os.getenv("STITCH_ACCESS_TOKEN")
            if token:
                return token
            return self._run(["gcloud", "auth", "print-access-token"]).strip()
        except Exception as e:
            logger.error(f"Failed to get gcloud token: {e}")
            raise

    def _call_mcp(self, method_name: str, arguments: dict, project_id: Optional[str] = None) -> dict:
        api_key = os.getenv("STITCH_API_KEY")
        headers = {"Content-Type": "application/json"}
        
        if api_key:
            headers["X-Goog-Api-Key"] = api_key
        else:
            access_token = self._get_access_token()
            headers["Authorization"] = f"Bearer {access_token}"
            # Some tools like list_projects don't require X-Goog-User-Project
            if project_id:
                headers["X-Goog-User-Project"] = project_id

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": method_name,
                "arguments": arguments
            },
            "id": 1
        }
        
        response = requests.post(self.BASE_URL, json=payload, headers=headers, timeout=300)
        
        if not response.ok:
            logger.error(f"Stitch API Error ({response.status_code}): {response.text}")
            raise Exception(f"Stitch API request failed: {response.status_code}")

        data = response.json()
        if "error" in data:
            raise Exception(f"Stitch API Error: {data['error']}")
        return data

    def create_project(self, title: str) -> str:
        logger.info(f"Creating new Stitch project: {title}")
        data = self._call_mcp("create_project", {"title": title})
        
        result = data.get("result", {})
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    inner = json.loads(block.get("text", ""))
                    # Returns e.g. "projects/4044680601076201931"
                    name = inner.get("name", "")
                    if name.startswith("projects/"):
                        pid = name.split("/")[1]
                        logger.info(f"New project created: {pid}")
                        return pid
                except json.JSONDecodeError:
                    pass
        raise Exception("Failed to parse project creation response")

    def generate_or_edit_screen(self, description: str, project_id: str, screen_id: Optional[str] = None) -> Tuple[str, str]:
        if screen_id:
            logger.info(f"Editing existing screen {screen_id} in project {project_id} using GEMINI_3_PRO: {description}")
            method = "edit_screens"
            arguments = {
                "projectId": project_id,
                "selectedScreenIds": [screen_id],
                "prompt": description,
                "modelId": "GEMINI_3_PRO"
            }
        else:
            logger.info(f"Generating new screen in project {project_id} using GEMINI_3_PRO: {description}")
            method = "generate_screen_from_text"
            arguments = {
                "projectId": project_id,
                "prompt": description,
                "modelId": "GEMINI_3_PRO"
            }
            
        logger.info(f"Calling Stitch API (method={method}, timeout=300s)...")
        data = self._call_mcp(method, arguments, project_id)
        
        result = data.get("result", {})
        content_blocks = result.get("content", [])
        html_content = ""
        new_screen_id = None
        
        for block in content_blocks:
            if block.get("type") == "text":
                raw_text = block.get("text", "")
                if "The service is currently unavailable" in raw_text:
                     raise Exception("Stitch Service Unavailable")
                try:
                    inner_json = json.loads(raw_text)
                    screens = inner_json.get("outputComponents", [{}])[0].get("design", {}).get("screens", [])
                    if screens:
                        screen = screens[0]
                        new_screen_id = screen.get("name", "").split("/")[-1] if screen.get("name") else screen_id
                        
                        # Download Screenshot
                        if "screenshot" in screen:
                            img_url = screen["screenshot"].get("downloadUrl")
                            if img_url:
                                logger.info(f"Downloading design screenshot from: {img_url}")
                                img_resp = requests.get(img_url, timeout=30)
                                if img_resp.ok:
                                    img_file = DESIGN_DIR / "reference.png"
                                    with open(img_file, "wb") as f:
                                        f.write(img_resp.content)

                        # Download HTML
                        if "htmlCode" in screen:
                            download_url = screen["htmlCode"].get("downloadUrl")
                            if download_url:
                                logger.info(f"Downloading HTML from: {download_url}")
                                html_resp = requests.get(download_url, timeout=30)
                                if html_resp.ok:
                                    html_content = html_resp.text
                except json.JSONDecodeError:
                    logger.warning("Could not parse inner JSON from Stitch response.")

        if not html_content:
            logger.warning("Stitch returned no HTML content. Using fallback.")
            raise Exception("No HTML content generated.")

        design_file = DESIGN_DIR / "latest_design.html"
        DESIGN_DIR.mkdir(parents=True, exist_ok=True)
        with open(design_file, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        return str(design_file), new_screen_id
