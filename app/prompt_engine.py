import os
import yaml
import datetime
from typing import Dict, Any, List
from app.config import PROMPTS_PATH

class PromptEngine:
    def __init__(self):
        self.prompts_path = PROMPTS_PATH
        self._prompts: Dict[str, Any] = {}
        self._last_loaded: float = 0.0
        self._load_prompts()

    def _load_prompts(self):
        if not os.path.exists(self.prompts_path):
            self._prompts = {
                "system_prompt": "You are a helpful project analysis AI assistant. Output JSON.",
                "project_analysis_prompt": "Analyze project {project_name}. KPIs: {kpis_summary}"
            }
            return

        try:
            mtime = os.path.getmtime(self.prompts_path)
            if mtime > self._last_loaded:
                with open(self.prompts_path, "r", encoding="utf-8") as f:
                    self._prompts = yaml.safe_load(f) or {}
                self._last_loaded = mtime
        except Exception as e:
            # Fallback if file read fails during edit
            if not self._prompts:
                self._prompts = {
                    "system_prompt": "You are a helpful project analysis AI assistant. Output JSON.",
                    "project_analysis_prompt": "Analyze project {project_name}. KPIs: {kpis_summary}"
                }

    @property
    def system_prompt(self) -> str:
        self._load_prompts()
        return self._prompts.get("system_prompt", "")

    @property
    def project_analysis_prompt_template(self) -> str:
        self._load_prompts()
        return self._prompts.get("project_analysis_prompt", "")

    def format_project_prompt(
        self,
        project: Dict[str, Any],
        kpis: List[Dict[str, Any]],
        status_history: List[Dict[str, Any]]
    ) -> str:
        self._load_prompts()

        # Parse fields
        project_id = project.get("id", 0)
        project_name = project.get("name", "Unnamed Project")
        project_number = project.get("number", "N/A")
        start_date = project.get("start", "")
        end_date = project.get("end", "")
        
        # Risk traffic light (Statusampel)
        overall_risk_obj = project.get("overallRisk")
        overall_risk = "N/A"
        if isinstance(overall_risk_obj, dict):
            overall_risk = overall_risk_obj.get("color") or overall_risk_obj.get("name") or "N/A"
        elif isinstance(overall_risk_obj, str):
            overall_risk = overall_risk_obj
            
        status_memo = project.get("statusMemo", "None")
        subject_memo = project.get("subjectMemo", "None")
        problem_memo = project.get("problemMemo", "None")

        # Parse KPIs for numerical calculations and overview
        planned_hours = 0.0
        actual_hours = 0.0
        progress_percent = 0.0
        kpi_lines = []

        for k in kpis:
            if k.get("period", "TOTAL") != "TOTAL":
                continue
            
            k_id = k.get("id", "")
            name = k.get("name", "")
            name_lower = name.lower()
            val = k.get("value", 0.0) or 0.0
            unit = k.get("unit", "") or ""
            
            kpi_lines.append(f"- {name}: {val} {unit}".strip())
            
            if k_id == "WorkTotalPlan":
                planned_hours = float(val)
            elif k_id == "WorkTotalActual":
                actual_hours = float(val)
            elif k_id == "SubjectiveProgress":
                progress_percent = float(val)
            elif ("plan" in name_lower or "basisplan" in name_lower) and ("aufwand" in name_lower or "arbeit" in name_lower or "effort" in name_lower):
                planned_hours = float(val)
            elif ("ist" in name_lower or "actual" in name_lower) and ("aufwand" in name_lower or "arbeit" in name_lower or "effort" in name_lower):
                actual_hours = float(val)
            elif "fortschritt" in name_lower or "progress" in name_lower or "fertigstellung" in name_lower:
                progress_percent = float(val)

        kpis_summary = "\n".join(kpi_lines) if kpi_lines else "No KPIs available."
        variance_hours = actual_hours - planned_hours
        variance_percent = (variance_hours / planned_hours * 100.0) if planned_hours > 0 else 0.0

        # Calculate timeline percentages
        elapsed_time_percent = 0.0
        now = datetime.datetime.now(datetime.timezone.utc)
        if start_date and end_date:
            try:
                # Replace typical ISO format suffix
                s_date = start_date.replace("Z", "+00:00")
                e_date = end_date.replace("Z", "+00:00")
                start_dt = datetime.datetime.fromisoformat(s_date)
                end_dt = datetime.datetime.fromisoformat(e_date)
                
                if end_dt > start_dt:
                    total_dur = (end_dt - start_dt).total_seconds()
                    elapsed_dur = (now - start_dt).total_seconds()
                    elapsed_time_percent = max(0.0, min(100.0, (elapsed_dur / total_dur) * 100.0))
            except Exception:
                pass

        # Estimate remaining hours (prognosis calculation)
        estimated_remaining_hours = 0.0
        if progress_percent > 0:
            # Simple linear extrapolation: total = actual / (progress/100)
            forecasted_total = actual_hours / (progress_percent / 100.0)
            estimated_remaining_hours = max(0.0, forecasted_total - actual_hours)
        else:
            # Fallback to planned minus actual if no progress recorded
            estimated_remaining_hours = max(0.0, planned_hours - actual_hours)
            
        forecasted_total_hours = actual_hours + estimated_remaining_hours

        # Determine if critical based on rules (for prompt formatting helper values)
        is_critical_bool = "false"
        if overall_risk.lower() in ["red", "yellow"] or variance_percent > 15.0 or "problem" in problem_memo.lower():
            is_critical_bool = "true"

        # Format status history log
        history_lines = []
        for h in status_history:
            date_str = h.get("date", "N/A")
            comment = h.get("comment", "")
            old_status = h.get("oldStatusId", {}).get("name", "Unknown") if isinstance(h.get("oldStatusId"), dict) else "Unknown"
            new_status = h.get("newStatusId", {}).get("name", "Unknown") if isinstance(h.get("newStatusId"), dict) else "Unknown"
            history_lines.append(f"[{date_str}] Status changed from {old_status} to {new_status}. Comment: {comment}")
            
        status_history_str = "\n".join(history_lines) if history_lines else "No status history comments recorded."

        # Format prompt template
        formatted_prompt = self.project_analysis_prompt_template.format(
            project_id=project_id,
            project_name=project_name,
            project_number=project_number,
            start_date=start_date,
            end_date=end_date,
            overall_risk=overall_risk,
            status_memo=status_memo,
            subject_memo=subject_memo,
            problem_memo=problem_memo,
            kpis_summary=kpis_summary,
            status_history=status_history_str,
            current_timestamp=now.isoformat(),
            planned_hours=planned_hours,
            actual_hours=actual_hours,
            variance_hours=variance_hours,
            variance_percent=round(variance_percent, 2),
            progress_percent=progress_percent,
            elapsed_time_percent=round(elapsed_time_percent, 2),
            estimated_remaining_hours=round(estimated_remaining_hours, 2),
            forecasted_total_hours=round(forecasted_total_hours, 2),
            is_critical_bool=is_critical_bool
        )

        return formatted_prompt

# Global instance of prompt engine
prompt_engine = PromptEngine()
