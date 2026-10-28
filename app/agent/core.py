"""
Agent Core — loop de tool calling com Google Gemini (SDK ``google-genai``).

Dois modos de operação:

* ``analyze(network, tx_hash)`` — **determinístico primeiro**: o pipeline Python
  roda a heurística ANTES de chamar o LLM. O veredito (``is_sandwich``) vem
  sempre da heurística; o Gemini recebe o resultado e só escreve a explicação
  (podendo consultar a base de conhecimento via tool calling).

* ``chat(question)`` — **agêntico**: o Gemini decide quais ferramentas chamar
  para responder a uma pergunta livre (ex.: "a tx 0x... foi sanduichada?").

Loop de tool calling:
    usuário → Gemini → [function_call] → executamos em Python → [function_response]
            → Gemini → ... → texto final
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.agent.prompts import SYSTEM_PROMPT, build_analysis_prompt
from app.tools.pipeline import investigate_transaction, summarize_transaction
from app.tools.web3_tools import get_block_neighbors, get_transaction

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TOOL_ROUNDS = 8  # proteção contra loops infinitos de tool calling

# Assinatura da busca RAG: (query, n_results) -> {"results": [{"source", "content", ...}]}
SearchFn = Callable[[str, int], dict[str, Any]]


# ─── Exceções do agente (mapeadas para HTTP na camada de API) ────────────────

class AgentError(Exception):
    """Erro genérico do agente/LLM."""


class LLMRateLimitError(AgentError):
    """A API do Gemini retornou 429 (limite de requisições/cota)."""


class LLMConfigError(AgentError):
    """Configuração ausente ou inválida (ex.: GEMINI_API_KEY)."""


# ─── Declaração das ferramentas (JSON Schema enviado ao Gemini) ──────────────

_NETWORK = {"type": "string", "enum": ["ethereum", "polygon"],
            "description": "Rede blockchain."}
_TX_HASH = {"type": "string",
            "description": "Hash da transação: 0x + 64 caracteres hexadecimais."}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_transaction",
        "description": "Busca uma transação e seu recibo. Retorna remetente, "
                       "bloco, posição, status e os swaps de DEX já decodificados.",
        "parameters": {"type": "object",
                       "properties": {"network": _NETWORK, "tx_hash": _TX_HASH},
                       "required": ["network", "tx_hash"]},
    },
    {
        "name": "get_block_neighbors",
        "description": "Lista as transações imediatamente antes e depois de uma "
                       "posição no mesmo bloco (sem logs).",
        "parameters": {"type": "object",
                       "properties": {
                           "network": _NETWORK,
                           "block_number": {"type": "integer"},
                           "tx_index": {"type": "integer",
                                        "description": "Posição da tx no bloco."},
                           "window": {"type": "integer",
                                      "description": "Txs de cada lado (1-10, padrão 3)."},
                       },
                       "required": ["network", "block_number", "tx_index"]},
    },
    {
        "name": "detect_sandwich",
        "description": "Executa a heurística DETERMINÍSTICA de detecção de sandwich "
                       "attack para a transação (busca vizinhos e recibos sozinha). "
                       "É a ÚNICA fonte válida para afirmar se houve ataque.",
        "parameters": {"type": "object",
                       "properties": {"network": _NETWORK, "tx_hash": _TX_HASH},
                       "required": ["network", "tx_hash"]},
    },
    {
        "name": "search_knowledge_base",
        "description": "Busca semântica na base de conhecimento sobre MEV, sandwich "
                       "attacks e DEXs. Retorna trechos com o documento de origem "
                       "para citação.",
        "parameters": {"type": "object",
                       "properties": {
                           "query": {"type": "string"},
                           "n_results": {"type": "integer",
                                         "description": "Padrão 3."},
                       },
                       "required": ["query"]},
    },
]


# ─── Executor de ferramentas (Python puro, testável sem LLM) ─────────────────

class ToolExecutor:
    """
    Executa as ferramentas pedidas pelo LLM e registra efeitos colaterais
    úteis (resultado da heurística, fontes do RAG) para a resposta estruturada.
    """

    def __init__(self, search_fn: SearchFn | None = None) -> None:
        self._search_fn = search_fn
        self.heuristic_result: dict[str, Any] | None = None
        self.rag_sources: list[str] = []
        self.calls: list[str] = []

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Executa a ferramenta; erros viram ``{"error": ...}`` para o LLM ler."""
        self.calls.append(name)
        logger.info("Tool call: %s(%s)", name, args)
        try:
            if name == "get_transaction":
                return summarize_transaction(get_transaction(args["network"], args["tx_hash"]))

            if name == "get_block_neighbors":
                window = max(1, min(int(args.get("window", 3)), 10))
                return get_block_neighbors(args["network"], int(args["block_number"]),
                                           int(args["tx_index"]), window)

            if name == "detect_sandwich":
                report = investigate_transaction(args["network"], args["tx_hash"])
                self.heuristic_result = report
                return report

            if name == "search_knowledge_base":
                return self.search(args["query"], int(args.get("n_results", 3)))

            return {"error": f"Ferramenta desconhecida: {name}"}

        except KeyError as exc:
            return {"error": f"Argumento obrigatório ausente: {exc}"}
        except (ValueError, LookupError, ConnectionError) as exc:
            return {"error": str(exc), "error_type": type(exc).__name__}
        except Exception as exc:  # noqa: BLE001 — o LLM precisa receber algo
            logger.exception("Erro inesperado na tool %s", name)
            return {"error": f"Erro interno: {exc}"}

    def search(self, query: str, n_results: int = 3) -> dict[str, Any]:
        """Busca no RAG e acumula as fontes citáveis."""
        if self._search_fn is None:
            return {"results": [], "warning": "Base de conhecimento indisponível."}
        out = self._search_fn(query, n_results)
        for doc in out.get("results", []):
            src = doc.get("source")
            if src and src not in self.rag_sources:
                self.rag_sources.append(src)
        return out


