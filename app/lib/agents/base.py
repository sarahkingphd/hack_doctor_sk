"""Base agent — wraps LLM client + state reporting."""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..llm import chat_json, get_client
from .. import pipeline_state as ps


class BaseAgent:
    name: str = "base"

    def __init__(self):
        self._client = None  # lazy — avoids import errors when LLM not needed

    @property
    def client(self):
        if self._client is None:
            self._client = get_client()
        return self._client

    # ── public entry point ────────────────────────────────────────────────────

    def run(self, df: pd.DataFrame, state: dict, upstream: dict[str, Any] | None = None) -> dict:
        """
        Execute the agent, mutating `state` in place with running/completed/failed
        transitions.  Returns the agent result dict on success.
        """
        ps.start_agent(state, self.name)
        ps.save(state)
        try:
            result = self._execute(df, upstream or {})
            ps.finish_agent(state, self.name, result=result)
            ps.save(state)
            return result
        except Exception as exc:
            ps.finish_agent(state, self.name, error=str(exc))
            ps.save(state)
            raise

    # ── override in subclasses ────────────────────────────────────────────────

    def _execute(self, df: pd.DataFrame, upstream: dict[str, Any]) -> dict:
        raise NotImplementedError

    # ── shared helpers ────────────────────────────────────────────────────────

    def _ask(self, system: str, user: str, **kwargs) -> Any:
        return chat_json(
            self.client,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            **kwargs,
        )

    @staticmethod
    def _sample(df: pd.DataFrame, n: int = 60) -> str:
        """Return a compact JSON sample of the dataframe for prompting."""
        cols = [c for c in [
            "name", "address_city", "address_stateOrRegion", "address_zipOrPostcode",
            "organization_type", "specialties", "capability", "description",
            "cluster_id", "source", "latitude", "longitude",
        ] if c in df.columns]
        return df[cols].head(n).fillna("").to_json(orient="records", indent=None)
