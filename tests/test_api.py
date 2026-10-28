"""
Testes unitários e de integração para os endpoints da API FastAPI.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.api.server import app

client = TestClient(app)

H_VAL = "0x" + "a" * 64


class TestHealthEndpoint:
    def test_health_check_returns_200(self) -> None:
        with patch("app.api.server.get_web3") as mock_w3, \
             patch("app.api.server.get_knowledge_base") as mock_kb:
            w3_instance = MagicMock()
            w3_instance.is_connected.return_value = True
            mock_w3.return_value = w3_instance

            kb_instance = MagicMock()
            kb_instance.count = 5
            mock_kb.return_value = kb_instance

            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
            assert "services" in data
            assert data["services"]["ethereum_rpc"] is True
            assert data["services"]["chroma"] is True


class TestAnalyzeEndpoint:
    def test_invalid_hash_returns_422_or_400(self) -> None:
        resp = client.post("/analyze", json={"network": "ethereum", "tx_hash": "invalid-hash"})
        assert resp.status_code == 422  # Validação do Pydantic

    def test_invalid_network_returns_422(self) -> None:
        resp = client.post("/analyze", json={"network": "bitcoin", "tx_hash": H_VAL})
        assert resp.status_code == 422

    def test_analyze_success(self) -> None:
        mock_result = {
            "is_sandwich": True,
            "confidence": "HIGH",
            "explanation": "Detectamos um sandwich attack clássico.",
            "heuristic": {"victim": {"hash": H_VAL}, "sandwich": {"is_sandwich": True}},
            "rag_sources": ["02_sandwich_attacks.md"],
            "tools_called": ["detect_sandwich"],
        }

        with patch("app.api.server.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.analyze.return_value = mock_result
            mock_get_agent.return_value = mock_agent

            resp = client.post("/analyze", json={"network": "ethereum", "tx_hash": H_VAL})
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_sandwich"] is True
            assert data["confidence"] == "HIGH"
            assert "sandwich" in data["explanation"]
            assert data["rag_sources"] == ["02_sandwich_attacks.md"]

    def test_analyze_not_found_returns_404(self) -> None:
        with patch("app.api.server.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.analyze.side_effect = LookupError("Transação não encontrada")
            mock_get_agent.return_value = mock_agent

            resp = client.post("/analyze", json={"network": "ethereum", "tx_hash": H_VAL})
            assert resp.status_code == 404
            assert "Transação não encontrada" in resp.json()["detail"]

    def test_analyze_rpc_connection_error_returns_502(self) -> None:
        with patch("app.api.server.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.analyze.side_effect = ConnectionError("RPC timeout")
            mock_get_agent.return_value = mock_agent

            resp = client.post("/analyze", json={"network": "ethereum", "tx_hash": H_VAL})
            assert resp.status_code == 502
            assert "Falha de comunicação com o nó RPC" in resp.json()["detail"]


class TestChatEndpoint:
    def test_chat_empty_message_returns_422(self) -> None:
        resp = client.post("/chat", json={"message": ""})
        assert resp.status_code == 422

    def test_chat_success(self) -> None:
        mock_result = {
            "explanation": "Slippage é a diferença de preço...",
            "rag_sources": ["05_slippage_price_impact.md"],
            "tools_called": ["search_knowledge_base"],
        }

        with patch("app.api.server.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.chat.return_value = mock_result
            mock_get_agent.return_value = mock_agent

            resp = client.post("/chat", json={"message": "O que é slippage?"})
            assert resp.status_code == 200
            data = resp.json()
            assert "Slippage é" in data["response"]
            assert data["rag_sources"] == ["05_slippage_price_impact.md"]
