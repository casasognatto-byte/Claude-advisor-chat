"""Backend FastAPI para o chat Executor + Advisor da API da Anthropic.

A chave da API fica somente no servidor (variável de ambiente ANTHROPIC_API_KEY)
e nunca é exposta ao frontend. O endpoint /api/chat repassa o histórico da
conversa para a API da Anthropic usando o padrão Executor + Advisor.

Autenticação: login por usuário/senha (configurados via AUTH_USERS) com cookie
de sessão assinado. Se AUTH_USERS estiver vazio, o site fica aberto (sem login).
"""

import os
import secrets
from typing import Any

# Carrega .env em desenvolvimento local; em produção (Render) as variáveis
# já vêm do ambiente, então a ausência do .env é ignorada.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

# --- Configuração (ajustável por variáveis de ambiente) ---------------------
EXECUTOR_MODEL = os.environ.get("EXECUTOR_MODEL", "claude-sonnet-4-6")
ADVISOR_MODEL = os.environ.get("ADVISOR_MODEL", "claude-opus-4-8")
ADVISOR_BETA = "advisor-tool-2026-03-01"
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
ADVISOR_MAX_USES = int(os.environ.get("ADVISOR_MAX_USES", "3"))
ADVISOR_MAX_TOKENS = int(os.environ.get("ADVISOR_MAX_TOKENS", "2048"))
# Adicione o contexto do Promob (ou qualquer instrução) via SYSTEM_PROMPT.
SYSTEM_PROMPT = (os.environ.get("SYSTEM_PROMPT") or "").strip()

# --- Autenticação -----------------------------------------------------------
# AUTH_USERS: "usuario1:senha1,usuario2:senha2"  (evite vírgula na senha).
# Se vazio, a autenticação fica DESLIGADA (site aberto).
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", str(60 * 60 * 12)))  # 12h
COOKIE_SECURE = (os.environ.get("COOKIE_SECURE", "true").lower() != "false")
_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="advisor-chat-session")


def _parse_users(raw: str) -> dict[str, str]:
    users: dict[str, str] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        u, p = pair.split(":", 1)
        if u.strip():
            users[u.strip()] = p
    return users


AUTH_USERS = _parse_users(os.environ.get("AUTH_USERS", ""))
AUTH_ENABLED = bool(AUTH_USERS)

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

# Lê ANTHROPIC_API_KEY do ambiente automaticamente.
client = anthropic.Anthropic()

app = FastAPI(title="Casa Sognatto · Advisor Chat")


class ChatRequest(BaseModel):
    # Histórico completo da conversa (a API da Anthropic é stateless).
    messages: list[dict[str, Any]]


class LoginRequest(BaseModel):
    username: str
    password: str


# --- Sessão / autenticação --------------------------------------------------
def current_user(request: Request) -> str | None:
    """Retorna o usuário logado, ou None se não autenticado.

    Quando a autenticação está desligada (AUTH_USERS vazio), todos passam.
    """
    if not AUTH_ENABLED:
        return "anon"
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def require_user(request: Request) -> str:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Não autenticado.")
    return user


# --- Helpers de extração ----------------------------------------------------
def _block_to_dict(block: Any) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return dict(block)


