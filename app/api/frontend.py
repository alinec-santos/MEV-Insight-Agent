"""
Interface interativa em Streamlit para o MEV Insight Agent.
"""

from __future__ import annotations

import os
import httpx
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(
    page_title="MEV Insight Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilização CSS personalizada
st.markdown(
    """
    <style>
    .metric-card {
        background-color: #1E222A;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
        border: 1px solid #2E3440;
    }
    .badge-attack {
        color: #ff4b4b;
        font-weight: bold;
    }
    .badge-safe {
        color: #00c04b;
        font-weight: bold;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🛡️ MEV Insight")
    st.caption("Investigador de Sandwich Attacks em DEXs")
    st.markdown("---")

    # Monitor de Saúde da API
    st.subheader("Status do Sistema")
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{API_BASE_URL}/health")
            if resp.status_code == 200:
                health = resp.json()
                status_icon = "🟢" if health["status"] == "ok" else "🟡"
                st.write(f"**API Backend:** {status_icon} `{health['status'].upper()}`")
                
                with st.expander("Serviços Conectados"):
                    for srv, up in health["services"].items():
                        icon = "✅" if up else "❌"
                        st.write(f"{icon} {srv.replace('_', ' ').title()}")
            else:
                st.warning("API respondendo com erro.")
    except Exception:
        st.error(f"❌ Não foi possível conectar à API ({API_BASE_URL}).")

    st.markdown("---")
    st.markdown(
        """
        ### Exemplos de Transações
        **Ethereum (Exemplo de Sandwich):**
        - `0x3b890832ea5102ff4ce63b78c948e8cf1f5eac7ba8ca6c8914c6fb73d17d47e8`

        **Polygon (Swap legítimo):**
        - `0x981504d41fa7b3967406085a6a0907ad5a2da19f96b27005cbe0da867d34cdfc`
        """
    )
    st.caption("Desenvolvido para análise transparente de MEV.")

# ─── Navegação por Tabs ────────────────────────────────────────────────────────
tab_investigate, tab_chat, tab_about = st.tabs(["🔍 Investigar Transação", "💬 Chat com Agente", "📚 Sobre MEV"])

# ──────────────────────────────────────────────────────────────────────────────
# TAB 1: Investigação de Transação
# ──────────────────────────────────────────────────────────────────────────────
with tab_investigate:
    st.subheader("Análise Forense On-Chain")
    st.markdown("Insira o hash da transação para verificar se houve front-run e back-run malicioso no mesmo bloco.")

    col1, col2 = st.columns([1, 3])
    with col1:
        network = st.selectbox("Rede Blockchain", ["ethereum", "polygon"], index=0)
    with col2:
        tx_hash_input = st.text_input(
            "Hash da Transação",
            placeholder="0x...",
            help="Cole o hash de 66 caracteres da transação na DEX.",
        )

    btn_analyze = st.button("🚀 Analisar Transação", type="primary", use_container_width=True)

    if btn_analyze:
        if not tx_hash_input.strip():
            st.error("Por favor, informe o hash da transação.")
        else:
            with st.spinner("Buscando dados on-chain, calculando heurística e gerando explicação..."):
                try:
                    payload = {"network": network, "tx_hash": tx_hash_input.strip()}
                    with httpx.Client(timeout=45.0) as client:
                        response = client.post(f"{API_BASE_URL}/analyze", json=payload)

                    if response.status_code == 200:
                        data = response.json()
                        st.success("Análise concluída!")

                        # Cartões de Destaque
                        st.markdown("---")
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if data["is_sandwich"]:
                                st.metric("Veredito", "Sandwich Detectado ⚠️", delta="- Alerta", delta_color="inverse")
                            else:
                                st.metric("Veredito", "Transação Segura ✅", delta="Normal", delta_color="normal")
                        with c2:
                            conf = data.get("confidence") or "N/A"
                            st.metric("Confiança da Heurística", conf)
                        with c3:
                            sources_count = len(data.get("rag_sources", []))
                            st.metric("Fontes RAG Citadas", f"{sources_count} docs")

                        # Explicação em Markdown gerada pelo LLM
                        st.markdown("### 📝 Explicação do Agente")
                        st.markdown(data["explanation"])

                        # Detalhes Técnicos Expandíveis
                        if data.get("heuristic_data"):
                            with st.expander("🛠️ Ver Dados Técnicos Estruturados (JSON)"):
                                st.json(data["heuristic_data"])

                        # Fontes Consultadas
                        if data.get("rag_sources"):
                            st.caption(f"**Documentos de referência consultados:** {', '.join(data['rag_sources'])}")

                    else:
                        err_detail = response.json().get("detail", response.text)
                        st.error(f"Erro na requisição ({response.status_code}): {err_detail}")

                except httpx.ConnectError:
                    st.error(f"Erro de conexão: Não foi possível alcançar o servidor da API em {API_BASE_URL}.")
                except Exception as ex:
                    st.error(f"Erro ao executar análise: {ex}")

# ──────────────────────────────────────────────────────────────────────────────
# TAB 2: Chat com o Agente
# ──────────────────────────────────────────────────────────────────────────────
with tab_chat:
    st.subheader("Converse com o Especialista em MEV")
    st.markdown("Tire dúvidas conceituais, pergunte sobre estratégias de proteção ou peça análise de hashes.")

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Olá! Sou seu assistente de MEV. Pode me fazer perguntas conceituais ou pedir para analisar um hash de transação na Ethereum ou Polygon.",
            }
        ]

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ex: O que é slippage e como um sandwich attack se aproveita dele?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Pensando e pesquisando base de conhecimento..."):
                try:
                    with httpx.Client(timeout=45.0) as client:
                        resp = client.post(f"{API_BASE_URL}/chat", json={"message": prompt})

                    if resp.status_code == 200:
                        ans = resp.json()
                        reply = ans["response"]
                        st.markdown(reply)
                        if ans.get("rag_sources"):
                            st.caption(f"📚 Fontes: {', '.join(ans['rag_sources'])}")
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                    else:
                        err = f"Erro ({resp.status_code}): {resp.text}"
                        st.error(err)
                except Exception as ex:
                    st.error(f"Erro ao contatar API: {ex}")

# ──────────────────────────────────────────────────────────────────────────────
# TAB 3: Sobre MEV
# ──────────────────────────────────────────────────────────────────────────────
with tab_about:
    st.markdown(
        """
        ### O que é Maximal Extractable Value (MEV)?
        MEV é o valor máximo que pode ser extraído da produção de blocos além das recompensas padrão, 
        através da inclusão, exclusão e reordenação de transações.

        #### Como funciona o Sandwich Attack?
        1. **Front-run:** O atacante observa uma transação pendente no mempool e envia uma ordem de compra com taxa de gás superior.
        2. **Vítima:** A transação do usuário é executada a um preço piorado pela compra anterior.
        3. **Back-run:** O atacante vende os tokens imediatamente após, embolsando o lucro e recompondo o pool.

        #### Dicas de Proteção:
        - Utilize RPCs com proteção de MEV (ex: **Flashbots Protect**, **MEV Blocker**).
        - Configure a tolerância de slippage para valores baixos (0.1% a 0.5% em pares líquidos).
        - Utilize agregadores que realizam leilões em lote (como **CoW Swap**).
        """
    )
