"""
Heurística determinística para detecção de sandwich attacks em DEXs.

Princípio de design: esta módulo NÃO usa LLM. Toda a lógica é pura
Python, testável e reprodutível. O LLM consome o ``SandwichResult``
gerado aqui apenas para produzir a explicação em linguagem natural.

Suporte:
    - Uniswap V2 e forks compatíveis (SushiSwap, QuickSwap, etc.)
    - Uniswap V3 e forks compatíveis

Algoritmo de detecção:
    1. Extrai eventos ``Swap`` dos logs da transação vítima.
    2. Extrai eventos ``Swap`` de todas as transações candidatas
       (vizinhas no mesmo bloco).
    3. Para cada swap da vítima, procura:
       a. Um **front-run**: mesmo pool, mesma direção de troca,
          posição anterior, endereço diferente do da vítima.
       b. Um **back-run**: mesmo pool, direção OPOSTA, posição
          posterior, MESMO endereço do front-run.
    4. Se o par (front-run, back-run) for encontrado, o ataque é
       confirmado com confiança HIGH.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Assinaturas dos eventos Swap ─────────────────────────────────────────────

# Uniswap V2: Swap(address indexed sender, uint amount0In, uint amount1In,
#                  uint amount0Out, uint amount1Out, address indexed to)
SWAP_V2_TOPIC: str = (
    "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
)

# Uniswap V3: Swap(address indexed sender, address indexed recipient,
#                  int256 amount0, int256 amount1, uint160 sqrtPriceX96,
#                  uint128 liquidity, int24 tick)
SWAP_V3_TOPIC: str = (
    "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
)


# ─── Modelos de dados ─────────────────────────────────────────────────────────

@dataclass
class SwapEvent:
    """Representa um evento Swap decodificado de um log de transação DEX."""

    pool: str
    """Endereço do pool/par (em minúsculas)."""

    tx_hash: str
    """Hash da transação que contém o swap."""

    tx_index: int
    """Posição da transação no bloco (menor = mais cedo)."""

    from_address: str
    """Endereço EOA que submeteu a transação (em minúsculas)."""

    direction: bool
    """
    Direção do swap:
        True  = usuário está vendendo token0 (token0 → token1)
        False = usuário está vendendo token1 (token1 → token0)
    """

    amount_in: int
    """Quantidade do token enviado ao pool (em wei / menor unidade)."""

    amount_out: int
    """Quantidade do token recebido do pool (em wei / menor unidade)."""

    version: int
    """Versão do protocolo: 2 = Uniswap V2-style, 3 = Uniswap V3-style."""


@dataclass
class SandwichResult:
    """Resultado estruturado da análise heurística de sandwich attack."""

    is_sandwich: bool
    """True se o padrão de sandwich foi identificado."""

    confidence: str
    """
    Nível de confiança:
        HIGH  — par (front-run, back-run) identificado no mesmo pool
        NONE  — nenhum padrão encontrado
    """

    victim_tx: str
    """Hash da transação analisada como vítima."""

    front_run_tx: Optional[str] = None
    """Hash da transação de front-run (se encontrada)."""

    back_run_tx: Optional[str] = None
    """Hash da transação de back-run (se encontrada)."""

    attacker_address: Optional[str] = None
    """Endereço do atacante (mesmo nas duas txs flanqueadoras)."""

    pool_address: Optional[str] = None
    """Endereço do pool onde o ataque ocorreu."""

    estimated_slippage_pct: Optional[float] = None
    """
    Estimativa do slippage adicional causado pelo front-run (em %).
    Positivo = vítima recebeu menos do que o front-runner por unidade enviada.
    """

    details: str = ""
    """Descrição legível do resultado, pronta para o LLM usar como contexto."""


# ─── Decodificação de logs ────────────────────────────────────────────────────

def _decode_v2_swap(
    log: dict,
    tx_hash: str,
    tx_index: int,
    from_address: str,
) -> Optional[SwapEvent]:
    """
    Decodifica um log de evento Swap compatível com Uniswap V2.

    Layout do campo ``data`` (4 × uint256, big-endian, 32 bytes cada):
        bytes   0– 31 → amount0In
        bytes  32– 63 → amount1In
        bytes  64– 95 → amount0Out
        bytes  96–127 → amount1Out

    Returns:
        SwapEvent preenchido, ou None se o log for inválido/incompleto.
    """
    try:
        raw = log["data"]
        if isinstance(raw, str):
            raw = raw[2:] if raw.startswith("0x") else raw  # remove prefixo
        else:
            raw = raw.hex()

        if len(raw) < 256:  # 4 campos × 64 hex chars
            return None

        amount0_in  = int(raw[0:64],   16)
        amount1_in  = int(raw[64:128],  16)
        amount0_out = int(raw[128:192], 16)
        amount1_out = int(raw[192:256], 16)

        # Valida: pelo menos um token deve estar entrando no pool
        if amount0_in == 0 and amount1_in == 0:
            return None

        # direction=True → usuário vende token0 (amount0In > 0)
        direction  = amount0_in > 0
        amount_in  = amount0_in  if direction else amount1_in
        amount_out = amount1_out if direction else amount0_out

        return SwapEvent(
            pool=log["address"].lower(),
            tx_hash=tx_hash,
            tx_index=tx_index,
            from_address=from_address.lower(),
            direction=direction,
            amount_in=amount_in,
            amount_out=amount_out,
            version=2,
        )
    except (KeyError, ValueError, IndexError) as exc:
        logger.debug("Falha ao decodificar log Swap V2: %s", exc)
        return None


def _decode_v3_swap(
    log: dict,
    tx_hash: str,
    tx_index: int,
    from_address: str,
) -> Optional[SwapEvent]:
    """
    Decodifica um log de evento Swap compatível com Uniswap V3.

    Layout do campo ``data`` (int256, int256, uint160, uint128, int24):
        bytes  0– 31 → amount0  (int256, sinalizado)
        bytes 32– 63 → amount1  (int256, sinalizado)
        bytes 64– 95 → sqrtPriceX96 (ignorado aqui)
        bytes 96–127 → liquidity     (ignorado aqui)
        bytes 128–   → tick           (ignorado aqui)

    Convenção V3:
        amount0 > 0 → pool recebeu token0 → usuário está vendendo token0
        amount0 < 0 → pool enviou token0  → usuário está comprando token0

    Returns:
        SwapEvent preenchido, ou None se o log for inválido/incompleto.
    """
    try:
        raw = log["data"]
        if isinstance(raw, str):
            raw = raw[2:] if raw.startswith("0x") else raw
        else:
            raw = raw.hex()

        if len(raw) < 128:  # mínimo 2 campos de int256
            return None

        amount0 = int.from_bytes(bytes.fromhex(raw[0:64]),  "big", signed=True)
        amount1 = int.from_bytes(bytes.fromhex(raw[64:128]), "big", signed=True)

        if amount0 == 0 and amount1 == 0:
            return None

        # amount0 > 0 → pool recebeu token0 → direção: token0 → token1
        direction  = amount0 > 0
        amount_in  = abs(amount0) if direction else abs(amount1)
        amount_out = abs(amount1) if direction else abs(amount0)

        return SwapEvent(
            pool=log["address"].lower(),
            tx_hash=tx_hash,
            tx_index=tx_index,
            from_address=from_address.lower(),
            direction=direction,
            amount_in=amount_in,
            amount_out=amount_out,
            version=3,
        )
    except (KeyError, ValueError, IndexError) as exc:
        logger.debug("Falha ao decodificar log Swap V3: %s", exc)
        return None


# ─── API pública ──────────────────────────────────────────────────────────────

def parse_swap_events(tx_data: dict) -> list[SwapEvent]:
    """
    Extrai todos os eventos Swap (V2 e V3) dos logs de uma transação.

    Args:
        tx_data: Dicionário no formato produzido por ``get_transaction``,
                 contendo pelo menos os campos ``hash``,
                 ``transaction_index``, ``from_address`` e ``logs``.

    Returns:
        Lista de :class:`SwapEvent`. Vazia para transações sem swaps.
    """
    swaps: list[SwapEvent] = []
    tx_hash   = tx_data.get("hash", "")
    tx_index  = tx_data.get("transaction_index", 0)
    from_addr = tx_data.get("from_address", "")

    for log in tx_data.get("logs", []):
        topics = log.get("topics", [])
        if not topics:
            continue

        topic0 = topics[0].lower()
        event: Optional[SwapEvent] = None

        if topic0 == SWAP_V2_TOPIC:
            event = _decode_v2_swap(log, tx_hash, tx_index, from_addr)
        elif topic0 == SWAP_V3_TOPIC:
            event = _decode_v3_swap(log, tx_hash, tx_index, from_addr)

        if event is not None:
            swaps.append(event)

    return swaps


def _estimate_slippage(
    victim: SwapEvent,
    front_run: SwapEvent,
) -> Optional[float]:
    """
    Estima o slippage adicional causado pelo front-run na vítima.

    Compara as taxas de câmbio efetivas:
        taxa = amount_out / amount_in  (tokens recebidos por unidade enviada)

    O slippage causado pelo ataque é a queda percentual nessa taxa entre
    a transação do front-runner (que operou com um preço ainda favorável)
    e a da vítima (que operou após o front-run deteriorar o preço).

    Formula::
        slippage_pct = (taxa_front_run - taxa_vítima) / taxa_front_run × 100

    Returns:
        Percentual de slippage (float positivo = vítima prejudicada),
        ou None se o cálculo não for possível.
    """
    if victim.amount_in == 0 or front_run.amount_in == 0:
        return None

    taxa_vitima    = victim.amount_out    / victim.amount_in
    taxa_front_run = front_run.amount_out / front_run.amount_in

    if taxa_front_run == 0:
        return None

    slippage = (taxa_front_run - taxa_vitima) / taxa_front_run * 100.0
    return round(slippage, 4)


def detect_sandwich(
    victim_tx: dict,
    candidate_txs: list[dict],
) -> SandwichResult:
    """
    Heurística determinística de detecção de sandwich attack.

    Recebe a transação vítima e uma lista de transações candidatas
    (tipicamente as vizinhas imediatas no mesmo bloco, já buscadas com
    ``get_transaction`` para conter os logs/recibos completos).

    O algoritmo busca o padrão clássico de sandwich::

        [front-run]  ← mesmo pool, mesma direção, ANTES da vítima, endereço X
        [VÍTIMA]     ← transação analisada
        [back-run]   ← mesmo pool, direção OPOSTA, DEPOIS da vítima, MESMO endereço X

    Args:
        victim_tx:     Dict no formato de ``get_transaction``.
        candidate_txs: Lista de dicts no mesmo formato, representando as
                       transações vizinhas com logs disponíveis.

    Returns:
        :class:`SandwichResult` com o resultado completo da análise.
    """
    victim_hash  = victim_tx.get("hash", "")
    victim_index = victim_tx.get("transaction_index", 0)

    logger.info(
        "Iniciando detecção de sandwich | tx=%s | candidatos=%d",
        victim_hash, len(candidate_txs),
    )

    # Passo 1: extrai swaps da vítima
    victim_swaps = parse_swap_events(victim_tx)
    if not victim_swaps:
        return SandwichResult(
            is_sandwich=False,
            confidence="NONE",
            victim_tx=victim_hash,
            details=(
                "A transação analisada não contém eventos Swap reconhecíveis "
                "(Uniswap V2 ou V3). Não é possível aplicar a heurística."
            ),
        )

    # Passo 2: extrai swaps de todos os candidatos
    candidate_swaps: list[SwapEvent] = []
    for tx in candidate_txs:
        candidate_swaps.extend(parse_swap_events(tx))

    logger.debug(
        "Swaps extraídos | vítima=%d | candidatos=%d",
        len(victim_swaps), len(candidate_swaps),
    )

    # Passo 3: busca par (front-run, back-run) para cada swap da vítima
    for victim_swap in victim_swaps:
        pool = victim_swap.pool

        # Front-runs: mesmo pool, mesma direção, antes da vítima, endereço distinto
        front_runs = [
            s for s in candidate_swaps
            if (
                s.pool      == pool
                and s.direction  == victim_swap.direction
                and s.tx_index   <  victim_index
                and s.from_address != victim_swap.from_address
            )
        ]

        # Back-runs: mesmo pool, direção OPOSTA, depois da vítima
        back_runs = [
            s for s in candidate_swaps
            if (
                s.pool      == pool
                and s.direction  != victim_swap.direction
                and s.tx_index   >  victim_index
            )
        ]

        # Passo 4: verifica se algum front-runner fez também o back-run
        for fr in front_runs:
            matching_backs = [
                br for br in back_runs if br.from_address == fr.from_address
            ]
            if not matching_backs:
                continue

            br = matching_backs[0]
            slippage = _estimate_slippage(victim_swap, fr)

            partes = [
                f"✅ Sandwich attack detectado no pool {pool}.",
                f"• Front-run : {fr.tx_hash} (índice {fr.tx_index})"
                f" | endereço atacante: {fr.from_address}",
                f"• Vítima    : {victim_hash} (índice {victim_index})",
                f"• Back-run  : {br.tx_hash} (índice {br.tx_index})"
                f" | mesmo atacante confirmado",
            ]
            if slippage is not None:
                partes.append(
                    f"• Slippage estimado causado pelo ataque: {slippage:.2f}%"
                )

            logger.info(
                "Sandwich confirmado | pool=%s | atacante=%s | slippage=%.2f%%",
                pool, fr.from_address, slippage or 0.0,
            )

            return SandwichResult(
                is_sandwich=True,
                confidence="HIGH",
                victim_tx=victim_hash,
                front_run_tx=fr.tx_hash,
                back_run_tx=br.tx_hash,
                attacker_address=fr.from_address,
                pool_address=pool,
                estimated_slippage_pct=slippage,
                details="\n".join(partes),
            )

    # Nenhum padrão encontrado
    return SandwichResult(
        is_sandwich=False,
        confidence="NONE",
        victim_tx=victim_hash,
        details=(
            f"❌ Nenhum padrão de sandwich encontrado. "
            f"Analisados {len(candidate_swaps)} swaps de "
            f"{len(candidate_txs)} transações vizinhas."
        ),
    )
