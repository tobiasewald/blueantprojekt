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
from app.project_metrics import (
    compute_effort_forecast,
    compute_elapsed_time_percent,
    compute_forecast_completion_date,
    evaluate_criticality,
)
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

    def test_real_blueant_shape_counts_overdue(self):
        """Regression test against the real payload shape from the demo tenant:
        milestones have start == end (a milestone is a point in time, so "end" is
        the PLANNED date, not a completion date) and usually no "endWished".
        Treating a set "end" as "completed" previously made every milestone count
        as done, so the dashboard always reported 0 overdue."""
        import datetime
        milestones = [
            {"description": "Projektstart", "startWished": None, "endWished": None,
             "start": "2020-06-30T17:30:00+02:00", "end": "2020-06-30T17:30:00+02:00", "progressActual": 0.0},
            {"description": "Freigabe", "startWished": "2021-06-06", "endWished": None,
             "start": "2021-06-06T16:00:00+02:00", "end": "2021-06-06T16:00:00+02:00", "progressActual": 100.0},
            {"description": "Abnahme", "startWished": "2024-10-30", "endWished": "2024-10-30",
             "start": "2024-10-30T23:00:00+01:00", "end": "2024-10-30T23:00:00+01:00", "progressActual": 0.0},
        ]
        result = summarize_milestones(milestones, today=datetime.date(2026, 7, 23))
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(result["overdue_count"], 2)

    def test_future_milestone_is_not_overdue(self):
        import datetime
        milestones = [
            {"description": "Zukunft", "endWished": None,
             "start": "2030-01-01T00:00:00+01:00", "end": "2030-01-01T00:00:00+01:00", "progressActual": 0.0},
        ]
        result = summarize_milestones(milestones, today=datetime.date(2026, 7, 23))
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


class TestProjectMetrics(unittest.TestCase):
    """Regression tests for defects found during the live demo review."""

    def test_elapsed_time_computed_for_date_only_range(self):
        """Bug: 'Verstrichene Zeit (Soll)' showed N/A although start and end dates
        existed, because the value was only passed into the prompt and never
        written back - the displayed value came unchecked from the LLM."""
        import datetime
        pct = compute_elapsed_time_percent(
            "2020-04-01", "2020-12-31", now=datetime.datetime(2020, 7, 1, tzinfo=datetime.timezone.utc)
        )
        self.assertIsNotNone(pct)
        self.assertGreater(pct, 0.0)
        self.assertLess(pct, 100.0)

    def test_elapsed_time_none_when_dates_missing(self):
        self.assertIsNone(compute_elapsed_time_percent(None, None))
        self.assertIsNone(compute_elapsed_time_percent("2020-01-01", ""))

    def test_criticality_flag_and_level_never_contradict(self):
        """Bug: the detail modal showed 'Kritikalität: Mittel' while the overview
        table showed 'Stabil', because is_critical and criticality_level were two
        independent LLM outputs."""
        critical = evaluate_criticality("yellow", 0.0, 50.0, 50.0, 0)
        self.assertTrue(critical["is_critical"])
        self.assertNotEqual(critical["criticality_level"], "low")

        stable = evaluate_criticality("green", 0.0, 50.0, 50.0, 0)
        self.assertFalse(stable["is_critical"])
        self.assertEqual(stable["criticality_level"], "low")

    def test_criticality_reacts_to_statusampel(self):
        self.assertTrue(evaluate_criticality("red", 0.0, 50.0, 50.0, 0)["is_critical"])
        self.assertFalse(evaluate_criticality("unbekannt", 0.0, 50.0, 50.0, 0)["is_critical"])

    def test_effort_forecast_matches_linear_extrapolation(self):
        """Regression test with the real figures of project #362519895, where the
        LLM reported 130,404 remaining hours instead of 259 - a factor of ~500."""
        forecast = compute_effort_forecast(planned_hours=4535.01, actual_hours=318.57, progress_percent=55.15)
        self.assertAlmostEqual(forecast["estimated_remaining_hours"], 259.07, places=1)
        self.assertAlmostEqual(forecast["forecasted_total_hours"], 577.64, places=1)

    def test_effort_forecast_without_progress_falls_back_to_plan(self):
        forecast = compute_effort_forecast(planned_hours=100.0, actual_hours=30.0, progress_percent=0.0)
        self.assertEqual(forecast["estimated_remaining_hours"], 70.0)
        self.assertEqual(forecast["forecasted_total_hours"], 100.0)

    def test_forecast_completion_date_needs_a_basis(self):
        self.assertIsNone(compute_forecast_completion_date(None, None, 50.0))
        self.assertIsNone(compute_forecast_completion_date("2020-01-01", "2021-01-01", 0.0))

    def test_forecast_completion_date_extrapolates(self):
        import datetime
        # Half done one year in -> roughly another year to go (2024 is a leap year,
        # so the doubled span lands on 2026-01-02).
        result = compute_forecast_completion_date(
            "2024-01-01", "2025-01-01", 50.0,
            now=datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
        )
        self.assertEqual(result, "2026-01-02")

    def test_completed_project_forecast_uses_end_date(self):
        result = compute_forecast_completion_date("2020-01-01", "2021-06-30", 100.0)
        self.assertEqual(result, "2021-06-30")

    def test_criticality_detects_progress_lag(self):
        result = evaluate_criticality("green", 0.0, 10.0, 80.0, 0)
        self.assertTrue(result["is_critical"])
        self.assertTrue(any("Fortschritt" in r for r in result["criticality_reasons"]))


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
        # Configure mocks. The Statusampel is taken from the Blue Ant record, not
        # from whatever the LLM claims, so the project must carry a resolved risk.
        mock_project.return_value = {
            "id": 1,
            "name": "Proj 1",
            "overallRisk": {"color": "green", "name": "A - gering"},
        }
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
    @patch("app.blueant_client.BlueAntClient.get_project_kpis")
    @patch("app.blueant_client.BlueAntClient.get_project_status_history")
    @patch("app.blueant_client.BlueAntClient.get_project_milestones")
    @patch("app.llm_client.LLMClient.generate_analysis")
    async def test_contradictory_llm_output_is_corrected(self, mock_llm, mock_milestones, mock_history, mock_kpis, mock_project):
        """The LLM claims a green, non-critical project with a made-up elapsed time,
        while the Blue Ant data says the traffic light is red. The data must win."""
        mock_project.return_value = {
            "id": 7,
            "name": "Contradiction Test",
            "start": "2020-01-01",
            "end": "2030-01-01",
            "overallRisk": {"color": "red", "name": "C - hoch"},
        }
        mock_kpis.return_value = []
        mock_history.return_value = []
        mock_milestones.return_value = []
        mock_llm.return_value = """
        {
            "project_id": 7,
            "progress_analysis": {"progress_percent": 99.0, "elapsed_time_percent": 12345.0},
            "risk_assessment": {"statusampel": "green", "is_critical": false, "criticality_level": "medium"}
        }
        """

        result = await analysis_service.analyze_project(project_id=7, api_key="test-key")

        self.assertEqual(result["risk_assessment"]["statusampel"], "red")
        self.assertTrue(result["risk_assessment"]["is_critical"])
        self.assertNotEqual(result["risk_assessment"]["criticality_level"], "low")
        self.assertNotEqual(result["progress_analysis"]["elapsed_time_percent"], 12345.0)
        self.assertLessEqual(result["progress_analysis"]["elapsed_time_percent"], 100.0)

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
