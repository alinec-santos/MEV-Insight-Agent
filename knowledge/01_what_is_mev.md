# O que é MEV (Maximal Extractable Value)

## Definição

MEV, ou *Maximal Extractable Value* (valor máximo extraível), é o lucro que quem monta um bloco consegue obter ao **incluir, excluir ou reordenar** transações dentro desse bloco, além da recompensa normal e das taxas de gás. O termo surgiu como *Miner Extractable Value* na época do Proof of Work; depois do Merge (2022), o Ethereum passou a usar validadores, e o "M" passou a significar "Maximal".

## Por que o MEV existe

Em blockchains públicas, as transações pendentes ficam visíveis no **mempool** antes de serem confirmadas. Qualquer um pode observar uma transação grande de compra em uma DEX e prever que ela vai mover o preço. Como a ordem das transações dentro do bloco é decidida por quem o produz, surge a oportunidade de se posicionar antes ou depois dessa transação.

## Quem extrai MEV

- **Searchers (buscadores):** operadores de bots que monitoram o mempool e o estado da blockchain procurando oportunidades lucrativas. Eles enviam transações ou *bundles* (pacotes ordenados de transações).
- **Builders (construtores):** montam blocos completos combinando bundles dos searchers para maximizar o valor.
- **Validadores/proposers:** escolhem qual bloco propor, geralmente o que paga mais.

## Tipos comuns de MEV

- **Arbitragem entre DEXs:** comprar um token onde está barato e vender onde está caro, na mesma transação. Em geral é considerado um MEV "benigno", pois alinha preços entre mercados.
- **Liquidações:** executar liquidações em protocolos de empréstimo (como Aave ou Compound) e receber a bonificação.
- **Sandwich attacks:** cercar a transação de um usuário com uma compra antes e uma venda depois, lucrando com o impacto de preço causado pela vítima. É um MEV **prejudicial ao usuário**.
- **Front-running genérico:** copiar uma transação lucrativa e executá-la antes da original, pagando mais gás.

## Impacto

O MEV prejudicial aumenta o custo efetivo dos usuários (eles recebem menos tokens do que poderiam), congestiona a rede com guerras de gás e cria incentivos para centralização da produção de blocos. Daian et al. (2019) mostraram que bots disputavam ativamente essas oportunidades em leilões de gás prioritários (*priority gas auctions*).

## Fontes

- Ethereum.org — "Maximal extractable value (MEV)": https://ethereum.org/en/developers/docs/mev/
- Daian, P. et al. (2019). "Flash Boys 2.0: Frontrunning, Transaction Reordering, and Consensus Instability in Decentralized Exchanges". arXiv:1904.05234 — https://arxiv.org/abs/1904.05234
- Flashbots Docs — "MEV and Flashbots": https://docs.flashbots.net/
