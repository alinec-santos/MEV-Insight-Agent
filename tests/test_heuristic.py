"""
Testes unitários da heurística de detecção de sandwich attack.

Todos os testes são independentes de rede, RPC ou LLM.
Os dados são construídos programaticamente para cobrir os cenários:
    - Sandwich completo (HIGH confidence)
    - Sem sandwich (transações não relacionadas)
    - Front-run sem back-run correspondente
    - Vítima sem eventos Swap
    - Cálculo de slippage
    - Decodificação de logs V2 e V3
"""

from __future__ import annotations

import pytest

from app.tools.heuristic import (
    SWAP_V2_TOPIC,
    SWAP_V3_TOPIC,
    SwapEvent,
    SandwichResult,
    _decode_v2_swap,
    _decode_v3_swap,
    _estimate_slippage,
    detect_sandwich,
    parse_swap_events,
)

# ─── Constantes dos fixtures ──────────────────────────────────────────────────

ATTACKER = "0xdeadbeef00000000000000000000000000000001"
VICTIM   = "0xcafebabe00000000000000000000000000000002"
POOL     = "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852"  # USDT/WETH V2 (mainnet)
OTHER_POOL = "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"  # USDC/WETH V2 (mainnet)


# ─── Helpers para construção de fixtures ──────────────────────────────────────

def _enc256(n: int) -> str:
    """Codifica inteiro não-sinalizado como 64 hex chars (32 bytes big-endian)."""
    return n.to_bytes(32, "big").hex()


def _enc256_signed(n: int) -> str:
    """Codifica inteiro sinalizado (int256) como 64 hex chars big-endian."""
    return n.to_bytes(32, "big", signed=True).hex()


def _v2_log(
    pool: str,
    amount0_in: int,
    amount1_in: int,
    amount0_out: int,
    amount1_out: int,
) -> dict:
    """Cria um log de evento Swap V2 com os valores especificados."""
    data = "0x" + (
        _enc256(amount0_in)
        + _enc256(amount1_in)
        + _enc256(amount0_out)
        + _enc256(amount1_out)
    )
    return {
        "address": pool,
        "topics": [
            SWAP_V2_TOPIC,
            "0x" + "0" * 64,  # sender (ignorado pela heurística)
            "0x" + "0" * 64,  # to     (ignorado pela heurística)
        ],
        "data": data,
        "log_index": 0,
        "transaction_index": 0,
    }


def _v3_log(pool: str, amount0: int, amount1: int) -> dict:
    """
    Cria um log de evento Swap V3.
    amount0/amount1 são int256 (sinalizados): positivo = entrando no pool.
    """
    # Preenche campos extras com zeros (sqrtPriceX96, liquidity, tick)
    data = "0x" + (
        _enc256_signed(amount0)
        + _enc256_signed(amount1)
        + _enc256(0)   # sqrtPriceX96
        + _enc256(0)   # liquidity
        + _enc256(0)   # tick
    )
    return {
        "address": pool,
        "topics": [
            SWAP_V3_TOPIC,
            "0x" + "0" * 64,  # sender
            "0x" + "0" * 64,  # recipient
        ],
        "data": data,
        "log_index": 0,
        "transaction_index": 0,
    }


def _tx(
    tx_hash: str,
    tx_index: int,
    from_address: str,
    logs: list[dict],
) -> dict:
    """Cria uma transação mockada no formato de get_transaction."""
    return {
        "hash":              tx_hash,
        "transaction_index": tx_index,
        "from_address":      from_address,
        "to_address":        "0xrouteraddress",
        "value":             0,
        "gas_price":         20_000_000_000,
        "status":            1,
        "logs":              [
            {**log, "transaction_index": tx_index}
            for log in logs
        ],
    }


# ─── Fixture: cenário de sandwich completo ───────────────────────────────────

@pytest.fixture
def sandwich_scenario() -> tuple[dict, list[dict]]:
    """
    Sandwich attack clássico no pool USDT/WETH:
        - token0 = USDT (6 decimais)
        - token1 = WETH (18 decimais)

    Sequência no bloco:
        índice 10: front-run  — atacante vende 5 WETH, recebe 15 000 USDT
        índice 11: vítima     — vende 1 WETH, recebe apenas 2 900 USDT
        índice 12: back-run   — atacante vende 15 000 USDT, recebe 5.05 WETH (lucro)

    Direção: amount1In > 0 → direction=False (vendendo WETH = token1)
    Back-run: amount0In > 0 → direction=True  (vendendo USDT = token0) — OPOSTO
    """
    # front-run: vende WETH (amount1In > 0), recebe USDT (amount0Out > 0)
    front_log = _v2_log(POOL, 0, 5 * 10**18, 15_000 * 10**6, 0)
    # vítima: mesmo padrão, mas recebe menos (preço piorou)
    victim_log = _v2_log(POOL, 0, 1 * 10**18, 2_900 * 10**6, 0)
    # back-run: vende USDT (amount0In > 0), recebe WETH — direção OPOSTA
    back_log = _v2_log(POOL, 15_000 * 10**6, 0, 0, 5_050 * 10**15)

    victim_tx = _tx("0xvictim",    11, VICTIM,   [victim_log])
    front_tx  = _tx("0xfront_run", 10, ATTACKER, [front_log])
    back_tx   = _tx("0xback_run",  12, ATTACKER, [back_log])

    return victim_tx, [front_tx, back_tx]


