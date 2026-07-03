import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# Mock settings before importing app modules
import os
os.environ["BLUEANT_API_KEY"] = "mock-blueant-key"
os.environ["OLLAMA_API_KEY"] = "mock-ollama-key"

from app.config import settings
from app.prompt_engine import prompt_engine
from app.blueant_client import blueant_client, normalize_risk_color
from app.kpi_utils import extract_effort_kpis
from app.milestone_utils import summarize_milestones
from app.analysis_service import analysis_service
from app.main import app


class TestConfig(unittest.TestCase):
    def test_settings_load(self):
        self.assertEqual(settings.blueant_api_key, "mock-blueant-key")
        self.assertEqual(settings.ollama_api_key, "mock-ollama-key")
        self.assertTrue(settings.blueant_url.startswith("http"))


class TestKpiUtils(unittest.TestCase):
    def test_priority_matching_prefers_total_kpi_over_subproject(self):
        kpis = [
            {"id": "SomeSubBudgetTeilprojektAufwandPlan", "name": "Teilprojekt Plan-Aufwand", "value": 10.0, "unit": "h"},
            {"id": "WorkTotalPlan", "name": "Gesamtaufwand Plan", "value": 100.0, "unit": "h"},
        ]
        result = extract_effort_kpis(kpis)
        self.assertEqual(result["planned_hours"], 100.0)

    def test_pt_converted_to_hours(self):
        kpis = [{"id": "WorkTotalPlan", "name": "Plan", "value": 5.0, "unit": "PT"}]
        result = extract_effort_kpis(kpis)
        self.assertEqual(result["planned_hours"], 40.0)


class TestMilestoneUtils(unittest.TestCase):
    def test_overdue_milestone_detected(self):
        import datetime
        milestones = [
            {"description": "Kickoff", "endWished": "2020-01-01", "end": "2020-01-01", "progressActual": 100},
            {"description": "Go-Live", "endWished": "2020-01-01", "end": None, "progressActual": 40},
        ]
        result = summarize_milestones(milestones, today=datetime.date(2026, 1, 1))
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(result["overdue_count"], 1)

    def test_no_milestones(self):
        result = summarize_milestones([])
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["overdue_count"], 0)


class TestRiskColorNormalization(unittest.TestCase):
    def test_recognizes_german_and_english_names(self):
        self.assertEqual(normalize_risk_color("Rot"), "red")
        self.assertEqual(normalize_risk_color("Yellow"), "yellow")
        self.assertEqual(normalize_risk_color("Grün"), "green")
        self.assertEqual(normalize_risk_color(None), "unbekannt")
        self.assertEqual(normalize_risk_color("Sonderfall"), "sonderfall")

    def test_recognizes_severity_level_naming(self):
        """Regression test: the live demo tenant uses severity levels
        ("A - gering", "B - mittel", "C - hoch") instead of traffic-light colors."""
        self.assertEqual(normalize_risk_color("C - hoch"), "red")
        self.assertEqual(normalize_risk_color("B - mittel"), "yellow")
        self.assertEqual(normalize_risk_color("A - gering"), "green")


class TestStatusampelResolution(unittest.TestCase):
    """Regression tests for resolving the Statusampel from the custom 'Status Ampel
    manuell' listbox field (confirmed against the live demo tenant), with the
    built-in overallRisk field as fallback when the custom field isn't set."""

    def test_custom_field_takes_priority(self):
        project = {"id": 1, "customFields": {"999": "2"}}
        blueant_client._resolve_statusampel(project, 999, {"2": "Gelb"}, {})
        self.assertEqual(project["overallRisk"]["color"], "yellow")
        self.assertEqual(project["overallRisk"]["name"], "Gelb")

    def test_falls_back_to_overall_risk_when_custom_field_unset(self):
        project = {"id": 2, "overallRisk": {"overallRiskId": 5, "riskAssessment": "x"}}
        blueant_client._resolve_statusampel(project, 999, {"2": "Gelb"}, {5: "C - hoch"})
        self.assertEqual(project["overallRisk"]["color"], "red")

    def test_no_data_available_leaves_unresolved(self):
        project = {"id": 3}
        blueant_client._resolve_statusampel(project, None, {}, {})
        self.assertNotIn("overallRisk", project)


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

    def test_date_only_start_end_does_not_crash_and_computes_progress(self):
        """Regression test: Blue Ant returns start/end as date-only strings
        ("2018-09-21"), not full ISO datetimes. This previously produced a naive
        datetime that crashed when compared against a timezone-aware "now"."""
        project = {
            "id": 1, "name": "Date Test", "number": "P-1",
            "start": "2020-01-01", "end": "2030-01-01",
        }
        prompt = prompt_engine.format_project_prompt(project, [], [])
        self.assertNotIn("elapsed_time_percent=0.0", prompt.replace(" ", ""))

    def test_null_memo_fields_do_not_crash(self):
        """Regression test: project.get("problemMemo", "None") returns None (not
        the string default) when Blue Ant sends an explicit null, which used to
        crash on problem_memo.lower()."""
        project = {
            "id": 2, "name": "Null Memo Test", "number": "P-2",
            "start": "2026-01-01", "end": "2026-06-01",
            "statusMemo": None, "subjectMemo": None, "problemMemo": None,
        }
        # Should not raise
        prompt = prompt_engine.format_project_prompt(project, [], [])
        self.assertIn("Null Memo Test", prompt)

    def test_overdue_milestone_marks_project_critical(self):
        project = {"id": 3, "name": "Milestone Test", "number": "P-3"}
        milestones = [
            {"description": "Meilenstein 1", "endWished": "2020-01-01", "end": None, "progressActual": 10},
        ]
        prompt = prompt_engine.format_project_prompt(project, [], [], milestones)
        self.assertIn("is_critical", prompt)