# ─── Agente ──────────────────────────────────────────────────────────────────

class MEVAgent:
    """
    Agente de análise de MEV.

    Exemplo::

        agent = MEVAgent(search_fn=knowledge_base.search)
        out = agent.analyze("ethereum", "0x...")
        print(out["is_sandwich"], out["explanation"])
    """

    def __init__(
        self,
        search_fn: SearchFn | None = None,
        client: Any | None = None,
        model: str | None = None,
    ) -> None:
        """
        Args:
            search_fn: Busca RAG (opcional — sem ela o agente avisa e segue).
            client:    Cliente ``genai.Client`` (injetável para testes).
            model:     Nome do modelo; padrão via env ``GEMINI_MODEL``.
        """
        self._search_fn = search_fn
        self._model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        if client is None:
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if not api_key or api_key.startswith("your_"):
                raise LLMConfigError("GEMINI_API_KEY não definida no .env.")
            client = genai.Client(api_key=api_key)
        self._client = client

        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,  # explicações consistentes, pouca "criatividade"
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters_json_schema=t["parameters"],
                )
                for t in TOOL_SCHEMAS
            ])],
            # Nós controlamos o loop manualmente (logs, limites, captura de dados)
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    # ── API pública ──────────────────────────────────────────────────────────

    def analyze(self, network: str, tx_hash: str) -> dict[str, Any]:
        """
        Analisa uma transação. A heurística roda ANTES do LLM; se a busca
        on-chain falhar, a exceção é propagada (a API converte em HTTP 4xx/5xx).
        """
        executor = ToolExecutor(self._search_fn)
        report = investigate_transaction(network, tx_hash)
        executor.heuristic_result = report

        # Pré-carrega contexto do RAG para garantir citações mesmo se o LLM
        # não chamar a ferramenta.
        query = ("sandwich attack front-running slippage"
                 if report["sandwich"]["is_sandwich"]
                 else "como funciona swap em DEX e MEV")
        rag = executor.search(query, 3)

        prompt = build_analysis_prompt(report, rag.get("results", []))
        explanation = self._run_loop(prompt, executor)
        return self._build_output(executor, explanation)

    def chat(self, question: str) -> dict[str, Any]:
        """Responde uma pergunta livre usando tool calling."""
        executor = ToolExecutor(self._search_fn)
        explanation = self._run_loop(question, executor)
        return self._build_output(executor, explanation)

    # ── Internos ─────────────────────────────────────────────────────────────

    def _generate(self, contents: list[types.Content]) -> Any:
        """Chama o Gemini traduzindo erros do SDK para exceções do domínio."""
        try:
            return self._client.models.generate_content(
                model=self._model, contents=contents, config=self._config,
            )
        except genai_errors.APIError as exc:
            if getattr(exc, "code", None) == 429:
                raise LLMRateLimitError("Limite de requisições do Gemini atingido.") from exc
            if getattr(exc, "code", None) in (401, 403):
                raise LLMConfigError(f"Chave do Gemini inválida: {exc}") from exc
            raise AgentError(f"Erro na API do Gemini: {exc}") from exc

    def _run_loop(self, user_message: str, executor: ToolExecutor) -> str:
        """Loop de tool calling até o modelo devolver texto final."""
        contents: list[types.Content] = [
            types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
        ]

        for round_ in range(1, MAX_TOOL_ROUNDS + 1):
            response = self._generate(contents)
            calls = response.function_calls or []
            if not calls:
                return (response.text or "").strip() or "O modelo não retornou texto."

            logger.debug("Rodada %d: %d tool call(s)", round_, len(calls))
            # Mantém o turno do modelo no histórico (necessário para o protocolo)
            contents.append(response.candidates[0].content)
            parts = [
                types.Part.from_function_response(
                    name=call.name,
                    response={"result": _json_safe(executor.execute(call.name, dict(call.args or {})))},
                )
                for call in calls
            ]
            contents.append(types.Content(role="user", parts=parts))

        logger.warning("Limite de %d rodadas de tool calling atingido.", MAX_TOOL_ROUNDS)
        return "Não consegui concluir a análise dentro do limite de etapas. Tente novamente."

    @staticmethod
    def _build_output(executor: ToolExecutor, explanation: str) -> dict[str, Any]:
        """Monta a saída estruturada. Veredito vem SEMPRE da heurística."""
        report = executor.heuristic_result
        sandwich = report["sandwich"] if report else None
        return {
            "is_sandwich": bool(sandwich and sandwich["is_sandwich"]),
            "confidence": sandwich["confidence"] if sandwich else None,
            "heuristic": report,
            "explanation": explanation,
            "rag_sources": executor.rag_sources,
            "tools_called": executor.calls,
        }


def _json_safe(obj: Any) -> Any:
    """Garante serialização JSON (ints gigantes de wei viram string)."""
    return json.loads(json.dumps(obj, default=str),
                      parse_int=lambda s: int(s) if len(s) < 16 else s)
