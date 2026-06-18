import json
import logging
import asyncio
import datetime
from typing import Dict, Any, List, Optional
from app.blueant_client import blueant_client
from app.prompt_engine import prompt_engine
from app.llm_client import llm_client
from app.config import settings

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
        project = await blueant_client.get_project(project_id, api_key=api_key)
        if not project:
            return {"error": f"Project {project_id} not found in Blue Ant."}

        kpis = await blueant_client.get_project_kpis(project_id, api_key=api_key)
        logger.info(f"FETCHED KPIs for project {project_id}: {kpis}")
        status_history = await blueant_client.get_project_status_history(project_id, api_key=api_key)

        # 2. Format Prompt
        prompt = prompt_engine.format_project_prompt(project, kpis, status_history)
        system_prompt = prompt_engine.system_prompt

        # 3. Call LLM (with concurrency semaphore)
        async with self.semaphore:
            llm_response = await llm_client.generate_analysis(prompt, system_prompt, api_key=ollama_api_key)


        # 4. Parse & Fallback
        if not llm_response:
            logger.warning(f"LLM generated no response for project {project_id}. Generating fallback analysis.")
            return self._generate_project_fallback(project, kpis, "LLM failed to return a response.")

        try:
            cleaned_text = self._clean_json_response(llm_response)
            parsed_json = json.loads(cleaned_text)
            return parsed_json
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON for project {project_id}: {e}. Raw response: {llm_response}")
            return self._generate_project_fallback(project, kpis, f"Failed to parse LLM output: {str(e)}")

    def _generate_project_fallback(self, project: Dict[str, Any], kpis: List[Dict[str, Any]], error_msg: str) -> Dict[str, Any]:
        """Generate a rule-based fallback analysis if the LLM fails."""
        project_id = project.get("id", 0)
        project_name = project.get("name", "Unnamed Project")
        project_number = project.get("number", "N/A")
        
        overall_risk_obj = project.get("overallRisk")
        overall_risk = "N/A"
        if isinstance(overall_risk_obj, dict):
            overall_risk = overall_risk_obj.get("color") or overall_risk_obj.get("name") or "N/A"
        elif isinstance(overall_risk_obj, str):
            overall_risk = overall_risk_obj

        planned_hours = 0.0
        actual_hours = 0.0
        progress_percent = 0.0
        
        # Track priority strength (to prevent sub-budgets from overwriting main metrics)
        planned_strength = 0
        actual_strength = 0
        
        for k in kpis:
            if k.get("period", "TOTAL") != "TOTAL":
                continue
            
            k_id = k.get("id", "")
            name_lower = k.get("name", "").lower()
            val = float(k.get("value", 0.0) or 0.0)
            unit = k.get("unit", "")
            
            # Convert Person Days (PT) to Hours (h)
            if unit == "PT":
                val = val * 8.0
            
            if k_id == "SubjectiveProgress":
                progress_percent = val
            elif "fortschritt" in name_lower or "progress" in name_lower or "fertigstellung" in name_lower:
                if k_id == "SubjectiveProgress" or progress_percent == 0.0:
                    progress_percent = val
            
            # Planned hours matching priority
            if k_id == "WorkTotalPlan":
                planned_hours = val
                planned_strength = 3
            elif k_id == "ProjectBudgetWorkPlan":
                if planned_strength < 3:
                    planned_hours = val
                    planned_strength = 2
            elif k_id == "BudgetPlanWork":
                if planned_strength < 2:
                    planned_hours = val
                    planned_strength = 1
            elif ("plan" in name_lower or "basisplan" in name_lower) and ("aufwand" in name_lower or "arbeit" in name_lower or "effort" in name_lower):
                if "teilprojekt" not in name_lower and "ticket" not in name_lower and "mehrarbeit" not in name_lower:
                    if planned_strength == 0:
                        planned_hours = val
            
            # Actual hours matching priority
            if k_id == "WorkTotalActual":
                actual_hours = val
                actual_strength = 3
            elif k_id == "ProjectBudgetWorkActual":
                if actual_strength < 3:
                    actual_hours = val
                    actual_strength = 2
            elif k_id == "BudgetIsWork":
                if actual_strength < 2:
                    actual_hours = val
                    actual_strength = 1
            elif ("ist" in name_lower or "actual" in name_lower) and ("aufwand" in name_lower or "arbeit" in name_lower or "effort" in name_lower):
                if "teilprojekt" not in name_lower and "ticket" not in name_lower and "mehrarbeit" not in name_lower:
                    if actual_strength == 0:
                        actual_hours = val

        variance_hours = actual_hours - planned_hours
        variance_percent = round((variance_hours / planned_hours * 100.0) if planned_hours > 0 else 0.0, 2)
        is_critical = overall_risk.lower() in ["red", "yellow"] or variance_percent > 15.0

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
            "predictions": {
                "estimated_remaining_hours": max(0.0, planned_hours - actual_hours),
                "forecasted_total_hours": max(planned_hours, actual_hours),
                "expected_completion_date": "N/A",
                "prognosis_confidence": "niedrig",
                "prognosis_text": "KI-Generierung war nicht verfügbar. Einfache lineare Extrapolations-Prognose verwendet."
            },
            "text_summaries": {
                "status_summary": project.get("statusMemo", "N/A"),
                "subject_summary": project.get("subjectMemo", "N/A"),
                "problems_summary": project.get("problemMemo", "N/A")
            },
            "risk_assessment": {
                "statusampel": overall_risk,
                "is_critical": is_critical,
                "criticality_level": "hoch" if is_critical else "niedrig",
                "criticality_reasons": ["Ampelstatus oder Abweichungsschwelle überschritten (Fallback)"] if is_critical else [],
                "goals_vs_status_eval": "KI-Prüfung fehlgeschlagen. Einhaltung der Projektziele konnte nicht bewertet werden."
            }
        }

    async def analyze_portfolio(self, portfolio_id: int, api_key: Optional[str] = None, ollama_api_key: Optional[str] = None) -> Dict[str, Any]:
        """Fetch portfolio and all its projects, analyze projects concurrently, and generate a portfolio-level summary."""
        # 1. Fetch Portfolio details
        portfolio = await blueant_client.get_portfolio(portfolio_id, api_key=api_key)
        if not portfolio:
            return {"error": f"Portfolio {portfolio_id} not found in Blue Ant."}

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
                    "status_distribution": {"green": 0, "yellow": 0, "red": 0}
                },
                "executive_summary": "Dieses Portfolio enthält keine Projekte.",
                "critical_projects_overview": [],
                "systemic_issues": [],
                "action_recommendations": [],
                "projects_analysis": []
            }

        # 2. Fetch all projects in one call (optimized to avoid rate limit spamming)
        all_projects = await blueant_client.get_projects(api_key=api_key)
        
        # 3. Filter projects belonging to this portfolio
        portfolio_projects = [p for p in all_projects if p.get("id") in project_ids]
        
        # If no projects matched but we had IDs, fetch them individually as backup (rare)
        if not portfolio_projects and project_ids:
            logger.info("Portfolio projects not found in main project list, attempting individual fetches.")
            portfolio_projects = []
            for pid in project_ids:
                p = await blueant_client.get_project(pid, api_key=api_key)
                if p:
                    portfolio_projects.append(p)

        # 4. Concurrently analyze each project
        async def analyze_single_project(proj):
            try:
                # Fetch project-specific KPIs & status history
                pid = proj.get("id")
                kpis = await blueant_client.get_project_kpis(pid, api_key=api_key)
                logger.info(f"FETCHED KPIs for portfolio project {pid}: {kpis}")
                status_history = await blueant_client.get_project_status_history(pid, api_key=api_key)
                
                # Calculate correct baseline values to override LLM hallucinations
                planned_hours = 0.0
                actual_hours = 0.0
                progress_percent = 0.0
                
                # Track priority strength (to prevent sub-budgets from overwriting main metrics)
                planned_strength = 0
                actual_strength = 0
                
                for k in kpis:
                    if k.get("period", "TOTAL") != "TOTAL":
                        continue
                    
                    k_id = k.get("id", "")
                    name_lower = k.get("name", "").lower()
                    val = float(k.get("value", 0.0) or 0.0)
                    unit = k.get("unit", "")
                    
                    # Convert Person Days (PT) to Hours (h)
                    if unit == "PT":
                        val = val * 8.0
                    
                    if k_id == "SubjectiveProgress":
                        progress_percent = val
                    elif "fortschritt" in name_lower or "progress" in name_lower or "fertigstellung" in name_lower:
                        if k_id == "SubjectiveProgress" or progress_percent == 0.0:
                            progress_percent = val
                    
                    # Planned hours matching priority
                    if k_id == "WorkTotalPlan":
                        planned_hours = val
                        planned_strength = 3
                    elif k_id == "ProjectBudgetWorkPlan":
                        if planned_strength < 3:
                            planned_hours = val
                            planned_strength = 2
                    elif k_id == "BudgetPlanWork":
                        if planned_strength < 2:
                            planned_hours = val
                            planned_strength = 1
                    elif ("plan" in name_lower or "basisplan" in name_lower) and ("aufwand" in name_lower or "arbeit" in name_lower or "effort" in name_lower):
                        if "teilprojekt" not in name_lower and "ticket" not in name_lower and "mehrarbeit" not in name_lower:
                            if planned_strength == 0:
                                planned_hours = val
                    
                    # Actual hours matching priority
                    if k_id == "WorkTotalActual":
                        actual_hours = val
                        actual_strength = 3
                    elif k_id == "ProjectBudgetWorkActual":
                        if actual_strength < 3:
                            actual_hours = val
                            actual_strength = 2
                    elif k_id == "BudgetIsWork":
                        if actual_strength < 2:
                            actual_hours = val
                            actual_strength = 1
                    elif ("ist" in name_lower or "actual" in name_lower) and ("aufwand" in name_lower or "arbeit" in name_lower or "effort" in name_lower):
                        if "teilprojekt" not in name_lower and "ticket" not in name_lower and "mehrarbeit" not in name_lower:
                            if actual_strength == 0:
                                actual_hours = val
                
                variance_hours = actual_hours - planned_hours
                variance_percent = round((variance_hours / planned_hours * 100.0) if planned_hours > 0 else 0.0, 2)

                # Format Prompt
                prompt = prompt_engine.format_project_prompt(proj, kpis, status_history)
                system_prompt = prompt_engine.system_prompt
                
                # Concurrency Semaphore for LLM
                async with self.semaphore:
                    llm_response = await llm_client.generate_analysis(prompt, system_prompt, api_key=ollama_api_key)
                
                if llm_response:
                    cleaned = self._clean_json_response(llm_response)
                    result_data = json.loads(cleaned)
                    
                    # Sanitize / overwrite calculated numerical fields to prevent LLM math hallucinations
                    if "effort_analysis" not in result_data:
                        result_data["effort_analysis"] = {}
                    result_data["effort_analysis"]["planned_hours"] = planned_hours
                    result_data["effort_analysis"]["actual_hours"] = actual_hours
                    result_data["effort_analysis"]["variance_hours"] = variance_hours
                    result_data["effort_analysis"]["variance_percent"] = variance_percent
                    
                    if "progress_analysis" not in result_data:
                        result_data["progress_analysis"] = {}
                    result_data["progress_analysis"]["progress_percent"] = progress_percent
                    
                    return result_data
                else:
                    return self._generate_project_fallback(proj, kpis, "LLM generated no response.")
            except Exception as e:
                logger.error(f"Error analyzing project {proj.get('id')}: {e}")
                # Fallback to avoid breaking portfolio-wide analysis
                return self._generate_project_fallback(proj, [], f"Error: {str(e)}")

        tasks = [analyze_single_project(p) for p in portfolio_projects]
        projects_analysis_results = await asyncio.gather(*tasks)

        # 5. Aggregate Portfolio Statistics
        total_projects = len(projects_analysis_results)
        critical_projects = [p for p in projects_analysis_results if p.get("risk_assessment", {}).get("is_critical", False)]
        critical_count = len(critical_projects)

        status_counts = {"green": 0, "yellow": 0, "red": 0}
        for res in projects_analysis_results:
            color = res.get("risk_assessment", {}).get("statusampel", "green").lower()
            if color in status_counts:
                status_counts[color] += 1
            else:
                status_counts["green"] += 1 # Default fallback

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
                "problems_summary": res.get("text_summaries", {}).get("problems_summary")
            }
            projects_summary_payload.append(project_brief)

        projects_summary_str = json.dumps(projects_summary_payload, indent=2)
        
        portfolio_prompt = prompt_engine._prompts.get("portfolio_analysis_prompt", "").format(
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
            red_count=status_counts["red"]
        )

        async with self.semaphore:
            portfolio_llm_response = await llm_client.generate_analysis(portfolio_prompt, prompt_engine.system_prompt, api_key=ollama_api_key)

        portfolio_summary_json = {}
        if portfolio_llm_response:
            try:
                cleaned_port = self._clean_json_response(portfolio_llm_response)
                portfolio_summary_json = json.loads(cleaned_port)
            except Exception as e:
                logger.error(f"Failed to parse portfolio LLM JSON: {e}")
        
        # Build final response combining portfolio overview and project results
        final_portfolio_analysis = {
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio_name,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "metrics": {
                "total_projects": total_projects,
                "critical_projects_count": critical_count,
                "status_distribution": status_counts
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