@pytest.fixture
def no_sandwich_scenario() -> tuple[dict, list[dict]]:
    """Transações não relacionadas: pools diferentes, endereços diferentes."""
    # Vizinho opera em pool diferente
    neighbor_log = _v2_log(OTHER_POOL, 0, 10**18, 2_900 * 10**6, 0)
    victim_log   = _v2_log(POOL,        0, 10**18, 2_900 * 10**6, 0)

    victim_tx   = _tx("0xvictim",    5, VICTIM,        [victim_log])
    neighbor_tx = _tx("0xneighbor",  4, "0xother_user", [neighbor_log])

    return victim_tx, [neighbor_tx]


# ─── Testes de detect_sandwich ────────────────────────────────────────────────

class TestDetectSandwich:

    def test_sandwich_detectado_com_confianca_high(self, sandwich_scenario):
        """Deve detectar sandwich e retornar confiança HIGH."""
        victim, candidates = sandwich_scenario
        result = detect_sandwich(victim, candidates)

        assert result.is_sandwich is True
        assert result.confidence == "HIGH"
        assert result.victim_tx == "0xvictim"

    def test_sandwich_identifica_atacante_correto(self, sandwich_scenario):
        """Deve identificar o endereço do atacante corretamente."""
        victim, candidates = sandwich_scenario
        result = detect_sandwich(victim, candidates)

        assert result.attacker_address == ATTACKER.lower()

    def test_sandwich_identifica_pool_correto(self, sandwich_scenario):
        """Deve identificar o pool onde o ataque ocorreu."""
        victim, candidates = sandwich_scenario
        result = detect_sandwich(victim, candidates)

        assert result.pool_address == POOL.lower()

    def test_sandwich_identifica_txs_front_e_back(self, sandwich_scenario):
        """Deve retornar os hashes de front-run e back-run."""
        victim, candidates = sandwich_scenario
        result = detect_sandwich(victim, candidates)

        assert result.front_run_tx == "0xfront_run"
        assert result.back_run_tx  == "0xback_run"

    def test_sandwich_calcula_slippage_positivo(self, sandwich_scenario):
        """Vítima recebe menos → slippage deve ser positivo."""
        victim, candidates = sandwich_scenario
        result = detect_sandwich(victim, candidates)

        assert result.estimated_slippage_pct is not None
        assert result.estimated_slippage_pct > 0

    def test_sandwich_detalhe_nao_vazio(self, sandwich_scenario):
        """Campo details deve conter explicação legível."""
        victim, candidates = sandwich_scenario
        result = detect_sandwich(victim, candidates)

        assert len(result.details) > 0
        # Deve mencionar o pool
        assert POOL.lower() in result.details.lower()

    def test_sem_sandwich_pools_diferentes(self, no_sandwich_scenario):
        """Não deve detectar sandwich quando os pools são diferentes."""
        victim, candidates = no_sandwich_scenario
        result = detect_sandwich(victim, candidates)

        assert result.is_sandwich is False

    def test_sem_sandwich_sem_candidatos(self):
        """Não deve detectar sandwich com lista de candidatos vazia."""
        log = _v2_log(POOL, 0, 10**18, 2_900 * 10**6, 0)
        victim = _tx("0xvictim", 5, VICTIM, [log])
        result = detect_sandwich(victim, [])

        assert result.is_sandwich is False
        assert result.victim_tx == "0xvictim"

    def test_sem_sandwich_vitima_sem_swap(self):
        """Vítima sem eventos Swap → heurística não aplicável."""
        victim = _tx("0xvictim", 5, VICTIM, [])  # sem logs
        result = detect_sandwich(victim, [])

        assert result.is_sandwich is False
        assert "Swap" in result.details

    def test_sem_sandwich_frontrun_sem_backrun(self):
        """Front-run sem back-run correspondente não é sandwich."""
        front_log  = _v2_log(POOL, 0, 5 * 10**18, 15_000 * 10**6, 0)
        victim_log = _v2_log(POOL, 0, 1 * 10**18,  2_900 * 10**6, 0)

        victim   = _tx("0xvictim",    11, VICTIM,   [victim_log])
        front_tx = _tx("0xfront_run", 10, ATTACKER, [front_log])
        # Sem back-run!

        result = detect_sandwich(victim, [front_tx])
        assert result.is_sandwich is False

    def test_sem_sandwich_mesmo_endereco_vitima_frontrun(self):
        """
        Front-run do mesmo endereço da vítima não é sandwich.
        (Pode ser um MEV bot que é o próprio remetente — descartado.)
        """
        log = _v2_log(POOL, 0, 5 * 10**18, 15_000 * 10**6, 0)
        # Front-run e vítima têm o MESMO endereço
        front_tx = _tx("0xfront", 10, VICTIM, [log])
        victim   = _tx("0xvictim", 11, VICTIM, [log])

        result = detect_sandwich(victim, [front_tx])
        assert result.is_sandwich is False

    def test_sandwich_v3_detectado(self):
        """
        Deve detectar sandwich em pools Uniswap V3.

        V3: amount0 > 0 → vendendo token0; amount0 < 0 → comprando token0.
        Front-run e vítima vendem token1 (amount1 > 0 → pool recebe token1).
        Back-run vende token0 (amount0 > 0).
        """
        # Front-run: pool recebe token1 (amount1 > 0), envia token0 (amount0 < 0)
        front_log = _v3_log(POOL, -(15_000 * 10**6), 5 * 10**18)
        # Vítima: mesmo padrão
        victim_log = _v3_log(POOL, -(2_900 * 10**6), 1 * 10**18)
        # Back-run: pool recebe token0 (amount0 > 0), envia token1 (amount1 < 0)
        back_log  = _v3_log(POOL, 15_000 * 10**6, -(5_050 * 10**15))

        victim   = _tx("0xvictim_v3",    11, VICTIM,   [victim_log])
        front_tx = _tx("0xfront_run_v3", 10, ATTACKER, [front_log])
        back_tx  = _tx("0xback_run_v3",  12, ATTACKER, [back_log])

        result = detect_sandwich(victim, [front_tx, back_tx])
        assert result.is_sandwich is True
        assert result.confidence == "HIGH"
        assert result.attacker_address == ATTACKER.lower()


