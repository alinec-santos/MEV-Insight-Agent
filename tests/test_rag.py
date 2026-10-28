"""
Testes do RAG (app/rag/knowledge_base.py).

Usa um embedder FALSO e determinístico (bag-of-words com hashing): não chama
a API do Gemini, mas preserva a noção de "textos com palavras em comum ficam
próximos", suficiente para validar o fluxo de indexação e busca.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.rag.knowledge_base import (
    DEFAULT_KNOWLEDGE_DIR,
    GeminiEmbedder,
    KnowledgeBase,
    load_chunks,
    parse_markdown,
)

DIM = 512


class FakeEmbedder:
    def __init__(self) -> None:
        self.document_calls = 0

    @staticmethod
    def _vec(text: str) -> list[float]:
        norm = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
        v = [0.0] * DIM
        for tok in re.findall(r"[a-z0-9]{3,}", norm):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


SAMPLE_MD = """# Documento Teste

Texto introdutório.

## Seção A
Conteúdo da seção A.

## Seção B
Conteúdo da seção B.

## Fontes
- https://exemplo.org/a
"""


@pytest.fixture
def kb(tmp_path: Path) -> KnowledgeBase:
    base = KnowledgeBase(FakeEmbedder(), persist_dir=tmp_path / "chroma")
    base.index(DEFAULT_KNOWLEDGE_DIR)
    return base


# ─── Chunking ─────────────────────────────────────────────────────────────────

class TestChunking:
    def test_divide_por_secao_e_extrai_titulo(self) -> None:
        chunks = parse_markdown("doc.md", SAMPLE_MD)
        assert [c.section for c in chunks] == ["Introdução", "Seção A", "Seção B"]
        assert all(c.title == "Documento Teste" for c in chunks)
        assert chunks[1].id == "doc.md::1"

    def test_secao_fontes_vira_metadado(self) -> None:
        chunks = parse_markdown("doc.md", SAMPLE_MD)
        assert all("Fontes" not in c.section for c in chunks)
        assert all("https://exemplo.org/a" in c.references for c in chunks)

    def test_texto_para_embedding_tem_contexto(self) -> None:
        c = parse_markdown("doc.md", SAMPLE_MD)[1]
        assert c.text_for_embedding.startswith("Documento Teste — Seção A")

    def test_base_real_tem_entre_5_e_10_documentos_com_fontes(self) -> None:
        chunks = load_chunks(DEFAULT_KNOWLEDGE_DIR)
        sources = {c.source for c in chunks}
        assert 5 <= len(sources) <= 10
        # Todo documento precisa citar a origem (requisito do projeto)
        for src in sources:
            refs = next(c.references for c in chunks if c.source == src)
            assert "http" in refs, f"{src} sem seção de Fontes"

    def test_diretorio_inexistente(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_chunks(tmp_path / "nao_existe")


# ─── Indexação ────────────────────────────────────────────────────────────────

class TestIndex:
    def test_indexa_todos_os_chunks(self, kb: KnowledgeBase) -> None:
        assert kb.count == len(load_chunks(DEFAULT_KNOWLEDGE_DIR))

    def test_reindexacao_e_idempotente(self, tmp_path: Path) -> None:
        emb = FakeEmbedder()
        base = KnowledgeBase(emb, persist_dir=tmp_path / "c")
        first = base.index(DEFAULT_KNOWLEDGE_DIR)
        calls_after_first = emb.document_calls
        second = base.index(DEFAULT_KNOWLEDGE_DIR)

        assert first.added == first.total_chunks
        assert second.added == 0 and second.unchanged == second.total_chunks
        assert emb.document_calls == calls_after_first  # nenhuma chamada extra à API

    def test_detecta_alteracao_e_remocao(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(SAMPLE_MD, encoding="utf-8")
        (docs / "b.md").write_text("# B\n\n## X\nalgo", encoding="utf-8")
        base = KnowledgeBase(FakeEmbedder(), persist_dir=tmp_path / "c")
        base.index(docs)

        (docs / "a.md").write_text(SAMPLE_MD.replace("seção A.", "seção A editada."), encoding="utf-8")
        (docs / "b.md").unlink()
        stats = base.index(docs)

        assert stats.added == 1     # só a seção editada
        assert stats.removed == 1   # chunk de b.md
        assert base.count == 3

    def test_persistencia_entre_instancias(self, tmp_path: Path) -> None:
        KnowledgeBase(FakeEmbedder(), persist_dir=tmp_path / "c").index(DEFAULT_KNOWLEDGE_DIR)
        reopened = KnowledgeBase(FakeEmbedder(), persist_dir=tmp_path / "c")
        assert reopened.count > 0


# ─── Busca ────────────────────────────────────────────────────────────────────

class TestSearch:
    @pytest.mark.parametrize("query, expected_source", [
        ("sandwich attack front-run back-run vítima atacante", "02_sandwich_attacks.md"),
        ("fórmula produto constante reservas x y k", "03_amm_constant_product.md"),
        ("Flashbots Protect MEV Blocker RPC privado proteção", "07_mev_protection.md"),
        ("liquidez concentrada ticks Uniswap V3", "04_uniswap_v3.md"),
    ])
    def test_recupera_documento_relevante(self, kb: KnowledgeBase, query: str,
                                          expected_source: str) -> None:
        sources = [r["source"] for r in kb.search(query, 3)["results"]]
        assert expected_source in sources

    def test_formato_do_resultado(self, kb: KnowledgeBase) -> None:
        res = kb.search("slippage", 2)
        assert res["query"] == "slippage"
        assert len(res["results"]) == 2
        r = res["results"][0]
        assert set(r) == {"source", "title", "section", "content", "score", "references"}
        assert 0.0 <= r["score"] <= 1.0
        assert res["results"][0]["score"] >= res["results"][1]["score"]

    def test_query_vazia(self, kb: KnowledgeBase) -> None:
        assert kb.search("   ")["results"] == []

    def test_base_vazia(self, tmp_path: Path) -> None:
        res = KnowledgeBase(FakeEmbedder(), persist_dir=tmp_path / "vazio").search("mev")
        assert res["results"] == [] and "warning" in res

    def test_integra_com_tool_executor(self, kb: KnowledgeBase) -> None:
        from app.agent.core import ToolExecutor
        ex = ToolExecutor(search_fn=kb.search)
        out = ex.execute("search_knowledge_base", {"query": "sandwich attack", "n_results": 2})
        assert len(out["results"]) == 2
        assert ex.rag_sources  # fontes registradas para citação


# ─── GeminiEmbedder (cliente falso) ───────────────────────────────────────────

class TestGeminiEmbedder:
    def test_usa_task_types_distintos_e_lotes(self) -> None:
        calls: list[tuple[int, str]] = []

        def embed_content(model: str, contents: list[str], config: object) -> SimpleNamespace:
            calls.append((len(contents), config.task_type))
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2]) for _ in contents])

        client = SimpleNamespace(models=SimpleNamespace(embed_content=embed_content))
        emb = GeminiEmbedder(client=client, model="fake")

        vecs = emb.embed_documents(["t"] * 150)
        q = emb.embed_query("pergunta")

        assert len(vecs) == 150 and q == [0.1, 0.2]
        assert calls == [(100, "RETRIEVAL_DOCUMENT"), (50, "RETRIEVAL_DOCUMENT"),
                         (1, "RETRIEVAL_QUERY")]

    def test_sem_chave_levanta_erro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        with pytest.raises(RuntimeError):
            GeminiEmbedder()
