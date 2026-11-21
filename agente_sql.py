"""Agente de análise SQL com Gemini Function Calling, telemetria e SQLite somente leitura."""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

import tempfile

BASE_DIR = Path(__file__).resolve().parent
LOCAL_DB = BASE_DIR / "data" / "operacoes_delivery.db"
DB_PATH = LOCAL_DB if LOCAL_DB.exists() else Path(tempfile.gettempdir()) / "operacoes_delivery.db"

PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = [PRIMARY_MODEL, "gemini-3.5-flash-lite"]
MAX_TOOL_ROUNDS = 5
MAX_ROWS = 200

# Estimativa referencial (USD por 1M tokens) para telemetria de portfólio
CUSTO_POR_MILHAO_TOKENS = {
    "entrada": 0.15,
    "saida": 0.60,
}

SYSTEM_INSTRUCTION = """
Você é um analista sênior de operações de delivery e especialista em SQL.
Responda em português do Brasil, com clareza executiva e sem inventar dados.

Schema do banco SQLite disponível:
- restaurantes (restaurante_id, nome, categoria, zona, sla_preparo_min, ativo)
- pedidos (pedido_id, restaurante_id, data_pedido, zona_entrega, valor_pedido, tempo_preparo_min, tempo_entrega_min, status, motivo_cancelamento, avaliacao)

Regras:
1. Gere SQL SQLite válido e use somente SELECT (CTEs com WITH são permitidas).
2. Nunca tente alterar dados ou estrutura do banco.
3. Para análises quantitativas, mostre período, denominador e fórmula quando relevante.
4. Diferencie correlação de causalidade. Não afirme causa sem evidência.
5. Se uma consulta falhar, leia o erro e tente corrigir. Não repita a mesma query sem mudança.
6. Seja objetivo: execute no máximo 2 ou 3 consultas SQL agregadas (GROUP BY, AVG, MAX, COUNT) e já redija a resposta final.
7. Ao concluir, apresente: resposta direta, principais evidências numéricas,
   interpretação operacional e uma recomendação prática.
"""


def _conexao_readonly() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Banco não encontrado em {DB_PATH}. Execute primeiro: python criar_banco.py"
        )
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def inspecionar_schema() -> dict[str, Any]:
    """Retorna tabelas, colunas e chaves do banco."""
    with _conexao_readonly() as conn:
        tabelas = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """).fetchall()
        resultado = {}
        for item in tabelas:
            nome = item["name"]
            colunas = conn.execute(f'PRAGMA table_info("{nome}")').fetchall()
            resultado[nome] = [
                {
                    "coluna": c["name"],
                    "tipo": c["type"],
                    "obrigatoria": bool(c["notnull"]),
                    "chave_primaria": bool(c["pk"]),
                }
                for c in colunas
            ]
        return {"tabelas": resultado}


def _validar_select(query: str) -> str:
    """Validação em camadas: uma instrução, SELECT/CTE e sem palavras perigosas."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("A consulta SQL está vazia.")
    sql = query.strip()
    sem_comentarios = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", sql, flags=re.S).strip()
    if ";" in sem_comentarios.rstrip(";"):
        raise ValueError("Somente uma instrução SQL por vez é permitida.")
    sem_comentarios = sem_comentarios.rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", sem_comentarios, flags=re.I):
        raise ValueError("Bloqueado: somente consultas SELECT (ou WITH ... SELECT) são permitidas.")
    proibidos = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|"
        r"VACUUM|REINDEX|PRAGMA|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\b",
        flags=re.I,
    )
    if proibidos.search(sem_comentarios):
        raise ValueError("A consulta contém uma operação não permitida.")
    return sem_comentarios


def executar_sql(query: str) -> dict[str, Any]:
    """Executa SELECT validado e retorna colunas, linhas e SQL auditável."""
    sql = _validar_select(query)
    with _conexao_readonly() as conn:
        cursor = conn.execute(sql)
        colunas = [desc[0] for desc in (cursor.description or [])]
        linhas = cursor.fetchmany(MAX_ROWS + 1)
        truncado = len(linhas) > MAX_ROWS
        linhas = linhas[:MAX_ROWS]
        dados = [dict(linha) for linha in linhas]
    return {
        "sql": sql,
        "colunas": colunas,
        "linhas": dados,
        "total_retornado": len(dados),
        "limite_aplicado": MAX_ROWS,
        "resultado_truncado": truncado,
    }


