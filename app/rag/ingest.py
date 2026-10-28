"""
CLI de indexação da base de conhecimento.

Uso:
    python -m app.rag.ingest            # indexa só o que mudou
    python -m app.rag.ingest --force    # reindexa tudo
    python -m app.rag.ingest --query "o que é sandwich attack"   # testa a busca
"""

from __future__ import annotations

import argparse
import logging

from app.rag.knowledge_base import get_knowledge_base


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexa a base de conhecimento MEV no ChromaDB.")
    parser.add_argument("--force", action="store_true", help="Reindexa todos os chunks.")
    parser.add_argument("--query", help="Executa uma busca de teste após indexar.")
    parser.add_argument("-k", type=int, default=3, help="Número de resultados da busca.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    kb = get_knowledge_base(auto_index=False)
    stats = kb.index(force=args.force)
    print(f"\n✔ {stats.total_chunks} chunks de {len(stats.sources)} documentos "
          f"(novos/alterados: {stats.added}, inalterados: {stats.unchanged}, removidos: {stats.removed})")

    if args.query:
        print(f"\n🔎 {args.query}\n")
        for r in kb.search(args.query, args.k)["results"]:
            print(f"  [{r['source']}] {r['section']}  (score={r['score']})")
            print(f"    {r['content'][:160].replace(chr(10), ' ')}...\n")


if __name__ == "__main__":
    main()
