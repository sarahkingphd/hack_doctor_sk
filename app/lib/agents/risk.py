"""
RiskAgent — synthesizes dedup + geo + shortage into a risk matrix.

Input : full facilities DataFrame + all upstream agent results
Output: prioritised risk matrix + planning recommendations
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .base import BaseAgent

SYSTEM = """You are a strategic healthcare planning analyst.

You have received outputs from three prior analysis agents:
  - dedup: duplicate facility analysis
  - geo:   geographic quality and coverage gaps
  - shortage: care shortage areas by state

Synthesise these into a final risk assessment and planning recommendations.

Return ONLY valid JSON in this exact shape:
{
  "risks": [
    {
      "risk_id": "R01",
      "priority": "P0|P1|P2",
      "category": "data_quality|coverage_gap|shortage|planning",
      "title": "Short title",
      "description": "2-3 sentences",
      "affected_states": ["..."],
      "affected_care_types": ["..."],
      "root_cause": "dedup|geo|shortage|combined",
      "recommended_action": "...",
      "owner": "Data team|Field team|Planning team|AI agent",
      "confidence": "high|medium|low",
      "estimated_impact_score": 0
    }
  ],
  "executive_summary": "3-5 sentence narrative for planners",
  "top_3_priorities": ["...", "...", "..."],
  "data_readiness_score": 0,
  "planning_readiness_score": 0
}"""


class RiskAgent(BaseAgent):
    name = "risk"

    def _execute(self, df: pd.DataFrame, upstream: dict[str, Any]) -> dict:
        dedup_result = upstream.get("dedup", {})
        geo_result = upstream.get("geo", {})
        shortage_result = upstream.get("shortage", {})

        user_msg = (
            f"Synthesise risk assessment for a healthcare facility dataset "
            f"with {len(df):,} records.\n\n"
            f"=== DEDUP AGENT OUTPUT ===\n"
            f"Summary: {dedup_result.get('summary', {})}\n"
            f"Sample cluster decisions (first 5): {dedup_result.get('clusters', [])[:5]}\n\n"
            f"=== GEO AGENT OUTPUT ===\n"
            f"Summary: {geo_result.get('summary', {})}\n"
            f"Coverage gaps: {geo_result.get('coverage_gaps', [])[:5]}\n\n"
            f"=== SHORTAGE AGENT OUTPUT ===\n"
            f"Summary: {shortage_result.get('summary', {})}\n"
            f"Critical shortage areas: {[a for a in shortage_result.get('shortage_areas', []) if a.get('severity') == 'critical'][:5]}\n\n"
            f"Produce a risk matrix and executive summary for the planning team."
        )

        return self._ask(SYSTEM, user_msg, max_tokens=3000)
