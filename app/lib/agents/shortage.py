"""
ShortageAgent — identifies healthcare service shortages by geography.

Input : full facilities DataFrame + dedup results (upstream)
Output: shortage analysis by state/district with care-type breakdown
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .base import BaseAgent

SYSTEM = """You are a healthcare access analyst specialising in shortage area identification.

You will receive aggregate statistics and a sample of healthcare facility records.
Identify:
1. States / districts with critical shortages (emergency, ICU, NICU, maternity)
2. States that appear data-poor vs. genuinely underserved
3. Capability gaps — common care types missing from certain regions
4. Priority areas for intervention based on facility density and capability evidence

Return ONLY valid JSON in this exact shape:
{
  "shortage_areas": [
    {
      "state": "...",
      "district_or_city": "...",
      "care_types_missing": ["ICU", "NICU", "Emergency"],
      "severity": "critical|high|medium|low",
      "facility_count": 0,
      "evidence": "one sentence",
      "data_confidence": "high|medium|low"
    }
  ],
  "capability_gaps": [
    {
      "care_type": "ICU|NICU|Emergency|Maternity|Oncology|Dialysis|Surgery",
      "affected_states": ["..."],
      "gap_severity": "high|medium|low"
    }
  ],
  "summary": {
    "critical_shortage_states": 0,
    "total_shortage_areas": 0,
    "most_underserved_state": "...",
    "top_missing_care_type": "..."
  }
}"""


class ShortageAgent(BaseAgent):
    name = "shortage"

    def _execute(self, df: pd.DataFrame, upstream: dict[str, Any]) -> dict:
        state_col = "address_stateOrRegion"
        cap_col = "capability"
        spec_col = "specialties"

        # Build per-state capability summary
        state_summary: list[dict] = []
        if state_col in df.columns:
            for state, grp in df.groupby(state_col):
                has_cap = grp[cap_col].fillna("").astype(str).str.len().gt(4).sum() if cap_col in grp else 0
                has_spec = grp[spec_col].fillna("").astype(str).str.len().gt(4).sum() if spec_col in grp else 0
                state_summary.append({
                    "state": state,
                    "facility_count": len(grp),
                    "has_capability_data": int(has_cap),
                    "has_specialty_data": int(has_spec),
                })

        dedup_summary = upstream.get("dedup", {}).get("summary", {})

        user_msg = (
            f"Analyse healthcare shortages across {len(df):,} facilities "
            f"in {len(state_summary)} states.\n\n"
            f"Dedup context: {dedup_summary}\n\n"
            f"State capability summary:\n{pd.DataFrame(state_summary).to_json(orient='records')}\n\n"
            f"Sample records:\n{self._sample(df)}"
        )

        return self._ask(SYSTEM, user_msg)
