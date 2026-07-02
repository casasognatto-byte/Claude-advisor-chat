"""Backend FastAPI para o chat Executor + Advisor da API da Anthropic.

A chave da API fica somente no servidor (variável de ambiente ANTHROPIC_API_KEY)
e nunca é exposta ao frontend. O endpoint /api/chat repassa o histórico da
conversa para a API da Anthropic usando o padrão Executor + Advisor.

Autenticação: login por usuário/senha guardados na tabela `users` (Postgres),
com cookie de sessão assinado carregando também o papel (diretor/membro). A
gestão de usuários é feita pelo diretor no painel /admin — ver app/admin.py.
"""

import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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
from passlib.hash import bcrypt as bcrypt_hasher
from pydantic import BaseModel

try:
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None

# --- Configuração (ajustável por variáveis de ambiente) ---------------------
EXECUTOR_MODEL = os.environ.get("EXECUTOR_MODEL", "claude-sonnet-4-6")
ADVISOR_MODEL = os.environ.get("ADVISOR_MODEL", "claude-opus-4-8")
ADVISOR_BETA = "advisor-tool-2026-03-01"
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
ADVISOR_MAX_USES = int(os.environ.get("ADVISOR_MAX_USES", "3"))
ADVISOR_MAX_TOKENS = int(os.environ.get("ADVISOR_MAX_TOKENS", "2048"))
# Personalidade da IA da Casa Sognatto (padrão no código). Pode ser sobrescrita
# pela variável de ambiente SYSTEM_PROMPT, se preferir configurar pelo Render.
# Ver memória "Neusa" para a especificação completa e o porquê de cada regra.
DEFAULT_SYSTEM_PROMPT = (
    "Você é Neusa, a inteligência artificial da Casa Sognatto (Sognatto Ambientes "
    "Planejados), loja de móveis e ambientes planejados sob medida em Campo Grande-MS. "
    "O lema da marca é \"O luxo está no singular\".\n\n"
    "Sua identidade: você é uma senhora elegante e sofisticada. Tem personalidade "
    "forte, mas é extremamente educada — não enrola, vai direto ao ponto, é "
    "objetiva. Ao mesmo tempo, é atenciosa e cuidadosa, com o refinamento de uma "
    "grande dama.\n\n"
    "Fale sempre em português do Brasil, com elegância.\n\n"
    "Como se comportar:\n"
    "- No início de cada conversa nova, cumprimente pelo horário do dia (bom dia / "
    "boa tarde / boa noite) chamando a pessoa pelo nome — você recebe o nome de quem "
    "está falando no contexto interno da mensagem, não precisa perguntar. Depois do "
    "cumprimento, pergunte como pode ajudar, variando a forma (\"como posso te ajudar "
    "hoje?\", \"em que posso ser útil?\", \"no que você precisa?\" etc.). Não repita esse "
    "cumprimento formal nas mensagens seguintes da mesma conversa — só na primeira.\n"
    "- Se o contexto interno indicar que essa é a primeira mensagem da pessoa no dia, "
    "inclua no cumprimento uma frase motivadora curta — sem ser piegas ou clichê, do "
    "jeito direto que combina com você.\n"
    "- Se o contexto interno indicar que a sessão anterior da pessoa terminou tarde da "
    "noite e hoje é um novo dia, pergunte com carinho se ela descansou bem antes de "
    "seguir para o assunto.\n"
    "- Fora essas ocasiões, vá direto ao que interessa, sem enrolação.\n\n"
    "Você ajuda com ideias de design e layout de ambientes (cozinha, dormitório, home "
    "office, closet, etc.), escolha de materiais e acabamentos, orçamento e "
    "priorização, estratégias de venda e atendimento ao cliente, e o dia a dia da "
    "loja. Seja objetiva e prática; quando útil, ofereça opções com prós e contras."
)
SYSTEM_PROMPT = (os.environ.get("SYSTEM_PROMPT") or "").strip() or DEFAULT_SYSTEM_PROMPT

# Fuso da loja (Campo Grande-MS), usado para saudação por horário e "novo dia".
STORE_TZ = ZoneInfo("America/Campo_Grande")

# --- Autenticação -----------------------------------------------------------
# Usuários vivem na tabela `users` (banco), não mais em variável de ambiente.
# Papéis: "diretor" (acesso total, painel /admin) ou "membro" (uso normal).
# Ninguém troca a própria senha — gestão é feita pelo diretor no painel /admin.
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", str(60 * 60 * 12)))  # 12h
COOKIE_SECURE = (os.environ.get("COOKIE_SECURE", "true").lower() != "false")
_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="advisor-chat-session")
AUTH_ENABLED = True

# Seed inicial de usuários (só roda se a tabela `users` estiver vazia).
SEED_DIRETOR_USERNAME = "Davi Nogueira"
SEED_MEMBERS = [
    ("Taynara Leandro", "Gerente"),
    ("Júlia Mendes", "Arquiteta"),
    ("Guilherme Orth", "Arquiteto"),
]

