import logging
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("loom")

class DatabaseProvisioner:
    """Manages the autonomous provisioning of PocketBase collections."""
    
    def __init__(self, pb_url: str = "http://127.0.0.1:8090"):
        self.pb_url = pb_url
        self.admin_email = "admin@loom.local"
        self.admin_password = "loom_secure_password"
        self.token = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))
    def ensure_admin(self):
        """Creates an initial admin account if one doesn't exist, and authenticates."""
        logger.info("Connecting to PocketBase Database Soul...")
        
        # 1. Try to Authenticate
        auth_url = f"{self.pb_url}/api/admins/auth-with-password"
        payload = {"identity": self.admin_email, "password": self.admin_password}
        
        try:
            resp = requests.post(auth_url, json=payload, timeout=5)
            if resp.status_code == 200:
                self.token = resp.json().get("token")
                logger.info("Successfully authenticated as PocketBase Admin.")
                return True
        except requests.exceptions.ConnectionError:
             logger.warning("PocketBase server is unreachable. Is the Docker container running?")
             raise Exception("PocketBase unreachable")

        # 2. If Auth fails, try to create the first admin
        logger.info("Admin auth failed. Attempting to create initial admin account...")
        admins_url = f"{self.pb_url}/api/admins"
        create_payload = {
            "email": self.admin_email,
            "password": self.admin_password,
            "passwordConfirm": self.admin_password
        }
        
        # PocketBase allows creating the first admin without auth
        resp = requests.post(admins_url, json=create_payload)
        if resp.status_code in [200, 201]:
            logger.info("Created initial Admin account.")
            # Re-authenticate
            auth_resp = requests.post(auth_url, json=payload)
            if auth_resp.status_code == 200:
                self.token = auth_resp.json().get("token")
                return True
                
        logger.error(f"Failed to create or authenticate Admin: {resp.text}")
        return False

    def provision_schema(self, schema_json: list):
        """
        Takes a list of PocketBase collection definition dicts and pushes them to the API.
        This allows the LLM to define tables and we blindly create them.
        """
        if not self.token:
            if not self.ensure_admin():
                return False

        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json"
        }
        
        collections_url = f"{self.pb_url}/api/collections"
        
        # 1. Get existing collections to avoid duplicates/errors
        existing_resp = requests.get(collections_url, headers=headers)
        existing_collections = []
        if existing_resp.status_code == 200:
            existing_collections = [c['name'] for c in existing_resp.json().get('items', [])]
            
        success_count = 0
        
        for collection in schema_json:
            name = collection.get("name")
            if not name: continue
            
            # We skip 'users' as it's a default system collection that PB handles
            if name == "users" and "users" in existing_collections:
                logger.info("Skipping 'users' collection (system default).")
                continue
                
            if name in existing_collections:
                logger.info(f"Collection '{name}' already exists. Skipping.")
                # We could run an update/patch here in the future if schema changes
                success_count += 1
                continue
                
            logger.info(f"Provisioning new collection: '{name}'...")
            
            # Ensure open API rules so the React app can read/write without complex auth initially
            if "listRule" not in collection: collection["listRule"] = ""
            if "viewRule" not in collection: collection["viewRule"] = ""
            if "createRule" not in collection: collection["createRule"] = ""
            if "updateRule" not in collection: collection["updateRule"] = ""
            if "deleteRule" not in collection: collection["deleteRule"] = ""
            
            resp = requests.post(collections_url, json=collection, headers=headers)
            if resp.status_code in [200, 201]:
                logger.info(f"Successfully created collection '{name}'.")
                success_count += 1
            else:
                logger.error(f"Failed to create collection '{name}': {resp.text}")
                
        return success_count == len(schema_json)
