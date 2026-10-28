# Sandwich Attack (Ataque Sanduíche)

## O que é

Um **sandwich attack** é um tipo de MEV em que um atacante "ensanduicha" a transação de swap de uma vítima entre duas transações próprias, no mesmo bloco:

1. **Front-run (compra antecipada):** o atacante vê no mempool que a vítima vai comprar o token X. Ele compra X primeiro, no mesmo pool, empurrando o preço para cima.
2. **Transação da vítima:** a vítima executa a compra a um preço pior do que o esperado, empurrando o preço ainda mais para cima.
3. **Back-run (venda posterior):** logo depois, o atacante vende o X que comprou, agora a um preço mais alto, e embolsa a diferença.

## Analogia

Imagine que você avisa em voz alta numa feira que vai comprar todas as laranjas de uma barraca. Alguém ouve, corre na sua frente, compra as laranjas pelo preço normal e as revende para você mais caro. Você ainda consegue as laranjas, mas paga a mais, e esse "a mais" é o lucro do atacante.

## Por que funciona

- Transações pendentes são **públicas** no mempool.
- Em AMMs (como Uniswap), o preço muda de forma **determinística** conforme o tamanho da negociação, então o atacante consegue calcular exatamente o lucro.
- A vítima define uma **tolerância de slippage** (ex.: 1%). O atacante empurra o preço até quase esse limite, extraindo o máximo sem fazer a transação da vítima falhar.

## Características on-chain

- As três transações estão no **mesmo bloco**, normalmente em posições consecutivas ou muito próximas.
- Front-run e back-run vêm do **mesmo endereço** (ou do mesmo contrato de bot).
- As três operam no **mesmo pool**.
- Front-run tem a **mesma direção** da vítima; back-run tem a **direção oposta**.
- O atacante termina com mais do token inicial do que começou (descontado o gás).

## Escala do problema

Zhou et al. (2021) estudaram ataques sanduíche em exchanges descentralizadas e mostraram que eles são lucrativos mesmo para atacantes sem privilégios especiais. Estudos posteriores (Qin et al., 2022) quantificaram milhões de dólares extraídos de usuários por esse tipo de ataque no Ethereum.

## Fontes

- Ethereum.org — "MEV: Sandwich trading": https://ethereum.org/en/developers/docs/mev/#mev-examples-sandwich-trading
- Zhou, L., Qin, K., Torres, C. F., Le, D. V., Gervais, A. (2021). "High-Frequency Trading on Decentralized On-Chain Exchanges". IEEE S&P. arXiv:2009.14021 — https://arxiv.org/abs/2009.14021
- Qin, K., Zhou, L., Gervais, A. (2022). "Quantifying Blockchain Extractable Value: How dark is the forest?". IEEE S&P. arXiv:2101.05511 — https://arxiv.org/abs/2101.05511
