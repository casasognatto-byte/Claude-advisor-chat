"""Biblioteca de Apresentações — Fase 4: o Sogno como arquiteta auxiliar.

Fluxo: a arquiteta cria um "projeto de cliente", sobe as imagens exportadas
do Promob (em qualquer ordem) e o sistema classifica cada uma por ambiente
(visão computacional) e reordena na sequência natural de um passeio pela
casa. As decisões de estilo por imagem (cor de MDF, iluminação, decoração)
ficam salvas aqui, guiadas por uma entrevista à parte (não implementada
neste módulo) e alimentadas por uma biblioteca de padrões técnicos
recorrentes (ex: "cristaleira com lateral de vidro -> luz ao fundo").

A apresentação estática é um deck padrão: um número fixo de slides
institucionais (loja + indústria/fornecedores, sempre os mesmos, editáveis
pela equipe) seguido pelos slides de ambientes do cliente, na ordem já
calculada. Sem Canva/Templated — montado nativamente aqui, servido como uma
lista ordenada de imagens que o frontend usa pra apresentação em tela cheia
ou exportação.

Mesma regra de sempre: imports de `app.main` ficam dentro das funções para
evitar import circular. Arquivos ficam em `app.storage` (R2 ou disco local).
"""

import asyncio
import io
import json
import secrets

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/presentations")

GENERIC_CLASSIFY_ERROR = "outro"

# Ordem natural de um passeio pela casa — usada tanto pra ordenar as imagens
# quanto como lista de opções pra classificação automática. Adicionar um
# ambiente novo aqui já reordena tudo automaticamente (não precisa migração).
ROOM_ORDER = [
    "fachada",
    "hall_entrada",
    "sala_estar",
    "sala_jantar",
    "lavabo",
    "escritorio",
    "cozinha",
    "area_servico",
    "area_gourmet",
    "varanda",
    "suite_master",
    "closet",
    "banheiro_suite",
    "quarto",
    "banheiro_social",
    "outro",
]

ROOM_LABELS = {
    "fachada": "Fachada",
    "hall_entrada": "Hall de entrada",
    "sala_estar": "Sala de estar",
    "sala_jantar": "Sala de jantar",
    "lavabo": "Lavabo",
    "escritorio": "Escritório",
    "cozinha": "Cozinha",
    "area_servico": "Área de serviço",
    "area_gourmet": "Área gourmet",
    "varanda": "Varanda",
    "suite_master": "Suíte master",
    "closet": "Closet / vestidor",
    "banheiro_suite": "Banheiro da suíte",
    "quarto": "Quarto",
    "banheiro_social": "Banheiro social",
    "outro": "Outro ambiente",
}

_MIME_OK = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_PDF_MIME = "application/pdf"


def _rasterize_pdf(data: bytes, dpi: int = 120) -> list[bytes]:
    """Abertura/Fechamento também podem ser enviados como PDF (ex: deck
    institucional já pronto da equipe) — cada página vira um slide (PNG),
    na mesma ordem do PDF, reaproveitando o modelo de slides já existente."""
    import fitz  # PyMuPDF

    pages = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages


