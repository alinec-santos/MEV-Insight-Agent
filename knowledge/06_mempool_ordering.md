# Mempool, ordenação de transações e PBS

## O mempool público

Quando você assina e envia uma transação, ela não entra imediatamente em um bloco. Primeiro ela é propagada pela rede peer-to-peer e fica no **mempool** (a área de transações pendentes) de cada nó. Qualquer pessoa com um nó, ou acesso a um provedor RPC, consegue ver essas transações, com destino, calldata e valores.

## Como a ordem é decidida

Dentro de um bloco, a ordem das transações é escolhida por quem o produz. Desde o EIP-1559, cada transação paga uma **base fee** (queimada) mais uma **priority fee** (gorjeta ao produtor do bloco). Historicamente, os bots competiam pela posição pagando gorjetas maiores, nos chamados *priority gas auctions*.

## Proposer-Builder Separation (PBS) e MEV-Boost

Hoje, no Ethereum, a maioria dos blocos é produzida via **MEV-Boost**:

1. **Searchers** enviam *bundles* (sequências ordenadas e atômicas de transações) a **builders**.
2. **Builders** montam o bloco mais lucrativo possível e o oferecem aos validadores por meio de **relays**.
3. O **validador** (proposer) escolhe o bloco que paga mais.

Um sandwich normalmente é enviado como um bundle `[front-run, vítima, back-run]`. Isso garante a ordem exata e que o atacante não perca dinheiro se a vítima não for incluída.

## Polygon PoS

A Polygon PoS é uma rede compatível com a EVM, com blocos de cerca de 2 segundos e taxas baixas. Ela também tem mempool público e produtores de bloco que ordenam transações, então os mesmos tipos de MEV, incluindo sandwiches, ocorrem lá. As taxas baixas tornam viáveis ataques até em swaps de valor menor.

## Por que isso importa para a detecção

- O sandwich fica **no mesmo bloco** que a vítima, geralmente em índices adjacentes.
- Olhar uma janela pequena de transações ao redor da vítima (ex.: 3 antes e 3 depois) costuma ser suficiente.
- Bundles privados não deixam rastro no mempool, mas o resultado **fica registrado on-chain** nos logs do bloco. Por isso a análise é feita a partir dos recibos.

## Fontes

- Ethereum.org — "Transactions": https://ethereum.org/en/developers/docs/transactions/
- Ethereum.org — "Gas and fees" (EIP-1559): https://ethereum.org/en/developers/docs/gas/
- Ethereum.org — "Proposer-builder separation": https://ethereum.org/en/roadmap/pbs/
- Flashbots Docs — "MEV-Boost": https://docs.flashbots.net/flashbots-mev-boost/introduction
- Polygon Docs — "Polygon PoS": https://docs.polygon.technology/pos/
