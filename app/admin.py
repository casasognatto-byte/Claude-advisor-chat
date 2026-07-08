"""Painel do diretor: gestão de usuários, todas as conversas, log de auditoria.

Todas as rotas exigem `require_admin` (papel "diretor"). Os imports de
`app.main` são feitos dentro de cada função (não no topo do arquivo) para
evitar import circular, já que `app.main` inclui este router.
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin")


class UserCreate(BaseModel):
    email: str
    name: str
    role: str = "membro"
    cargo: str | None = None


def _send_invite(username: str, email: str, background_tasks: BackgroundTasks) -> None:
    """Gera token de confirmação e agenda o convite em segundo plano, por
    dois canais: e-mail (SMTP direto do Render pra KingHost não funciona —
    ver memória do projeto, "Errno 101") e chat do ClickUp (funciona por
    HTTPS). Nenhum dos dois pode travar a resposta pro navegador."""
    from app.main import CONFIRM_TTL, _create_auth_token, _public_base_url
    from app.email_send import send_invite_email
    from app.clickup_alert import send_clickup_dm

    token = _create_auth_token(username, "confirm", CONFIRM_TTL)
    link = f"{_public_base_url()}/definir-senha?token={token}"
    background_tasks.add_task(send_invite_email, email, username, link)
    background_tasks.add_task(
        send_clickup_dm, email,
        f"👋 Olá, {username}! Seu acesso à plataforma da Casa Sognatto foi criado. "
        f"Confirme e defina sua senha aqui: {link}\n\nEste link expira em 7 dias.",
    )


@router.get("/users")
def list_users(request: Request):
    from app.main import _db, _require_db, require_admin

    require_admin(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT username, email, role, cargo, active, email_confirmed, created_at "
            "FROM users ORDER BY created_at"
        )
        rows = cur.fetchall()
    return [
        {
            "username": r[0],
            "email": r[1],
            "role": r[2],
            "cargo": r[3],
            "active": r[4],
            "emailConfirmed": r[5],
            "createdAt": r[6].isoformat(),
        }
        for r in rows
    ]


@router.post("/users")
def create_user(body: UserCreate, request: Request, background_tasks: BackgroundTasks):
    from app.main import _db, _require_db, require_admin

    require_admin(request)
    _require_db()
    email = body.email.strip().lower()
    name = body.name.strip()
    if not email or "@" not in email or not name:
        raise HTTPException(400, "E-mail válido e nome são obrigatórios.")
    role = body.role if body.role in ("diretor", "membro") else "membro"
    with _db() as conn, conn.cursor() as cur:
        # E-mail já em uso por outra pessoa?
        cur.execute(
            "SELECT username FROM users WHERE lower(email) = %s AND username <> %s",
            (email, name),
        )
        if cur.fetchone():
            raise HTTPException(409, "Já existe um usuário com este e-mail.")
        cur.execute(
            "INSERT INTO users (username, email, role, cargo, active, email_confirmed) "
            "VALUES (%s, %s, %s, %s, true, false) "
            "ON CONFLICT (username) DO UPDATE SET "
            "email = EXCLUDED.email, role = EXCLUDED.role, cargo = EXCLUDED.cargo, active = true",
            (name, email, role, body.cargo),
        )
    _send_invite(name, email, background_tasks)
    return {"ok": True}


@router.post("/users/{username}/resend-invite")
def resend_invite(username: str, request: Request, background_tasks: BackgroundTasks):
    from app.main import _db, _require_db, require_admin

    require_admin(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE username = %s AND active", (username,))
        row = cur.fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "Usuário não encontrado ou sem e-mail.")
    _send_invite(username, row[0], background_tasks)
    return {"ok": True}


@router.delete("/users/{username}")
def deactivate_user(username: str, request: Request):
    """Desativa a pessoa (soft delete) — nunca apaga, preserva histórico de conversas."""
    from app.main import _db, _require_db, require_admin

    admin = require_admin(request)
    if username == admin["username"]:
        raise HTTPException(400, "Você não pode desativar a própria conta.")
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET active = false WHERE username = %s", (username,))
    return {"ok": True}


@router.get("/conversations")
def all_conversations(request: Request):
    from app.main import _db, _require_db, require_admin

    require_admin(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, owner_username, EXTRACT(EPOCH FROM updated_at) "
            "FROM conversations ORDER BY updated_at DESC"
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "title": r[1], "owner": r[2], "updatedAt": float(r[3])} for r in rows
    ]


class ConversationBulkDelete(BaseModel):
    ids: list[str]


@router.post("/conversations/bulk-delete")
def bulk_delete_conversations(body: ConversationBulkDelete, request: Request):
    from app.main import _db, _log_activity, _require_db, require_admin

    admin = require_admin(request)
    _require_db()
    if not body.ids:
        return {"deleted": 0}
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, title FROM conversations WHERE id = ANY(%s)", (body.ids,))
        rows = cur.fetchall()
        cur.execute("DELETE FROM conversations WHERE id = ANY(%s)", (body.ids,))
    for _cid, title in rows:
        _log_activity(admin["username"], "conversa_deletada", title)
    return {"deleted": len(rows)}


@router.get("/activity-log")
def activity_log(request: Request, q: str | None = None):
    from app.main import _db, _require_db, require_admin

    require_admin(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        if q:
            cur.execute(
                "SELECT event_type, title, username, created_at FROM activity_log "
                "WHERE title ILIKE %s ORDER BY created_at DESC LIMIT 500",
                (f"%{q}%",),
            )
        else:
            cur.execute(
                "SELECT event_type, title, username, created_at FROM activity_log "
                "ORDER BY created_at DESC LIMIT 500"
            )
        rows = cur.fetchall()

    labels = {"conversa_criada": "Conversa criada", "conversa_deletada": "Conversa deletada"}
    lines: list[dict[str, Any]] = []
    for event_type, title, username, created_at in rows:
        label = labels.get(event_type, event_type)
        lines.append(
            {
                "text": f'{created_at.strftime("%d/%m/%Y")}. {label}: "{title}". ({username})',
                "eventType": event_type,
                "title": title,
                "username": username,
                "createdAt": created_at.isoformat(),
            }
        )
    return lines
