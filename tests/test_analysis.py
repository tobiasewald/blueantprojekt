import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# Mock settings before importing app modules
import os
os.environ["BLUEANT_API_KEY"] = "mock-blueant-key"
os.environ["OLLAMA_API_KEY"] = "mock-ollama-key"

from app.config import settings
from app.prompt_engine import prompt_engine
from app.blueant_client import blueant_client
from app.analysis_service import analysis_service
from app.main import app

class TestConfig(unittest.TestCase):
    def test_settings_load(self):
        self.assertEqual(settings.blueant_api_key, "mock-blueant-key")
        self.assertEqual(settings.ollama_api_key, "mock-ollama-key")
        self.assertTrue(settings.blueant_url.startswith("http"))

class TestPromptEngine(unittest.TestCase):
    def test_format_project_prompt(self):
        project = {
            "id": 42,
            "name": "Super Test Project",
            "number": "P-42",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-12-31T23:59:59Z",
            "overallRisk": {"color": "red", "name": "High Risk"},
            "statusMemo": "Status memo content",
            "subjectMemo": "Subject memo content",
            "problemMemo": "Problem memo content"
        }
        kpis = [
            {"name": "Plan-Aufwand", "value": 100.0, "unit": "h"},
            {"name": "Ist-Aufwand", "value": 45.0, "unit": "h"},
            {"name": "Projektfortschritt", "value": 50.0, "unit": "%"}
        ]
        status_history = [
            {"date": "2026-02-15", "comment": "Initial status", "oldStatusId": {"name": "Draft"}, "newStatusId": {"name": "Active"}}
        ]
        
        prompt = prompt_engine.format_project_prompt(project, kpis, status_history)
        
        self.assertIn("Super Test Project", prompt)
        self.assertIn("P-42", prompt)
        self.assertIn("Plan-Aufwand: 100.0 h", prompt)
        self.assertIn("Ist-Aufwand: 45.0 h", prompt)
        self.assertIn("red", prompt)
        self.assertIn("Status changed from Draft to Active", prompt)

class TestBlueAntClientCaching(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient.request")
    async def test_api_caching(self, mock_request):
        # Configure mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"projects": [{"id": 1, "name": "Cached Project"}]}
        mock_request.return_value = mock_response
        
        # Clear cache first
        blueant_client.clear_cache()
        
        # First call (should hit mock API)
        res1 = await blueant_client.get_projects(api_key="test-key")
        self.assertEqual(res1[0]["name"], "Cached Project")
        self.assertEqual(mock_request.call_count, 1)
        
        # Second call (should hit cache, mock API call count should remain 1)
        res2 = await blueant_client.get_projects(api_key="test-key")
        self.assertEqual(res2[0]["name"], "Cached Project")
        self.assertEqual(mock_request.call_count, 1)

class TestAnalysisService(unittest.IsolatedAsyncioTestCase):
    @patch("app.blueant_client.BlueAntClient.get_project")
    @patch("app.blueant_client.BlueAntClient.get_project_kpis")
    @patch("app.blueant_client.BlueAntClient.get_project_status_history")
    @patch("app.llm_client.LLMClient.generate_analysis")
    async def test_analyze_project_success(self, mock_llm, mock_history, mock_kpis, mock_project):
        # Configure mocks
        mock_project.return_value = {"id": 1, "name": "Proj 1"}
        mock_kpis.return_value = [{"name": "Plan-Aufwand", "value": 100.0}]
        mock_history.return_value = []
        
        mock_llm.return_value = """
        {
            "project_id": 1,
            "project_name": "Proj 1",
            "timestamp": "2026-05-21T00:00:00",
            "effort_analysis": {
                "planned_hours": 100.0,
                "actual_hours": 20.0,
                "variance_hours": -80.0,
                "variance_percent": -80.0,
                "assessment": "Under budget"
            },
            "progress_analysis": {
                "progress_percent": 20.0,
                "elapsed_time_percent": 10.0,
                "status_relative_to_deadline": "On track"
            },
            "predictions": {
                "estimated_remaining_hours": 80.0,
                "forecasted_total_hours": 100.0,
                "expected_completion_date": "2026-12-31",
                "prognosis_confidence": "high",
                "prognosis_text": "Looks fine"
            },
            "text_summaries": {
                "status_summary": "Good",
                "subject_summary": "Objectives",
                "problems_summary": "None"
            },
            "risk_assessment": {
                "statusampel": "green",
                "is_critical": false,
                "criticality_level": "low",
                "criticality_reasons": [],
                "goals_vs_status_eval": "Aligned"
            }
        }
        """
        
        result = await analysis_service.analyze_project(project_id=1, api_key="test-key")
        self.assertEqual(result["project_id"], 1)
        self.assertEqual(result["risk_assessment"]["statusampel"], "green")
        self.assertFalse(result["risk_assessment"]["is_critical"])

    @patch("app.blueant_client.BlueAntClient.get_project")
    @patch("app.blueant_client.BlueAntClient.get_project_kpis")
    @patch("app.blueant_client.BlueAntClient.get_project_status_history")
    @patch("app.llm_client.LLMClient.generate_analysis")
    async def test_analyze_project_fallback_on_llm_error(self, mock_llm, mock_history, mock_kpis, mock_project):
        # Configure mocks to simulate LLM fail
        mock_project.return_value = {"id": 1, "name": "Proj 1", "overallRisk": {"color": "red"}}
        mock_kpis.return_value = [
            {"name": "Plan-Aufwand", "value": 100.0},
            {"name": "Ist-Aufwand", "value": 120.0}
        ]
        mock_history.return_value = []
        mock_llm.return_value = None  # Simulates failure
        
        result = await analysis_service.analyze_project(project_id=1, api_key="test-key")
        self.assertEqual(result["project_id"], 1)
        self.assertEqual(result["effort_analysis"]["planned_hours"], 100.0)
        self.assertEqual(result["effort_analysis"]["actual_hours"], 120.0)
        self.assertEqual(result["effort_analysis"]["variance_hours"], 20.0)
        self.assertEqual(result["risk_assessment"]["statusampel"], "red")
        self.assertTrue(result["risk_assessment"]["is_critical"])
        self.assertIn("fallback", result["effort_analysis"]["assessment"].lower())

class TestFastAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    def test_get_prompts(self):
        response = self.client.get("/api/prompts")
        self.assertEqual(response.status_code, 200)
        self.assertIn("system_prompt", response.json())
        self.assertIn("project_analysis_prompt", response.json())

    def test_serve_index_root(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Blue Ant KI", response.text)

    def test_serve_index_dashboard(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Blue Ant KI", response.text)


if __name__ == "__main__":
    unittest.main()

