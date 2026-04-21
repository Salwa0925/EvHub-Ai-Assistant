import logging
import time
import requests

log = logging.getLogger(__name__)

class OdooClient:
    """
    Handles authentication and raw API calls to an Odoo JSON-2 endpoint.
    """

    def __init__(self, url: str, db: str, api_key: str):
        self.url = url
        self.db = db
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "X-Odoo-Database": self.db,
        }

    def verify_connection(self) -> None:
        """Confirm the server is reachable and the API key is valid."""
        log.info(f"Connecting to {self.url}...")
        try:
            resp = requests.get(f"{self.url}/web/version", timeout=10)
            resp.raise_for_status()
            version = resp.json().get("version", "unknown")
            log.info(f"Server reachable. Odoo version: {version}")
        except Exception as e:
            log.error(f"Could not reach Odoo: {e}")
            raise

        users = self.execute("res.users", "search_read",
                             domain=[], fields=["name", "login"], limit=1)
        if not users:
            raise RuntimeError("Authentication failed — check your API key.")
        log.info(f"Authenticated as: {users[0]['name']} ({users[0]['login']})")

    def execute(self, model: str, method: str, max_retries: int = 3, **kwargs) -> any:
        """
        Call any Odoo model method via the JSON-2 API.
        """
        url = f"{self.url}/json/2/{model}/{method}"

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, json=kwargs, headers=self.headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                if isinstance(data, dict):
                    if "error" in data:
                        raise RuntimeError(f"Odoo error ({model}.{method}): {data['error']}")
                    return data.get("result", data)
                
                return data

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    log.error(f"Model or method not found (404): {model}.{method}")
                    raise
                log.warning(f"Attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    wait = 2 ** attempt
                    log.info(f"Retrying in {wait}s...")
                    time.sleep(wait)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                log.warning(f"Attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    wait = 2 ** attempt
                    log.info(f"Retrying in {wait}s...")
                    time.sleep(wait)

        raise RuntimeError(f"All {max_retries} attempts failed for {model}.{method}")