def _text_from_content(content: Any) -> str:
    """Extrai texto de um `content` que pode ser str, dict (bloco único) ou lista.

    No caso do advisor, `advisor_tool_result.content` é um objeto (dict) do tipo
    `advisor_result` com o conselho em `.text`.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content.get("text", "") or ""
    parts = []
    if isinstance(content, list):
        for item in content:
            d = item if isinstance(item, dict) else _block_to_dict(item)
            if isinstance(d, dict) and d.get("text"):
                parts.append(d["text"])
    return "\n".join(parts)


def _extract(content_blocks) -> tuple[list[str], list[dict]]:
    """Separa o texto do executor das consultas ao advisor."""
    text_parts: list[str] = []
    advisor_items: list[dict] = []
    for raw in content_blocks:
        b = _block_to_dict(raw)
        t = b.get("type")
        if t == "text":
            text_parts.append(b.get("text", ""))
        elif t == "server_tool_use" and b.get("name") == "advisor":
            advisor_items.append({"question": b.get("input") or {}, "advice": None})
        elif t in ("advisor_tool_result", "tool_result"):
            advice = _text_from_content(b.get("content"))
            if advisor_items and advisor_items[-1]["advice"] is None:
                advisor_items[-1]["advice"] = advice
            else:
                advisor_items.append({"question": None, "advice": advice})
    return text_parts, advisor_items


def _advisor_usage(iterations: list[dict] | None) -> dict | None:
    """Soma os tokens do advisor a partir do array `usage.iterations`.

    Cada item de `iterations` traz o tipo da chamada interna: `message` é o
    executor e `advisor_message` é o advisor (Opus). Retorna None se o advisor
    não foi consultado.
    """
    inp = out = 0
    found = False
    for it in iterations or []:
        if it.get("type") == "advisor_message":
            inp += it.get("input_tokens") or 0
            out += it.get("output_tokens") or 0
            found = True
    if not found:
        return None
    return {"input_tokens": inp, "output_tokens": out}


def _api_error_detail(e: anthropic.APIStatusError) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or {}
        if err.get("message"):
            return err["message"]
    return getattr(e, "message", str(e))


# --- Rotas de autenticação --------------------------------------------------
@app.post("/api/login")
def login(body: LoginRequest):
    expected = AUTH_USERS.get(body.username)
    if not expected or not secrets.compare_digest(body.password, expected):
        raise HTTPException(401, "Usuário ou senha inválidos.")
    token = _serializer.dumps(body.username)
    resp = JSONResponse({"ok": True, "user": body.username})
    resp.set_cookie(
        "session", token, httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=SESSION_MAX_AGE,
    )
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp


@app.get("/api/me")
def me(request: Request):
    return {"user": current_user(request), "auth_enabled": AUTH_ENABLED}


# --- Rota principal do chat -------------------------------------------------
@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    require_user(request)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY não está configurada no servidor.")

    working = list(req.messages)
    appended: list[dict] = []
    all_text: list[str] = []
    all_advisor: list[dict] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "iterations": []}

    try:
        # A advisor tool roda um loop server-side; em casos longos a API pode
        # devolver stop_reason="pause_turn". Reenviamos para continuar, com um
        # limite de segurança para não rodar indefinidamente.
        for _ in range(6):
            response = client.beta.messages.create(
                model=EXECUTOR_MODEL,
                max_tokens=MAX_TOKENS,
                betas=[ADVISOR_BETA],
                system=SYSTEM_PROMPT or anthropic.NOT_GIVEN,
                tools=[
                    {
                        "type": "advisor_20260301",
                        "name": "advisor",
                        "model": ADVISOR_MODEL,
                        "max_uses": ADVISOR_MAX_USES,
                        "max_tokens": ADVISOR_MAX_TOKENS,
                    }
                ],
                messages=working,
            )

            assistant_msg = {
                "role": "assistant",
                "content": [_block_to_dict(b) for b in response.content],
            }
            appended.append(assistant_msg)
            working.append(assistant_msg)

            texts, advisors = _extract(response.content)
            all_text.extend(texts)
            all_advisor.extend(advisors)

            u = response.usage.model_dump() if response.usage else {}
            usage["input_tokens"] += u.get("input_tokens") or 0
            usage["output_tokens"] += u.get("output_tokens") or 0
            usage["iterations"].extend(u.get("iterations") or [])

            if response.stop_reason != "pause_turn":
                break
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=e.status_code, detail=_api_error_detail(e))
    except anthropic.APIConnectionError:
        raise HTTPException(503, "Não foi possível conectar à API da Anthropic.")

    return {
        # Mensagens do assistente a anexar ao histórico (preserva os blocos
        # advisor_tool_result, exigidos em conversas de múltiplos turnos).
        "append": appended,
        "text": "\n".join(t for t in all_text if t).strip(),
        "advisor": all_advisor,
        "usage": {
            "executor": {
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
            },
            "advisor": _advisor_usage(usage.get("iterations")),
            # Quantidade de consultas ao advisor neste turno.
            "advisor_calls": len([a for a in all_advisor if a.get("advice")]),
        },
    }


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "auth_enabled": AUTH_ENABLED,
    }


# --- Páginas ----------------------------------------------------------------
@app.get("/")
def index(request: Request):
    if current_user(request) is None:
        return FileResponse(os.path.join(STATIC_DIR, "login.html"))
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
