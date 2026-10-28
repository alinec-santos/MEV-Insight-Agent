"""
Testes do agente (app/agent/core.py) com um cliente Gemini FALSO.

Nenhuma chamada real ao Gemini ou à blockchain: validamos o loop de tool
calling, a captura do resultado da heurística e o tratamento de erros.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from google.genai import errors as genai_errors

from app.agent.core import (
    LLMConfigError,
    LLMRateLimitError,
    MEVAgent,
    ToolExecutor,
)

H = "0x" + "a" * 64

REPORT_SANDWICH: dict[str, Any] = {
    "network": "ethereum",
    "victim": {"hash": H, "swaps": []},
    "neighbors_checked": 6,
    "candidates_fetched": 2,
    "sandwich": {"is_sandwich": True, "confidence": "HIGH", "victim_tx": H,
                 "attacker_address": "0xbot", "estimated_slippage_pct": 3.3},
}


# ─── Fakes do SDK ─────────────────────────────────────────────────────────────

def _text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(function_calls=None, text=text, candidates=[])


def _call_response(*calls: tuple[str, dict]) -> SimpleNamespace:
    fcs = [SimpleNamespace(name=n, args=a) for n, a in calls]
    content = SimpleNamespace(role="model", parts=[])
    return SimpleNamespace(function_calls=fcs, text=None,
                           candidates=[SimpleNamespace(content=content)])


class FakeClient:
    """Imita ``genai.Client``: devolve respostas pré-programadas em sequência."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.requests: list[list[Any]] = []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model: str, contents: list[Any], config: Any) -> Any:
        self.requests.append(list(contents))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_search(query: str, n_results: int) -> dict[str, Any]:
    return {"results": [{"source": "sandwich_attacks.md", "content": "Um sandwich..."}]}


# ─── ToolExecutor ─────────────────────────────────────────────────────────────

class TestToolExecutor:
    def test_detect_sandwich_registra_resultado(self) -> None:
        ex = ToolExecutor()
        with patch("app.agent.core.investigate_transaction", return_value=REPORT_SANDWICH):
            out = ex.execute("detect_sandwich", {"network": "ethereum", "tx_hash": H})
        assert out == REPORT_SANDWICH
        assert ex.heuristic_result == REPORT_SANDWICH

    def test_erros_viram_dict_para_o_llm(self) -> None:
        ex = ToolExecutor()
        with patch("app.agent.core.investigate_transaction", side_effect=ValueError("hash ruim")):
            out = ex.execute("detect_sandwich", {"network": "ethereum", "tx_hash": "0x1"})
        assert out["error"] == "hash ruim"
        assert out["error_type"] == "ValueError"

    def test_argumento_ausente(self) -> None:
        out = ToolExecutor().execute("get_transaction", {"network": "ethereum"})
        assert "ausente" in out["error"]

    def test_ferramenta_desconhecida(self) -> None:
        assert "desconhecida" in ToolExecutor().execute("rm_rf", {})["error"]

    def test_search_acumula_fontes_sem_duplicar(self) -> None:
        ex = ToolExecutor(fake_search)
        ex.execute("search_knowledge_base", {"query": "a"})
        ex.execute("search_knowledge_base", {"query": "b"})
        assert ex.rag_sources == ["sandwich_attacks.md"]

    def test_search_sem_rag_retorna_aviso(self) -> None:
        out = ToolExecutor().execute("search_knowledge_base", {"query": "x"})
        assert out["results"] == [] and "warning" in out


# ─── MEVAgent ─────────────────────────────────────────────────────────────────

class TestMEVAgent:
    def test_sem_api_key_levanta_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        with pytest.raises(LLMConfigError):
            MEVAgent()

    def test_analyze_veredito_vem_da_heuristica(self) -> None:
        # Mesmo que o LLM "diga" outra coisa, is_sandwich vem da heurística
        client = FakeClient([_text_response("Não houve ataque nenhum!")])
        agent = MEVAgent(search_fn=fake_search, client=client)
        with patch("app.agent.core.investigate_transaction", return_value=REPORT_SANDWICH):
            out = agent.analyze("ethereum", H)

        assert out["is_sandwich"] is True
        assert out["confidence"] == "HIGH"
        assert out["rag_sources"] == ["sandwich_attacks.md"]
        # O prompt enviado contém o JSON da heurística
        prompt = client.requests[0][0].parts[0].text
        assert '"is_sandwich": true' in prompt

    def test_analyze_propaga_erro_onchain(self) -> None:
        agent = MEVAgent(client=FakeClient([]))
        with patch("app.agent.core.investigate_transaction", side_effect=LookupError("x")):
            with pytest.raises(LookupError):
                agent.analyze("ethereum", H)

    def test_chat_executa_tool_calls_e_devolve_texto(self) -> None:
        client = FakeClient([
            _call_response(("detect_sandwich", {"network": "ethereum", "tx_hash": H})),
            _call_response(("search_knowledge_base", {"query": "sandwich"})),
            _text_response("Sim, foi um sandwich [sandwich_attacks.md]."),
        ])
        agent = MEVAgent(search_fn=fake_search, client=client)
        with patch("app.agent.core.investigate_transaction", return_value=REPORT_SANDWICH):
            out = agent.chat(f"A tx {H} foi sanduichada?")

        assert out["tools_called"] == ["detect_sandwich", "search_knowledge_base"]
        assert out["is_sandwich"] is True
        assert "sandwich" in out["explanation"]
        # Histórico: user, model(call), user(resp), model(call), user(resp)
        assert len(client.requests[-1]) == 5

    def test_chat_sem_heuristica_nao_afirma_veredito(self) -> None:
        agent = MEVAgent(client=FakeClient([_text_response("MEV é...")]))
        out = agent.chat("O que é MEV?")
        assert out["is_sandwich"] is False
        assert out["confidence"] is None
        assert out["heuristic"] is None

    def test_limite_de_rodadas(self) -> None:
        loop = [_call_response(("search_knowledge_base", {"query": "x"}))] * 20
        agent = MEVAgent(search_fn=fake_search, client=FakeClient(loop))
        out = agent.chat("loop")
        assert "limite" in out["explanation"]

    def test_429_vira_rate_limit_error(self) -> None:
        err = genai_errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
        agent = MEVAgent(client=FakeClient([err]))
        with pytest.raises(LLMRateLimitError):
            agent.chat("oi")
