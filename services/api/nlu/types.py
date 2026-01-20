from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class NLUEntities(BaseModel):
    comuna: Optional[str] = None
    device: Optional[str] = None
    symptoms: List[str] = Field(default_factory=list)
    urgency: Optional[str] = None  # e.g., "hoy", "urgente", "esta semana"


class NLUResult(BaseModel):
    """
    Resultado normalizado de interpretación.

    Importante: intent_id debe pertenecer al catálogo (allowlist).
    """
    intent_id: Optional[str] = None
    confidence: float = 0.0
    entities: NLUEntities = Field(default_factory=NLUEntities)

    need_clarification: bool = False
    clarifying_question: Optional[str] = None
    clarifying_options: List[str] = Field(default_factory=list)

    # trazabilidad
    method: str = "rules"  # rules|llm|hybrid
    debug: Dict[str, Any] = Field(default_factory=dict)
