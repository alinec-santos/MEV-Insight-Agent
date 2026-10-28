# Uniswap V3 e liquidez concentrada

## Liquidez concentrada

No Uniswap V3, os provedores de liquidez escolhem uma **faixa de preço** onde seu capital fica ativo, em vez de espalhá-lo de zero a infinito como no V2. Dentro de cada faixa o pool se comporta como um AMM de produto constante "virtual", mas com muito mais liquidez efetiva perto do preço atual.

## Consequências práticas

- **Menor impacto de preço** para swaps pequenos em pools com liquidez bem concentrada.
- **Saltos de liquidez:** quando o preço sai de uma faixa (*tick*), a liquidez disponível pode cair abruptamente, aumentando o impacto de preço.
- **Múltiplas taxas por par:** o mesmo par de tokens pode ter pools separados com taxas diferentes (por exemplo 0,05%, 0,30% e 1%). Cada um é um contrato diferente, o que importa para a detecção: um sandwich precisa acontecer **no mesmo pool**.

## O evento Swap no V3

    Swap(address indexed sender, address indexed recipient,
         int256 amount0, int256 amount1,
         uint160 sqrtPriceX96, uint128 liquidity, int24 tick)

Diferente do V2, `amount0` e `amount1` são **inteiros com sinal**, vistos pela ótica do pool:

- valor **positivo** = token entrou no pool (o usuário pagou);
- valor **negativo** = token saiu do pool (o usuário recebeu).

O campo `sqrtPriceX96` informa a raiz quadrada do preço **depois** do swap, em formato de ponto fixo Q64.96.

## Sandwiches no V3

O mecanismo do ataque é o mesmo do V2: o atacante compra antes, a vítima compra a preço pior e o atacante vende depois. Liquidez concentrada pode tornar o ataque **mais barato** em pools rasos fora da faixa principal, e **menos lucrativo** em pools profundos com muita liquidez perto do preço atual.

## Disponibilidade

O Uniswap V3 está implantado no Ethereum e no Polygon, entre outras redes. Forks e protocolos compatíveis costumam emitir o mesmo evento.

## Fontes

- Adams, H. et al. (2021). "Uniswap v3 Core" (whitepaper): https://uniswap.org/whitepaper-v3.pdf
- Uniswap Docs — "Concentrated Liquidity": https://docs.uniswap.org/concepts/protocol/concentrated-liquidity
- Uniswap V3 Pool — eventos: https://docs.uniswap.org/contracts/v3/reference/core/interfaces/pool/IUniswapV3PoolEvents