# ─── Testes de parse_swap_events ─────────────────────────────────────────────

class TestParseSwapEvents:

    def test_parse_log_v2_corretamente(self):
        """Deve extrair swap V2 com os valores corretos."""
        log = _v2_log(POOL, 0, 10**18, 3_000 * 10**6, 0)
        tx  = _tx("0xhash", 5, VICTIM, [log])
        swaps = parse_swap_events(tx)

        assert len(swaps) == 1
        s = swaps[0]
        assert s.pool       == POOL.lower()
        assert s.direction  is False          # vendendo token1 (WETH)
        assert s.amount_in  == 10**18
        assert s.amount_out == 3_000 * 10**6
        assert s.version    == 2

    def test_parse_log_v2_direcao_true(self):
        """Deve identificar direção True quando amount0In > 0."""
        log = _v2_log(POOL, 3_000 * 10**6, 0, 0, 10**18)
        tx  = _tx("0xhash", 5, VICTIM, [log])
        swaps = parse_swap_events(tx)

        assert len(swaps) == 1
        assert swaps[0].direction is True     # vendendo token0 (USDT)

    def test_parse_log_v3_corretamente(self):
        """Deve extrair swap V3 com os valores e direção corretos."""
        log = _v3_log(POOL, -(3_000 * 10**6), 10**18)  # recebe token0, envia token1
        tx  = _tx("0xhash", 5, VICTIM, [log])
        swaps = parse_swap_events(tx)

        assert len(swaps) == 1
        s = swaps[0]
        # amount0 < 0 → pool enviou token0 → usuário comprou token0 → direction=False
        assert s.direction  is False
        assert s.amount_in  == 10**18          # token1 entrou (abs)
        assert s.amount_out == 3_000 * 10**6   # token0 saiu (abs)
        assert s.version    == 3

    def test_parse_sem_logs_retorna_vazio(self):
        """Transação sem logs deve retornar lista vazia."""
        tx = _tx("0xhash", 5, VICTIM, [])
        assert parse_swap_events(tx) == []

    def test_parse_ignora_log_topico_desconhecido(self):
        """Logs com tópicos não reconhecidos devem ser ignorados."""
        log = {
            "address": POOL,
            "topics":  ["0xdeadbeef" + "0" * 56],  # tópico desconhecido
            "data":    "0x" + "00" * 128,
            "log_index": 0,
        }
        tx = _tx("0xhash", 5, VICTIM, [log])
        assert parse_swap_events(tx) == []

    def test_parse_multiplos_swaps(self):
        """Transação com dois Swaps deve retornar ambos."""
        log1 = _v2_log(POOL,       0, 10**18,  3_000 * 10**6, 0)
        log2 = _v2_log(OTHER_POOL, 0, 2*10**18, 6_000 * 10**6, 0)
        tx   = _tx("0xhash", 5, VICTIM, [log1, log2])
        swaps = parse_swap_events(tx)

        assert len(swaps) == 2


