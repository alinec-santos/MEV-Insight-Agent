"""
API REST FastAPI para o MEV Insight Agent.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.agent.core import AgentError, LLMConfigError, LLMRateLimitError, MEVAgent
from app.api.schemas import AnalyzeRequest, AnalyzeResponse, ChatRequest, ChatResponse, HealthResponse
from app.rag.knowledge_base import get_knowledge_base
from app.tools.web3_tools import get_web3

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app.api")

_agent_instance: MEVAgent | None = None


def get_agent() -> MEVAgent:
    """Recupera ou instancia o singleton do agente."""
    global _agent_instance
    if _agent_instance is None:
        try:
            kb = get_knowledge_base(auto_index=True)
            _agent_instance = MEVAgent(search_fn=kb.search)
        except Exception as exc:
            logger.warning("Inicializando agente sem auto-indexação ou RAG offline: %s", exc)
            # Permite instanciar mesmo se a indexação do RAG falhar inicialmente
            _agent_instance = MEVAgent(search_fn=None)
    return _agent_instance


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Ciclo de vida da aplicação (startup / shutdown)."""
    logger.info("Iniciando MEV Insight Agent API...")
    yield
    logger.info("Encerrando aplicação.")


app = FastAPI(
    title="MEV Insight Agent API",
    description="API para investigação e explicação de Sandwich Attacks em DEXs (Ethereum e Polygon).",
    version="1.0.0",
)

# Habilita CORS para permitir conexão com frontend Streamlit e outras origens
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Monitoramento"])
def health_check() -> HealthResponse:
    """Verifica a saúde dos serviços e dependências da aplicação."""
    services: dict[str, bool] = {
        "llm": False,
        "chroma": False,
        "ethereum_rpc": False,
        "polygon_rpc": False,
    }

    # Verifica chave do LLM
    api_key = os.getenv("GEMINI_API_KEY", "")
    services["llm"] = bool(api_key and not api_key.startswith("your_"))

    # Verifica base vetorial ChromaDB
    try:
        kb = get_knowledge_base(auto_index=False)
        services["chroma"] = kb.count >= 0
    except Exception:
        services["chroma"] = False

    # Verifica conectividade com os RPCs
    try:
        w3_eth = get_web3("ethereum")
        services["ethereum_rpc"] = True
    except Exception:
        services["ethereum_rpc"] = False

    try:
        w3_poly = get_web3("polygon")
        services["polygon_rpc"] = True
    except Exception:
        services["polygon_rpc"] = False

    all_ok = all(services.values())
    status_str = "ok" if all_ok else ("degraded" if any(services.values()) else "down")

    return HealthResponse(
        status=status_str,
        version="1.0.0",
        services=services,
    )


@app.post("/analyze", response_model=AnalyzeResponse, tags=["Análise"])
def analyze_transaction(req: AnalyzeRequest) -> AnalyzeResponse:
    """
    Analisa uma transação específica para detectar se houve sandwich attack.
    O veredito da heurística determinística prevalece e o LLM gera a explicação.
    """
    agent = get_agent()
    logger.info("Requisição /analyze recebida: network=%s, tx=%s", req.network, req.tx_hash)

    try:
        result = agent.analyze(network=req.network, tx_hash=req.tx_hash)
        return AnalyzeResponse(
            is_sandwich=result["is_sandwich"],
            confidence=result.get("confidence"),
            explanation=result["explanation"],
            heuristic_data=result.get("heuristic"),
            rag_sources=result.get("rag_sources", []),
            tools_called=result.get("tools_called", []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha de comunicação com o nó RPC ({req.network}): {exc}",
        )
    except LLMRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except LLMConfigError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    except AgentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.exception("Erro inesperado no endpoint /analyze")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno no processamento: {exc}",
        )


@app.post("/chat", response_model=ChatResponse, tags=["Agente"])
def chat_agent(req: ChatRequest) -> ChatResponse:
    """
    Endpoint conversacional com o agente inteligente.
    Permite perguntas em linguagem natural e executa tool calling conforme necessário.
    """
    agent = get_agent()
    logger.info("Requisição /chat recebida: '%s...'", req.message[:60])

    try:
        result = agent.chat(question=req.message)
        return ChatResponse(
            response=result["explanation"],
            rag_sources=result.get("rag_sources", []),
            tools_called=result.get("tools_called", []),
        )
    except LLMRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except LLMConfigError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    except AgentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.exception("Erro inesperado no endpoint /chat")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno no chat: {exc}",
        )