# --- Banco de dados ----------------------------------------------------------
def init_presentations_db() -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS client_projects (
                    id          TEXT PRIMARY KEY,
                    client_name TEXT NOT NULL,
                    created_by  TEXT NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            # Modelos de apresentação (08/07/2026) — cada projeto de cliente
            # escolhe um modelo (Simonetto, Stimmo, por equipe etc); o deck
            # final fica sempre abertura do modelo -> imagens do cliente ->
            # fechamento do modelo. template_id fica nullable: projeto sem
            # modelo escolhido cai no primeiro modelo existente (ver get_deck).
            cur.execute("ALTER TABLE client_projects ADD COLUMN IF NOT EXISTS template_id TEXT;")
            # Token pro link público animado — só existe depois que alguém
            # gera o link pela primeira vez (nullable até lá).
            cur.execute("ALTER TABLE client_projects ADD COLUMN IF NOT EXISTS share_token TEXT;")
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_client_projects_share_token "
                "ON client_projects (share_token) WHERE share_token IS NOT NULL;"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS project_images (
                    id           TEXT PRIMARY KEY,
                    project_id   TEXT NOT NULL REFERENCES client_projects(id) ON DELETE CASCADE,
                    storage_key  TEXT NOT NULL,
                    mime         TEXT NOT NULL,
                    room_type    TEXT NOT NULL DEFAULT 'outro',
                    style        JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_images_project "
                "ON project_images (project_id);"
            )
            # Contador de "usar como base" — biblioteca de referências entre
            # projetos anteriores (ver memory/project_neusa_apresentacoes_arquitetas.md).
            cur.execute(
                "ALTER TABLE project_images ADD COLUMN IF NOT EXISTS "
                "usage_count INTEGER NOT NULL DEFAULT 0;"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_images_room_usage "
                "ON project_images (room_type, usage_count DESC);"
            )
            # Pastas de ambiente dentro de um cliente (09/07/2026) — a arquiteta
            # cria os ambientes da casa como subpastas, renderiza dentro de cada
            # uma pelo chat principal e depois escolhe a ordem final aqui em
            # Apresentações. Projetos antigos (sem nenhuma linha aqui) continuam
            # usando a ordenação por room_type de sempre — ver _room_position_sql
            # e get_deck/get_deck_pdf.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS client_environments (
                    id          TEXT PRIMARY KEY,
                    project_id  TEXT NOT NULL REFERENCES client_projects(id) ON DELETE CASCADE,
                    name        TEXT NOT NULL,
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    created_by  TEXT NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_client_environments_project "
                "ON client_environments (project_id, sort_order);"
            )
            cur.execute(
                "ALTER TABLE project_images ADD COLUMN IF NOT EXISTS environment_id "
                "TEXT REFERENCES client_environments(id) ON DELETE SET NULL;"
            )
            cur.execute(
                "ALTER TABLE project_images ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_images_environment "
                "ON project_images (environment_id, sort_order);"
            )
            # `conversations` já existe (criada em app.main._init_db, que roda
            # antes deste init) — a coluna entra aqui porque só agora
            # client_environments existe pra FK apontar.
            cur.execute(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS environment_id "
                "TEXT REFERENCES client_environments(id) ON DELETE SET NULL;"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_environment "
                "ON conversations (environment_id);"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS style_patterns (
                    id             SERIAL PRIMARY KEY,
                    furniture_type TEXT NOT NULL,
                    attribute      TEXT NOT NULL DEFAULT '',
                    recommendation TEXT NOT NULL,
                    created_by     TEXT NOT NULL,
                    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS style_pattern_versions (
                    id             SERIAL PRIMARY KEY,
                    pattern_id     INTEGER NOT NULL,
                    furniture_type TEXT NOT NULL,
                    attribute      TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    saved_at       TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS deleted_style_patterns (
                    id             SERIAL PRIMARY KEY,
                    furniture_type TEXT NOT NULL,
                    attribute      TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    created_by     TEXT NOT NULL,
                    deleted_by     TEXT NOT NULL,
                    deleted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                    restored       BOOLEAN NOT NULL DEFAULT false
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS presentation_templates (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS institutional_slides (
                    id          TEXT PRIMARY KEY,
                    storage_key TEXT NOT NULL,
                    mime        TEXT NOT NULL,
                    caption     TEXT NOT NULL DEFAULT '',
                    sort_order  INTEGER NOT NULL,
                    created_by  TEXT NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            # Modelos de apresentação: cada slide pertence a um modelo e é
            # marcado como abertura (padrão) ou fechamento. Slides antigos
            # (de antes dos modelos existirem) migram pra um modelo "Geral"
            # criado automaticamente, sem perder nada já cadastrado.
            cur.execute("ALTER TABLE institutional_slides ADD COLUMN IF NOT EXISTS template_id TEXT;")
            cur.execute("ALTER TABLE institutional_slides ADD COLUMN IF NOT EXISTS is_closing BOOLEAN NOT NULL DEFAULT false;")
            cur.execute("SELECT COUNT(*) FROM institutional_slides WHERE template_id IS NULL")
            orphan_count = cur.fetchone()[0]
            if orphan_count:
                cur.execute("SELECT id FROM presentation_templates ORDER BY created_at LIMIT 1")
                default_row = cur.fetchone()
                if default_row:
                    default_template_id = default_row[0]
                else:
                    default_template_id = "tpl" + secrets.token_hex(6)
                    cur.execute(
                        "INSERT INTO presentation_templates (id, name, created_by) VALUES (%s, %s, %s)",
                        (default_template_id, "Geral", "sistema"),
                    )
                cur.execute(
                    "UPDATE institutional_slides SET template_id = %s WHERE template_id IS NULL",
                    (default_template_id,),
                )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_institutional_slides_template "
                "ON institutional_slides (template_id, is_closing, sort_order);"
            )
    except Exception as e:
        print(f"[init_presentations_db] falha: {e}")


# --- Classificação automática de ambiente ------------------------------------
def _classify_room(image_bytes: bytes, mime: str) -> str:
    """Pergunta ao Claude qual ambiente a imagem mostra. Nunca derruba o
    upload se falhar — cai em 'outro' e a arquiteta reclassifica na mão."""
    import base64

    from app.main import EXECUTOR_MODEL, client

    options = ", ".join(ROOM_ORDER)
    try:
        resp = client.messages.create(
            model=EXECUTOR_MODEL,
            max_tokens=20,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(image_bytes).decode("ascii")},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Esta é uma renderização 3D (exportada do Promob) de um ambiente "
                                "residencial. Responda com APENAS uma palavra, exatamente uma "
                                f"destas opções, a que melhor descreve o ambiente: {options}. "
                                "Se não conseguir identificar com confiança, responda 'outro'."
                            ),
                        },
                    ],
                }
            ],
        )
        answer = resp.content[0].text.strip().lower()
        return answer if answer in ROOM_ORDER else "outro"
    except Exception as e:
        print(f"[presentations] falha ao classificar ambiente: {e}")
        return "outro"


def _room_position_sql() -> str:
    """Monta um CASE WHEN pra ordenar por ROOM_ORDER — evita depender de
    array_position com parâmetro (menos legível) e deixa a query auto-contida."""
    whens = " ".join(f"WHEN '{room}' THEN {i}" for i, room in enumerate(ROOM_ORDER))
    return f"CASE room_type {whens} ELSE {len(ROOM_ORDER)} END"


