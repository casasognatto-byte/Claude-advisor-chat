"""Sogno Code — módulo de desenvolvimento da plataforma Sogno (Kimi por padrão).

Chat de texto voltado à criação de ferramentas e automações da loja, chamando
a API da Moonshot (formato OpenAI) — modelo padrão: kimi-k3. As conversas
vivem em tabela própria (`code_conversations`), separadas das do Chat, pra
não misturar os dois módulos na barra lateral.

ACESSO RESTRITO (pedido do Davi, 26/07/2026): só o usuário master
(davinogueira@casasognatto.com.br) usa o Sogno Code — todas as rotas passam
por `_require_code_master`, e a página /code em app/main.py repete a checagem.
A comparação é pelo E-MAIL vindo do banco (não pelo papel "diretor"), então
mesmo que outra pessoa vire diretora no painel /admin, o Code continua só do
Davi.

Segue o padrão dos demais routers: imports de `app.main` dentro das funções
(não no topo) pra evitar import circular, já que `app.main` inclui este router.
A estrutura de CODE_MODELS já aceita entradas de outro provedor (Claude) na
fase futura de integração Kimi + Claude.
"""

import os
from typing import Any

import anthropic
import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/code")

# --- Configuração (ajustável por variáveis de ambiente) ---------------------
MOONSHOT_API_KEY = (os.environ.get("MOONSHOT_API_KEY") or "").strip()
MOONSHOT_BASE_URL = (os.environ.get("MOONSHOT_BASE_URL") or "https://api.moonshot.ai/v1").rstrip("/")
CODE_DEFAULT_MODEL = os.environ.get("CODE_DEFAULT_MODEL", "kimi-k3")
CODE_MAX_TOKENS = int(os.environ.get("CODE_MAX_TOKENS", "8192"))

# Integração Claude no Sogno Code (opcional). Usa CODE_ANTHROPIC_API_KEY se
# existir; senão, reusa ANTHROPIC_API_KEY do chat principal.
ANTHROPIC_API_KEY_FOR_CODE = (
    os.environ.get("CODE_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
).strip()
CODE_CLAUDE_DEFAULT_MODEL = os.environ.get("CODE_CLAUDE_DEFAULT_MODEL", "claude-sonnet-4-6")
CODE_CLAUDE_MAX_TOKENS = int(os.environ.get("CODE_CLAUDE_MAX_TOKENS", "4096"))

# E-mail do único usuário com acesso ao Sogno Code (ver docstring do módulo).
CODE_MASTER_EMAIL = (
    os.environ.get("CODE_MASTER_EMAIL") or "davinogueira@casasognatto.com.br"
).strip().lower()

# Modelos oferecidos no seletor da tela. `provider` agrupa por motor;
# `default` marca o modelo inicial das conversas novas.
CODE_MODELS = [
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "provider": "anthropic"},
    {"id": "claude-opus-4-8", "label": "Claude Opus 4.8", "provider": "anthropic"},
    {"id": "kimi-k3", "label": "Kimi K3", "provider": "moonshot"},
    {"id": "kimi-k2.7-code", "label": "Kimi K2.7 Code", "provider": "moonshot"},
    {"id": "kimi-k2.7-code-highspeed", "label": "Kimi K2.7 Code (rápido)", "provider": "moonshot"},
    {"id": "kimi-k2.6", "label": "Kimi K2.6", "provider": "moonshot"},
]

# Personalidade do Sogno Code. Pode ser sobrescrita pela variável de ambiente
# CODE_SYSTEM_PROMPT, se preferir configurar fora do código.
DEFAULT_CODE_SYSTEM_PROMPT = (
    "Você é o Sogno Code, o assistente de desenvolvimento da Casa Sognatto, "
    "loja de móveis e ambientes planejados sob medida em Campo Grande-MS. "
    "Quem fala com você é o Davi (diretor) ou alguém da equipe dele.\n\n"
    "Seu objetivo: ajudar a criar ferramentas, automações, scripts e pequenos "
    "sistemas que melhorem o dia a dia da loja — de scripts Python e planilhas "
    "inteligentes a páginas web e integrações com APIs.\n\n"
    "Como responder:\n"
    "- Fale sempre em português do Brasil.\n"
    "- Seja direto e prático: explique o essencial e entregue código completo "
    "e funcional, em blocos ``` com a linguagem indicada.\n"
    "- Quando o pedido estiver ambíguo, faça no máximo 1-2 perguntas "
    "essenciais — ou proponha primeiro uma versão simples que já funcione.\n"
    "- Prefira soluções simples, que rodem no Windows, sem dependências "
    "desnecessárias.\n"
    "- A plataforma Sogno (o sistema da loja) é um app FastAPI + HTML/JS "
    "vanilla com Postgres — quando o pedido envolver ela, descreva as "
    "mudanças pensando nesse stack."
)
CODE_SYSTEM_PROMPT = (os.environ.get("CODE_SYSTEM_PROMPT") or "").strip() or DEFAULT_CODE_SYSTEM_PROMPT


