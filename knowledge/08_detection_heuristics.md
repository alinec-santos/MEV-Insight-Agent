# Heurísticas para detectar sandwiches on-chain

## Ideia geral

Não existe um "selo" on-chain dizendo que uma transação foi um sandwich. A detecção é feita **a posteriori**, procurando um padrão nos logs dos eventos Swap de um bloco. As heurísticas usadas na literatura acadêmica e em ferramentas de análise (como os estudos de Qin et al. e Zhou et al.) seguem regras parecidas.

## Regras clássicas

Dada uma transação vítima V em um bloco, procura-se um par de transações (A1, A2) tal que:

1. **Mesmo bloco:** A1, V e A2 estão no mesmo bloco.
2. **Ordem:** índice(A1) < índice(V) < índice(A2).
3. **Mesmo pool:** os três swaps ocorrem no mesmo contrato de pool.
4. **Mesmo ator:** A1 e A2 vêm do mesmo endereço remetente, ou chamam o mesmo contrato de bot. V vem de outro endereço.
5. **Direções:** A1 troca na **mesma direção** que V; A2 troca na **direção oposta**.
6. **(Opcional) Quantidades compatíveis:** o que o atacante comprou em A1 ≈ o que vendeu em A2.
7. **(Opcional) Lucro:** o atacante termina com mais do token inicial do que tinha.

## Níveis de confiança

- **Alta:** regras 1–5 satisfeitas e quantidades compatíveis (regra 6).
- **Média:** regras 1–5 satisfeitas, mas as quantidades não batem bem, como em ataques com múltiplas vítimas.
- **Nenhuma:** sem par compatível.

## Falsos positivos e falsos negativos

- **Falsos positivos:** arbitradores ou market makers legítimos que, por coincidência, operam no mesmo pool antes e depois.
- **Falsos negativos:**
  - atacante usa **endereços diferentes** para front-run e back-run;
  - swaps passam por **múltiplos pools** (rotas multi-hop) ou DEXs não-Uniswap com eventos diferentes;
  - **múltiplas vítimas** entre o mesmo front-run e back-run;
  - o ataque ocorre em blocos diferentes (raro, exige controle de blocos consecutivos).

## Estimativa de prejuízo

A estimativa simples compara a taxa de câmbio do front-run com a da vítima. Uma estimativa exata exigiria **simular** o bloco sem o front-run, por exemplo com um fork local do nó, o que fica fora do escopo de uma análise leve.

## Fontes

- Qin, K., Zhou, L., Gervais, A. (2022). "Quantifying Blockchain Extractable Value: How dark is the forest?". IEEE S&P. arXiv:2101.05511 — https://arxiv.org/abs/2101.05511
- Zhou, L. et al. (2021). "High-Frequency Trading on Decentralized On-Chain Exchanges". IEEE S&P. arXiv:2009.14021 — https://arxiv.org/abs/2009.14021
- Torres, C. F., Camino, R., State, R. (2021). "Frontrunner Jones and the Raiders of the Dark Forest: An Empirical Study of Frontrunning on the Ethereum Blockchain". USENIX Security. arXiv:2102.03347 — https://arxiv.org/abs/2102.03347
