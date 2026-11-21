# Agente SQL Delivery
[![Abrir no Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://agente-sql-delivery-hwiu4dbhsmwm3tqmapp6fok.streamlit.app)

> **Demonstração ao vivo:** [Acesse o Agente Autônomo no Streamlit Cloud](https://agente-sql-delivery-hwiu4dbhsmwm3tqmapp6fok.streamlit.app)
Agente de análise de dados que recebe perguntas em português, inspeciona um banco SQLite,
gera consultas SQL por Function Calling do Gemini e devolve uma análise executiva com
trilha de auditoria.

> **Importante:** todos os registros são sintéticos. O projeto é independente e não usa
> dados, sistemas ou informações internas do iFood.

## 1. Requisitos

- Python 3.10 ou superior
- Uma chave da API Gemini (Google AI Studio)
- VS Code (opcional, mas recomendado)

## 2. Instalação

Abra a pasta do projeto no VS Code e execute no terminal:

```bash
python -m venv .venv
```

Ative o ambiente virtual:

**Windows PowerShell**
```powershell
.venv\Scripts\Activate.ps1
```

**Windows CMD**
```cmd
.venv\Scripts\activate.bat
```

**macOS/Linux**
```bash
source .venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

## 3. Configure a API

1. Copie `.env.example` e renomeie a cópia para `.env`.
2. Abra `.env` e substitua `sua_chave_aqui` pela sua chave Gemini.
3. Nunca compartilhe o arquivo `.env` nem publique sua chave no GitHub.

## 4. Crie o banco sintético

```bash
python criar_banco.py
```

O script cria `data/operacoes_delivery.db`, com 12 restaurantes e 1.200 pedidos.
Foram inseridos padrões operacionais intencionais para investigação:

- Burger Lab: aumento do tempo de preparo no horário de pico.
- Zona Lapa: maior incidência de atrasos e cancelamentos.
- Wok Express: instabilidade adicional em determinados dias.

Esses padrões são hipóteses de teste criadas no gerador, não conclusões sobre uma operação real.

## 5. Execute a aplicação

```bash
streamlit run app.py
```

O Streamlit abrirá a aplicação no navegador. Se não abrir automaticamente, acesse
o endereço local indicado no terminal.

## 6. Exemplos de perguntas

- Qual restaurante tem a maior taxa de pedidos acima do SLA?
- Qual zona apresenta a maior taxa de cancelamento?
- Como o horário de pico afeta o tempo de preparo?
- Quais restaurantes têm melhor avaliação média?
- Quais são os principais gargalos operacionais?

## 7. Segurança e limitações

- O SQLite é aberto em modo `mode=ro` (somente leitura).
- `PRAGMA query_only=ON` adiciona uma segunda camada de proteção.
- A validação permite apenas consultas iniciadas por `SELECT` ou `WITH`.
- A aplicação limita cada resultado a 200 linhas para evitar excesso de dados na interface.
- A validação textual é uma camada de defesa, não um sandbox universal para SQL arbitrário.
  O modo somente leitura do SQLite é a proteção principal.
- O agente depende de conexão com a API Gemini; o banco e a interface rodam localmente.
- O conteúdo da análise depende da qualidade da pergunta e da consulta gerada pelo modelo.

## 8. Próximas evoluções para portfólio

1. Criar testes automatizados para consultas permitidas e bloqueadas.
2. Adicionar métricas de SLA, cancelamento, ticket médio e avaliação.
3. Exibir gráficos comparativos e evolução diária.
4. Criar um conjunto de perguntas de avaliação para medir precisão do agente.
5. Registrar tempo de resposta, número de chamadas e custo estimado da API.
