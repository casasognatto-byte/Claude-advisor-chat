"""Painel do diretor: gestão de usuários, todas as conversas, log de auditoria.

Todas as rotas exigem `require_admin` (papel "diretor"). Os imports de
`app.main` são feitos dentro de cada função (não no topo do arquivo) para
evitar import circular, já que `app.main` inclui este router.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin")


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "membro"
    cargo: str | None = None


@router.get("/users")
def list_users(request: Request):
    from app.main import _db, _require_db, require_admin

    require_admin(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT username, role, cargo, active, created_at FROM users ORDER BY created_at"
        )
        rows = cur.fetchall()
    return [
        {
            "username": r[0],
            "role": r[1],
            "cargo": r[2],
            "active": r[3],
            "createdAt": r[4].isoformat(),
        }
        for r in rows
    ]


@router.post("/users")
def create_user(body: UserCreate, request: Request):
    from app.main import _db, _require_db, bcrypt_hasher, require_admin

    require_admin(request)
    _require_db()
    if not body.username.strip() or not body.password:
        raise HTTPException(400, "Usuário e senha são obrigatórios.")
    role = body.role if body.role in ("diretor", "membro") else "membro"
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, role, cargo) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (username) DO UPDATE SET "
            "password_hash = EXCLUDED.password_hash, role = EXCLUDED.role, "
            "cargo = EXCLUDED.cargo, active = true",
            (body.username.strip(), bcrypt_hasher.hash(body.password), role, body.cargo),
        )
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