def _ordered_images_sql(select_cols: str) -> str:
    """Query completa (só falta o parâmetro project_id) que lista as imagens
    de um projeto na ordem "natural" da tela: se o projeto já tem ambientes
    (client_environments), ordena por ambiente arrastado + posição arrastada
    dentro dele. Projeto sem nenhum ambiente cadastrado (todo projeto antigo,
    hoje) cai no critério de sempre (room_type fixo + data) — LEFT JOIN faz
    `ce.*` virar NULL nesse caso, sem quebrar nada já existente."""
    return (
        f"SELECT {select_cols} FROM project_images "
        "LEFT JOIN client_environments ce ON ce.id = project_images.environment_id "
        "WHERE project_images.project_id = %s "
        "ORDER BY (project_images.environment_id IS NULL), ce.sort_order, "
        f"project_images.sort_order, {_room_position_sql()}, project_images.created_at"
    )


# --- Projetos de cliente ------------------------------------------------------
class ProjectCreate(BaseModel):
    client_name: str


@router.post("")
def create_project(body: ProjectCreate, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    name = (body.client_name or "").strip()
    if not name:
        raise HTTPException(400, "Nome do cliente é obrigatório.")
    project_id = "p" + secrets.token_hex(8)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO client_projects (id, client_name, created_by) VALUES (%s, %s, %s)",
            (project_id, name, user["username"]),
        )
    return {"id": project_id, "clientName": name}


@router.get("")
def list_projects(request: Request):
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT p.id, p.client_name, p.created_by, EXTRACT(EPOCH FROM p.created_at), "
            "COUNT(i.id) FROM client_projects p LEFT JOIN project_images i ON i.project_id = p.id "
            "GROUP BY p.id ORDER BY p.created_at DESC"
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "clientName": r[1], "createdBy": r[2], "createdAt": float(r[3]), "imageCount": r[4]}
        for r in rows
    ]


# --- Modelos de apresentação (abertura + fechamento) ------------------------
# Cada modelo (Simonetto, Stimmo, por equipe etc.) tem slides de abertura e
# slides de fechamento. Um projeto de cliente escolhe um modelo; o deck final
# é sempre abertura do modelo -> imagens do cliente -> fechamento do modelo
# (ver get_deck). Editável por qualquer membro logado, como o resto da
# Biblioteca de Apresentações.
#
# Registradas ANTES de /{project_id} (abaixo): rotas de um único segmento
# como "/templates" seriam capturadas pelo catch-all "/{project_id}" se
# viessem depois, já que o FastAPI/Starlette casa rotas na ordem de
# registro (bug real encontrado e corrigido aqui: GET /templates devolvia
# 404 "Projeto não encontrado").
@router.get("/templates")
def list_templates(request: Request):
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT t.id, t.name, t.created_by, EXTRACT(EPOCH FROM t.created_at), COUNT(s.id) "
            "FROM presentation_templates t LEFT JOIN institutional_slides s ON s.template_id = t.id "
            "GROUP BY t.id ORDER BY t.created_at"
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "name": r[1], "createdBy": r[2], "createdAt": float(r[3]), "slideCount": r[4]}
        for r in rows
    ]


class TemplateCreate(BaseModel):
    name: str


@router.post("/templates")
def create_template(body: TemplateCreate, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Nome do modelo não pode ser vazio.")
    template_id = "tpl" + secrets.token_hex(6)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO presentation_templates (id, name, created_by) VALUES (%s, %s, %s)",
            (template_id, name, user["username"]),
        )
    return {"id": template_id, "name": name}


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, request: Request):
    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT storage_key FROM institutional_slides WHERE template_id = %s", (template_id,))
        slide_keys = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM presentation_templates WHERE id = %s RETURNING id", (template_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Modelo não encontrado.")
        cur.execute("DELETE FROM institutional_slides WHERE template_id = %s", (template_id,))
        cur.execute("UPDATE client_projects SET template_id = NULL WHERE template_id = %s", (template_id,))
    for key in slide_keys:
        storage.delete(key)
    return {"ok": True}


@router.get("/templates/{template_id}/slides")
def list_template_slides(template_id: str, request: Request):
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, caption, sort_order, is_closing, created_by, EXTRACT(EPOCH FROM created_at) "
            "FROM institutional_slides WHERE template_id = %s ORDER BY is_closing, sort_order",
            (template_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0], "caption": r[1], "sortOrder": r[2], "isClosing": r[3],
            "createdBy": r[4], "createdAt": float(r[5]),
        }
        for r in rows
    ]


