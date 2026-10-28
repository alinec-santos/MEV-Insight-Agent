"""
Testes do pipeline determinístico (app/tools/pipeline.py).

As chamadas RPC são substituídas por mocks; reaproveitamos os geradores de
logs de Swap de ``test_heuristic``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.tools.pipeline import investigate_transaction, select_candidates, summarize_transaction
from tests.test_heuristic import ATTACKER, POOL, VICTIM, _tx, _v2_log

ETH = "ethereum"
H_VICTIM = "0x" + "a" * 64
H_FRONT = "0x" + "f" * 64
H_BACK = "0x" + "b" * 64
H_NOISE = "0x" + "c" * 64


def _neighbor(h: str, idx: int, sender: str, to: str = "0xrouter") -> dict:
    return {"hash": h, "transaction_index": idx, "from_address": sender,
            "to_address": to, "gas_price": 1, "fn_selector": "0x12345678"}


@pytest.fixture
def chain() -> dict[str, dict]:
    """Bloco simulado: front-run (10), vítima (11), back-run (12)."""
    victim = _tx(H_VICTIM, 11, VICTIM, [_v2_log(POOL, 0, 10**18, 2_900 * 10**6, 0)])
    front = _tx(H_FRONT, 10, ATTACKER, [_v2_log(POOL, 0, 5 * 10**18, 15_000 * 10**6, 0)])
    back = _tx(H_BACK, 12, ATTACKER, [_v2_log(POOL, 15_000 * 10**6, 0, 0, 5_050 * 10**15)])
    for tx in (victim, front, back):
        tx["block_number"] = 100
    return {H_VICTIM: victim, H_FRONT: front, H_BACK: back}


class TestSelectCandidates:
    def test_seleciona_endereco_presente_nos_dois_lados(self) -> None:
        neighbors = {
            "before": [_neighbor(H_NOISE, 9, "0xnoise", "0xother"), _neighbor(H_FRONT, 10, ATTACKER, "0xbot")],
            "after": [_neighbor(H_BACK, 12, ATTACKER, "0xbot")],
        }
        assert select_candidates(neighbors, VICTIM) == [H_FRONT, H_BACK]

    def test_ignora_vizinhos_sem_par(self) -> None:
        neighbors = {
            "before": [_neighbor(H_FRONT, 10, "0xa", "0xc1")],
            "after": [_neighbor(H_BACK, 12, "0xb", "0xc2")],
        }
        assert select_candidates(neighbors, VICTIM) == []

    def test_ignora_o_proprio_endereco_da_vitima(self) -> None:
        neighbors = {
            "before": [_neighbor(H_FRONT, 10, VICTIM, "0xc1")],
            "after": [_neighbor(H_BACK, 12, VICTIM, "0xc2")],
        }
        assert select_candidates(neighbors, VICTIM) == []

    def test_mesmo_contrato_bot_com_remetentes_diferentes(self) -> None:
        """Bots costumam usar EOAs diferentes chamando o mesmo contrato."""
        neighbors = {
            "before": [_neighbor(H_FRONT, 10, "0xeoa1", "0xbotcontract")],
            "after": [_neighbor(H_BACK, 12, "0xeoa2", "0xbotcontract")],
        }
        assert select_candidates(neighbors, VICTIM) == [H_FRONT, H_BACK]


class TestSummarize:
    def test_resumo_remove_logs_e_decodifica_swaps(self, chain: dict) -> None:
        s = summarize_transaction(chain[H_VICTIM])
        assert "logs" not in s and "input" not in s
        assert s["status"] == "sucesso"
        assert len(s["swaps"]) == 1
        assert s["swaps"][0]["pool"].lower() == POOL
        assert isinstance(s["swaps"][0]["amount_in"], str)  # sem perda de precisão


class TestInvestigate:
    def test_detecta_sandwich_ponta_a_ponta(self, chain: dict) -> None:
        neighbors = {
            "block_number": 100, "victim_index": 11, "total_txs_in_block": 20,
            "before": [_neighbor(H_FRONT, 10, ATTACKER)],
            "after": [_neighbor(H_BACK, 12, ATTACKER)],
        }
        with patch("app.tools.pipeline.get_transaction", side_effect=lambda n, h: chain[h]), \
             patch("app.tools.pipeline.get_block_neighbors", return_value=neighbors) as gbn:
            report = investigate_transaction(ETH, H_VICTIM)

        gbn.assert_called_once_with(network=ETH, block_number=100, tx_index=11, window=3)
        assert report["sandwich"]["is_sandwich"] is True
        assert report["sandwich"]["attacker_address"].lower() == ATTACKER
        assert report["candidates_fetched"] == 2
        assert report["victim"]["hash"] == H_VICTIM

    def test_candidato_com_falha_rpc_nao_derruba_analise(self, chain: dict) -> None:
        neighbors = {"before": [_neighbor(H_FRONT, 10, ATTACKER)],
                     "after": [_neighbor(H_BACK, 12, ATTACKER)]}

        def fake_get(network: str, h: str) -> dict:
            if h == H_BACK:
                raise ConnectionError("timeout")
            return chain[h]

        with patch("app.tools.pipeline.get_transaction", side_effect=fake_get), \
             patch("app.tools.pipeline.get_block_neighbors", return_value=neighbors):
            report = investigate_transaction(ETH, H_VICTIM)

        assert report["candidates_fetched"] == 1
        assert report["sandwich"]["is_sandwich"] is False

    def test_erro_na_vitima_e_propagado(self) -> None:
        with patch("app.tools.pipeline.get_transaction", side_effect=LookupError("nao achei")):
            with pytest.raises(LookupError):
                investigate_transaction(ETH, H_VICTIM)