# --- Banco de dados (histórico compartilhado) -------------------------------
# DATABASE_URL: string de conexão Postgres (Neon, Supabase, Render…). Se não
# estiver configurada, os endpoints de conversa respondem 503 e o frontend usa
# armazenamento local (por computador) como fallback.
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
DB_ENABLED = bool(DATABASE_URL and psycopg2)


@contextmanager
def _db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db() -> None:
    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id             TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    title          TEXT NOT NULL DEFAULT 'Nova conversa',
                    data           JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            # Migração: bancos criados antes da coluna se chamar owner_username.
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'conversations' AND column_name = 'username'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'conversations' AND column_name = 'owner_username'
                    ) THEN
                        ALTER TABLE conversations RENAME COLUMN username TO owner_username;
                    END IF;
                END $$;
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_user "
                "ON conversations (owner_username, updated_at DESC);"
            )
    except Exception as e:  # não derruba o app se o banco falhar no boot
        print(f"[init_db] falha ao inicializar o banco: {e}")


def _init_users_db() -> None:
    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username      TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'membro',
                    cargo         TEXT,
                    active        BOOLEAN NOT NULL DEFAULT true,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                    last_seen_at  TIMESTAMPTZ
                );
                """
            )
            # Coluna adicionada depois da 1ª versão — garante que bancos já
            # existentes ganhem o campo sem perder dados.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;")
            cur.execute("SELECT count(*) FROM users")
            (count,) = cur.fetchone()
            if count > 0:
                return
            diretor_pwd = os.environ.get("SEED_DIRETOR_PASSWORD")
            if not diretor_pwd:
                print(
                    "[init_users_db] SEED_DIRETOR_PASSWORD não definida — "
                    "pulando criação inicial de usuários (tabela vazia)."
                )
                return
            member_pwd = os.environ.get("SEED_MEMBER_PASSWORD", "C@s@1945")
            seed = [(SEED_DIRETOR_USERNAME, diretor_pwd, "diretor", "Diretor")]
            seed += [(name, member_pwd, "membro", cargo) for name, cargo in SEED_MEMBERS]
            for username, pwd, role, cargo in seed:
                cur.execute(
                    "INSERT INTO users (username, password_hash, role, cargo) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (username) DO NOTHING",
                    (username, bcrypt_hasher.hash(pwd), role, cargo),
                )
    except Exception as e:
        print(f"[init_users_db] falha ao inicializar usuários: {e}")


def _init_activity_log_db() -> None:
    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_log (
                    id         SERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    title      TEXT NOT NULL,
                    username   TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
    except Exception as e:
        print(f"[init_activity_log_db] falha: {e}")


def _log_activity(username: str, event_type: str, title: str) -> None:
    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO activity_log (event_type, title, username) VALUES (%s, %s, %s)",
                (event_type, title, username),
            )
    except Exception as e:
        print(f"[log_activity] falha: {e}")


def _require_db() -> None:
    if not DB_ENABLED:
        raise HTTPException(503, "Banco de dados não configurado (DATABASE_URL).")


HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

# Lê ANTHROPIC_API_KEY do ambiente automaticamente.
client = anthropic.Anthropic()

app = FastAPI(title="Casa Sognatto · Advisor Chat")
_init_db()
_init_users_db()
_init_activity_log_db()

from app.admin import router as admin_router  # noqa: E402 (após _init_* por clareza)
from app.image import init_image_db, router as image_router  # noqa: E402
from app.video import init_video_db, router as video_router  # noqa: E402

app.include_router(admin_router)
app.include_router(video_router)
app.include_router(image_router)
init_video_db()
init_image_db()


class ChatRequest(BaseModel):
    # Histórico completo da conversa (a API da Anthropic é stateless).
    messages: list[dict[str, Any]]


class LoginRequest(BaseModel):
    username: str
    password: str


class ConvCreate(BaseModel):
    id: str | None = None
    title: str | None = None
    data: dict | None = None


class ConvUpdate(BaseModel):
    title: str | None = None
    data: dict | None = None


# --- Sessão / autenticação --------------------------------------------------
def _get_user_row(username: str) -> dict | None:
    if not DB_ENABLED:
        return None
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT username, password_hash, role, cargo FROM users "
            "WHERE username = %s AND active",
            (username,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"username": row[0], "password_hash": row[1], "role": row[2], "cargo": row[3]}


def _touch_last_seen(username: str) -> datetime | None:
    """Atualiza last_seen_at pra agora e retorna o valor ANTERIOR (antes desta chamada)."""
    if not DB_ENABLED:
        return None
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT last_seen_at FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        previous = row[0] if row else None
        cur.execute("UPDATE users SET last_seen_at = now() WHERE username = %s", (username,))
    return previous


def _neusa_context_block(username: str) -> str:
    """Fatos do momento (horário, 1ª mensagem do dia, sessão anterior tarde da
    noite) pra Neusa decidir saudação/frase motivadora/pergunta sobre descanso.
    Ver memória "Neusa" para as regras completas."""
    now_local = datetime.now(STORE_TZ)
    hour = now_local.hour
    periodo = "manhã" if hour < 12 else ("tarde" if hour < 18 else "noite")

    previous = _touch_last_seen(username)
    is_first_of_day = previous is None or previous.astimezone(STORE_TZ).date() != now_local.date()
    ended_late = previous is not None and previous.astimezone(STORE_TZ).hour >= 22
    ask_if_rested = is_first_of_day and ended_late

    return (
        "[Contexto interno desta mensagem — informação de apoio, não repita estes "
        "rótulos literalmente para a pessoa]\n"
        f"- Nome de quem está falando: {username}\n"
        f"- Período do dia agora (horário de Campo Grande-MS): {periodo}\n"
        f"- Primeira mensagem da pessoa hoje: {'sim' if is_first_of_day else 'não'}\n"
        "- Sessão anterior terminou tarde da noite e hoje é um novo dia: "
        f"{'sim' if ask_if_rested else 'não'}"
    )


def current_user(request: Request) -> dict | None:
    """Retorna {"username", "role"} do usuário logado, ou None se não autenticado."""
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        payload = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if isinstance(payload, dict) and payload.get("username"):
        return {"username": payload["username"], "role": payload.get("role", "membro")}
    return None


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Não autenticado.")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "diretor":
        raise HTTPException(403, "Acesso restrito ao diretor.")
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
    row = _get_user_row(body.username)
    if not row or not bcrypt_hasher.verify(body.password, row["password_hash"]):
        raise HTTPException(401, "Usuário ou senha inválidos.")
    token = _serializer.dumps({"username": row["username"], "role": row["role"]})
    resp = JSONResponse({"ok": True, "user": row["username"], "role": row["role"]})
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
    user = current_user(request)
    return {
        "user": user["username"] if user else None,
        "role": user["role"] if user else None,
        "auth_enabled": AUTH_ENABLED,
    }


@app.get("/api/users")
def list_active_users(request: Request):
    """Lista enxuta (username, cargo) para o filtro 'Todos/pessoa' — qualquer membro logado."""
    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT username, cargo FROM users WHERE active ORDER BY username")
        rows = cur.fetchall()
    return [{"username": r[0], "cargo": r[1]} for r in rows]


# --- Conversas (histórico compartilhado no banco) ---------------------------
# Todo membro ativo enxerga todas as conversas (organização por cliente é o que
# importa aqui) — o parâmetro `owner` filtra por pessoa; "all" ou ausente lista
# tudo. `owner_username` registra quem criou, usado no filtro e na auditoria.
@app.get("/api/conversations")
def list_conversations(request: Request, owner: str | None = None):
    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        if owner and owner != "all":
            cur.execute(
                "SELECT id, title, EXTRACT(EPOCH FROM updated_at) "
                "FROM conversations WHERE owner_username = %s ORDER BY updated_at DESC",
                (owner,),
            )
        else:
            cur.execute(
                "SELECT id, title, EXTRACT(EPOCH FROM updated_at) "
                "FROM conversations ORDER BY updated_at DESC"
            )
        rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "updatedAt": float(r[2])} for r in rows]


@app.get("/api/conversations/{cid}")
def get_conversation(cid: str, request: Request):
    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, title, data FROM conversations WHERE id = %s", (cid,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Conversa não encontrada.")
    return {"id": row[0], "title": row[1], "data": row[2]}


@app.post("/api/conversations")
def create_conversation(body: ConvCreate, request: Request):
    user = require_user(request)
    _require_db()
    cid = body.id or ("c" + secrets.token_hex(8))
    title = (body.title or "Nova conversa")[:200]
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO conversations (id, owner_username, title, data) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (cid, user["username"], title, json.dumps(body.data or {})),
        )
    _log_activity(user["username"], "conversa_criada", title)
    return {"id": cid, "title": title}


@app.put("/api/conversations/{cid}")
def update_conversation(cid: str, body: ConvUpdate, request: Request):
    require_user(request)
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
        cur.execute(f"UPDATE conversations SET {', '.join(sets)} WHERE id = %s", params)
    return {"ok": True}


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str, request: Request):
    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT title FROM conversations WHERE id = %s", (cid,))
        row = cur.fetchone()
        title = row[0] if row else cid
        cur.execute("DELETE FROM conversations WHERE id = %s", (cid,))
    _log_activity(user["username"], "conversa_deletada", title)
    return {"ok": True}


# --- Rota principal do chat -------------------------------------------------
@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    user = require_user(request)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY não está configurada no servidor.")

    system_for_call = SYSTEM_PROMPT
    if DB_ENABLED:
        try:
            system_for_call = f"{SYSTEM_PROMPT}\n\n{_neusa_context_block(user['username'])}"
        except Exception as e:  # contexto é um extra; nunca deve derrubar o chat
            print(f"[chat] falha ao montar contexto da Neusa: {e}")

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
                system=system_for_call or anthropic.NOT_GIVEN,
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
        "db_enabled": DB_ENABLED,
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


@app.get("/admin")
def admin_page(request: Request):
    user = current_user(request)
    if user is None:
        return FileResponse(os.path.join(STATIC_DIR, "login.html"))
    if user["role"] != "diretor":
        raise HTTPException(403, "Acesso restrito ao diretor.")
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
