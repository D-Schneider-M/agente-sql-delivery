"""Gera um banco SQLite sintético para análise de operações de delivery.

Todos os dados são fictícios e foram criados para demonstração/portfólio.
Execute: python criar_banco.py
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "operacoes_delivery.db"
RANDOM_SEED = 42

RESTAURANTES = [
    ("Sabor da Vila", "Brasileira", "Centro", 35),
    ("Pasta & Ponto", "Italiana", "Pinheiros", 40),
    ("Temaki House", "Japonesa", "Vila Mariana", 45),
    ("Burger Lab", "Hambúrguer", "Moema", 30),
    ("Verde no Prato", "Saudável", "Paulista", 35),
    ("Cantina do Sul", "Brasileira", "Tatuapé", 40),
    ("Wok Express", "Asiática", "Itaim Bibi", 30),
    ("Pizza da Praça", "Pizzaria", "Santana", 50),
    ("Açaí Tropical", "Sobremesas", "Lapa", 25),
    ("Frango & Cia", "Brasileira", "Santo Amaro", 35),
    ("Doce Momento", "Sobremesas", "Perdizes", 30),
    ("Grill 011", "Churrasco", "Morumbi", 45),
]

ZONAS = [
    "Centro", "Pinheiros", "Vila Mariana", "Moema", "Paulista",
    "Tatuapé", "Itaim Bibi", "Santana", "Lapa", "Santo Amaro",
    "Perdizes", "Morumbi",
]

def criar_banco() -> Path:
    random.seed(RANDOM_SEED)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE restaurantes (
        restaurante_id INTEGER PRIMARY KEY,
        nome TEXT NOT NULL,
        categoria TEXT NOT NULL,
        zona TEXT NOT NULL,
        sla_preparo_min INTEGER NOT NULL,
        ativo INTEGER NOT NULL CHECK (ativo IN (0, 1))
    );

    CREATE TABLE pedidos (
        pedido_id INTEGER PRIMARY KEY,
        restaurante_id INTEGER NOT NULL,
        data_pedido TEXT NOT NULL,
        zona_entrega TEXT NOT NULL,
        valor_pedido REAL NOT NULL,
        tempo_preparo_min INTEGER NOT NULL,
        tempo_entrega_min INTEGER NOT NULL,
        status TEXT NOT NULL,
        motivo_cancelamento TEXT,
        avaliacao INTEGER,
        FOREIGN KEY (restaurante_id) REFERENCES restaurantes(restaurante_id)
    );

    CREATE INDEX idx_pedidos_data ON pedidos(data_pedido);
    CREATE INDEX idx_pedidos_restaurante ON pedidos(restaurante_id);
    CREATE INDEX idx_pedidos_zona ON pedidos(zona_entrega);
    """)

    restaurantes = []
    for i, (nome, categoria, zona, sla) in enumerate(RESTAURANTES, start=1):
        restaurantes.append((i, nome, categoria, zona, sla, 1))
    cur.executemany(
        "INSERT INTO restaurantes VALUES (?, ?, ?, ?, ?, ?)", restaurantes
    )

    inicio = datetime(2026, 1, 1, 10, 0, 0)
    pedidos = []
    motivos = ["Atraso na entrega", "Problema no preparo", "Cliente desistiu", "Indisponibilidade"]

    # 1.200 pedidos distribuídos por aproximadamente 90 dias.
    for pedido_id in range(1, 1201):
        restaurante_id = random.randint(1, len(RESTAURANTES))
        nome, categoria, zona_rest, sla = RESTAURANTES[restaurante_id - 1]
        dia = random.randint(0, 89)
        hora = random.choices(
            [random.randint(10, 16), random.randint(17, 22)],
            weights=[0.42, 0.58],
        )[0]
        minuto = random.randint(0, 59)
        momento = inicio + timedelta(days=dia)
        momento = momento.replace(hour=hora, minute=minuto)

        zona_entrega = random.choice(ZONAS)
        pico = 18 <= hora <= 21

        # Base operacional: pequenas variações naturais.
        preparo = max(8, int(random.gauss(sla + (7 if pico else 0), 7)))
        entrega = max(10, int(random.gauss(29 + (8 if pico else 0), 9)))
        valor = round(random.uniform(22, 115), 2)
        status = "Entregue"
        motivo = None
        avaliacao = random.choices([3, 4, 5], weights=[0.12, 0.38, 0.50])[0]

        # Anomalia 1: Burger Lab tem forte estouro de SLA no horário de pico.
        if restaurante_id == 4 and pico:
            preparo += random.randint(18, 38)

        # Anomalia 2: entregas para a zona Lapa têm mais atrasos e cancelamentos.
        if zona_entrega == "Lapa":
            entrega += random.randint(8, 24)

        # Anomalia 3: Wok Express tem instabilidade adicional em alguns dias.
        if restaurante_id == 7 and dia % 9 in (0, 1):
            preparo += random.randint(12, 25)

        # Cancelamentos são mais prováveis quando há atraso.
        prob_cancelamento = 0.035
        if zona_entrega == "Lapa":
            prob_cancelamento += 0.12
        if restaurante_id == 4 and pico:
            prob_cancelamento += 0.10
        if preparo > sla + 25 or entrega > 55:
            prob_cancelamento += 0.08

        if random.random() < prob_cancelamento:
            status = "Cancelado"
            motivo = random.choices(
                motivos,
                weights=[0.58, 0.22, 0.12, 0.08],
            )[0]
            avaliacao = None
        elif preparo > sla + 18 or entrega > 60:
            status = "Entregue com atraso"
            avaliacao = random.choices([1, 2, 3, 4], weights=[0.25, 0.30, 0.35, 0.10])[0]

        pedidos.append((
            pedido_id, restaurante_id, momento.strftime("%Y-%m-%d %H:%M:%S"),
            zona_entrega, valor, preparo, entrega, status, motivo, avaliacao
        ))

    cur.executemany("""
        INSERT INTO pedidos (
            pedido_id, restaurante_id, data_pedido, zona_entrega, valor_pedido,
            tempo_preparo_min, tempo_entrega_min, status, motivo_cancelamento, avaliacao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, pedidos)

    conn.commit()
    conn.close()
    return DB_PATH


if __name__ == "__main__":
    caminho = criar_banco()
    print(f"Banco criado com sucesso: {caminho}")
    print("Tabelas: restaurantes (12 registros) e pedidos (1.200 registros)")
    print("Dados sintéticos; anomalias operacionais foram inseridas intencionalmente.")
