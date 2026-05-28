import time
import logging
from typing import Dict, Any, List, Optional
import httpx
from app.config import settings

logger = logging.getLogger("blueant_client")
logging.basicConfig(level=logging.INFO)

class BlueAntClient:
    def __init__(self):
        self.base_url = settings.blueant_url
        self.cache_ttl = settings.blueant_cache_ttl
        # Simple in-memory cache: {cache_key: (timestamp, data)}
        self._cache: Dict[str, tuple[float, Any]] = {}

    def _get_auth_headers(self, api_key: Optional[str] = None) -> Dict[str, str]:
        # Use provided api_key, default to settings key
        token = api_key or settings.blueant_api_key
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["BA-Authorization"] = token
        return headers

    def _get_cache_key(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> str:
        param_str = ""
        if params:
            param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{endpoint}?{param_str}"

    def _get_cached_data(self, key: str) -> Optional[Any]:
        if key in self._cache:
            timestamp, data = self._cache[key]
            if time.time() - timestamp < settings.blueant_cache_ttl:
                logger.info(f"Cache hit for: {key}")
                return data
            else:
                logger.info(f"Cache expired for: {key}")
                del self._cache[key]
        return None

    def _set_cached_data(self, key: str, data: Any):
        self._cache[key] = (time.time(), data)

    def clear_cache(self):
        self._cache.clear()
        logger.info("Blue Ant client cache cleared.")

    async def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, api_key: Optional[str] = None) -> Any:
        url = f"{settings.blueant_url.rstrip('/')}/{endpoint.lstrip('/')}"
        cache_key = self._get_cache_key(endpoint, params)

        # Only GET requests are cached
        if method.upper() == "GET":
            cached = self._get_cached_data(cache_key)
            if cached is not None:
                return cached

        headers = self._get_auth_headers(api_key)
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                logger.info(f"Sending API request: {method} {url} with params: {params}")
                response = await client.request(method, url, headers=headers, params=params)
                
                # Check for unauthorized or bad responses
                if response.status_code == 401:
                    logger.error("Authentication failed for Blue Ant API. Invalid or missing API key.")
                    raise httpx.HTTPStatusError("Unauthorized", request=response.request, response=response)
                
                response.raise_for_status()
                data = response.json()

                if method.upper() == "GET":
                    self._set_cached_data(cache_key, data)

                return data
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
                raise e
            except httpx.RequestError as e:
                logger.error(f"Network error occurred while requesting {e.request.url}: {e}")
                raise e

    async def get_portfolios(self, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all portfolios from Blue Ant."""
        try:
            res = await self._request("GET", "/v1/portfolios", api_key=api_key)
            return res.get("portfolios", [])
        except Exception as e:
            logger.error(f"Failed to fetch portfolios: {e}")
            return []

    async def get_portfolio(self, portfolio_id: int, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch details for a single portfolio."""
        try:
            res = await self._request("GET", f"/v1/portfolios/{portfolio_id}", api_key=api_key)
            return res.get("portfolio")
        except Exception as e:
            logger.error(f"Failed to fetch portfolio {portfolio_id}: {e}")
            return None

    async def get_projects(self, include_archived: bool = False, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all projects with memos and overall risk (traffic lights) in a single request."""
        params = {
            "includeMemoFields": "true",
            "includeOverallRisk": "true",
            "includeCustomFields": "true",
            "includeArchived": "true" if include_archived else "false"
        }
        try:
            res = await self._request("GET", "/v1/projects", params=params, api_key=api_key)
            return res.get("projects", [])
        except Exception as e:
            logger.error(f"Failed to fetch projects: {e}")
            return []

    async def get_project(self, project_id: int, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single project by its ID."""
        params = {
            "includeMemoFields": "true",
            "includeOverallRisk": "true",
            "includeCustomFields": "true"
        }
        try:
            res = await self._request("GET", f"/v1/projects/{project_id}", params=params, api_key=api_key)
            return res.get("project")
        except Exception as e:
            logger.error(f"Failed to fetch project {project_id}: {e}")
            return None

    async def get_project_kpis(self, project_id: int, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch KPIs for a specific project."""
        try:
            res = await self._request("GET", f"/v1/projects/{project_id}/kpis", api_key=api_key)
            return res.get("kpis", [])
        except Exception as e:
            logger.error(f"Failed to fetch KPIs for project {project_id}: {e}")
            return []

    async def get_project_status_history(self, project_id: int, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch the status history list for a project."""
        try:
            res = await self._request("GET", f"/v1/projects/{project_id}/statushistory", api_key=api_key)
            return res.get("projectStatusHistory", [])
        except Exception as e:
            logger.error(f"Failed to fetch status history for project {project_id}: {e}")
            return []

# Global instance of Blue Ant client
blueant_client = BlueAntClient()
