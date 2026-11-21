"""Interface Streamlit do Agente SQL Delivery com Dashboard, Telemetria e Histórico."""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from agente_sql import analisar, carregar_dados_dashboard, DB_PATH
import criar_banco

@st.cache_resource
def inicializar_banco() -> bool:
    criar_banco.DB_PATH = DB_PATH
    if not DB_PATH.exists():
        criar_banco.criar_banco()
    return True

inicializar_banco()
st.set_page_config(
    page_title="Agente SQL | Delivery Intelligence",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Agente Autônomo de Dados — Delivery Intelligence")
st.caption("Gemini Function Calling + SQLite Read-Only + Engenharia de Operações")

if not DB_PATH.exists():
    st.warning("O banco ainda não foi criado. No terminal, execute: `python criar_banco.py`")
    st.stop()

if "historico_analises" not in st.session_state:
    st.session_state.historico_analises = []
if "pergunta_input" not in st.session_state:
    st.session_state.pergunta_input = ""

PERGUNTAS = [
    "Quais restaurantes mais ultrapassam o SLA de preparo? Mostre quantidade e percentual.",
    "Qual zona de entrega tem a maior taxa de cancelamento e quais são os números?",
    "Compare o tempo de preparo do Burger Lab no horário de pico versus fora do pico.",
    "Quais restaurantes têm a maior instabilidade (desvio ou picos) no tempo de preparo?",
    "Faça um diagnóstico executivo dos 3 principais gargalos operacionais da base.",
]

with st.sidebar:
    st.header("Investigação guiada")
    st.caption("Clique em uma pergunta para preencher o campo de análise:")
    for idx, sugestao in enumerate(PERGUNTAS):
        if st.button(sugestao, key=f"sug_{idx}", use_container_width=True):
            st.session_state.pergunta_input = sugestao

    st.divider()
    st.markdown("**Arquitetura & Guardrails**")
    st.caption("• Banco: `data/operacoes_delivery.db` (1.200 pedidos)")
    st.caption("• Proteção: `mode=ro` + `PRAGMA query_only` + filtro `SELECT`")
    st.caption("• Fallback automático em erros `503`/`429`")

aba_agente, aba_dashboard, aba_historico = st.tabs([
    "💬 Agente Investigador",
    "📈 Dashboard Operacional",
    f"🕒 Histórico da Sessão ({len(st.session_state.historico_analises)})",
])

# ==============================================================================
# ABA 1: AGENTE INVESTIGADOR
# ==============================================================================
with aba_agente:
    pergunta = st.text_area(
        "O que você gostaria de investigar na operação?",
        key="pergunta_input",
        height=95,
        placeholder="Ex.: Quais restaurantes estouram mais o SLA de preparo e qual o impacto no cancelamento?",
    )

    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        executar = st.button("Analisar operação", type="primary", use_container_width=True)
    with col_info:
        st.caption("Dados sintéticos criados para demonstrar investigação autônoma de gargalos operacionais.")

    if executar:
        if not pergunta.strip():
            st.error("Digite uma pergunta antes de executar.")
        else:
            try:
                with st.spinner("O agente está inspecionando o schema e executando consultas SQL..."):
                    resultado = analisar(pergunta)
                st.session_state.ultima_analise = resultado
                st.session_state.historico_analises.insert(0, resultado)
            except Exception as erro:
                st.error(f"Não foi possível concluir a análise: {erro}")

    resultado = st.session_state.get("ultima_analise")
    if resultado:
        st.divider()
        tel = resultado.get("telemetria", {})
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Latência total", f"{tel.get('latencia_seg', 0)} s")
        m2.metric("Consultas SQL", f"{tel.get('queries_sql', 0)} query(s)")
        m3.metric("Tokens consumidos", f"{tel.get('tokens_total', 0):,}".replace(",", "."))
        m4.metric("Custo estimado", f"US$ {tel.get('custo_estimado_usd', 0):.5f}")

        st.subheader("Conclusão executiva")
        st.markdown(resultado["resposta"])

        dados = resultado.get("ultimo_resultado")
        if dados and dados["linhas"]:
            st.subheader("Evidências extraídas do banco")
            df = pd.DataFrame(dados["linhas"], columns=dados["colunas"])
            st.dataframe(df, use_container_width=True, hide_index=True)

            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    "Baixar tabela em CSV",
                    data=df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="evidencias_delivery.csv",
                    mime="text/csv",
                )
            with col_dl2:
                st.download_button(
                    "Baixar trilha de auditoria (JSON)",
                    data=json.dumps(resultado["auditoria"], ensure_ascii=False, indent=2),
                    file_name="auditoria_agente_sql.json",
                    mime="application/json",
                )

        with st.expander("🔎 Trilha de Auditoria: SQL gerado e etapas do agente", expanded=False):
            st.caption(f"Modelo utilizado: `{resultado.get('modelo')}` | Chamadas LLM: `{tel.get('chamadas_llm', 0)}`")
            for i, item in enumerate(resultado.get("auditoria", []), start=1):
                status = "✅ Sucesso" if item["sucesso"] else "⚠️ Erro corrigido"
                st.markdown(f"**Etapa {i} — `{item['ferramenta']}` — {status}**")
                if item.get("sql"):
                    st.code(item["sql"], language="sql")
                if item.get("erro"):
                    st.error(item["erro"])
                elif item.get("resultado_resumido"):
                    st.caption(item["resultado_resumido"])

