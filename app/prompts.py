"""Biblioteca de prompts para as arquitetas: prompts pré-definidos (padrão da
Casa Sognatto, só o diretor mantém) e prompts pessoais (qualquer membro cria,
todos veem — mesmo modelo de visibilidade das conversas).

Regras de permissão:
- Pré-definidos: leitura livre para qualquer membro logado; criar/editar/
  apagar só o diretor.
- Pessoais: leitura livre para qualquer membro logado (compartilhados, como
  as conversas); criar qualquer um; editar/apagar só quem criou.

Imports de `app.main` ficam dentro das funções (não no topo do arquivo) para
evitar import circular, já que `app.main` inclui este router.
"""

import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/prompts")

# Categorias fixas — mesma nomenclatura de ambientes usada nos renders
# (ver Nomenclatura_Renders_CasaSognatto.csv).
CATEGORIES = [
    "Hall de Entrada", "Living / Sala de Estar", "Sala de TV", "Copa", "Lavabo",
    "Suíte Master", "Closet", "Banheiro Suíte Master", "Quarto 1",
    "Banheiro Quarto 1", "Quarto 2", "Banheiro Quarto 2", "Escritório",
    "Brinquedoteca", "Cozinha", "Gourmet", "Dispensa", "Lavanderia",
    "Quarto Empregada", "Banheiro Empregada", "Outro",
]


class PredefinedPromptBody(BaseModel):
    name: str
    category: str
    content: str


class PersonalPromptCreate(BaseModel):
    name: str
    content: str
    category: str | None = None
    source_predefined_id: str | None = None


class PersonalPromptUpdate(BaseModel):
    name: str
    content: str
    category: str | None = None


def init_prompts_db() -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS predefined_prompts (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    category   TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_prompts (
                    id                   TEXT PRIMARY KEY,
                    name                 TEXT NOT NULL,
                    category             TEXT,
                    content              TEXT NOT NULL,
                    owner_username       TEXT NOT NULL,
                    source_predefined_id TEXT,
                    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_personal_prompts_owner "
                "ON personal_prompts (owner_username, updated_at DESC);"
            )
    except Exception as e:
        print(f"[init_prompts_db] falha: {e}")


# --- Categorias / listagem geral --------------------------------------------
@router.get("/categories")
def list_categories(request: Request):
    from app.main import require_user

    require_user(request)
    return CATEGORIES


@router.get("/predefined")
def list_predefined(request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, category, content FROM predefined_prompts "
            "ORDER BY category, name"
        )
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "category": r[2], "content": r[3]} for r in rows]


@router.get("/personal")
def list_personal(request: Request, owner: str | None = None):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        if owner and owner != "all":
            cur.execute(
                "SELECT id, name, category, content, owner_username FROM personal_prompts "
                "WHERE owner_username = %s ORDER BY updated_at DESC",
                (owner,),
            )
        else:
            cur.execute(
                "SELECT id, name, category, content, owner_username FROM personal_prompts "
                "ORDER BY updated_at DESC"
            )
        rows = cur.fetchall()
    return [
        {"id": r[0], "name": r[1], "category": r[2], "content": r[3], "owner": r[4]}
        for r in rows
    ]


# --- Pré-definidos: só diretor cria/edita/apaga ------------------------------
@router.post("/predefined")
def create_predefined(body: PredefinedPromptBody, request: Request):
    from app.main import _db, _require_db, require_admin

    user = require_admin(request)
    _require_db()
    if body.category not in CATEGORIES:
        raise HTTPException(400, "Categoria inválida.")
    pid = "pp" + secrets.token_hex(8)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO predefined_prompts (id, name, category, content, created_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (pid, body.name.strip()[:200], body.category, body.content, user["username"]),
        )
    return {"id": pid}


@router.put("/predefined/{prompt_id}")
def update_predefined(prompt_id: str, body: PredefinedPromptBody, request: Request):
    from app.main import _db, _require_db, require_admin

    require_admin(request)
    _require_db()
    if body.category not in CATEGORIES:
        raise HTTPException(400, "Categoria inválida.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE predefined_prompts SET name=%s, category=%s, content=%s, updated_at=now() "
            "WHERE id=%s",
            (body.name.strip()[:200], body.category, body.content, prompt_id),
        )
    return {"ok": True}


@router.delete("/predefined/{prompt_id}")
def delete_predefined(prompt_id: str, request: Request):
    from app.main import _db, _require_db, require_admin

    require_admin(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM predefined_prompts WHERE id=%s", (prompt_id,))
    return {"ok": True}


# --- Pessoais: qualquer um cria; só o dono edita/apaga -----------------------
@router.post("/personal")
def create_personal(body: PersonalPromptCreate, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    if body.category is not None and body.category not in CATEGORIES:
        raise HTTPException(400, "Categoria inválida.")
    pid = "up" + secrets.token_hex(8)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO personal_prompts "
            "(id, name, category, content, owner_username, source_predefined_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                pid, body.name.strip()[:200], body.category, body.content,
                user["username"], body.source_predefined_id,
            ),
        )
    return {"id": pid}


def _require_owner(cur, prompt_id: str, username: str) -> None:
    cur.execute("SELECT owner_username FROM personal_prompts WHERE id = %s", (prompt_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Prompt não encontrado.")
    if row[0] != username:
        raise HTTPException(403, "Só quem criou pode alterar este prompt.")


@router.put("/personal/{prompt_id}")
def update_personal(prompt_id: str, body: PersonalPromptUpdate, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    if body.category is not None and body.category not in CATEGORIES:
        raise HTTPException(400, "Categoria inválida.")
    with _db() as conn, conn.cursor() as cur:
        _require_owner(cur, prompt_id, user["username"])
        cur.execute(
            "UPDATE personal_prompts SET name=%s, category=%s, content=%s, updated_at=now() "
            "WHERE id=%s",
            (body.name.strip()[:200], body.category, body.content, prompt_id),
        )
    return {"ok": True}


@router.delete("/personal/{prompt_id}")
def delete_personal(prompt_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        _require_owner(cur, prompt_id, user["username"])
        cur.execute("DELETE FROM personal_prompts WHERE id=%s", (prompt_id,))
    return {"ok": True}