def _default_engine() -> str:
    return "anthropic" if ANTHROPIC_API_KEY_FOR_CODE else "moonshot"


def _default_model(provider: str | None = None) -> str:
    provider = provider or _default_engine()
    valid = [m["id"] for m in CODE_MODELS if m["provider"] == provider]
    if provider == "anthropic":
        return CODE_CLAUDE_DEFAULT_MODEL if CODE_CLAUDE_DEFAULT_MODEL in valid else (valid[0] if valid else "")
    return CODE_DEFAULT_MODEL if CODE_DEFAULT_MODEL in valid else (valid[0] if valid else "")


# --- Controle de acesso (só o usuário master) --------------------------------
def is_code_master(username: str) -> bool:
    """True se o username pertence ao e-mail master configurado. Usado tanto
    pelas rotas da API quanto pela página /code em app.main.py. Sem banco,
    ninguém é master (e sem banco ninguém loga, de qualquer forma)."""
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED or not username:
        return False
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
    return bool(row and (row[0] or "").strip().lower() == CODE_MASTER_EMAIL)


def _require_code_master(request: Request) -> dict:
    """require_user + trava do master. 403 pra qualquer outro usuário logado."""
    from app.main import require_user

    user = require_user(request)
    if not is_code_master(user["username"]):
        raise HTTPException(403, "O Sogno Code é restrito ao usuário master.")
    return user


# --- Banco de dados (conversas do Code, separadas das do Chat) --------------
def init_code_db() -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS code_conversations (
                    id             TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    title          TEXT NOT NULL DEFAULT 'Nova conversa',
                    data           JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_code_conv_user "
                "ON code_conversations (owner_username, updated_at DESC);"
            )
    except Exception as e:  # não derruba o app se o banco falhar no boot
        print(f"[init_code_db] falha ao inicializar o banco: {e}")


# --- Modelos de request -----------------------------------------------------
class CodeChatRequest(BaseModel):
    # Histórico completo da conversa (a API é stateless) + motor/modelo.
    messages: list[dict[str, Any]]
    engine: str | None = None  # "claude" | "kimi"
    model: str | None = None


class ConvCreate(BaseModel):
    id: str | None = None
    title: str | None = None
    data: dict | None = None


class ConvUpdate(BaseModel):
    title: str | None = None
    data: dict | None = None


class ConvBulkDelete(BaseModel):
    ids: list[str]


# --- Rotas ------------------------------------------------------------------
@router.get("/models")
def list_models(request: Request):
    _require_code_master(request)
    default = _default_model()
    return {
        "models": [{**m, "default": m["id"] == default} for m in CODE_MODELS],
        "default": default,
    }


@router.get("/conversations")
def list_conversations(request: Request, owner: str | None = None):
    from app.main import _db, _require_db

    _require_code_master(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        if owner and owner != "all":
            cur.execute(
                "SELECT id, title, EXTRACT(EPOCH FROM updated_at) "
                "FROM code_conversations WHERE owner_username = %s ORDER BY updated_at DESC",
                (owner,),
            )
        else:
            cur.execute(
                "SELECT id, title, EXTRACT(EPOCH FROM updated_at) "
                "FROM code_conversations ORDER BY updated_at DESC"
            )
        rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "updatedAt": float(r[2])} for r in rows]


@router.get("/conversations/{cid}")
def get_conversation(cid: str, request: Request):
    from app.main import _db, _require_db

    _require_code_master(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, title, data FROM code_conversations WHERE id = %s", (cid,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Conversa não encontrada.")
    return {"id": row[0], "title": row[1], "data": row[2]}