# ==============================================================================
# ABA 2: DASHBOARD OPERACIONAL
# ==============================================================================
with aba_dashboard:
    st.subheader("Visão Geral da Operação (Base Completa)")
    dados_dash = carregar_dados_dashboard()
    kpis = dados_dash["kpis"]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total de Pedidos", f"{kpis.get('total_pedidos', 0):,}".replace(",", "."))
    k2.metric("Ticket Médio", f"R$ {kpis.get('ticket_medio', 0):.2f}")
    k3.metric("Estouro de SLA", f"{kpis.get('taxa_estouro_sla', 0)}%")
    k4.metric("Taxa de Cancelamento", f"{kpis.get('taxa_cancelamento', 0)}%")
    k5.metric("Avaliação Média", f"{kpis.get('avaliacao_media', 0)} ★")

    st.divider()
    df_rest = pd.DataFrame(dados_dash["por_restaurante"])
    df_zona = pd.DataFrame(dados_dash["por_zona"])

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**% de Pedidos Acima do SLA por Restaurante**")
        st.bar_chart(df_rest.set_index("restaurante")["pct_acima_sla"], color="#ff4b4b")

    with g2:
        st.markdown("**% de Cancelamento por Zona de Entrega**")
        st.bar_chart(df_zona.set_index("zona")["pct_cancelamento"], color="#ffa421")

    g3, g4 = st.columns(2)
    with g3:
        st.markdown("**Ticket Médio por Restaurante (R$)**")
        st.bar_chart(df_rest.set_index("restaurante")["ticket_medio"], color="#29b5e8")

    with g4:
        st.markdown("**Tempo Médio de Entrega por Zona (min)**")
        st.bar_chart(df_zona.set_index("zona")["entrega_media_min"], color="#00c0f2")

    with st.expander("Ver tabela consolidada por restaurante"):
        st.dataframe(df_rest, use_container_width=True, hide_index=True)

# ==============================================================================
# ABA 3: HISTÓRICO DA SESSÃO
# ==============================================================================
with aba_historico:
    st.subheader("Perguntas investigadas nesta sessão")
    historico = st.session_state.historico_analises
    if not historico:
        st.info("Nenhuma análise executada ainda. Faça uma pergunta na aba 'Agente Investigador'.")
    else:
        if st.button("Limpar histórico"):
            st.session_state.historico_analises = []
            st.rerun()

        for idx, item in enumerate(historico, start=1):
            tel = item.get("telemetria", {})
            titulo = f"#{idx} • {item['pergunta']} ({tel.get('latencia_seg', 0)}s | {tel.get('queries_sql', 0)} SQL)"
            with st.expander(titulo, expanded=(idx == 1)):
                st.markdown(item["resposta"])
                for etapa in item.get("auditoria", []):
                    if etapa.get("sql"):
                        st.code(etapa["sql"], language="sql")