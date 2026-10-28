"""
Pipeline determinístico de investigação de sandwich attack.

Orquestra as ferramentas de baixo nível (Web3 + heurística) sem envolver o LLM:

    1. get_transaction(vítima)            → dados + logs da vítima
    2. get_block_neighbors(...)           → vizinhos no bloco (sem logs)
    3. pré-filtro de candidatos           → só busca recibos de quem pode ser atacante
    4. get_transaction(candidatos)        → logs dos candidatos
    5. detect_sandwich(vítima, candidatos) → veredito determinístico

Por que existe: deixar o LLM encadear essas chamadas e copiar JSONs com logs
entre ferramentas é frágil (alucinação de campos, estouro de contexto, custo).
Aqui o LLM só passa identificadores e recebe um resumo compacto.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from app.tools.heuristic import detect_sandwich, parse_swap_events
from app.tools.web3_tools import get_block_neighbors, get_transaction

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = 3  # sandwiches costumam ser adjacentes à vítima


def summarize_transaction(tx: dict[str, Any]) -> dict[str, Any]:
    """
    Resumo compacto de uma transação para enviar ao LLM.

    Remove calldata e logs crus (que só ocupam contexto) e inclui os swaps
    já decodificados pela heurística.
    """
    swaps = [asdict(s) for s in parse_swap_events(tx)]
    # Inteiros de 256 bits viram string para não perder precisão em JSON
    for s in swaps:
        s["amount_in"] = str(s["amount_in"])
        s["amount_out"] = str(s["amount_out"])
    return {
        "hash": tx.get("hash"),
        "block_number": tx.get("block_number"),
        "transaction_index": tx.get("transaction_index"),
        "from_address": tx.get("from_address"),
        "to_address": tx.get("to_address"),
        "status": "sucesso" if tx.get("status") == 1 else "revertida",
        "value_wei": str(tx.get("value", 0)),
        "total_logs": len(tx.get("logs", [])),
        "swaps": swaps,
    }


def select_candidates(neighbors: dict[str, Any], victim_from: str) -> list[str]:
    """
    Pré-filtro: escolhe quais vizinhos merecem busca completa (com recibo).

    Um sandwich exige o MESMO ator antes e depois da vítima. Então só
    interessam endereços (remetente ou contrato chamado) presentes nos dois
    lados. Isso reduz drasticamente as chamadas RPC (de 2×window para ~2).

    Returns:
        Hashes dos candidatos, em ordem de posição no bloco.
    """
    before = neighbors.get("before", [])
    after = neighbors.get("after", [])

    def _addrs(txs: list[dict], key: str) -> set[str]:
        return {(t.get(key) or "").lower() for t in txs if t.get(key)}

    victim = (victim_from or "").lower()
    shared_from = (_addrs(before, "from_address") & _addrs(after, "from_address")) - {victim}
    shared_to = _addrs(before, "to_address") & _addrs(after, "to_address")

    selected = [
        t for t in before + after
        if (t.get("from_address") or "").lower() in shared_from
        or (t.get("to_address") or "").lower() in shared_to
    ]
    selected.sort(key=lambda t: t.get("transaction_index", 0))
    return [t["hash"] for t in selected]


def investigate_transaction(
    network: str,
    tx_hash: str,
    window: int = DEFAULT_WINDOW,
) -> dict[str, Any]:
    """
    Executa a investigação completa de uma transação.

    Args:
        network: "ethereum" ou "polygon".
        tx_hash: Hash da transação suspeita de ser vítima.
        window:  Quantas transações olhar de cada lado no bloco.

    Returns:
        ``{"network", "victim", "neighbors_checked", "candidates_fetched",
        "sandwich": <SandwichResult como dict>}``

    Raises:
        ValueError / LookupError / ConnectionError propagados das ferramentas.
    """
    logger.info("Investigando tx=%s | rede=%s | janela=%d", tx_hash, network, window)

    victim = get_transaction(network, tx_hash)
    neighbors = get_block_neighbors(
        network=network,
        block_number=victim["block_number"],
        tx_index=victim["transaction_index"],
        window=window,
    )

    candidate_hashes = select_candidates(neighbors, victim.get("from_address", ""))
    candidates: list[dict[str, Any]] = []
    for h in candidate_hashes:
        try:
            candidates.append(get_transaction(network, h))
        except (LookupError, ConnectionError) as exc:
            # Um vizinho com falha não deve derrubar a análise inteira
            logger.warning("Falha ao buscar candidato %s: %s", h, exc)

    result = detect_sandwich(victim, candidates)

    return {
        "network": network,
        "victim": summarize_transaction(victim),
        "neighbors_checked": len(neighbors.get("before", [])) + len(neighbors.get("after", [])),
        "candidates_fetched": len(candidates),
        "sandwich": asdict(result),
    }
