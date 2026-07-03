import json
import logging
import asyncio
import datetime
from typing import Dict, Any, List, Optional
from app.blueant_client import blueant_client, BlueAntAPIError
from app.prompt_engine import prompt_engine
from app.llm_client import llm_client
from app.kpi_utils import extract_effort_kpis
from app.milestone_utils import summarize_milestones

logger = logging.getLogger("analysis_service")


class AnalysisService:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(3)  # Max 3 concurrent LLM queries

    def _clean_json_response(self, text: str) -> str:
        """Clean markdown markers or extra text if the LLM output is not clean JSON."""
        text = text.strip()
        if text.startswith("```"):
            # Try to strip ```json ... ``` or ``` ... ```
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Find first '{' and last '}'
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx + 1]
        return text

    async def analyze_project(self, project_id: int, api_key: Optional[str] = None, ollama_api_key: Optional[str] = None) -> Dict[str, Any]:
        """Fetch project details, format prompts, run LLM analysis, and return structured JSON."""
        # 1. Fetch data from Blue Ant
        try:
            project = await blueant_client.get_project(project_id, api_key=api_key)
        except BlueAntAPIError as e:
            return {"error": str(e), "status_code": e.status_code}
        if not project:
            return {"error": f"Project {project_id} not found in Blue Ant.", "status_code": 404}

        kpis = await blueant_client.get_project_kpis(project_id, api_key=api_key)
        logger.info(f"FETCHED KPIs for project {project_id}: {kpis}")
        status_history = await blueant_client.get_project_status_history(project_id, api_key=api_key)
        milestones = await blueant_client.get_project_milestones(project_id, api_key=api_key)

        # 2. Format Prompt & 3. Call LLM. Any failure here (bad user-edited prompt
        # template, unexpected data shape, etc.) must degrade to the rule-based
        # fallback instead of surfacing as an unhandled 500.
        try:
            prompt = prompt_engine.format_project_prompt(project, kpis, status_history, milestones)
            system_prompt = prompt_engine.system_prompt
            async with self.semaphore:
                llm_response = await llm_client.generate_analysis(prompt, system_prompt, api_key=ollama_api_key)
        except Exception as e:
            logger.error(f"Failed to build prompt or reach LLM for project {project_id}: {e}")
            return self._generate_project_fallback(project, kpis, milestones, f"Prompt/LLM error: {str(e)}")

        # 4. Parse & Fallback
        if not llm_response:
            logger.warning(f"LLM generated no response for project {project_id}. Generating fallback analysis.")
            return self._generate_project_fallback(project, kpis, milestones, "LLM failed to return a response.")

        try:
            cleaned_text = self._clean_json_response(llm_response)
            parsed_json = json.loads(cleaned_text)
            return parsed_json
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON for project {project_id}: {e}. Raw response: {llm_response}")
            return self._generate_project_fallback(project, kpis, milestones, f"Failed to parse LLM output: {str(e)}")

    def _generate_project_fallback(
        self,
        project: Dict[str, Any],
        kpis: List[Dict[str, Any]],
        milestones: List[Dict[str, Any]],
        error_msg: str
    ) -> Dict[str, Any]:
        """Generate a rule-based fallback analysis if the LLM fails."""
        project_id = project.get("id", 0)
        project_name = project.get("name", "Unnamed Project")

        overall_risk_obj = project.get("overallRisk")
        overall_risk = "N/A"
        if isinstance(overall_risk_obj, dict):
            overall_risk = overall_risk_obj.get("color") or overall_risk_obj.get("name") or "N/A"
        elif isinstance(overall_risk_obj, str):
            overall_risk = overall_risk_obj

        effort = extract_effort_kpis(kpis)
        planned_hours = effort["planned_hours"]
        actual_hours = effort["actual_hours"]
        progress_percent = effort["progress_percent"]
        variance_hours = effort["variance_hours"]
        variance_percent = effort["variance_percent"]

        milestone_summary = summarize_milestones(milestones or [])

        criticality_reasons = []
        if overall_risk.lower() in ["red", "yellow"]:
            criticality_reasons.append(f"Statusampel steht auf {overall_risk}.")
        if variance_percent > 15.0:
            criticality_reasons.append(f"Aufwandsabweichung von {variance_percent}% überschreitet die Schwelle.")
        if milestone_summary["overdue_count"] > 0:
            criticality_reasons.append(f"{milestone_summary['overdue_count']} Meilenstein(e) überfällig.")
        is_critical = len(criticality_reasons) > 0

        return {
            "project_id": project_id,
            "project_name": project_name,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "effort_analysis": {
                "planned_hours": planned_hours,
                "actual_hours": actual_hours,
                "variance_hours": variance_hours,
                "variance_percent": variance_percent,
                "assessment": f"Regelbasierte Fallback-Berechnung (Fehler: {error_msg}). Abweichung beträgt {variance_hours} Stunden ({variance_percent}%)."
            },
            "progress_analysis": {
                "progress_percent": progress_percent,
                "elapsed_time_percent": 0.0,
                "status_relative_to_deadline": "Verstrichene Zeit im Fallback-Modus nicht berechenbar."
            },
            "milestones_overview": {
                "total_count": milestone_summary["total_count"],
                "overdue_count": milestone_summary["overdue_count"],
                "summary": milestone_summary["summary_text"]
            },
            "predictions": {
                "estimated_remaining_hours": max(0.0, planned_hours - actual_hours),
                "forecasted_total_hours": max(planned_hours, actual_hours),
                "expected_completion_date": "N/A",
                "prognosis_confidence": "niedrig",
                "prognosis_text": "KI-Generierung war nicht verfügbar. Einfache lineare Extrapolations-Prognose verwendet."
            },
            "text_summaries": {
                "status_summary": project.get("statusMemo") or "N/A",
                "subject_summary": project.get("subjectMemo") or "N/A",
                "problems_summary": project.get("problemMemo") or "N/A"
            },
            "risk_assessment": {
                "statusampel": overall_risk,
                "is_critical": is_critical,
                # English enum to match the LLM's JSON schema (see prompts.yaml)
                # and the frontend, which only recognizes "low/medium/high".
                "criticality_level": "high" if is_critical else "low",
                "criticality_reasons": criticality_reasons,
                "goals_vs_status_eval": "KI-Prüfung fehlgeschlagen. Einhaltung der Projektziele konnte nicht bewertet werden."
            }
        }

    async def analyze_portfolio(self, portfolio_id: int, api_key: Optional[str] = None, ollama_api_key: Optional[str] = None) -> Dict[str, Any]:
        """Fetch portfolio and all its projects, analyze projects concurrently, and generate a portfolio-level summary."""
        # 1. Fetch Portfolio details
        try:
            portfolio = await blueant_client.get_portfolio(portfolio_id, api_key=api_key)
        except BlueAntAPIError as e:
            return {"error": str(e), "status_code": e.status_code}
        if not portfolio:
            return {"error": f"Portfolio {portfolio_id} not found in Blue Ant.", "status_code": 404}

        portfolio_name = portfolio.get("name", "Unnamed Portfolio")
        project_ids = portfolio.get("projectIds", [])

        if not project_ids:
            return {
                "portfolio_id": portfolio_id,
                "portfolio_name": portfolio_name,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "metrics": {
                    "total_projects": 0,
                    "critical_projects_count": 0,
                    "status_distribution": {"green": 0, "yellow": 0, "red": 0, "other": 0},
                    "overdue_milestones_total": 0
                },
                "executive_summary": "Dieses Portfolio enthält keine Projekte.",
                "critical_projects_overview": [],
                "systemic_issues": [],
                "action_recommendations": [],
                "projects_analysis": []
            }

        # 2. Fetch all projects in one call (optimized to avoid rate limit spamming)
        try:
            all_projects = await blueant_client.get_projects(api_key=api_key)
        except BlueAntAPIError as e:
            return {"error": str(e), "status_code": e.status_code}

        # 3. Filter projects belonging to this portfolio
        portfolio_projects = [p for p in all_projects if p.get("id") in project_ids]

        # If no projects matched but we had IDs, fetch them individually as backup (rare).
        # Tolerate individual failures so one bad project id doesn't sink the whole portfolio.
        if not portfolio_projects and project_ids:
            logger.info("Portfolio projects not found in main project list, attempting individual fetches.")
            portfolio_projects = []
            for pid in project_ids:
                try:
                    p = await blueant_client.get_project(pid, api_key=api_key)
                except BlueAntAPIError as e:
                    logger.error(f"Failed to fetch project {pid} individually: {e}")
                    continue
                if p:
                    portfolio_projects.append(p)

        # 4. Concurrently analyze each project
        async def analyze_single_project(proj):
            try:
                pid = proj.get("id")
                kpis = await blueant_client.get_project_kpis(pid, api_key=api_key)
                logger.info(f"FETCHED KPIs for portfolio project {pid}: {kpis}")
                status_history = await blueant_client.get_project_status_history(pid, api_key=api_key)
                milestones = await blueant_client.get_project_milestones(pid, api_key=api_key)

                # Calculate correct baseline values to override LLM hallucinations
                effort = extract_effort_kpis(kpis)
                milestone_summary = summarize_milestones(milestones)

                # Format Prompt
                prompt = prompt_engine.format_project_prompt(proj, kpis, status_history, milestones)
                system_prompt = prompt_engine.system_prompt

                # Concurrency Semaphore for LLM
                async with self.semaphore:
                    llm_response = await llm_client.generate_analysis(prompt, system_prompt, api_key=ollama_api_key)

                if llm_response:
                    cleaned = self._clean_json_response(llm_response)
                    result_data = json.loads(cleaned)
                else:
                    result_data = None

                if result_data is None:
                    return self._generate_project_fallback(proj, kpis, milestones, "LLM generated no response.")

                # Sanitize / overwrite calculated numerical fields to prevent LLM math hallucinations
                result_data.setdefault("effort_analysis", {})
                result_data["effort_analysis"]["planned_hours"] = effort["planned_hours"]
                result_data["effort_analysis"]["actual_hours"] = effort["actual_hours"]
                result_data["effort_analysis"]["variance_hours"] = effort["variance_hours"]
                result_data["effort_analysis"]["variance_percent"] = effort["variance_percent"]

                result_data.setdefault("progress_analysis", {})
                result_data["progress_analysis"]["progress_percent"] = effort["progress_percent"]

                result_data.setdefault("milestones_overview", {})
                result_data["milestones_overview"]["total_count"] = milestone_summary["total_count"]
                result_data["milestones_overview"]["overdue_count"] = milestone_summary["overdue_count"]

                return result_data
            except Exception as e:
                logger.error(f"Error analyzing project {proj.get('id')}: {e}")
                # Fallback to avoid breaking portfolio-wide analysis
                return self._generate_project_fallback(proj, [], [], f"Error: {str(e)}")

        tasks = [analyze_single_project(p) for p in portfolio_projects]
        projects_analysis_results = await asyncio.gather(*tasks)

        # 5. Aggregate Portfolio Statistics
        total_projects = len(projects_analysis_results)
        critical_projects = [p for p in projects_analysis_results if p.get("risk_assessment", {}).get("is_critical", False)]
        critical_count = len(critical_projects)
        overdue_milestones_total = sum(
            p.get("milestones_overview", {}).get("overdue_count", 0) for p in projects_analysis_results
        )

        status_counts = {"green": 0, "yellow": 0, "red": 0, "other": 0}
        for res in projects_analysis_results:
            color = (res.get("risk_assessment", {}).get("statusampel") or "other").lower()
            if color in ("green", "yellow", "red"):
                status_counts[color] += 1
            else:
                # Unresolved/unknown risk levels are tracked separately instead of
                # being silently counted as "green", which previously masked real
                # red/yellow projects whenever the Statusampel couldn't be resolved.
                status_counts["other"] += 1

        # 6. Generate Portfolio Executive Summary via LLM
        projects_summary_payload = []
        for res in projects_analysis_results:
            project_brief = {
                "project_id": res.get("project_id"),
                "project_name": res.get("project_name"),
                "statusampel": res.get("risk_assessment", {}).get("statusampel"),
                "is_critical": res.get("risk_assessment", {}).get("is_critical"),
                "criticality_reasons": res.get("risk_assessment", {}).get("criticality_reasons", []),
                "variance_percent": res.get("effort_analysis", {}).get("variance_percent"),
                "progress_percent": res.get("progress_analysis", {}).get("progress_percent"),
                "milestones_overdue": res.get("milestones_overview", {}).get("overdue_count", 0),
                "milestones_total": res.get("milestones_overview", {}).get("total_count", 0),
                "problems_summary": res.get("text_summaries", {}).get("problems_summary")
            }
            projects_summary_payload.append(project_brief)

        projects_summary_str = json.dumps(projects_summary_payload, indent=2)

        portfolio_summary_json = {}
        try:
            portfolio_prompt = prompt_engine.portfolio_analysis_prompt_template.format(
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
                date_from=portfolio.get("dateFrom", "N/A"),
                date_to=portfolio.get("dateTo", "N/A"),
                projects_data_summary=projects_summary_str,
                current_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                total_projects=total_projects,
                critical_count=critical_count,
                green_count=status_counts["green"],
                yellow_count=status_counts["yellow"],
                red_count=status_counts["red"],
                other_count=status_counts["other"],
                overdue_milestones_total=overdue_milestones_total
            )

            async with self.semaphore:
                portfolio_llm_response = await llm_client.generate_analysis(portfolio_prompt, prompt_engine.system_prompt, api_key=ollama_api_key)

            if portfolio_llm_response:
                cleaned_port = self._clean_json_response(portfolio_llm_response)
                portfolio_summary_json = json.loads(cleaned_port)
        except Exception as e:
            # A bad user-edited prompt template or unexpected LLM output must not
            # take down an otherwise-successful portfolio analysis - degrade to the
            # deterministic summary computed below instead.
            logger.error(f"Failed to build/parse portfolio-level LLM summary: {e}")

        # Build final response combining portfolio overview and project results
        final_portfolio_analysis = {
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio_name,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "metrics": {
                "total_projects": total_projects,
                "critical_projects_count": critical_count,
                "status_distribution": status_counts,
                "overdue_milestones_total": overdue_milestones_total
            },
            "executive_summary": portfolio_summary_json.get("executive_summary", f"Portfolio-Analyse erstellt. {critical_count} von {total_projects} Projekten sind kritisch."),
            "critical_projects_overview": portfolio_summary_json.get("critical_projects_overview", [
                {"project_id": cp.get("project_id"), "project_name": cp.get("project_name"), "reason_critical": ", ".join(cp.get("risk_assessment", {}).get("criticality_reasons", []))}
                for cp in critical_projects
            ]),
            "systemic_issues": portfolio_summary_json.get("systemic_issues", []),
            "action_recommendations": portfolio_summary_json.get("action_recommendations", []),
            "projects_analysis": projects_analysis_results
        }

        return final_portfolio_analysis


# Global instance of Analysis Service
analysis_service = AnalysisService()
