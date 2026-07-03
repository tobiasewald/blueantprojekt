import time
import logging
from typing import Dict, Any, List, Optional
import httpx
from app.config import settings

logger = logging.getLogger("blueant_client")
logging.basicConfig(level=logging.INFO)

# Keywords used to classify a Blue Ant "overall risk" masterdata name (which is
# free text configured per instance, e.g. "Rot"/"Gelb"/"Grün" or "Red/Yellow/Green")
# into the red/yellow/green traffic-light buckets the dashboard understands.
_RISK_COLOR_KEYWORDS = {
    "red": ("rot", "red", "kritisch", "critical"),
    "yellow": ("gelb", "yellow", "amber", "orange", "warn"),
    "green": ("grün", "gruen", "green", "ok"),
}


def normalize_risk_color(name: Optional[str]) -> str:
    """Map a masterdata risk-level name to green/yellow/red, or fall back to the raw name."""
    if not name:
        return "unbekannt"
    lname = name.lower()
    for color, keywords in _RISK_COLOR_KEYWORDS.items():
        if any(kw in lname for kw in keywords):
            return color
    return lname


class BlueAntAPIError(Exception):
    """Raised when a Blue Ant request fails, carrying enough info to map to an HTTP status."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class BlueAntClient:
    def __init__(self):
        # Simple in-memory cache: {cache_key: (timestamp, data)}
        self._cache: Dict[str, tuple] = {}

    def _get_auth_headers(self, api_key: Optional[str] = None) -> Dict[str, str]:
        token = api_key or settings.blueant_api_key
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
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

                if response.status_code in (401, 403):
                    logger.error("Authentication failed for Blue Ant API. Invalid or missing API key.")
                    raise BlueAntAPIError("Blue Ant hat den API-Key abgelehnt (401/403).", status_code=401)

                if response.status_code == 404:
                    raise BlueAntAPIError(f"Blue Ant meldet 404 für {endpoint}.", status_code=404)

                response.raise_for_status()
                data = response.json()

                if method.upper() == "GET":
                    self._set_cached_data(cache_key, data)

                return data
            except BlueAntAPIError:
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
                raise BlueAntAPIError(f"Blue Ant antwortete mit Status {e.response.status_code}.", status_code=502)
            except httpx.RequestError as e:
                logger.error(f"Network error occurred while requesting {e.request.url}: {e}")
                raise BlueAntAPIError(f"Blue Ant war nicht erreichbar: {e}", status_code=502)

    # --- Masterdata lookups (cached like any other GET, resolved lazily) -------------

    async def _get_overall_risk_map(self, api_key: Optional[str] = None) -> Dict[Any, str]:
        """id -> risk-level name, e.g. {1: "Rot", 2: "Gelb", 3: "Grün"}."""
        try:
            res = await self._request("GET", "/v1/masterdata/projects/overallrisks", api_key=api_key)
            return {r.get("id"): r.get("name") for r in res.get("risks", [])}
        except Exception as e:
            logger.error(f"Failed to fetch overall risk masterdata: {e}")
            return {}

    async def _get_project_status_map(self, api_key: Optional[str] = None) -> Dict[Any, str]:
        """id -> workflow status text, e.g. {1: "Aktiv", 2: "Abgeschlossen"}."""
        try:
            res = await self._request("GET", "/v1/masterdata/projects/statuses", api_key=api_key)
            return {s.get("id"): s.get("text") for s in res.get("statuses", [])}
        except Exception as e:
            logger.error(f"Failed to fetch project status masterdata: {e}")
            return {}

    def _resolve_overall_risk(self, project: Dict[str, Any], risk_map: Dict[Any, str]) -> None:
        """Replace project['overallRisk'] (raw {overallRiskId, riskAssessment}) with a
        resolved {id, name, color, assessment} object so downstream code can read
        color/name directly."""
        risk_obj = project.get("overallRisk")
        if not isinstance(risk_obj, dict):
            return
        risk_id = risk_obj.get("overallRiskId")
        name = risk_map.get(risk_id)
        project["overallRisk"] = {
            "id": risk_id,
            "name": name or "Unbekannt",
            "color": normalize_risk_color(name),
            "assessment": risk_obj.get("riskAssessment", ""),
        }

    async def get_portfolios(self, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all portfolios from Blue Ant."""
        res = await self._request("GET", "/v1/portfolios", api_key=api_key)
        return res.get("portfolios", [])

    async def get_portfolio(self, portfolio_id: int, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch details for a single portfolio."""
        res = await self._request("GET", f"/v1/portfolios/{portfolio_id}", api_key=api_key)
        return res.get("portfolio")

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
            projects = res.get("projects", [])
        except Exception as e:
            logger.error(f"Failed to fetch projects: {e}")
            return []

        risk_map = await self._get_overall_risk_map(api_key=api_key)
        for p in projects:
            self._resolve_overall_risk(p, risk_map)
        return projects

    async def get_project(self, project_id: int, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single project by its ID."""
        params = {
            "includeMemoFields": "true",
            "includeOverallRisk": "true",
            "includeCustomFields": "true"
        }
        res = await self._request("GET", f"/v1/projects/{project_id}", params=params, api_key=api_key)
        project = res.get("project")
        if project:
            risk_map = await self._get_overall_risk_map(api_key=api_key)
            self._resolve_overall_risk(project, risk_map)
        return project

    async def get_project_kpis(self, project_id: int, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch KPIs for a specific project."""
        try:
            res = await self._request("GET", f"/v1/projects/{project_id}/kpis", api_key=api_key)
            return res.get("kpis", [])
        except Exception as e:
            logger.error(f"Failed to fetch KPIs for project {project_id}: {e}")
            return []

    async def get_project_status_history(self, project_id: int, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch the status history list for a project, with old/new status ids resolved to names."""
        try:
            res = await self._request("GET", f"/v1/projects/{project_id}/statushistory", api_key=api_key)
            history = res.get("projectStatusHistory", [])
        except Exception as e:
            logger.error(f"Failed to fetch status history for project {project_id}: {e}")
            return []

        status_map = await self._get_project_status_map(api_key=api_key)
        for h in history:
            for key in ("oldStatusId", "newStatusId"):
                raw = h.get(key)
                if isinstance(raw, dict):
                    continue  # already expanded
                h[key] = {"name": status_map.get(raw, "Unbekannt")}
        return history

    async def get_project_milestones(self, project_id: int, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch planning entries for a project and return only the milestone entries."""
        try:
            res = await self._request("GET", f"/v1/projects/{project_id}/planningentries", api_key=api_key)
            entries = res.get("entries", [])
            return [e for e in entries if str(e.get("entryType", "")).lower() == "milestone"]
        except Exception as e:
            logger.error(f"Failed to fetch milestones for project {project_id}: {e}")
            return []


# Global instance of Blue Ant client
blueant_client = BlueAntClient()
