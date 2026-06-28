# Chat Executor + Advisor

Interface web simples para a **Advisor tool** da API da Anthropic, usando o padrão
**Executor + Advisor**: um modelo rápido (`claude-sonnet-4-6`, executor) consulta um
modelo mais inteligente (`claude-opus-4-8`, advisor) em momentos estratégicos antes
de responder.

- **Backend** (FastAPI): guarda a chave da API com segurança e chama
  `https://api.anthropic.com/v1/messages` com o header `anthropic-beta: advisor-tool-2026-03-01`.
- **Frontend** (HTML/JS puro): chat no navegador, sem instalar nada. Mostra quando o
  advisor foi consultado (bloco dourado), a contagem de tokens (executor e advisor
  separados) e um botão para limpar a conversa.

A chave da API **nunca** vai para o navegador — fica só no servidor, em variável de ambiente.

## Estrutura

```
advisor-chat/
├── app/
│   ├── main.py            # backend FastAPI
│   └── static/index.html  # frontend (sem build)
├── requirements.txt
├── render.yaml            # deploy no Render
├── .env.example
└── README.md
```

## Rodar localmente

Pré-requisito: Python 3.10+.

```bash
cd advisor-chat
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # depois edite .env e cole sua ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

Abra http://127.0.0.1:8000

> Confira se a chave está carregada: http://127.0.0.1:8000/api/health → `"api_key_set": true`.

## Deploy no Render (URL única para os dois escritórios)

1. Suba esta pasta para um repositório no GitHub.
2. No Render: **New → Blueprint** e aponte para o repo (ele lê o `render.yaml`).
   - Ou **New → Web Service** manualmente:
     - Build: `pip install -r requirements.txt`
     - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Em **Environment**, adicione:
   - `ANTHROPIC_API_KEY` = sua chave (marque como secreta)
   - `SYSTEM_PROMPT` = (opcional) o contexto do Promob, etc.
4. Deploy. O Render gera uma URL `https://advisor-chat-xxxx.onrender.com` que os dois
   escritórios abrem no navegador.

(O fluxo é equivalente no Railway: mesmo Build/Start command e as mesmas variáveis de ambiente.)

## Configuração

Tudo por variável de ambiente (ver `.env.example`):

| Variável | Padrão | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Obrigatória.** Chave da API. |
| `SYSTEM_PROMPT` | vazio | System prompt do executor (ex.: contexto do Promob). |
| `EXECUTOR_MODEL` | `claude-sonnet-4-6` | Modelo executor (rápido). |
| `ADVISOR_MODEL` | `claude-opus-4-8` | Modelo advisor. Deve ser ≥ executor em capacidade. |
| `MAX_TOKENS` | `4096` | Máximo de tokens da resposta. |
| `ADVISOR_MAX_USES` | `3` | Máximo de consultas ao advisor por turno. |
| `ADVISOR_MAX_TOKENS` | `2048` | Tokens por consulta ao advisor. |

## Pontos a verificar contra a API (beta)

A Advisor tool é um recurso **beta** (`advisor_20260301`). Dois detalhes valem
conferência contra a saída real da API:

1. **Tokens do advisor separados.** O backend tenta localizar o breakdown de tokens
   do advisor no objeto `usage` (`app/main.py` → `_advisor_usage`). Se a API expuser
   esse dado em outra chave, o frontend mostra `n/d` — basta ajustar a função. Para
   inspecionar o formato real, veja o campo `usage.raw` no JSON de resposta do
   `/api/chat`.
2. **`max_uses` / `max_tokens` na definição da tool.** São plausíveis e seguem o
   padrão de outras server-tools, mas não estão explicitamente documentados para a
   advisor tool. Se a API recusar (400), remova-os da tool em `app/main.py`.

O pareamento de modelos está correto: o advisor (`claude-opus-4-8`) é igual ou mais
capaz que o executor (`claude-sonnet-4-6`) — exigência da API.
