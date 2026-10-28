"""
Ferramentas de acesso à blockchain usando Web3.py.

Fornece funções para buscar transações completas (tx + recibo) e as
transações vizinhas no mesmo bloco — insumos para a heurística de
detecção de sandwich attack.

Redes suportadas: Ethereum mainnet, Polygon mainnet.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from web3 import Web3
from web3.exceptions import BlockNotFound, TransactionNotFound

load_dotenv()

logger = logging.getLogger(__name__)

# ─── Configuração de RPCs ─────────────────────────────────────────────────────

RPC_URLS: dict[str, str] = {
    "ethereum": os.getenv("ETH_RPC_URL", "https://eth.llamarpc.com"),
    "polygon":  os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com"),
}

# Cache de instâncias Web3 (uma por rede, evita reconexões)
_web3_cache: dict[str, Web3] = {}


def get_web3(network: str) -> Web3:
    """
    Retorna uma instância Web3 conectada à rede especificada.
    Reutiliza instâncias via cache para evitar reconexões.

    Args:
        network: "ethereum" ou "polygon" (case-insensitive).

    Returns:
        Instância Web3 pronta para uso.

    Raises:
        ValueError: se a rede não for suportada.
        ConnectionError: se não conseguir conectar ao RPC.
    """
    network = network.lower().strip()

    if network not in RPC_URLS:
        raise ValueError(
            f"Rede não suportada: '{network}'. "
            f"Opções válidas: {list(RPC_URLS.keys())}"
        )

    if network not in _web3_cache:
        url = RPC_URLS[network]
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))

        if not w3.is_connected():
            raise ConnectionError(
                f"Não foi possível conectar ao RPC da rede '{network}': {url}"
            )

        _web3_cache[network] = w3
        logger.info("Web3 conectado | rede=%s | rpc=%s", network, url)

    return _web3_cache[network]


def _clear_web3_cache() -> None:
    """Limpa o cache de conexões. Útil em testes."""
    _web3_cache.clear()


# ─── Busca de transação ───────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def get_transaction(network: str, tx_hash: str) -> dict[str, Any]:
    """
    Busca uma transação e seu recibo na blockchain.

    Combina os dados de ``eth_getTransactionByHash`` e
    ``eth_getTransactionReceipt`` em um único dicionário serializado.

    Args:
        network:  "ethereum" ou "polygon".
        tx_hash:  Hash da transação (com ou sem prefixo "0x").

    Returns:
        Dicionário com campos::

            {
                "hash":              str,   # "0x..."
                "block_number":      int,
                "transaction_index": int,
                "from_address":      str,
                "to_address":        str | None,
                "value":             int,  # em wei
                "gas_price":         int,  # em wei
                "input":             str,  # calldata hexadecimal
                "status":            int,  # 1 = sucesso, 0 = revert
                "logs": [
                    {
                        "address":          str,
                        "topics":           list[str],
                        "data":             str,
                        "log_index":        int,
                        "transaction_index": int,
                    },
                    ...
                ]
            }

    Raises:
        ValueError:      Hash inválido (tamanho incorreto).
        LookupError:     Transação não encontrada na rede.
        ConnectionError: Falha de comunicação com o RPC.
    """
    # Normaliza o hash
    tx_hash = tx_hash.strip()
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    if len(tx_hash) != 66:
        raise ValueError(
            f"Hash de transação inválido — esperado 66 caracteres, "
            f"recebido {len(tx_hash)}: '{tx_hash}'"
        )

    w3 = get_web3(network)

    try:
        tx = w3.eth.get_transaction(tx_hash)          # type: ignore[arg-type]
        receipt = w3.eth.get_transaction_receipt(tx_hash)  # type: ignore[arg-type]
    except TransactionNotFound:
        raise LookupError(
            f"Transação não encontrada na rede '{network}': {tx_hash}"
        )
    except Exception as exc:
        logger.error("Erro ao buscar tx %s | rede=%s | erro=%s", tx_hash, network, exc)
        raise ConnectionError(f"Falha na comunicação com o RPC: {exc}") from exc

    # Serializa os logs (HexBytes → str)
    serialized_logs = [
        {
            "address":           log["address"],
            "topics":            [
                t.hex() if isinstance(t, bytes) else str(t)
                for t in log["topics"]
            ],
            "data":              log["data"] if isinstance(log["data"], str) else log["data"].hex(),
            "log_index":         log["logIndex"],
            "transaction_index": log["transactionIndex"],
        }
        for log in receipt["logs"]
    ]

    raw_input = tx["input"]
    input_hex = raw_input.hex() if isinstance(raw_input, bytes) else str(raw_input)

    return {
        "hash":              tx_hash,
        "block_number":      tx["blockNumber"],
        "transaction_index": tx["transactionIndex"],
        "from_address":      tx["from"],
        "to_address":        tx.get("to"),
        "value":             tx["value"],
        "gas_price":         tx.get("gasPrice", 0),
        "input":             input_hex,
        "status":            receipt["status"],
        "logs":              serialized_logs,
    }


# ─── Busca de vizinhos no bloco ───────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def get_block_neighbors(
    network: str,
    block_number: int,
    tx_index: int,
    window: int = 5,
) -> dict[str, Any]:
    """
    Retorna as transações vizinhas da vítima no mesmo bloco.

    Busca até ``window`` transações antes e depois do índice da vítima.
    Os dados retornados são simplificados (sem logs/recibos) para reduzir
    a latência — o agente decide quais vizinhos merecem busca completa.

    Args:
        network:      "ethereum" ou "polygon".
        block_number: Número do bloco.
        tx_index:     Posição (index) da transação vítima no bloco.
        window:       Número de transações a buscar para cada lado (padrão 5).

    Returns:
        Dicionário com::

            {
                "block_number":        int,
                "victim_index":        int,
                "total_txs_in_block":  int,
                "before": [
                    {
                        "hash":              str,
                        "transaction_index": int,
                        "from_address":      str,
                        "to_address":        str | None,
                        "gas_price":         int,
                        "fn_selector":       str,  # primeiros 4 bytes do calldata
                    },
                    ...
                ],
                "after": [ ... ]  # mesmo formato
            }

    Raises:
        LookupError:     Bloco não encontrado.
        ConnectionError: Falha de comunicação com o RPC.
    """
    w3 = get_web3(network)

    try:
        block = w3.eth.get_block(block_number, full_transactions=True)
    except BlockNotFound:
        raise LookupError(f"Bloco não encontrado: {block_number}")
    except Exception as exc:
        raise ConnectionError(
            f"Falha ao buscar bloco {block_number} na rede '{network}': {exc}"
        ) from exc

    all_txs = block["transactions"]
    total = len(all_txs)

    start = max(0, tx_index - window)
    end   = min(total, tx_index + window + 1)

    def _simplify(tx: Any) -> dict[str, Any]:
        """Extrai apenas os campos essenciais para triagem rápida."""
        raw_input = tx.get("input", b"")
        input_hex = raw_input.hex() if isinstance(raw_input, bytes) else str(raw_input)
        # Selector de função = primeiros 4 bytes do calldata
        fn_selector = ("0x" + input_hex[2:10]) if len(input_hex) >= 10 else "0x"

        raw_hash = tx.get("hash", b"")
        tx_hash  = raw_hash.hex() if isinstance(raw_hash, bytes) else str(raw_hash)

        return {
            "hash":              tx_hash,
            "transaction_index": tx["transactionIndex"],
            "from_address":      tx["from"],
            "to_address":        tx.get("to"),
            "gas_price":         tx.get("gasPrice", 0),
            "fn_selector":       fn_selector,
        }

    return {
        "block_number":       block_number,
        "victim_index":       tx_index,
        "total_txs_in_block": total,
        "before":             [_simplify(all_txs[i]) for i in range(start, tx_index)],
        "after":              [_simplify(all_txs[i]) for i in range(tx_index + 1, end)],
    }