def carregar_dados_dashboard() -> dict[str, list[dict[str, Any]]]:
    """Extrai visões agregadas diretamente do banco para o Dashboard Operacional."""
    with _conexao_readonly() as conn:
        kpis = conn.execute("""
            SELECT
                COUNT(*) AS total_pedidos,
                ROUND(AVG(p.valor_pedido), 2) AS ticket_medio,
                ROUND(100.0 * SUM(CASE WHEN p.status = 'Cancelado' THEN 1 ELSE 0 END) / COUNT(*), 2) AS taxa_cancelamento,
                ROUND(100.0 * SUM(CASE WHEN p.tempo_preparo_min > r.sla_preparo_min THEN 1 ELSE 0 END) / COUNT(*), 2) AS taxa_estouro_sla,
                ROUND(AVG(p.avaliacao), 2) AS avaliacao_media
            FROM pedidos p
            JOIN restaurantes r ON p.restaurante_id = r.restaurante_id
        """).fetchone()

        por_restaurante = conn.execute("""
            SELECT
                r.nome AS restaurante,
                r.categoria,
                r.sla_preparo_min AS sla_alvo_min,
                COUNT(*) AS total_pedidos,
                ROUND(AVG(p.tempo_preparo_min), 1) AS preparo_medio_min,
                ROUND(100.0 * SUM(CASE WHEN p.tempo_preparo_min > r.sla_preparo_min THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_acima_sla,
                ROUND(100.0 * SUM(CASE WHEN p.status = 'Cancelado' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_cancelamento,
                ROUND(AVG(p.valor_pedido), 2) AS ticket_medio
            FROM pedidos p
            JOIN restaurantes r ON p.restaurante_id = r.restaurante_id
            GROUP BY r.restaurante_id, r.nome, r.categoria, r.sla_preparo_min
            ORDER BY pct_acima_sla DESC
        """).fetchall()

        por_zona = conn.execute("""
            SELECT
                zona_entrega AS zona,
                COUNT(*) AS total_pedidos,
                ROUND(AVG(tempo_entrega_min), 1) AS entrega_media_min,
                ROUND(100.0 * SUM(CASE WHEN status = 'Cancelado' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_cancelamento
            FROM pedidos
            GROUP BY zona_entrega
            ORDER BY pct_cancelamento DESC
        """).fetchall()

    return {
        "kpis": dict(kpis) if kpis else {},
        "por_restaurante": [dict(row) for row in por_restaurante],
        "por_zona": [dict(row) for row in por_zona],
    }


def _declarar_ferramentas() -> types.Tool:
    return types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="inspecionar_schema",
            description="Inspeciona as tabelas e colunas disponíveis no banco SQLite.",
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="executar_sql",
            description="Executa uma consulta SQL somente leitura. Use apenas SELECT ou WITH ... SELECT.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="Consulta SQL SQLite somente leitura."
                    )
                },
                required=["query"],
            ),
        ),
    ])


def _chamar_gemini_resiliente(
    client: genai.Client,
    historico: list[types.Content],
    ferramenta: types.Tool,
) -> tuple[Any, str]:
    """Executa chamada ao Gemini com retry curto e fallback de modelo em falhas temporárias."""
    modelos_unicos = list(dict.fromkeys(FALLBACK_MODELS))
    ultimo_erro: Exception | None = None

    for modelo in modelos_unicos:
        for tentativa in range(1, 3):
            try:
                resposta = client.models.generate_content(
                    model=modelo,
                    contents=historico,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        tools=[ferramenta],
                        temperature=0.2,
                    ),
                )
                return resposta, modelo
            except Exception as exc:
                ultimo_erro = exc
                msg = str(exc).lower()
                transitorio = any(
                    cod in msg for cod in ("503", "429", "404", "not_found", "unavailable", "resource_exhausted", "deadline")
                )
                if not transitorio:
                    raise
                time.sleep(1.2 * tentativa)

    raise RuntimeError(f"Falha após tentativas nos modelos de fallback: {ultimo_erro}")


