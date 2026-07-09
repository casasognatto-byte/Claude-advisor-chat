"""Biblioteca de prompts para as arquitetas: prompts pré-definidos (padrão da
Casa Sognatto) e prompts pessoais (compartilhados, como as conversas).

Regras de permissão (atualizado em 2026-07-06 — antes só o diretor mexia nos
pré-definidos; agora qualquer membro logado pode):
- Pré-definidos: leitura, criação, edição e exclusão livres para qualquer
  membro logado.
- Pessoais: leitura livre para qualquer membro logado (compartilhados); criar
  qualquer um; editar/apagar só quem criou.

Rede de segurança pra essa liberação (pedido explícito do Davi, tipo
"ctrl+z"): toda edição guarda o estado anterior em `prompt_versions` (pilha
por prompt) e toda exclusão guarda uma cópia completa em `deleted_prompts`
antes de apagar de verdade — dá pra desfazer uma edição ou restaurar uma
exclusão acidental por qualquer usuário (exclusão/edição de pessoal continua
restrita ao dono; pré-definido é livre pra todos, incluindo desfazer/restaurar).

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
            # Pilha de versões anteriores — uma linha por edição, mais recente
            # primeiro; "desfazer" remove a última linha e reaplica seu conteúdo.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_versions (
                    id                SERIAL PRIMARY KEY,
                    kind              TEXT NOT NULL,
                    prompt_id         TEXT NOT NULL,
                    name              TEXT NOT NULL,
                    category          TEXT,
                    content           TEXT NOT NULL,
                    saved_by          TEXT NOT NULL,
                    saved_at          TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_prompt_versions_lookup "
                "ON prompt_versions (kind, prompt_id, saved_at DESC);"
            )
            # Cópia completa de todo prompt apagado — permite restaurar.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS deleted_prompts (
                    id                   SERIAL PRIMARY KEY,
                    kind                 TEXT NOT NULL,
                    original_id          TEXT NOT NULL,
                    name                 TEXT NOT NULL,
                    category             TEXT,
                    content              TEXT NOT NULL,
                    owner_or_creator     TEXT NOT NULL,
                    source_predefined_id TEXT,
                    deleted_by           TEXT NOT NULL,
                    deleted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
                    restored             BOOLEAN NOT NULL DEFAULT false
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_deleted_prompts_lookup "
                "ON deleted_prompts (kind, restored, deleted_at DESC);"
            )
            # Favoritos por pessoa — viram os chips de atalho no composer
            # (09/07/2026: substituem os 4 chips de texto fixo que existiam
            # antes; cada arquiteta favorita os prompts que quer ter à mão).
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS favorite_prompts (
                    username   TEXT NOT NULL,
                    kind       TEXT NOT NULL,
                    prompt_id  TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (username, kind, prompt_id)
                );
                """
            )
        _seed_default_favorites()
    except Exception as e:
        print(f"[init_prompts_db] falha: {e}")


def _seed_default_favorites() -> None:
    """Migração única: os chips fixos 'Humanizar' e 'Nível do olhar' (só
    esses dois eram frases prontas de verdade — 'Ajustar Luz' e 'Trocar MDF'
    só escreviam um rótulo incompleto e foram descartados, o segundo já é
    coberto melhor pelo seletor de Cores) viram prompts pré-definidos de
    verdade, editáveis e removíveis, favoritados por padrão pra todo mundo já
    ter os mesmos atalhos de antes."""
    from app.main import _db

    seeds = [
        ("Humanizar", "Humanizar a cena: adicionar elementos como livros, plantas e objetos de "
                       "decoração para dar vida ao ambiente."),
        ("Nível do olhar", "Ângulo de câmera: nível do olhar."),
    ]
    with _db() as conn, conn.cursor() as cur:
        seed_ids = []
        for name, content in seeds:
            cur.execute("SELECT id FROM predefined_prompts WHERE name = %s", (name,))
            row = cur.fetchone()
            if row:
                seed_ids.append(row[0])
                continue
            pid = "pp" + secrets.token_hex(8)
            cur.execute(
                "INSERT INTO predefined_prompts (id, name, category, content, created_by) "
                "VALUES (%s, %s, %s, %s, %s)",
                (pid, name, "Outro", content, "sistema"),
            )
            seed_ids.append(pid)

        cur.execute("SELECT username FROM users WHERE active")
        usernames = [r[0] for r in cur.fetchall()]
        for username in usernames:
            for pid in seed_ids:
                cur.execute(
                    "INSERT INTO favorite_prompts (username, kind, prompt_id) VALUES (%s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (username, "predefined", pid),
                )


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


