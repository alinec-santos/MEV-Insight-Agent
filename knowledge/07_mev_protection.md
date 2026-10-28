# Como se proteger de sandwich attacks

## 1. Use RPCs privados / com proteção de MEV

Em vez de enviar a transação ao mempool público, envie diretamente a builders que se comprometem a não fazer front-running:

- **Flashbots Protect:** RPC que envia transações de forma privada a builders. Transações que reverteriam não são incluídas, então você não paga gás por falhas. Também oferece reembolso de parte do MEV de backrun.
- **MEV Blocker:** RPC mantido por CoW Protocol e parceiros. Permite apenas backruns (que não prejudicam o usuário) e devolve ao usuário a maior parte do valor gerado.

Na prática, basta trocar a URL RPC na carteira (ex.: MetaMask) pela URL do serviço.

## 2. Ajuste a tolerância de slippage

A tolerância define o lucro máximo de um sandwich. Use valores baixos (0,1%–0,5% em pares líquidos). Tolerâncias de 5% ou mais em tokens populares são uma das causas mais comuns de ataques bem-sucedidos.

## 3. Use DEXs e agregadores com proteção nativa

- **CoW Swap (CoW Protocol):** usa leilões em lote (*batch auctions*) com preço uniforme e *solvers* que competem para executar as ordens. Como as ordens são assinadas off-chain e liquidadas em lote, não há como inserir um front-run entre elas.
- **UniswapX** e outros sistemas baseados em *intents* transferem a execução para *fillers* que competem entre si, reduzindo a exposição ao mempool.

## 4. Divida ordens grandes

Swaps grandes em relação à liquidez do pool têm grande impacto de preço e são alvos mais lucrativos. Dividir a ordem ou usar ordens TWAP reduz o incentivo.

## 5. Escolha pools profundos

Quanto mais liquidez, menor o impacto de preço e menor o lucro possível do atacante.

## O que NÃO funciona

- **Pagar gás mais alto** não protege: o atacante coloca o front-run antes e o back-run depois de qualquer forma.
- **Mudar de carteira** não muda nada se ela continuar enviando ao mempool público.

## Fontes

- Flashbots Docs — "Flashbots Protect": https://docs.flashbots.net/flashbots-protect/overview
- MEV Blocker: https://mevblocker.io/
- CoW Protocol Docs — "MEV protection" / batch auctions: https://docs.cow.fi/
- Uniswap Docs — "UniswapX overview": https://docs.uniswap.org/contracts/uniswapx/overview
- Ethereum.org — "MEV: mitigations": https://ethereum.org/en/developers/docs/mev/
