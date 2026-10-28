# Slippage e impacto de preço

## Impacto de preço (price impact)

É quanto o **seu próprio swap** move o preço do pool. Em um AMM de produto constante, quanto maior a troca em relação às reservas, maior o impacto. Trocar 1% das reservas de um pool causa um impacto de cerca de 1%; trocar 10% causa bem mais, porque a curva x · y = k fica cada vez mais inclinada.

## Slippage

**Slippage** é a diferença entre o preço que você **esperava** quando assinou a transação e o preço que você **efetivamente recebeu** quando ela foi executada. Ele pode acontecer por:

- movimentos normais do mercado entre o envio e a confirmação;
- outras transações legítimas executadas antes da sua no mesmo bloco;
- **ataques sandwich**, em que um front-run piora o preço de propósito.

## Tolerância de slippage

As interfaces de DEX pedem uma **tolerância de slippage** (ex.: 0,5% ou 1%). Ela vira um parâmetro da transação, como `amountOutMin` nos roteadores da Uniswap: se o valor recebido ficar abaixo desse mínimo, a transação **reverte**.

O ponto crítico: a tolerância também define **quanto um atacante pode extrair**. Com 5% de tolerância, o bot pode piorar seu preço em quase 5% sem que sua transação falhe. Tolerâncias altas em tokens líquidos são um convite para sandwiches.

## Como estimar o prejuízo de um sandwich

Uma estimativa simples compara as **taxas de câmbio efetivas**:

    taxa = tokens recebidos / tokens enviados

    prejuízo % ≈ (taxa_front_run − taxa_vítima) / taxa_front_run × 100

O front-run opera antes da vítima, com um preço ainda "limpo". Ainda assim, essa estimativa **mistura** o impacto de preço natural da vítima com o efeito do ataque. Uma medida exata exigiria simular o swap da vítima sem o front-run (contrafactual).

## Boas práticas

- Use a menor tolerância que ainda permita a execução (pares líquidos: 0,1%–0,5%).
- Divida ordens grandes ou use agregadores com proteção de MEV.
- Prefira pools com liquidez profunda.

## Fontes

- Uniswap Docs — "Swaps" (price impact e slippage): https://docs.uniswap.org/concepts/protocol/swaps
- Uniswap Support — "What is price impact?": https://support.uniswap.org/hc/en-us/articles/8671539602317-What-is-price-impact
- Zhou, L. et al. (2021). "High-Frequency Trading on Decentralized On-Chain Exchanges" (relação entre tolerância de slippage e lucro do atacante). arXiv:2009.14021 — https://arxiv.org/abs/2009.14021
