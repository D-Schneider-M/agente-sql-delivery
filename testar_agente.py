"""Suíte de testes de segurança (guardrails SQL) e precisão analítica do agente."""
from __future__ import annotations

import sys
from agente_sql import analisar, executar_sql

QUERIES_MALICIOSAS = [
    "DROP TABLE pedidos;",
    "DELETE FROM pedidos WHERE pedido_id = 1;",
    "UPDATE restaurantes SET sla_preparo_min = 999;",
    "INSERT INTO restaurantes VALUES (99, 'Fake', 'Teste', 'Centro', 10, 1);",
    "SELECT * FROM pedidos; DROP TABLE pedidos;",
    "SELECT * FROM pedidos /* DELETE FROM pedidos */ WHERE 1=1; UPDATE pedidos SET status='x'",
    "PRAGMA writable_schema = ON;",
    "ATTACH DATABASE 'hack.db' AS hack;",
]

CASOS_AVALIACAO = [
    {
        "nome": "Anomalia 1 — Gargalo de preparo no pico",
        "pergunta": "Qual restaurante apresenta o maior estouro de SLA de preparo no horário de pico?",
        "esperado_na_resposta": ["burger lab"],
    },
    {
        "nome": "Anomalia 2 — Zona crítica de cancelamento",
        "pergunta": "Qual zona de entrega concentra a maior taxa de cancelamentos e atrasos?",
        "esperado_na_resposta": ["lapa"],
    },
    {
        "nome": "Anomalia 3 — Instabilidade periódica no preparo",
        "pergunta": "Além do Burger Lab, qual outro restaurante tem picos atípicos de tempo de preparo em dias específicos?",
        "esperado_na_resposta": ["wok express"],
    },
]


def rodar_testes_seguranca() -> bool:
    print("\n=== 1. TESTES DE SEGURANÇA (SQL GUARDRAILS) ===")
    passou_todos = True

    for query in QUERIES_MALICIOSAS:
        try:
            executar_sql(query)
            print(f"[FALHA] Query perigosa NÃO foi bloqueada: {query}")
            passou_todos = False
        except ValueError as exc:
            print(f"[OK] Bloqueada ({exc}): {query}")

    try:
        res = executar_sql("SELECT COUNT(*) AS total FROM pedidos")
        assert res["linhas"][0]["total"] == 1200
        print("[OK] Consulta SELECT legítima executada com sucesso (1.200 registros).")
    except Exception as exc:
        print(f"[FALHA] Consulta legítima falhou: {exc}")
        passou_todos = False

    return passou_todos


def rodar_testes_precisao() -> bool:
    print("\n=== 2. AVALIAÇÃO DE PRECISÃO DO AGENTE (EVALS) ===")
    acertos = 0

    for caso in CASOS_AVALIACAO:
        print(f"\nTestando: {caso['nome']}")
        print(f"Pergunta: {caso['pergunta']}")
        resultado = analisar(caso["pergunta"])
        texto = resultado["resposta"].lower()
        tel = resultado["telemetria"]

        encontrou = all(termo in texto for termo in caso["esperado_na_resposta"])
        if encontrou:
            acertos += 1
            status = "PASSOU"
        else:
            status = "FALHOU"

        print(
            f"[{status}] Esperado: {caso['esperado_na_resposta']} | "
            f"Latência: {tel['latencia_seg']}s | Queries: {tel['queries_sql']} | "
            f"Tokens: {tel['tokens_total']}"
        )

    taxa = (acertos / len(CASOS_AVALIACAO)) * 100
    print(f"\nResumo Evals: {acertos}/{len(CASOS_AVALIACAO)} ({taxa:.0f}% de acerto)")
    return acertos == len(CASOS_AVALIACAO)


if __name__ == "__main__":
    ok_seg = rodar_testes_seguranca()
    rodar_evals = "--completo" in sys.argv

    if not rodar_evals:
        print("\nDica: rode `python testar_agente.py --completo` para executar também os Evals com a API Gemini.")
        sys.exit(0 if ok_seg else 1)

    ok_prec = rodar_testes_precisao()
    sys.exit(0 if (ok_seg and ok_prec) else 1)