@router.post("/templates/{template_id}/slides")
async def add_template_slide(
    template_id: str, request: Request, image: UploadFile = File(...),
    caption: str = Form(""), is_closing: bool = Form(False), replace: bool = Form(False),
):
    from app import storage
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    mime = image.content_type or "image/jpeg"
    file_bytes = await image.read()
    if not file_bytes:
        raise HTTPException(400, "Arquivo vazio ou não enviado.")

    if mime == _PDF_MIME:
        try:
            pages = await asyncio.to_thread(_rasterize_pdf, file_bytes)
        except Exception:
            raise HTTPException(400, "Não foi possível ler o PDF.")
        if not pages:
            raise HTTPException(400, "PDF sem páginas.")
        page_files = [(p, "image/png") for p in pages]
    elif mime in _MIME_OK:
        page_files = [(file_bytes, mime)]
    else:
        raise HTTPException(400, "Formato não suportado (use imagem ou PDF).")

    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM presentation_templates WHERE id = %s", (template_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Modelo não encontrado.")

    if replace:
        # "Substituir" — apaga todo o grupo atual (abertura OU fechamento,
        # nunca os dois) antes de inserir os novos slides, pra não ficar com
        # o conjunto antigo e o novo misturados.
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT storage_key FROM institutional_slides WHERE template_id = %s AND is_closing = %s",
                (template_id, is_closing),
            )
            old_keys = [r[0] for r in cur.fetchall()]
            cur.execute(
                "DELETE FROM institutional_slides WHERE template_id = %s AND is_closing = %s",
                (template_id, is_closing),
            )
        for key in old_keys:
            storage.delete(key)

    slide_ids = ["inst" + secrets.token_hex(8) for _ in page_files]
    storage_keys = []
    for slide_id, (_data, page_mime) in zip(slide_ids, page_files):
        ext = page_mime.split("/", 1)[1]
        storage_keys.append(f"institutional/{slide_id}.{ext}")

    sem = asyncio.Semaphore(6)

    async def _put(key: str, data: bytes, put_mime: str):
        async with sem:
            await asyncio.to_thread(storage.put, key, data, put_mime)

    await asyncio.gather(*(
        _put(key, data, put_mime)
        for key, (data, put_mime) in zip(storage_keys, page_files)
    ))

    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM institutional_slides "
            "WHERE template_id = %s AND is_closing = %s",
            (template_id, is_closing),
        )
        next_order = cur.fetchone()[0]
        for i, (slide_id, storage_key, (_data, page_mime)) in enumerate(zip(slide_ids, storage_keys, page_files)):
            slide_caption = caption if len(page_files) == 1 else ""
            cur.execute(
                "INSERT INTO institutional_slides "
                "(id, storage_key, mime, caption, sort_order, is_closing, created_by, template_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (slide_id, storage_key, page_mime, slide_caption, next_order + i, is_closing, user["username"], template_id),
            )
    return {"ids": slide_ids, "count": len(slide_ids), "isClosing": is_closing}