class TestBlueAntClientCaching(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient.request")
    async def test_api_caching(self, mock_request):
        # Configure mock response (used for both the projects list and the
        # overall-risk masterdata lookup that get_projects() now also performs)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"projects": [{"id": 1, "name": "Cached Project"}], "risks": []}
        mock_request.return_value = mock_response

        # Clear cache first
        blueant_client.clear_cache()

        # First call (should hit mock API for the project list + the risk masterdata)
        res1 = await blueant_client.get_projects(api_key="test-key")
        self.assertEqual(res1[0]["name"], "Cached Project")
        first_call_count = mock_request.call_count
        self.assertGreaterEqual(first_call_count, 1)

        # Second call (should hit cache for both, no additional HTTP calls)
        res2 = await blueant_client.get_projects(api_key="test-key")
        self.assertEqual(res2[0]["name"], "Cached Project")
        self.assertEqual(mock_request.call_count, first_call_count)


class TestAnalysisService(unittest.IsolatedAsyncioTestCase):
    @patch("app.blueant_client.BlueAntClient.get_project")
    @patch("app.blueant_client.BlueAntClient.get_project_kpis")
    @patch("app.blueant_client.BlueAntClient.get_project_status_history")
    @patch("app.blueant_client.BlueAntClient.get_project_milestones")
    @patch("app.llm_client.LLMClient.generate_analysis")
    async def test_analyze_project_success(self, mock_llm, mock_milestones, mock_history, mock_kpis, mock_project):
        # Configure mocks
        mock_project.return_value = {"id": 1, "name": "Proj 1"}
        mock_kpis.return_value = [{"name": "Plan-Aufwand", "value": 100.0}]
        mock_history.return_value = []
        mock_milestones.return_value = []

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
    @patch("app.blueant_client.BlueAntClient.get_project_milestones")
    @patch("app.llm_client.LLMClient.generate_analysis")
    async def test_analyze_project_fallback_on_llm_error(self, mock_llm, mock_milestones, mock_history, mock_kpis, mock_project):
        # Configure mocks to simulate LLM fail
        mock_project.return_value = {"id": 1, "name": "Proj 1", "overallRisk": {"color": "red"}}
        mock_kpis.return_value = [
            {"name": "Plan-Aufwand", "value": 100.0},
            {"name": "Ist-Aufwand", "value": 120.0}
        ]
        mock_history.return_value = []
        mock_milestones.return_value = []
        mock_llm.return_value = None  # Simulates failure

        result = await analysis_service.analyze_project(project_id=1, api_key="test-key")
        self.assertEqual(result["project_id"], 1)
        self.assertEqual(result["effort_analysis"]["planned_hours"], 100.0)
        self.assertEqual(result["effort_analysis"]["actual_hours"], 120.0)
        self.assertEqual(result["effort_analysis"]["variance_hours"], 20.0)
        self.assertEqual(result["risk_assessment"]["statusampel"], "red")
        self.assertTrue(result["risk_assessment"]["is_critical"])
        self.assertIn("fallback", result["effort_analysis"]["assessment"].lower())

    @patch("app.blueant_client.BlueAntClient.get_project")
    @patch("app.blueant_client.BlueAntClient.get_project_kpis")
    @patch("app.blueant_client.BlueAntClient.get_project_status_history")
    @patch("app.blueant_client.BlueAntClient.get_project_milestones")
    @patch("app.llm_client.LLMClient.generate_analysis")
    async def test_analyze_project_null_memo_does_not_500(self, mock_llm, mock_milestones, mock_history, mock_kpis, mock_project):
        """Regression test for the null-memo crash: a project with problemMemo=None
        must still produce a fallback analysis instead of raising."""
        mock_project.return_value = {"id": 5, "name": "Proj Null Memo", "problemMemo": None, "statusMemo": None, "subjectMemo": None}
        mock_kpis.return_value = []
        mock_history.return_value = []
        mock_milestones.return_value = []
        mock_llm.return_value = None

        result = await analysis_service.analyze_project(project_id=5, api_key="test-key")
        self.assertEqual(result["project_id"], 5)
        self.assertNotIn("error", result)

    @patch("app.blueant_client.BlueAntClient.get_project")
    async def test_analyze_project_not_found(self, mock_project):
        mock_project.return_value = None
        result = await analysis_service.analyze_project(project_id=999, api_key="test-key")
        self.assertIn("error", result)
        self.assertEqual(result["status_code"], 404)


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
