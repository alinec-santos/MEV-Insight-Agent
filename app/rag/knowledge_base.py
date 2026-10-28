"""
Base de conhecimento (RAG): documentos Markdown → chunks → embeddings Gemini → ChromaDB.

Fluxo:
    knowledge/*.md ──load_chunks()──► Chunk[] ──Embedder──► vetores ──► ChromaDB
    pergunta ──Embedder.embed_query()──► vetor ──► top-k chunks (com `source` p/ citação)

Decisões:
- Chunking por seção (``##``): os documentos são curtos e bem estruturados, então
  cada seção é uma unidade semântica natural. O título do documento e da seção
  são prefixados ao texto antes do embedding para dar contexto ao vetor.
- A seção "Fontes" NÃO vira chunk (é só lista de URLs); ela é guardada como
  metadado ``references`` de todos os chunks do documento.
- Embeddings calculados por nós (não pela embedding_function do Chroma), o que
  facilita trocar o provedor e injetar um embedder falso nos testes.
- Indexação idempotente: cada chunk guarda o hash do conteúdo; só reindexa o
  que mudou e remove chunks de documentos apagados.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
DEFAULT_COLLECTION = "mev_knowledge"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768        # gemini-embedding-001 aceita dimensões reduzidas (MRL)
EMBED_BATCH_SIZE = 100     # limite de itens por requisição de embedding
REFERENCES_HEADINGS = {"fontes", "referências", "referencias", "sources"}


# ─── Chunking ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Chunk:
    """Trecho indexável de um documento."""

    id: str
    source: str            # nome do arquivo (usado na citação)
    title: str             # título do documento (H1)
    section: str           # título da seção (H2)
    content: str           # texto da seção
    references: str = ""   # URLs da seção "Fontes"

    @property
    def text_for_embedding(self) -> str:
        return f"{self.title} — {self.section}\n\n{self.content}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text_for_embedding.encode()).hexdigest()[:16]


def parse_markdown(source: str, text: str) -> list[Chunk]:
    """
    Divide um documento Markdown em chunks por seção ``##``.

    O texto antes da primeira seção (após o H1) vira a seção "Introdução".
    """
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else Path(source).stem
    body = text[title_match.end():] if title_match else text

    # re.split com grupo de captura devolve [pré, título1, corpo1, título2, corpo2, ...]
    parts = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    sections: list[tuple[str, str]] = []
    if parts[0].strip():
        sections.append(("Introdução", parts[0].strip()))
    sections += [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts), 2)]

    references = "\n".join(
        content for heading, content in sections if heading.lower() in REFERENCES_HEADINGS
    )
    return [
        Chunk(id=f"{source}::{i}", source=source, title=title, section=heading,
              content=content, references=references)
        for i, (heading, content) in enumerate(
            (h, c) for h, c in sections if h.lower() not in REFERENCES_HEADINGS and c
        )
    ]


def load_chunks(knowledge_dir: Path | str = DEFAULT_KNOWLEDGE_DIR) -> list[Chunk]:
    """Lê todos os ``*.md`` do diretório (ordem alfabética) e gera os chunks."""
    directory = Path(knowledge_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"Diretório de conhecimento não encontrado: {directory}")
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(parse_markdown(path.name, path.read_text(encoding="utf-8")))
    return chunks


# ─── Embeddings ───────────────────────────────────────────────────────────────

class Embedder(Protocol):
    """Interface mínima de um provedor de embeddings."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbedder:
    """
    Embeddings via API do Gemini.

    Usa ``task_type`` distinto para documentos e consultas: o modelo otimiza os
    vetores para recuperação assimétrica (pergunta curta × trecho longo).
    """

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        from google import genai  # import tardio: só necessário em produção

        if client is None:
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if not api_key or api_key.startswith("your_"):
                raise RuntimeError("GEMINI_API_KEY não definida — necessária para embeddings.")
            client = genai.Client(api_key=api_key)
        self._client = client
        self.model = model or os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i:i + EMBED_BATCH_SIZE]
            result = self._client.models.embed_content(
                model=self.model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type, output_dimensionality=EMBEDDING_DIM,
                ),
            )
            vectors.extend(list(e.values) for e in result.embeddings)
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


