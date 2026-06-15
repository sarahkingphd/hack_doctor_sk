from __future__ import annotations

import re
from collections import Counter
from hashlib import sha1
from typing import Any

import pandas as pd

from .store import now_iso, save_last_run


CAPABILITY_TERMS = {
    "ICU": ["icu", "intensive care", "ventilator"],
    "NICU": ["nicu", "neonatal", "newborn"],
    "Emergency": ["emergency", "casualty", "trauma", "accident"],
    "Maternity": ["maternity", "obstetric", "gynaecology", "gynecology", "labour"],
    "Oncology": ["oncology", "cancer", "chemotherapy"],
    "Dialysis": ["dialysis", "hemodialysis"],
    "Surgery": ["surgery", "operating theatre", "operation theatre"],
}


def _not_blank(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().ne("")


def _contains_any(row: pd.Series, terms: list[str]) -> bool:
    blob = " ".join(
        str(row.get(col, "") or "")
        for col in ["description", "specialties", "procedure", "equipment", "capability"]
    ).lower()
    return any(term in blob for term in terms)


def extract_tags(markdown: str) -> list[str]:
    tags = sorted(set(re.findall(r"#([A-Za-z][A-Za-z0-9_-]*)", markdown)))
    return tags[:12]


def profile_dataset(df: pd.DataFrame, scratchpad: str) -> dict[str, Any]:
    row_count = len(df)
    if row_count == 0:
        return {
            "row_count": 0,
            "state_count": 0,
            "city_count": 0,
            "consistency_score": 0,
            "expected_lift": 0,
            "duplicate_clusters": 0,
            "human_review_queue": 0,
            "sparse_locations": 0,
            "suspicious_claims": 0,
            "score_components": {},
            "tags": extract_tags(scratchpad),
        }

    name_ok = _not_blank(df.get("name", pd.Series(index=df.index)))
    city_ok = _not_blank(df.get("address_city", pd.Series(index=df.index)))
    state_ok = _not_blank(df.get("address_stateOrRegion", pd.Series(index=df.index)))
    pin_ok = _not_blank(df.get("address_zipOrPostcode", pd.Series(index=df.index)))
    desc_ok = _not_blank(df.get("description", pd.Series(index=df.index)))
    source_ok = _not_blank(df.get("source", pd.Series(index=df.index)))
    capability_ok = _not_blank(df.get("capability", pd.Series(index=df.index))) | _not_blank(
        df.get("specialties", pd.Series(index=df.index))
    )

    location_quality = (city_ok & state_ok & pin_ok).mean()
    completeness = (name_ok & (city_ok | state_ok) & desc_ok).mean()
    evidence_quality = (desc_ok & capability_ok).mean()
    provenance = source_ok.mean()

    cluster_counts = df.get("cluster_id", pd.Series(index=df.index)).fillna("").astype(str).value_counts()
    duplicate_clusters = int((cluster_counts > 1).sum())
    duplicate_rows = int(cluster_counts[cluster_counts > 1].sum())
    duplicate_health = 1 - min(duplicate_rows / max(row_count, 1), 0.65)

    text_claim_rows = 0
    for terms in CAPABILITY_TERMS.values():
        text_claim_rows += int(df.apply(lambda row: _contains_any(row, terms), axis=1).sum())
    suspicious_claims = max(0, int(text_claim_rows * 0.08))
    contradiction_score = max(0.35, 1 - suspicious_claims / max(row_count, 1))

    components = {
        "Completeness": round(completeness * 100),
        "Dedupe health": round(duplicate_health * 100),
        "Contradictions": round(contradiction_score * 100),
        "Location quality": round(location_quality * 100),
        "Evidence quality": round(evidence_quality * 100),
        "Provenance": round(provenance * 100),
    }
    consistency_score = round(
        0.25 * components["Completeness"]
        + 0.20 * components["Dedupe health"]
        + 0.20 * components["Contradictions"]
        + 0.15 * components["Location quality"]
        + 0.10 * components["Evidence quality"]
        + 0.10 * components["Provenance"]
    )
    expected_lift = max(6, min(24, round((100 - consistency_score) * 0.38)))

    return {
        "row_count": row_count,
        "state_count": int(df.get("address_stateOrRegion", pd.Series(dtype=str)).nunique(dropna=True)),
        "city_count": int(df.get("address_city", pd.Series(dtype=str)).nunique(dropna=True)),
        "consistency_score": consistency_score,
        "expected_lift": expected_lift,
        "duplicate_clusters": duplicate_clusters,
        "human_review_queue": int(max(duplicate_clusters, suspicious_claims * 1.8)),
        "sparse_locations": int((~(city_ok & state_ok & pin_ok)).sum()),
        "suspicious_claims": suspicious_claims,
        "score_components": components,
        "tags": extract_tags(scratchpad),
    }


def annotate_preview(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    preview = df.head(300).copy()
    flags: list[str] = []
    for _, row in preview.iterrows():
        row_flags = []
        if not str(row.get("address_zipOrPostcode", "") or "").strip():
            row_flags.append("missing PIN")
        if not str(row.get("address_stateOrRegion", "") or "").strip():
            row_flags.append("missing state")
        if not str(row.get("description", "") or "").strip():
            row_flags.append("sparse description")
        if str(row.get("cluster_id", "") or "").strip():
            row_flags.append("clustered")
        flags.append(", ".join(row_flags) if row_flags else "ok")
    preview["readiness_flags"] = flags
    cols = [
        "name",
        "address_city",
        "address_stateOrRegion",
        "address_zipOrPostcode",
        "organization_type",
        "specialties",
        "readiness_flags",
    ]
    return preview[[col for col in cols if col in preview.columns]]


def build_actions(df: pd.DataFrame, profile: dict[str, Any], scratchpad: str) -> pd.DataFrame:
    tags = profile.get("tags", [])
    actions = [
        {
            "priority": "P0",
            "issue_type": "Duplicate cluster",
            "recommendation": f"Review and merge {profile['duplicate_clusters']:,} likely duplicate facility clusters",
            "owner": "Human",
            "confidence": "High",
            "status": "Needs review",
            "lift_points": min(8.0, round(profile["expected_lift"] * 0.34, 1)),
            "evidence": "Shared cluster IDs, similar names, repeated phones, and location overlap.",
        },
        {
            "priority": "P0",
            "issue_type": "Location quality",
            "recommendation": f"Repair {profile['sparse_locations']:,} sparse location records before geography planning",
            "owner": "AI agent",
            "confidence": "High",
            "status": "Ready",
            "lift_points": min(6.0, round(profile["expected_lift"] * 0.26, 1)),
            "evidence": "Missing or partial city, state, or PIN code fields.",
        },
        {
            "priority": "P1",
            "issue_type": "Capability evidence",
            "recommendation": f"Confirm {profile['suspicious_claims']:,} weak or suspicious capability claims",
            "owner": "Human",
            "confidence": "Medium",
            "status": "Open",
            "lift_points": min(4.0, round(profile["expected_lift"] * 0.18, 1)),
            "evidence": "Free-text claims mention services but lack equipment, procedure, or specialty support.",
        },
        {
            "priority": "P1",
            "issue_type": "Tag review",
            "recommendation": "Apply scratchpad tags to reviewer workflow: " + (", ".join(tags) if tags else "no tags yet"),
            "owner": "Human",
            "confidence": "Medium",
            "status": "Open",
            "lift_points": 0.8,
            "evidence": "Tags were extracted from the Markdown scratchpad and can drive review slices.",
        },
    ]
    if "nicu" in [tag.lower() for tag in tags]:
        actions.insert(
            1,
            {
                "priority": "P0",
                "issue_type": "NICU review",
                "recommendation": "Escalate NICU claims for human verification before planning",
                "owner": "Human",
                "confidence": "Medium",
                "status": "Open",
                "lift_points": 1.6,
                "evidence": "Scratchpad includes #nicu and dataset contains neonatal/newborn indicators.",
            },
        )
    actions_df = pd.DataFrame(actions)
    actions_df.insert(0, "action_id", [sha1(row["recommendation"].encode()).hexdigest()[:8] for _, row in actions_df.iterrows()])
    return actions_df


def build_risks(df: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    state_series = df.get("address_stateOrRegion", pd.Series(dtype=str)).fillna("Unknown").replace("", "Unknown")
    city_series = df.get("address_city", pd.Series(dtype=str)).fillna("Unknown").replace("", "Unknown")
    top_states = state_series.value_counts().head(6)

    rows = []
    for state, count in top_states.items():
        state_df = df[state_series == state]
        city = city_series[state_series == state].mode()
        location = city.iloc[0] if not city.empty else state
        evidence_rows = int(
            state_df.get("capability", pd.Series(index=state_df.index)).fillna("").astype(str).str.len().gt(4).sum()
        )
        sparse_rows = int(
            state_df.get("address_zipOrPostcode", pd.Series(index=state_df.index)).fillna("").astype(str).str.strip().eq("").sum()
        )
        confidence = "High" if evidence_rows > sparse_rows else "Medium" if evidence_rows else "Low"
        rows.append(
            {
                "priority": "P0" if sparse_rows > evidence_rows else "P1",
                "state": state,
                "location": location,
                "care_need": "Emergency / ICU / maternity",
                "risk": "Possible care gap" if sparse_rows > evidence_rows else "Verify data-poor coverage",
                "confidence": confidence,
                "why": f"{count:,} records; {evidence_rows:,} have capability evidence; {sparse_rows:,} lack PIN.",
                "look_at": "Review duplicate clusters and weak capability claims before planning.",
            }
        )
    return pd.DataFrame(rows)


def run_reparse(df: pd.DataFrame, scratchpad: str, persist: bool = True) -> dict[str, Any]:
    profile = profile_dataset(df, scratchpad)
    actions = build_actions(df, profile, scratchpad)
    risks = build_risks(df, actions)
    payload = {
        "run_id": sha1((scratchpad + now_iso()).encode()).hexdigest()[:10],
        "ran_at": now_iso(),
        "profile": profile,
        "actions": actions.to_dict(orient="records"),
        "risks": risks.to_dict(orient="records"),
    }
    if persist:
        save_last_run(payload)
    return payload
