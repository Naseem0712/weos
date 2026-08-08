"""WEOS Agent — live orchestrator + suggestion engine wired into the quote workflow.

UI → API → Quote Store → Calculation → **Agent** → Suggestions → Database → UI.
"""

from WEOS.agent.orchestrator import TRIGGERS, analyze, status
from WEOS.agent.suggestion_engine import explain_glass_size, generate

__all__ = ["analyze", "status", "generate", "explain_glass_size", "TRIGGERS"]