# ─── Base vetorial ────────────────────────────────────────────────────────────

@dataclass
class IndexStats:
    total_chunks: int = 0
    added: int = 0
    unchanged: int = 0
    removed: int = 0
    sources: list[str] = field(default_factory=list)


class KnowledgeBase:
    """Wrapper do ChromaDB com indexação idempotente e busca com citação."""

    def __init__(
        self,
        embedder: Embedder,
        persist_dir: str | Path | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        settings = Settings(anonymized_telemetry=False)
        self._client = (
            chromadb.PersistentClient(path=str(persist_dir), settings=settings)
            if persist_dir else chromadb.EphemeralClient(settings=settings)
        )
        # embedding_function=None: nós fornecemos os vetores (evita o download
        # do modelo ONNX padrão do Chroma).
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )
        self._embedder = embedder

    @property
    def count(self) -> int:
        return self._collection.count()

    def index(self, knowledge_dir: Path | str = DEFAULT_KNOWLEDGE_DIR,
              force: bool = False) -> IndexStats:
        """
        Sincroniza a coleção com os arquivos de ``knowledge_dir``.

        Só gera embeddings para chunks novos ou alterados (economiza cota da API).
        """
        chunks = load_chunks(knowledge_dir)
        existing = self._collection.get(include=["metadatas"])
        existing_hash = {
            cid: (meta or {}).get("hash") for cid, meta in zip(existing["ids"], existing["metadatas"])
        }

        wanted = {c.id for c in chunks}
        stale = [cid for cid in existing_hash if cid not in wanted]
        to_upsert = [c for c in chunks if force or existing_hash.get(c.id) != c.content_hash]

        if stale:
            self._collection.delete(ids=stale)
        if to_upsert:
            vectors = self._embedder.embed_documents([c.text_for_embedding for c in to_upsert])
            self._collection.upsert(
                ids=[c.id for c in to_upsert],
                embeddings=vectors,
                documents=[c.content for c in to_upsert],
                metadatas=[{"source": c.source, "title": c.title, "section": c.section,
                            "references": c.references, "hash": c.content_hash}
                           for c in to_upsert],
            )

        stats = IndexStats(
            total_chunks=len(chunks), added=len(to_upsert),
            unchanged=len(chunks) - len(to_upsert), removed=len(stale),
            sources=sorted({c.source for c in chunks}),
        )
        logger.info("Indexação RAG: %s", stats)
        return stats

    def search(self, query: str, n_results: int = 3) -> dict[str, Any]:
        """
        Busca semântica. Formato compatível com a ferramenta ``search_knowledge_base``.

        Returns:
            ``{"query", "results": [{"source", "title", "section", "content",
            "score", "references"}]}`` — ``score`` = similaridade de cosseno (0–1).
        """
        if not query.strip():
            return {"query": query, "results": []}
        n = max(1, min(n_results, 10, self.count or 1))
        if self.count == 0:
            return {"query": query, "results": [], "warning": "Base de conhecimento vazia."}

        res = self._collection.query(
            query_embeddings=[self._embedder.embed_query(query)],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        results = [
            {
                "source": meta["source"],
                "title": meta["title"],
                "section": meta["section"],
                "content": doc,
                "score": round(1.0 - dist, 4),  # distância de cosseno → similaridade
                "references": meta.get("references", ""),
            }
            for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
        ]
        return {"query": query, "results": results}


# ─── Fábrica (singleton de processo) ──────────────────────────────────────────

@lru_cache(maxsize=1)
def get_knowledge_base(auto_index: bool = True) -> KnowledgeBase:
    """
    Cria a base com configuração do ambiente e indexa na primeira chamada.

    Usada pela API: ``MEVAgent(search_fn=get_knowledge_base().search)``.
    """
    kb = KnowledgeBase(
        embedder=GeminiEmbedder(),
        persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"),
    )
    if auto_index:
        kb.index(os.getenv("KNOWLEDGE_DIR", DEFAULT_KNOWLEDGE_DIR))
    return kb