@router.post("/conversations")
def create_conversation(body: ConvCreate, request: Request):
    import json
    import secrets

    from app.main import _db, _log_activity, _require_db

    user = _require_code_master(request)
    _require_db()
    cid = body.id or ("k" + secrets.token_hex(8))
    title = (body.title or "Nova conversa")[:200]
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO code_conversations (id, owner_username, title, data) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (cid, user["username"], title, json.dumps(body.data or {})),
        )
    _log_activity(user["username"], "conversa_criada", f"[Code] {title}")
    return {"id": cid, "title": title}


@router.put("/conversations/{cid}")
def update_conversation(cid: str, body: ConvUpdate, request: Request):
    import json

    from app.main import _db, _require_db

    _require_code_master(request)
    _require_db()
    sets, params = [], []
    if body.title is not None:
        sets.append("title = %s")
        params.append(body.title[:200])
    if body.data is not None:
        sets.append("data = %s")
        params.append(json.dumps(body.data))
    if not sets:
        return {"ok": True}
    sets.append("updated_at = now()")
    params.append(cid)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE code_conversations SET {', '.join(sets)} WHERE id = %s", params)
    return {"ok": True}


@router.delete("/conversations/{cid}")
def delete_conversation(cid: str, request: Request):
    from app.main import _db, _log_activity, _require_db

    user = _require_code_master(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT title FROM code_conversations WHERE id = %s", (cid,))
        row = cur.fetchone()
        title = row[0] if row else cid
        cur.execute("DELETE FROM code_conversations WHERE id = %s", (cid,))
    _log_activity(user["username"], "conversa_deletada", f"[Code] {title}")
    return {"ok": True}


@router.post("/conversations/bulk-delete")
def bulk_delete_conversations(body: ConvBulkDelete, request: Request):
    from app.main import _db, _log_activity, _require_db

    user = _require_code_master(request)
    _require_db()
    if not body.ids:
        return {"deleted": 0}
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, title FROM code_conversations WHERE id = ANY(%s)", (body.ids,))
        rows = cur.fetchall()
        cur.execute("DELETE FROM code_conversations WHERE id = ANY(%s)", (body.ids,))
    for _cid, title in rows:
        _log_activity(user["username"], "conversa_deletada", f"[Code] {title}")
    return {"deleted": len(rows)}


def _content_to_text(content: Any) -> str:
    """`message.content` da resposta OpenAI-compatível: normalmente string,
    mas alguns modelos devolvem lista de partes — junta os textos."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


@router.post("/chat")
def code_chat(req: CodeChatRequest, request: Request):
    _require_code_master(request)
    if not MOONSHOT_API_KEY:
        raise HTTPException(500, "MOONSHOT_API_KEY não está configurada no servidor.")

    valid = {m["id"] for m in CODE_MODELS}
    model = req.model if req.model in valid else _default_model()

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": CODE_SYSTEM_PROMPT}] + req.messages,
        "max_tokens": CODE_MAX_TOKENS,
        # Sem "temperature": kimi-k3 só aceita temperature=1 (erro 400 em outro
        # valor) — deixar de fora usa o padrão de cada modelo. Achado no teste
        # local de 26/07/2026.
    }
    try:
        resp = httpx.post(
            f"{MOONSHOT_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {MOONSHOT_API_KEY}"},
            json=payload,
            timeout=120,
        )
    except httpx.HTTPError:
        raise HTTPException(503, "Não foi possível conectar à API da Moonshot.")

    if resp.status_code >= 400:
        detail = f"Erro da API do modelo (HTTP {resp.status_code})."
        try:
            err = resp.json().get("error") or {}
            if err.get("message"):
                detail = err["message"]
        except ValueError:
            pass
        raise HTTPException(resp.status_code, detail)

    data = resp.json()
    choices = data.get("choices") or [{}]
    text = _content_to_text((choices[0].get("message") or {}).get("content")).strip()
    usage_raw = data.get("usage") or {}

    appended = [{"role": "assistant", "content": text}]
    return {
        # Mesmo formato de resposta do /api/chat (Chat): o frontend reaproveita
        # a lógica de anexar ao histórico e somar tokens.
        "append": appended,
        "text": text,
        "advisor": [],
        "usage": {
            "executor": {
                "input_tokens": usage_raw.get("prompt_tokens") or 0,
                "output_tokens": usage_raw.get("completion_tokens") or 0,
            },
            "advisor": None,
            "advisor_calls": 0,
        },
    }