@router.get("/templates/{template_id}/slides/{slide_id}/file")
def get_template_slide_file(template_id: str, slide_id: str, request: Request):
    from fastapi.responses import Response

    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT storage_key, mime FROM institutional_slides WHERE id = %s AND template_id = %s",
            (slide_id, template_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Slide não encontrado.")
    data = storage.get(row[0])
    if data is None:
        raise HTTPException(404, "Arquivo não disponível.")
    return Response(content=data, media_type=row[1])


class SlideUpdate(BaseModel):
    caption: str | None = None
    isClosing: bool | None = None


@router.put("/templates/{template_id}/slides/{slide_id}")
def update_template_slide(template_id: str, slide_id: str, body: SlideUpdate, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT caption, is_closing FROM institutional_slides WHERE id = %s AND template_id = %s",
            (slide_id, template_id),
        )
        current = cur.fetchone()
        if not current:
            raise HTTPException(404, "Slide não encontrado.")
        caption = body.caption if body.caption is not None else current[0]
        is_closing = body.isClosing if body.isClosing is not None else current[1]
        cur.execute(
            "UPDATE institutional_slides SET caption = %s, is_closing = %s WHERE id = %s",
            (caption, is_closing, slide_id),
        )
    return {"ok": True}


@router.delete("/templates/{template_id}/slides/{slide_id}")
def delete_template_slide(template_id: str, slide_id: str, request: Request):
    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT storage_key FROM institutional_slides WHERE id = %s AND template_id = %s",
            (slide_id, template_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Slide não encontrado.")
        cur.execute("DELETE FROM institutional_slides WHERE id = %s", (slide_id,))
    storage.delete(row[0])
    return {"ok": True}


class SlideReorder(BaseModel):
    orderedIds: list[str]


@router.post("/templates/{template_id}/slides/reorder")
def reorder_template_slides(template_id: str, body: SlideReorder, request: Request):
    """Reordena dentro do mesmo grupo (abertura ou fechamento) — o frontend
    manda uma lista por vez, já que os dois grupos têm contadores de ordem
    independentes."""
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        for position, slide_id in enumerate(body.orderedIds):
            cur.execute(
                "UPDATE institutional_slides SET sort_order = %s WHERE id = %s AND template_id = %s",
                (position, slide_id, template_id),
            )
    return {"ok": True}


# --- Ambientes (subpastas dentro de um cliente) ------------------------------
# A arquiteta cria os ambientes da casa como subpastas de um cliente,
# renderiza dentro de cada uma pelo chat principal (1 ambiente = 1 conversa,
# ver get_environment_conversation) e depois escolhe a ordem final aqui em
# Apresentações. Ver memory/project_neusa_apresentacoes_arquitetas.md.
# Registradas ANTES de /{project_id} pelo mesmo motivo do bloco de /templates
# acima: "/tree" tem 1 segmento só, seria capturado pelo catch-all se viesse
# depois.
class EnvironmentCreate(BaseModel):
    name: str


class EnvironmentUpdate(BaseModel):
    name: str


class EnvironmentReorder(BaseModel):
    orderedIds: list[str]


@router.get("/tree")
def get_projects_tree(request: Request):
    """Clientes + ambientes, pra alimentar a árvore da sidebar do chat
    principal sem N+1 requests (1 chamada só)."""
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, client_name FROM client_projects ORDER BY created_at DESC")
        projects = cur.fetchall()
        cur.execute(
            "SELECT id, project_id, name, sort_order FROM client_environments "
            "ORDER BY project_id, sort_order"
        )
        envs_by_project: dict[str, list[dict]] = {}
        for env_id, project_id, name, sort_order in cur.fetchall():
            envs_by_project.setdefault(project_id, []).append(
                {"id": env_id, "name": name, "sortOrder": sort_order}
            )
    return [
        {"id": p[0], "clientName": p[1], "environments": envs_by_project.get(p[0], [])}
        for p in projects
    ]


@router.get("/{project_id}/environments")
def list_environments(project_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, sort_order FROM client_environments "
            "WHERE project_id = %s ORDER BY sort_order",
            (project_id,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "sortOrder": r[2]} for r in rows]


@router.post("/{project_id}/environments")
def create_environment(project_id: str, body: EnvironmentCreate, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Nome do ambiente é obrigatório.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM client_projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Projeto não encontrado.")
        cur.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM client_environments WHERE project_id = %s",
            (project_id,),
        )
        next_order = cur.fetchone()[0]
        env_id = "env" + secrets.token_hex(8)
        cur.execute(
            "INSERT INTO client_environments (id, project_id, name, sort_order, created_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (env_id, project_id, name, next_order, user["username"]),
        )
    return {"id": env_id, "name": name, "sortOrder": next_order}


@router.put("/{project_id}/environments/{env_id}")
def rename_environment(project_id: str, env_id: str, body: EnvironmentUpdate, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Nome do ambiente é obrigatório.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE client_environments SET name = %s WHERE id = %s AND project_id = %s RETURNING id",
            (name, env_id, project_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Ambiente não encontrado.")
    return {"ok": True}


@router.delete("/{project_id}/environments/{env_id}")
def delete_environment(project_id: str, env_id: str, request: Request):
    """Apagar o ambiente NÃO apaga as imagens/conversas ligadas a ele — a FK
    é ON DELETE SET NULL, então elas só "soltam" da pasta (viram órfãs, como
    já era o comportamento padrão antes desta feature existir)."""
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM client_environments WHERE id = %s AND project_id = %s RETURNING id",
            (env_id, project_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Ambiente não encontrado.")
    return {"ok": True}


@router.post("/{project_id}/environments/reorder")
def reorder_environments(project_id: str, body: EnvironmentReorder, request: Request):
    """Mesmo padrão de reorder_template_slides (linha ~623): o frontend manda
    a lista inteira já na nova ordem, o servidor reescreve sort_order."""
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        for position, env_id in enumerate(body.orderedIds):
            cur.execute(
                "UPDATE client_environments SET sort_order = %s WHERE id = %s AND project_id = %s",
                (position, env_id, project_id),
            )
    return {"ok": True}


@router.post("/environments/{env_id}/images/reorder")
def reorder_environment_images(env_id: str, body: EnvironmentReorder, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        for position, image_id in enumerate(body.orderedIds):
            cur.execute(
                "UPDATE project_images SET sort_order = %s WHERE id = %s AND environment_id = %s",
                (position, image_id, env_id),
            )
    return {"ok": True}


@router.get("/environments/{env_id}/conversation")
def get_environment_conversation(env_id: str, request: Request):
    """1 ambiente = 1 conversa — devolve a mais recente já ligada a este
    ambiente, criando a primeira se ainda não existir. Resolvido no servidor
    (não no frontend) pra dois cliques rápidos não criarem duas conversas."""
    from app.main import _db, _log_activity, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM client_environments WHERE id = %s", (env_id,))
        env = cur.fetchone()
        if not env:
            raise HTTPException(404, "Ambiente não encontrado.")
        cur.execute(
            "SELECT id, title FROM conversations WHERE environment_id = %s "
            "ORDER BY updated_at DESC LIMIT 1",
            (env_id,),
        )
        conv = cur.fetchone()
        if conv:
            return {"id": conv[0], "title": conv[1]}
        conv_id = "c" + secrets.token_hex(8)
        cur.execute(
            "INSERT INTO conversations (id, owner_username, title, environment_id) "
            "VALUES (%s, %s, %s, %s)",
            (conv_id, user["username"], env[0], env_id),
        )
    _log_activity(user["username"], "conversa_criada", env[0])
    return {"id": conv_id, "title": env[0]}


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, client_name, created_by, EXTRACT(EPOCH FROM created_at) "
            "FROM client_projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Projeto não encontrado.")
        cur.execute(
            f"SELECT id, room_type, style, EXTRACT(EPOCH FROM created_at), environment_id, sort_order "
            f"FROM project_images WHERE project_id = %s "
            f"ORDER BY (environment_id IS NULL), environment_id, sort_order, {_room_position_sql()}, created_at",
            (project_id,),
        )
        images = [
            {
                "id": r[0],
                "roomType": r[1],
                "roomLabel": ROOM_LABELS.get(r[1], r[1]),
                "style": r[2],
                "createdAt": float(r[3]),
                "environmentId": r[4],
                "sortOrder": r[5],
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            "SELECT id, name, sort_order FROM client_environments "
            "WHERE project_id = %s ORDER BY sort_order",
            (project_id,),
        )
        environments = [{"id": e[0], "name": e[1], "sortOrder": e[2]} for e in cur.fetchall()]
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT template_id, share_token FROM client_projects WHERE id = %s", (project_id,))
        extra = cur.fetchone()
    return {
        "id": row[0],
        "clientName": row[1],
        "createdBy": row[2],
        "createdAt": float(row[3]),
        "images": images,
        "environments": environments,
        "templateId": extra[0] if extra else None,
        "shareToken": extra[1] if extra else None,
    }


class ProjectUpdate(BaseModel):
    templateId: str | None = None


@router.put("/{project_id}")
def update_project(project_id: str, body: ProjectUpdate, request: Request):
    """Por enquanto só troca o modelo de apresentação atribuído ao projeto —
    ver `presentation_templates`."""
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE client_projects SET template_id = %s WHERE id = %s RETURNING id",
            (body.templateId, project_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Projeto não encontrado.")
    return {"ok": True}


@router.delete("/{project_id}")
def delete_project(project_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT storage_key FROM project_images WHERE project_id = %s", (project_id,))
        keys = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM client_projects WHERE id = %s", (project_id,))
    from app import storage

    for key in keys:
        storage.delete(key)
    return {"ok": True}


# --- Biblioteca de referências entre projetos anteriores ---------------------
# Pedido do Davi (2026-07-07): cada arquiteta lembra dos próprios projetos
# passados ("fiz uma cozinha assim pra fulana") e quer usar isso como
# referência de estilo pra uma imagem nova, sem vasculhar manualmente todos
# os projetos. Busca por ambiente (filtro mais útil — lembrança visual vem
# primeiro pelo tipo de ambiente) e opcionalmente por nome de cliente.
# Rotas com 2+ segmentos (ver nota em init_presentations_db/módulo) pra não
# colidir com o catch-all GET /{project_id}.
@router.get("/references/search")
def search_references(
    request: Request, room_type: str | None = None, client: str | None = None,
    exclude_project_id: str | None = None,
):
    """"Referências de projetos anteriores" — por definição, não deve incluir
    o próprio projeto que a arquiteta está editando no momento (senão as
    imagens que ela acabou de subir aparecem como "referência" de si mesmas)."""
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    conditions = []
    params: list = []
    if room_type:
        conditions.append("i.room_type = %s")
        params.append(room_type)
    if client:
        conditions.append("p.client_name ILIKE %s")
        params.append(f"%{client}%")
    if exclude_project_id:
        conditions.append("i.project_id != %s")
        params.append(exclude_project_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT i.id, i.project_id, p.client_name, i.room_type, i.style, i.usage_count "
            f"FROM project_images i JOIN client_projects p ON p.id = i.project_id "
            f"{where} ORDER BY i.usage_count DESC, i.created_at DESC LIMIT 60",
            params,
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "projectId": r[1],
            "clientName": r[2],
            "roomType": r[3],
            "roomLabel": ROOM_LABELS.get(r[3], r[3]),
            "style": r[4],
            "usageCount": r[5],
        }
        for r in rows
    ]


@router.post("/references/{image_id}/use")
def use_reference(image_id: str, request: Request):
    """Marca uma imagem de referência como usada (incrementa o contador de
    relevância) e devolve o estilo dela pra o frontend aplicar na imagem
    atual — não salva nada na imagem atual, só devolve os dados; quem
    persiste é o botão "Salvar" normal do painel de estilo."""
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE project_images SET usage_count = usage_count + 1 WHERE id = %s "
            "RETURNING style",
            (image_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Imagem de referência não encontrada.")
    return {"style": row[0]}


# --- Imagens do projeto -------------------------------------------------------
@router.post("/{project_id}/images")
async def upload_image(project_id: str, request: Request, image: UploadFile = File(...)):
    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    mime = image.content_type or "image/jpeg"
    if mime not in _MIME_OK:
        raise HTTPException(400, "Formato de imagem não suportado.")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(400, "Imagem vazia ou não enviada.")

    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM client_projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Projeto não encontrado.")

    room_type = _classify_room(image_bytes, mime)
    image_id = "img" + secrets.token_hex(8)
    ext = mime.split("/", 1)[1]
    storage_key = f"presentations/{project_id}/{image_id}.{ext}"
    storage.put(storage_key, image_bytes, mime)

    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO project_images (id, project_id, storage_key, mime, room_type) "
            "VALUES (%s, %s, %s, %s, %s)",
            (image_id, project_id, storage_key, mime, room_type),
        )
    return {"id": image_id, "roomType": room_type, "roomLabel": ROOM_LABELS.get(room_type, room_type)}


def _safe_filename_part(text: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in text).strip() or "arquivo"


@router.get("/{project_id}/images/download-all")
def download_all_images(project_id: str, request: Request):
    """Baixa em lote (.zip) todas as imagens de um projeto, na mesma ordem
    natural exibida na tela (ambiente a ambiente)."""
    import io
    import zipfile

    from fastapi.responses import Response

    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT client_name FROM client_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()
        if not project:
            raise HTTPException(404, "Projeto não encontrado.")
        cur.execute(_ordered_images_sql("storage_key, room_type, ce.name"), (project_id,))
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(404, "Nenhuma imagem neste projeto.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (storage_key, room_type, env_name) in enumerate(rows, start=1):
            data = storage.get(storage_key)
            if data is None:
                continue
            ext = storage_key.rsplit(".", 1)[-1] if "." in storage_key else "jpg"
            label = _safe_filename_part(env_name or ROOM_LABELS.get(room_type, room_type))
            zf.writestr(f"{i:02d}_{label}.{ext}", data)
    buf.seek(0)
    filename = _safe_filename_part(project[0]) + ".zip"
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/images/{image_id}/file")
def get_image_file(project_id: str, image_id: str, request: Request):
    from fastapi.responses import Response

    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT storage_key, mime FROM project_images WHERE id = %s AND project_id = %s",
            (image_id, project_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Imagem não encontrada.")
    data = storage.get(row[0])
    if data is None:
        raise HTTPException(404, "Arquivo não disponível.")
    return Response(content=data, media_type=row[1])


class ImageUpdate(BaseModel):
    roomType: str | None = None
    style: dict | None = None


@router.put("/{project_id}/images/{image_id}")
def update_image(project_id: str, image_id: str, body: ImageUpdate, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    if body.roomType is not None and body.roomType not in ROOM_ORDER:
        raise HTTPException(400, "Ambiente inválido.")
    with _db() as conn, conn.cursor() as cur:
        if body.roomType is not None:
            cur.execute(
                "UPDATE project_images SET room_type = %s WHERE id = %s AND project_id = %s",
                (body.roomType, image_id, project_id),
            )
        if body.style is not None:
            cur.execute(
                "UPDATE project_images SET style = %s WHERE id = %s AND project_id = %s",
                (json.dumps(body.style), image_id, project_id),
            )
        cur.execute("SELECT 1 FROM project_images WHERE id = %s AND project_id = %s", (image_id, project_id))
        if not cur.fetchone():
            raise HTTPException(404, "Imagem não encontrada.")
    return {"ok": True}


@router.delete("/{project_id}/images/{image_id}")
def delete_image(project_id: str, image_id: str, request: Request):
    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT storage_key FROM project_images WHERE id = %s AND project_id = %s",
            (image_id, project_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Imagem não encontrada.")
        cur.execute("DELETE FROM project_images WHERE id = %s", (image_id,))
    storage.delete(row[0])
    return {"ok": True}


# A geração de vídeo foi removida do Sogno em 08/07/2026 (decisão do Davi:
# o fornecedor de vídeo não mantinha fidelidade ao projeto — inventava
# ambientes e mudava materiais; foco do produto passou a ser renders de
# imagem + apresentações). O endpoint de vídeo por imagem que vivia aqui e
# o módulo app/video.py inteiro saíram — ver histórico do git se precisar.


# --- Montagem do deck completo (abertura + ambientes do cliente + fechamento)
@router.get("/{project_id}/deck")
def get_deck(project_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT client_name, template_id FROM client_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()
        if not project:
            raise HTTPException(404, "Projeto não encontrado.")

        template_id = project[1]
        if not template_id:
            cur.execute("SELECT id FROM presentation_templates ORDER BY created_at LIMIT 1")
            fallback = cur.fetchone()
            template_id = fallback[0] if fallback else None

        abertura, fechamento = [], []
        if template_id:
            cur.execute(
                "SELECT id, caption, is_closing FROM institutional_slides "
                "WHERE template_id = %s ORDER BY is_closing, sort_order",
                (template_id,),
            )
            for r in cur.fetchall():
                item = {
                    "kind": "institucional", "id": r[0], "caption": r[1],
                    "fileUrl": f"/api/presentations/templates/{template_id}/slides/{r[0]}/file",
                }
                (fechamento if r[2] else abertura).append(item)

        cur.execute(_ordered_images_sql("project_images.id, room_type, ce.name"), (project_id,))
        ambientes = [
            {
                "kind": "ambiente",
                "id": r[0],
                "caption": r[2] or ROOM_LABELS.get(r[1], r[1]),
                "fileUrl": f"/api/presentations/{project_id}/images/{r[0]}/file",
            }
            for r in cur.fetchall()
        ]
        slides = abertura + ambientes + fechamento
    return {
        "projectId": project_id, "clientName": project[0], "templateId": template_id, "slides": slides,
    }


def _open_slide_image(data: bytes):
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    return img.convert("RGB")


_A4_DPI = 150
_A4_LANDSCAPE_PX = (1754, 1240)  # 297x210mm a 150dpi — bate com resolution=_A4_DPI no save()
_TV_PX = (1920, 1080)  # widescreen 16:9 — pra exibir na TV, sem "papel" físico, so a proporção importa


def _fit_to_page(img, page_size):
    """Encaixa a imagem numa página de tamanho fixo (sempre paisagem — TV ou
    A4), sem distorcer: reduz mantendo a proporção original e centraliza,
    preenchendo o resto com branco."""
    from PIL import Image

    page_w, page_h = page_size
    w, h = img.size
    scale = min(page_w / w, page_h / h)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (page_w, page_h), "white")
    canvas.paste(resized, ((page_w - new_w) // 2, (page_h - new_h) // 2))
    return canvas


@router.get("/{project_id}/deck.pdf")
def get_deck_pdf(project_id: str, request: Request, target: str = "a4"):
    """Exporta o deck (abertura + ambientes + fechamento) como PDF de imagens
    fixas — usado quando a apresentação vira anexo de contrato (A4, pra
    imprimir) ou pra exibir numa TV widescreen (target=tv), ao contrário do
    link animado (ver /share/{token})."""
    from fastapi.responses import Response

    page_size = _TV_PX if target == "tv" else _A4_LANDSCAPE_PX

    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT client_name, template_id FROM client_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()
        if not project:
            raise HTTPException(404, "Projeto não encontrado.")

        template_id = project[1]
        if not template_id:
            cur.execute("SELECT id FROM presentation_templates ORDER BY created_at LIMIT 1")
            fallback = cur.fetchone()
            template_id = fallback[0] if fallback else None

        abertura_keys, fechamento_keys = [], []
        if template_id:
            cur.execute(
                "SELECT storage_key, is_closing FROM institutional_slides "
                "WHERE template_id = %s ORDER BY is_closing, sort_order",
                (template_id,),
            )
            for storage_key, is_closing in cur.fetchall():
                (fechamento_keys if is_closing else abertura_keys).append(storage_key)

        cur.execute(_ordered_images_sql("storage_key"), (project_id,))
        ambiente_keys = [r[0] for r in cur.fetchall()]

    ordered_keys = abertura_keys + ambiente_keys + fechamento_keys
    if not ordered_keys:
        raise HTTPException(400, "Este projeto ainda não tem slides para exportar.")

    images = []
    for storage_key in ordered_keys:
        data = storage.get(storage_key)
        if data is not None:
            images.append(_fit_to_page(_open_slide_image(data), page_size))
    if not images:
        raise HTTPException(400, "Nenhum arquivo de slide disponível para exportar.")

    save_kwargs = {"resolution": _A4_DPI} if target != "tv" else {}
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:], **save_kwargs)

    client_name = project[0] or "apresentacao"
    safe_name = "".join(c for c in client_name if c.isalnum() or c in " -_").strip() or "apresentacao"
    suffix = "tv" if target == "tv" else "a4"
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-{suffix}.pdf"'},
    )


# --- Link público animado (sem login, mesmo padrão de token do staging Luma)-
@router.post("/{project_id}/share")
def create_share_link(project_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    token = secrets.token_urlsafe(24)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE client_projects SET share_token = %s WHERE id = %s RETURNING id",
            (token, project_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Projeto não encontrado.")
    return {"shareToken": token, "shareUrl": f"/apresentacao/{token}"}


@router.delete("/{project_id}/share")
def revoke_share_link(project_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE client_projects SET share_token = NULL WHERE id = %s RETURNING id",
            (project_id,),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Projeto não encontrado.")
    return {"ok": True}


def _project_by_share_token(cur, token: str):
    cur.execute(
        "SELECT id, client_name, template_id FROM client_projects WHERE share_token = %s",
        (token,),
    )
    return cur.fetchone()


@router.get("/share/{token}/deck")
def get_shared_deck(token: str):
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        raise HTTPException(404, "Apresentação não encontrada.")
    with _db() as conn, conn.cursor() as cur:
        project = _project_by_share_token(cur, token)
        if not project:
            raise HTTPException(404, "Link inválido ou apresentação não encontrada.")
        project_id, client_name, template_id = project

        if not template_id:
            cur.execute("SELECT id FROM presentation_templates ORDER BY created_at LIMIT 1")
            fallback = cur.fetchone()
            template_id = fallback[0] if fallback else None

        abertura, fechamento = [], []
        if template_id:
            cur.execute(
                "SELECT id, caption, is_closing FROM institutional_slides "
                "WHERE template_id = %s ORDER BY is_closing, sort_order",
                (template_id,),
            )
            for r in cur.fetchall():
                item = {
                    "kind": "institucional", "id": r[0], "caption": r[1],
                    "fileUrl": f"/api/presentations/share/{token}/slide/{r[0]}/file",
                }
                (fechamento if r[2] else abertura).append(item)

        cur.execute(_ordered_images_sql("project_images.id, room_type, ce.name"), (project_id,))
        ambientes = [
            {
                "kind": "ambiente", "id": r[0], "caption": r[2] or ROOM_LABELS.get(r[1], r[1]),
                "fileUrl": f"/api/presentations/share/{token}/image/{r[0]}/file",
            }
            for r in cur.fetchall()
        ]
    return {"clientName": client_name, "slides": abertura + ambientes + fechamento}


@router.get("/share/{token}/slide/{slide_id}/file")
def get_shared_slide_file(token: str, slide_id: str):
    from fastapi.responses import Response

    from app import storage
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        raise HTTPException(404, "Arquivo não encontrado.")
    with _db() as conn, conn.cursor() as cur:
        project = _project_by_share_token(cur, token)
        if not project:
            raise HTTPException(404, "Link inválido.")
        cur.execute(
            "SELECT storage_key, mime FROM institutional_slides WHERE id = %s AND template_id = %s",
            (slide_id, project[2]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Slide não encontrado.")
    data = storage.get(row[0])
    if data is None:
        raise HTTPException(404, "Arquivo não disponível.")
    return Response(content=data, media_type=row[1])


@router.get("/share/{token}/image/{image_id}/file")
def get_shared_image_file(token: str, image_id: str):
    from fastapi.responses import Response

    from app import storage
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        raise HTTPException(404, "Arquivo não encontrado.")
    with _db() as conn, conn.cursor() as cur:
        project = _project_by_share_token(cur, token)
        if not project:
            raise HTTPException(404, "Link inválido.")
        cur.execute(
            "SELECT storage_key, mime FROM project_images WHERE id = %s AND project_id = %s",
            (image_id, project[0]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Imagem não encontrada.")
    data = storage.get(row[0])
    if data is None:
        raise HTTPException(404, "Arquivo não disponível.")
    return Response(content=data, media_type=row[1])
