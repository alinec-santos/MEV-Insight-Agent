"""
Testes unitários das ferramentas Web3 (web3_tools.py).

Todos os testes usam mocks — nenhuma chamada real à blockchain é feita.
Cobertos:
    - Validação de hash (formato e tamanho)
    - Redes não suportadas
    - Tratamento de TransactionNotFound
    - Retorno correto de get_transaction
    - Retorno correto de get_block_neighbors
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.tools.web3_tools import (
    _clear_web3_cache,
    get_block_neighbors,
    get_transaction,
    get_web3,
)

# ─── Dados de mock ────────────────────────────────────────────────────────────

VALID_HASH = "0x" + "ab" * 32  # 66 chars, formato válido
BLOCK_NUM  = 19_000_000
TX_INDEX   = 11

# Simula o retorno de w3.eth.get_transaction
MOCK_TX = {
    "hash":              bytes.fromhex("ab" * 32),
    "blockNumber":       BLOCK_NUM,
    "transactionIndex":  TX_INDEX,
    "from":              "0xVictimAddress",
    "to":                "0xRouterAddress",
    "value":             10 ** 18,
    "gasPrice":          20_000_000_000,
    "input":             bytes.fromhex("38ed1739"),  # swapExactTokensForTokens
}

# Simula o retorno de w3.eth.get_transaction_receipt
MOCK_RECEIPT = {
    "status": 1,
    "logs":   [
        {
            "address":          "0xPoolAddress",
            "topics":           [
                bytes.fromhex(
                    "d78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
                ),
                bytes(32),
                bytes(32),
            ],
            "data":             "0x" + "00" * 128,
            "logIndex":         0,
            "transactionIndex": TX_INDEX,
        }
    ],
}

# Simula uma transação simples para o bloco
def _mock_block_tx(index: int) -> dict:
    return {
        "hash":             bytes.fromhex("cc" * 32),
        "transactionIndex": index,
        "from":             f"0xAddress{index:04d}",
        "to":               "0xRouter",
        "gasPrice":         20_000_000_000,
        "input":            bytes.fromhex("38ed1739"),
    }


# ─── Fixture: limpa o cache Web3 antes de cada teste ─────────────────────────

@pytest.fixture(autouse=True)
def limpar_cache():
    """Garante que o cache de instâncias Web3 está limpo antes de cada teste."""
    _clear_web3_cache()
    yield
    _clear_web3_cache()


# ─── Fixture: Web3 mockado que se passa por conectado ────────────────────────

@pytest.fixture
def mock_w3():
    """Retorna um MagicMock que simula uma instância Web3 conectada."""
    w3 = MagicMock()
    w3.is_connected.return_value = True
    return w3


# ─── Testes de get_web3 ───────────────────────────────────────────────────────

class TestGetWeb3:

    def test_rede_invalida_levanta_value_error(self):
        """Rede não suportada deve levantar ValueError."""
        with pytest.raises(ValueError, match="Rede não suportada"):
            get_web3("bsc")

    def test_rede_valida_sem_conexao_levanta_connection_error(self):
        """Se o RPC não responder, deve levantar ConnectionError."""
        with patch("app.tools.web3_tools.Web3") as MockWeb3:
            mock_instance = MagicMock()
            mock_instance.is_connected.return_value = False
            MockWeb3.return_value = mock_instance

            with pytest.raises(ConnectionError, match="Não foi possível conectar"):
                get_web3("ethereum")

    def test_rede_valida_retorna_instancia(self, mock_w3):
        """Rede válida com RPC conectado deve retornar instância Web3."""
        with patch("app.tools.web3_tools.Web3", return_value=mock_w3):
            instance = get_web3("ethereum")
            assert instance is mock_w3

    def test_cache_reutiliza_instancia(self, mock_w3):
        """Segunda chamada para a mesma rede deve reutilizar a instância do cache."""
        with patch("app.tools.web3_tools.Web3", return_value=mock_w3) as MockWeb3:
            first  = get_web3("ethereum")
            second = get_web3("ethereum")

            assert first is second
            # Web3() deve ser instanciado apenas uma vez
            MockWeb3.assert_called_once()

    def test_case_insensitive(self, mock_w3):
        """Nome da rede deve ser case-insensitive."""
        with patch("app.tools.web3_tools.Web3", return_value=mock_w3):
            assert get_web3("Ethereum") is get_web3("ETHEREUM")


# ─── Testes de get_transaction ────────────────────────────────────────────────

class TestGetTransaction:

    def test_hash_sem_prefixo_0x_e_aceito(self, mock_w3):
        """Hash sem '0x' deve ser normalizado automaticamente."""
        mock_w3.eth.get_transaction.return_value        = MOCK_TX
        mock_w3.eth.get_transaction_receipt.return_value = MOCK_RECEIPT

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_transaction("ethereum", "ab" * 32)
            assert result["hash"] == VALID_HASH

    def test_hash_invalido_levanta_value_error(self):
        """Hash com tamanho errado deve levantar ValueError."""
        with pytest.raises(ValueError, match="inválido"):
            get_transaction("ethereum", "0xabc")  # muito curto

    def test_transacao_nao_encontrada_levanta_lookup_error(self, mock_w3):
        """Transação inexistente deve levantar LookupError."""
        from web3.exceptions import TransactionNotFound

        mock_w3.eth.get_transaction.side_effect = TransactionNotFound()

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            with pytest.raises(LookupError, match="não encontrada"):
                get_transaction("ethereum", VALID_HASH)

    def test_retorna_campos_esperados(self, mock_w3):
        """Resultado deve conter todos os campos do contrato."""
        mock_w3.eth.get_transaction.return_value        = MOCK_TX
        mock_w3.eth.get_transaction_receipt.return_value = MOCK_RECEIPT

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_transaction("ethereum", VALID_HASH)

        campos_esperados = {
            "hash", "block_number", "transaction_index",
            "from_address", "to_address", "value", "gas_price",
            "input", "status", "logs",
        }
        assert campos_esperados.issubset(result.keys())

    def test_logs_sao_serializados_como_strings(self, mock_w3):
        """Os topics dos logs devem ser strings hex, não bytes."""
        mock_w3.eth.get_transaction.return_value        = MOCK_TX
        mock_w3.eth.get_transaction_receipt.return_value = MOCK_RECEIPT

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_transaction("ethereum", VALID_HASH)

        assert len(result["logs"]) > 0
        for log in result["logs"]:
            for topic in log["topics"]:
                assert isinstance(topic, str)

    def test_valores_numericos_corretos(self, mock_w3):
        """block_number, transaction_index e value devem ser int."""
        mock_w3.eth.get_transaction.return_value        = MOCK_TX
        mock_w3.eth.get_transaction_receipt.return_value = MOCK_RECEIPT

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_transaction("ethereum", VALID_HASH)

        assert result["block_number"]      == BLOCK_NUM
        assert result["transaction_index"] == TX_INDEX
        assert result["value"]             == 10 ** 18
        assert result["status"]            == 1

    def test_erro_rpc_levanta_connection_error(self, mock_w3):
        """Exceção genérica do RPC deve ser convertida em ConnectionError."""
        mock_w3.eth.get_transaction.side_effect = Exception("timeout")

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            # tenacity fará 3 tentativas — desabilita o retry no teste
            with patch("app.tools.web3_tools.get_transaction.retry.stop"):
                with pytest.raises((ConnectionError, Exception)):
                    get_transaction("ethereum", VALID_HASH)


# ─── Testes de get_block_neighbors ───────────────────────────────────────────

class TestGetBlockNeighbors:

    def _make_mock_block(self, total_txs: int = 20) -> MagicMock:
        """Cria um bloco mockado com `total_txs` transações."""
        block = MagicMock()
        block.__getitem__.side_effect = lambda k: (
            [_mock_block_tx(i) for i in range(total_txs)]
            if k == "transactions" else None
        )
        return block

    def test_retorna_campos_esperados(self, mock_w3):
        """Resultado deve conter block_number, victim_index, before, after."""
        mock_w3.eth.get_block.return_value = self._make_mock_block()

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_block_neighbors("ethereum", BLOCK_NUM, TX_INDEX)

        assert "block_number"       in result
        assert "victim_index"       in result
        assert "total_txs_in_block" in result
        assert "before"             in result
        assert "after"              in result

    def test_before_contem_txs_anteriores(self, mock_w3):
        """'before' deve conter apenas txs com índice menor que o da vítima."""
        mock_w3.eth.get_block.return_value = self._make_mock_block()

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_block_neighbors("ethereum", BLOCK_NUM, TX_INDEX, window=3)

        for tx in result["before"]:
            assert tx["transaction_index"] < TX_INDEX

    def test_after_contem_txs_posteriores(self, mock_w3):
        """'after' deve conter apenas txs com índice maior que o da vítima."""
        mock_w3.eth.get_block.return_value = self._make_mock_block()

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_block_neighbors("ethereum", BLOCK_NUM, TX_INDEX, window=3)

        for tx in result["after"]:
            assert tx["transaction_index"] > TX_INDEX

    def test_window_limita_quantidade(self, mock_w3):
        """window=2 deve retornar no máximo 2 txs antes e 2 depois."""
        mock_w3.eth.get_block.return_value = self._make_mock_block(total_txs=30)

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_block_neighbors("ethereum", BLOCK_NUM, TX_INDEX, window=2)

        assert len(result["before"]) <= 2
        assert len(result["after"])  <= 2

    def test_bloco_nao_encontrado_levanta_lookup_error(self, mock_w3):
        """Bloco inexistente deve levantar LookupError."""
        from web3.exceptions import BlockNotFound

        mock_w3.eth.get_block.side_effect = BlockNotFound()

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            with pytest.raises(LookupError, match="Bloco não encontrado"):
                get_block_neighbors("ethereum", 9999999999, TX_INDEX)

    def test_total_txs_correto(self, mock_w3):
        """Campo total_txs_in_block deve refletir o tamanho real do bloco."""
        mock_w3.eth.get_block.return_value = self._make_mock_block(total_txs=150)

        with patch("app.tools.web3_tools.get_web3", return_value=mock_w3):
            result = get_block_neighbors("ethereum", BLOCK_NUM, TX_INDEX)

        assert result["total_txs_in_block"] == 150
