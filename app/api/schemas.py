"""
Modelos Pydantic para validação das requisições e respostas da API REST.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"] = "ok"
    version: str = "1.0.0"
    services: dict[str, bool] = Field(
        default_factory=lambda: {"llm": True, "chroma": True, "ethereum_rpc": True, "polygon_rpc": True}
    )


class AnalyzeRequest(BaseModel):
    network: Literal["ethereum", "polygon"] = Field(
        ..., description="Rede blockchain onde a transação ocorreu."
    )
    tx_hash: str = Field(
        ..., description="Hash da transação (66 caracteres hexadecimais começando com 0x)."
    )

    @field_validator("tx_hash")
    @classmethod
    def validate_tx_hash(cls, v: str) -> str:
        clean = v.strip().lower()
        if not clean.startswith("0x"):
            clean = "0x" + clean
        if len(clean) != 66 or not re.fullmatch(r"0x[0-9a-fA-F]{64}", clean):
            raise ValueError("Hash de transação inválido. Deve ter 66 caracteres e iniciar com '0x'.")
        return clean


class AnalyzeResponse(BaseModel):
    is_sandwich: bool = Field(..., description="Veredito da heurística determinística.")
    confidence: str | None = Field(None, description="Grau de confiança da detecção (HIGH, LOW, NONE).")
    explanation: str = Field(..., description="Explicação detalhada em linguagem natural gerada pelo LLM.")
    heuristic_data: dict[str, Any] | None = Field(None, description="Dados brutos da investigação heurística.")
    rag_sources: list[str] = Field(default_factory=list, description="Documentos da base de conhecimento citados.")
    tools_called: list[str] = Field(default_factory=list, description="Lista de ferramentas invocadas durante o fluxo.")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=2, max_length=1500, description="Pergunta ou mensagem do usuário.")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Resposta do agente em português.")
    rag_sources: list[str] = Field(default_factory=list, description="Fontes consultadas na resposta.")
    tools_called: list[str] = Field(default_factory=list, description="Ferramentas executadas para responder.")