def analisar(pergunta: str) -> dict[str, Any]:
    """Conduz o ciclo de Function Calling e devolve resposta, auditoria e telemetria."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            api_key = None
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY não configurada. Copie .env.example para .env e informe sua chave."
        )
    if not pergunta or not pergunta.strip():
        raise ValueError("Digite uma pergunta para iniciar a análise.")

    inicio_execucao = time.perf_counter()
    client = genai.Client(api_key=api_key)
    ferramenta = _declarar_ferramentas()
    historico = [
        types.Content(
            role="user",
            parts=[types.Part(text=pergunta.strip())],
        )
    ]

    auditoria: list[dict[str, Any]] = []
    ultimo_resultado = None
    modelo_usado = PRIMARY_MODEL
    tokens_entrada = 0
    tokens_saida = 0
    chamadas_llm = 0

    for rodada in range(1, MAX_TOOL_ROUNDS + 1):
        resposta, modelo_usado = _chamar_gemini_resiliente(client, historico, ferramenta)
        chamadas_llm += 1

        uso = getattr(resposta, "usage_metadata", None)
        if uso:
            tokens_entrada += getattr(uso, "prompt_token_count", 0) or 0
            tokens_saida += getattr(uso, "candidates_token_count", 0) or 0

        if not resposta.candidates:
            raise RuntimeError("O Gemini não retornou uma resposta. Tente novamente.")
        conteudo_modelo = resposta.candidates[0].content
        historico.append(conteudo_modelo)

        chamadas = [
            parte.function_call
            for parte in (conteudo_modelo.parts or [])
            if parte.function_call is not None
        ]

        if not chamadas:
            duracao_seg = round(time.perf_counter() - inicio_execucao, 2)
            custo_usd = round(
                (tokens_entrada / 1_000_000) * CUSTO_POR_MILHAO_TOKENS["entrada"]
                + (tokens_saida / 1_000_000) * CUSTO_POR_MILHAO_TOKENS["saida"],
                6,
            )
            queries_executadas = sum(
                1 for item in auditoria if item["ferramenta"] == "executar_sql"
            )
            texto = resposta.text or "Não foi possível produzir uma resposta textual."
            return {
                "pergunta": pergunta.strip(),
                "resposta": texto,
                "auditoria": auditoria,
                "ultimo_resultado": ultimo_resultado,
                "modelo": modelo_usado,
                "telemetria": {
                    "latencia_seg": duracao_seg,
                    "chamadas_llm": chamadas_llm,
                    "queries_sql": queries_executadas,
                    "tokens_entrada": tokens_entrada,
                    "tokens_saida": tokens_saida,
                    "tokens_total": tokens_entrada + tokens_saida,
                    "custo_estimado_usd": custo_usd,
                },
            }

        respostas_ferramentas = []
        for chamada in chamadas:
            nome = chamada.name
            argumentos = dict(chamada.args or {})
            try:
                if nome == "inspecionar_schema":
                    resultado = inspecionar_schema()
                elif nome == "executar_sql":
                    resultado = executar_sql(argumentos.get("query", ""))
                    ultimo_resultado = resultado
                else:
                    raise ValueError(f"Ferramenta desconhecida: {nome}")

                auditoria.append({
                    "rodada": rodada,
                    "ferramenta": nome,
                    "argumentos": argumentos,
                    "sucesso": True,
                    "resultado_resumido": (
                        f"{resultado.get('total_retornado')} linhas retornadas"
                        if nome == "executar_sql" else "Schema inspecionado"
                    ),
                    "sql": resultado.get("sql") if nome == "executar_sql" else None,
                })
                payload = {"ok": True, "resultado": resultado}
            except Exception as exc:
                auditoria.append({
                    "rodada": rodada,
                    "ferramenta": nome,
                    "argumentos": argumentos,
                    "sucesso": False,
                    "erro": str(exc),
                    "sql": argumentos.get("query") if nome == "executar_sql" else None,
                })
                payload = {"ok": False, "erro": str(exc)}

            respostas_ferramentas.append(
                types.Part.from_function_response(
                    name=nome,
                    response=payload,
                )
            )

        historico.append(types.Content(role="user", parts=respostas_ferramentas))

    # Se atingir MAX_TOOL_ROUNDS, força a síntese final sem chamar mais ferramentas
    historico.append(
        types.Content(
            role="user",
            parts=[types.Part(text="Com base apenas nas consultas já executadas acima, apresente agora sua conclusão final sem chamar novas ferramentas.")],
        )
    )
    resposta_final = client.models.generate_content(
        model=modelo_usado,
        contents=historico,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.2,
        ),
    )
    duracao_seg = round(time.perf_counter() - inicio_execucao, 2)
    return {
        "pergunta": pergunta.strip(),
        "resposta": resposta_final.text or "Análise concluída com limite de rodadas.",
        "auditoria": auditoria,
        "ultimo_resultado": ultimo_resultado,
        "modelo": modelo_usado,
        "telemetria": {
            "latencia_seg": duracao_seg,
            "chamadas_llm": chamadas_llm + 1,
            "queries_sql": sum(1 for item in auditoria if item["ferramenta"] == "executar_sql"),
            "tokens_entrada": tokens_entrada,
            "tokens_saida": tokens_saida,
            "tokens_total": tokens_entrada + tokens_saida,
            "custo_estimado_usd": round(
                (tokens_entrada / 1_000_000) * CUSTO_POR_MILHAO_TOKENS["entrada"]
                + (tokens_saida / 1_000_000) * CUSTO_POR_MILHAO_TOKENS["saida"],
                6,
            ),
        },
    }