@router.get("/deleted")
def list_deleted(request: Request, kind: str):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    if kind not in ("predefined", "personal"):
        raise HTTPException(400, "kind inválido.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, original_id, name, category, owner_or_creator, deleted_by, deleted_at "
            "FROM deleted_prompts WHERE kind = %s AND restored = false "
            "ORDER BY deleted_at DESC LIMIT 50",
            (kind,),
        )
        rows = cur.fetchall()
    return [
        {
            "log_id": r[0], "original_id": r[1], "name": r[2], "category": r[3],
            "owner_or_creator": r[4], "deleted_by": r[5],
            "deleted_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


@router.post("/deleted/{log_id}/restore")
def restore_deleted(log_id: int, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT kind, original_id, name, category, content, owner_or_creator, "
            "source_predefined_id, restored FROM deleted_prompts WHERE id = %s",
            (log_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Registro de exclusão não encontrado.")
        kind, original_id, name, category, content, owner_or_creator, source_id, restored = row
        if restored:
            raise HTTPException(400, "Este prompt já foi restaurado.")
        if kind == "personal" and owner_or_creator != user["username"]:
            raise HTTPException(403, "Só quem criou pode restaurar este prompt pessoal.")

        table = "predefined_prompts" if kind == "predefined" else "personal_prompts"
        cur.execute(f"SELECT 1 FROM {table} WHERE id = %s", (original_id,))
        new_id = original_id if not cur.fetchone() else (
            ("pp" if kind == "predefined" else "up") + secrets.token_hex(8)
        )
        if kind == "predefined":
            cur.execute(
                "INSERT INTO predefined_prompts (id, name, category, content, created_by) "
                "VALUES (%s, %s, %s, %s, %s)",
                (new_id, name, category, content, owner_or_creator),
            )
        else:
            cur.execute(
                "INSERT INTO personal_prompts "
                "(id, name, category, content, owner_username, source_predefined_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (new_id, name, category, content, owner_or_creator, source_id),
            )
        cur.execute("UPDATE deleted_prompts SET restored = true WHERE id = %s", (log_id,))
    return {"id": new_id}


# --- Favoritos: viram os chips de atalho no composer, por pessoa ------------
class FavoriteBody(BaseModel):
    kind: str
    promptId: str


@router.get("/favorites")
def list_favorites(request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT kind, prompt_id FROM favorite_prompts WHERE username = %s ORDER BY created_at",
            (user["username"],),
        )
        favs = cur.fetchall()
        result = []
        for kind, prompt_id in favs:
            table = "predefined_prompts" if kind == "predefined" else "personal_prompts"
            cur.execute(f"SELECT id, name, content FROM {table} WHERE id = %s", (prompt_id,))
            row = cur.fetchone()
            if row:
                result.append({"kind": kind, "id": row[0], "name": row[1], "content": row[2]})
    return result


@router.post("/favorites")
def add_favorite(body: FavoriteBody, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    if body.kind not in ("predefined", "personal"):
        raise HTTPException(400, "kind inválido.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO favorite_prompts (username, kind, prompt_id) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (user["username"], body.kind, body.promptId),
        )
    return {"ok": True}


@router.delete("/favorites/{kind}/{prompt_id}")
def remove_favorite(kind: str, prompt_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM favorite_prompts WHERE username = %s AND kind = %s AND prompt_id = %s",
            (user["username"], kind, prompt_id),
        )
    return {"ok": True}


def _save_version(cur, kind: str, prompt_id: str, name: str, category, content: str, saved_by: str) -> None:
    cur.execute(
        "INSERT INTO prompt_versions (kind, prompt_id, name, category, content, saved_by) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (kind, prompt_id, name, category, content, saved_by),
    )


def _pop_last_version(cur, kind: str, prompt_id: str):
    cur.execute(
        "SELECT id, name, category, content FROM prompt_versions "
        "WHERE kind = %s AND prompt_id = %s ORDER BY saved_at DESC LIMIT 1",
        (kind, prompt_id),
    )
    row = cur.fetchone()
    if not row:
        return None
    cur.execute("DELETE FROM prompt_versions WHERE id = %s", (row[0],))
    return {"name": row[1], "category": row[2], "content": row[3]}


# --- Pré-definidos: qualquer membro logado cria/edita/apaga ------------------
@router.post("/predefined")
def create_predefined(body: PredefinedPromptBody, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
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
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    if body.category not in CATEGORIES:
        raise HTTPException(400, "Categoria inválida.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, category, content FROM predefined_prompts WHERE id = %s", (prompt_id,)
        )
        current = cur.fetchone()
        if not current:
            raise HTTPException(404, "Prompt não encontrado.")
        _save_version(cur, "predefined", prompt_id, current[0], current[1], current[2], user["username"])
        cur.execute(
            "UPDATE predefined_prompts SET name=%s, category=%s, content=%s, updated_at=now() "
            "WHERE id=%s",
            (body.name.strip()[:200], body.category, body.content, prompt_id),
        )
    return {"ok": True}


@router.post("/predefined/{prompt_id}/undo")
def undo_predefined(prompt_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM predefined_prompts WHERE id = %s", (prompt_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Prompt não encontrado.")
        prev = _pop_last_version(cur, "predefined", prompt_id)
        if not prev:
            raise HTTPException(404, "Não há edição anterior para desfazer.")
        cur.execute(
            "UPDATE predefined_prompts SET name=%s, category=%s, content=%s, updated_at=now() "
            "WHERE id=%s",
            (prev["name"], prev["category"], prev["content"], prompt_id),
        )
    return {"id": prompt_id, "name": prev["name"], "category": prev["category"], "content": prev["content"]}


@router.delete("/predefined/{prompt_id}")
def delete_predefined(prompt_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, category, content, created_by FROM predefined_prompts WHERE id = %s",
            (prompt_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Prompt não encontrado.")
        cur.execute(
            "INSERT INTO deleted_prompts "
            "(kind, original_id, name, category, content, owner_or_creator, deleted_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("predefined", prompt_id, row[0], row[1], row[2], row[3], user["username"]),
        )
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
            "SELECT name, category, content FROM personal_prompts WHERE id = %s", (prompt_id,)
        )
        current = cur.fetchone()
        _save_version(cur, "personal", prompt_id, current[0], current[1], current[2], user["username"])
        cur.execute(
            "UPDATE personal_prompts SET name=%s, category=%s, content=%s, updated_at=now() "
            "WHERE id=%s",
            (body.name.strip()[:200], body.category, body.content, prompt_id),
        )
    return {"ok": True}


@router.post("/personal/{prompt_id}/undo")
def undo_personal(prompt_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        _require_owner(cur, prompt_id, user["username"])
        prev = _pop_last_version(cur, "personal", prompt_id)
        if not prev:
            raise HTTPException(404, "Não há edição anterior para desfazer.")
        cur.execute(
            "UPDATE personal_prompts SET name=%s, category=%s, content=%s, updated_at=now() "
            "WHERE id=%s",
            (prev["name"], prev["category"], prev["content"], prompt_id),
        )
    return {"id": prompt_id, "name": prev["name"], "category": prev["category"], "content": prev["content"]}


@router.delete("/personal/{prompt_id}")
def delete_personal(prompt_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        _require_owner(cur, prompt_id, user["username"])
        cur.execute(
            "SELECT name, category, content, owner_username, source_predefined_id "
            "FROM personal_prompts WHERE id = %s",
            (prompt_id,),
        )
        row = cur.fetchone()
        cur.execute(
            "INSERT INTO deleted_prompts "
            "(kind, original_id, name, category, content, owner_or_creator, source_predefined_id, deleted_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            ("personal", prompt_id, row[0], row[1], row[2], row[3], row[4], user["username"]),
        )
        cur.execute("DELETE FROM personal_prompts WHERE id=%s", (prompt_id,))
    return {"ok": True}
