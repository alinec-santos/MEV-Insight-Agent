# AMMs e a fórmula do produto constante (Uniswap V2)

## O que é um AMM

Um **Automated Market Maker** (formador de mercado automatizado) substitui o livro de ofertas tradicional por um **pool de liquidez**: um contrato que guarda reservas de dois tokens (ex.: WETH e USDC). Qualquer pessoa pode trocar um token pelo outro diretamente com o pool, e o preço é calculado por uma fórmula matemática.

## A fórmula x · y = k

No Uniswap V2, o pool mantém o produto das reservas constante:

    x · y = k

onde `x` e `y` são as reservas dos dois tokens. Quando alguém deposita Δx do token X, recebe Δy do token Y de forma que o produto continue igual (desconsiderando a taxa):

    (x + Δx) · (y − Δy) = k

O **preço marginal** é a razão entre as reservas (y/x). Cada compra torna o token comprado mais escasso no pool e, portanto, mais caro.

## Taxa

No Uniswap V2 cada swap paga **0,3%** de taxa, que fica no pool como remuneração aos provedores de liquidez.

## Por que isso importa para o MEV

Como o preço depende só das reservas, **qualquer pessoa pode calcular** com precisão quanto uma transação pendente vai mover o preço. Isso torna o AMM previsível, o que é ótimo para a transparência e também para quem quer explorar a ordem das transações (sandwich attacks).

## O evento Swap

Toda troca em um par V2 emite o evento:

    Swap(address indexed sender, uint amount0In, uint amount1In,
         uint amount0Out, uint amount1Out, address indexed to)

Analisando `amount0In`/`amount1In` é possível saber a **direção** da troca (qual token entrou no pool). Essa informação é a base para detectar sandwiches nos logs da transação.

## Pares e forks

Muitas DEXs são forks do Uniswap V2 e emitem o **mesmo evento Swap**: SushiSwap (Ethereum e Polygon), QuickSwap (Polygon), entre outras. Por isso a mesma heurística funciona em várias DEXs.

## Fontes

- Adams, H., Zinsmeister, N., Robinson, D. (2020). "Uniswap v2 Core" (whitepaper): https://uniswap.org/whitepaper.pdf
- Uniswap Docs — "How Uniswap works" (V2): https://docs.uniswap.org/contracts/v2/concepts/protocol-overview/how-uniswap-works
- Uniswap V2 Pair — eventos do contrato: https://docs.uniswap.org/contracts/v2/reference/smart-contracts/pair