# ─── Testes de _decode_v2_swap ────────────────────────────────────────────────

class TestDecodeV2Swap:

    def test_decode_valido(self):
        """Deve decodificar log V2 válido."""
        log = _v2_log(POOL, 0, 10**18, 3_000 * 10**6, 0)
        result = _decode_v2_swap(log, "0xhash", 5, VICTIM)

        assert result is not None
        assert result.direction is False
        assert result.amount_in == 10**18

    def test_decode_data_curta_retorna_none(self):
        """Data com menos de 256 hex chars deve retornar None."""
        log = {
            "address": POOL,
            "topics":  [SWAP_V2_TOPIC, "0x" + "0" * 64, "0x" + "0" * 64],
            "data":    "0x" + "00" * 10,  # muito curto
        }
        assert _decode_v2_swap(log, "0xhash", 5, VICTIM) is None

    def test_decode_amount_zeros_retorna_none(self):
        """Swap com todos os amounts zerados deve retornar None."""
        log = _v2_log(POOL, 0, 0, 0, 0)
        assert _decode_v2_swap(log, "0xhash", 5, VICTIM) is None


# ─── Testes de _decode_v3_swap ────────────────────────────────────────────────

class TestDecodeV3Swap:

    def test_decode_valido(self):
        """Deve decodificar log V3 válido."""
        log = _v3_log(POOL, -(3_000 * 10**6), 10**18)
        result = _decode_v3_swap(log, "0xhash", 5, VICTIM)

        assert result is not None
        assert result.version == 3
        assert result.direction is False  # amount0 < 0

    def test_decode_data_curta_retorna_none(self):
        """Data com menos de 128 hex chars deve retornar None."""
        log = {
            "address": POOL,
            "topics":  [SWAP_V3_TOPIC, "0x" + "0" * 64, "0x" + "0" * 64],
            "data":    "0x" + "00" * 20,
        }
        assert _decode_v3_swap(log, "0xhash", 5, VICTIM) is None


# ─── Testes de _estimate_slippage ────────────────────────────────────────────

class TestEstimateSlippage:

    def _make_swap(self, amount_in: int, amount_out: int, tx_index: int = 5) -> SwapEvent:
        return SwapEvent(
            pool=POOL, tx_hash="0xhash", tx_index=tx_index,
            from_address=VICTIM, direction=False,
            amount_in=amount_in, amount_out=amount_out, version=2,
        )

    def test_slippage_positivo_vitima_recebe_menos(self):
        """
        Taxa front-run = 3000/10^18
        Taxa vítima    = 2900/10^18  (pior)
        Slippage esperado ≈ 3.33%
        """
        fr = self._make_swap(10**18, 3_000 * 10**6, tx_index=10)
        v  = self._make_swap(10**18, 2_900 * 10**6, tx_index=11)

        s = _estimate_slippage(v, fr)
        assert s is not None
        assert s > 0
        # (3000 - 2900) / 3000 * 100 = 3.333...
        assert abs(s - 3.333) < 0.01

    def test_slippage_zero_mesma_taxa(self):
        """Quando as taxas são idênticas, slippage deve ser 0."""
        swap = self._make_swap(10**18, 3_000 * 10**6)
        assert _estimate_slippage(swap, swap) == 0.0

    def test_slippage_none_amount_in_zero(self):
        """Deve retornar None se amount_in for zero (divisão por zero)."""
        swap = self._make_swap(0, 0)
        assert _estimate_slippage(swap, swap) is None

    def test_slippage_negativo_vitima_recebe_mais(self):
        """
        Se a vítima recebeu mais que o front-runner (caso improvável),
        o slippage deve ser negativo.
        """
        fr = self._make_swap(10**18, 2_900 * 10**6, tx_index=10)
        v  = self._make_swap(10**18, 3_000 * 10**6, tx_index=11)

        s = _estimate_slippage(v, fr)
        assert s is not None
        assert s < 0
