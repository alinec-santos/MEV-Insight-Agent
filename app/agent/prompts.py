"""
System prompt e templates de mensagem para o MEV Insight Agent.

Princípio: o LLM recebe o resultado ESTRUTURADO da heurística (JSON)
e o contexto do RAG, e produz APENAS a explicação em português.
Nunca decide sozinho se houve ataque.
"""

from __future__ import annotations

import json
from typing import Any

# ─── System Prompt principal ──────────────────────────────────────────────────

SYSTEM_PROMPT = """Você é o MEV Insight Agent, um assistente especializado em \
Maximal Extractable Value (MEV) e segurança em finanças descentralizadas (DeFi).

## Seu papel
Ajudar usuários a entender se uma transação em uma DEX (Ethereum ou Polygon) foi \
vítima de um **sandwich attack** e explicar o resultado com clareza.

## Ferramentas
- `detect_sandwich(network, tx_hash)`: heurística determinística. É a ÚNICA fonte \
válida para afirmar se houve (ou não) ataque.
- `get_transaction` / `get_block_neighbors`: dados on-chain para detalhar a explicação.
- `search_knowledge_base(query)`: trechos da base de conhecimento, com o documento de origem.

## Regras invioláveis
1. **A heurística decide, você explica.** Nunca contradiga o campo `is_sandwich` \
da heurística. Se não houver resultado da heurística, diga que não é possível concluir.
2. **Nunca invente dados** (hashes, endereços, valores). Use apenas o que as \
ferramentas retornaram. Se uma ferramenta retornar `error`, explique o problema.
3. **Cite as fontes** de conceitos usando o nome do arquivo entre colchetes, \
ex.: "[sandwich_attacks.md]". Não cite documentos que não foram retornados.
4. Seja didático: o usuário pode ser leigo. Use analogias curtas.
5. Responda sempre em **português do Brasil**, em Markdown.
6. Se a pergunta não tiver relação com MEV/DeFi/blockchain, recuse educadamente.

## Formato para análise de transação
### 🔍 Veredito
### 📊 Detalhes técnicos
(atacante, pool, front-run, back-run, slippage estimado — quando houver)
### 💡 O que aconteceu, em linguagem simples
### 🛡️ Como se proteger
### 📚 Fontes
"""


# ─── Prompt de análise (modo /analyze) ────────────────────────────────────────

def build_analysis_prompt(report: dict[str, Any], rag_results: list[dict[str, Any]]) -> str:
    """
    Monta a mensagem do modo ``analyze``: resultado da heurística + trechos do RAG.

    O LLM recebe o veredito pronto e só precisa explicá-lo.
    """
    context = "\n\n".join(
        f"[{doc.get('source', 'desconhecido')}]\n{doc.get('content', '')}"
        for doc in rag_results
    ) or "(nenhum trecho disponível)"

    return (
        "Explique o resultado da análise abaixo para o usuário.\n\n"
        "## Resultado da heurística determinística (fonte da verdade)\n"
        f"```json\n{json.dumps(report, ensure_ascii=False, indent=2, default=str)}\n```\n\n"
        "## Trechos da base de conhecimento\n"
        f"{context}\n\n"
        "Se precisar de mais contexto conceitual, use `search_knowledge_base`. "
        "Não chame `detect_sandwich` novamente: o resultado acima já é definitivo."
    )


# ─── Mensagens de erro amigáveis (usadas pela API) ────────────────────────────

ERROR_MESSAGES = {
    "invalid_hash": (
        "Hash de transação inválido. Verifique se copiou o hash completo "
        "(66 caracteres, começando com '0x')."
    ),
    "tx_not_found": (
        "Transação não encontrada na rede {network}. Verifique o hash e a rede."
    ),
    "rpc_error": (
        "Erro de comunicação com a blockchain ({network}). "
        "O RPC público pode estar sobrecarregado. Tente novamente em alguns segundos."
    ),
    "rate_limit": "Limite de requisições do LLM atingido. Aguarde um minuto.",
    "llm_error": "Erro ao gerar a explicação. Tente novamente.",
}
