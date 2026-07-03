import os
import yaml
import datetime
from typing import Dict, Any, List, Optional
from app.config import PROMPTS_PATH
from app.kpi_utils import extract_effort_kpis
from app.milestone_utils import summarize_milestones


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

    @property
    def portfolio_analysis_prompt_template(self) -> str:
        self._load_prompts()
        return self._prompts.get("portfolio_analysis_prompt", "")

    @staticmethod
    def _parse_datetime_utc(value: str) -> Optional[datetime.datetime]:
        """Parse either a date-only string ("2018-09-21") or a full ISO datetime
        into a timezone-aware UTC datetime. Blue Ant's project start/end fields are
        date-only, which previously produced a naive datetime and crashed when
        compared against a timezone-aware "now"."""
        if not value:
            return None
        try:
            date_part = value.replace("Z", "+00:00").split("T")[0]
            d = datetime.date.fromisoformat(date_part)
            return datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
        except ValueError:
            return None

    def format_project_prompt(
        self,
        project: Dict[str, Any],
        kpis: List[Dict[str, Any]],
        status_history: List[Dict[str, Any]],
        milestones: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        self._load_prompts()

        # Parse fields
        project_id = project.get("id", 0)
        project_name = project.get("name", "Unnamed Project")
        project_number = project.get("number", "N/A")
        start_date = project.get("start", "")
        end_date = project.get("end", "")

        # Risk traffic light (Statusampel) - already resolved to {id, name, color, assessment}
        # by BlueAntClient; keep the isinstance checks so hand-crafted test fixtures
        # (or a raw upstream payload) still work.
        overall_risk_obj = project.get("overallRisk")
        overall_risk = "N/A"
        if isinstance(overall_risk_obj, dict):
            overall_risk = overall_risk_obj.get("color") or overall_risk_obj.get("name") or "N/A"
        elif isinstance(overall_risk_obj, str):
            overall_risk = overall_risk_obj

        # `.get(key, default)` only applies the default when the key is missing, not
        # when Blue Ant returns an explicit null for an empty memo field - use `or`.
        status_memo = project.get("statusMemo") or "None"
        subject_memo = project.get("subjectMemo") or "None"
        problem_memo = project.get("problemMemo") or "None"

        # Parse KPIs for numerical calculations and overview
        effort = extract_effort_kpis(kpis)
        planned_hours = effort["planned_hours"]
        actual_hours = effort["actual_hours"]
        progress_percent = effort["progress_percent"]
        variance_hours = effort["variance_hours"]
        variance_percent = effort["variance_percent"]
        kpis_summary = effort["kpis_summary"]

        # Calculate timeline percentages
        elapsed_time_percent = 0.0
        now = datetime.datetime.now(datetime.timezone.utc)
        start_dt = self._parse_datetime_utc(start_date)
        end_dt = self._parse_datetime_utc(end_date)
        if start_dt and end_dt and end_dt > start_dt:
            total_dur = (end_dt - start_dt).total_seconds()
            elapsed_dur = (now - start_dt).total_seconds()
            elapsed_time_percent = max(0.0, min(100.0, (elapsed_dur / total_dur) * 100.0))

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

        # Meilensteine (milestones)
        milestone_summary = summarize_milestones(milestones or [])

        # Determine if critical based on rules (for prompt formatting helper values)
        is_critical_bool = "false"
        if (
            overall_risk.lower() in ["red", "yellow"]
            or variance_percent > 15.0
            or "problem" in problem_memo.lower()
            or milestone_summary["overdue_count"] > 0
        ):
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
            milestones_summary=milestone_summary["summary_text"],
            milestones_total=milestone_summary["total_count"],
            milestones_overdue=milestone_summary["overdue_count"],
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
