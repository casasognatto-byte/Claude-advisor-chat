"""Biblioteca de Apresentações — Fase 4: a Neusa como arquiteta auxiliar.

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
            f"SELECT id, room_type, style, EXTRACT(EPOCH FROM created_at) FROM project_images "
            f"WHERE project_id = %s ORDER BY {_room_position_sql()}, created_at",
            (project_id,),
        )
        images = [
            {
                "id": r[0],
                "roomType": r[1],
                "roomLabel": ROOM_LABELS.get(r[1], r[1]),
                "style": r[2],
                "createdAt": float(r[3]),
            }
            for r in cur.fetchall()
        ]
    return {
        "id": row[0],
        "clientName": row[1],
        "createdBy": row[2],
        "createdAt": float(row[3]),
        "images": images,
    }


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
def search_references(request: Request, room_type: str | None = None, client: str | None = None):
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


def _style_to_prompt(style: dict) -> str:
    """Monta um prompt a partir das respostas da entrevista de estilo — usado
    como padrão ao gerar vídeo quando a arquiteta não escreve um prompt à
    mão. Evita começar do zero toda vez que os detalhes já foram capturados."""
    parts = []
    if style.get("mdfColor"):
        parts.append(f"Cor real do MDF/MDP: {style['mdfColor']}.")
    tom_label = {"quente": "quente (3000K)", "neutra": "neutra (4000K)", "fria": "fria (6000K)"}.get(
        style.get("ilumGeralTom"), ""
    )
    if tom_label:
        parts.append(f"Iluminação geral com temperatura {tom_label}.")
    if style.get("ilumGeralDetalhe"):
        parts.append(style["ilumGeralDetalhe"].rstrip(".") + ".")
    if style.get("ilumMoveis"):
        parts.append(f"Iluminação nos móveis: {style['ilumMoveis'].rstrip('.')}.")
    if style.get("decoracao"):
        parts.append("Decoração presente: " + ", ".join(style["decoracao"]) + ".")
    return " ".join(parts)


class VideoFromImageRequest(BaseModel):
    prompt: str | None = None


@router.post("/{project_id}/images/{image_id}/video")
async def create_video_from_image(project_id: str, image_id: str, body: VideoFromImageRequest, request: Request):
    """Gera vídeo (Luma/Veo) direto de uma imagem já armazenada aqui — sem
    precisar baixar e reenviar pelo chat principal."""
    from app import storage
    from app.main import _db, _require_db, require_user
    from app.video import create_video_job

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT storage_key, mime, style FROM project_images WHERE id = %s AND project_id = %s",
            (image_id, project_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Imagem não encontrada.")
    image_bytes = storage.get(row[0])
    if image_bytes is None:
        raise HTTPException(404, "Arquivo não disponível.")
    prompt = body.prompt if body.prompt is not None else _style_to_prompt(row[2] or {})
    return create_video_job(user, image_bytes, row[1], prompt, conversation_id=None, variant=None)


# --- Biblioteca de padrões técnicos (iluminação/decoração por tipo de móvel) -
class PatternCreate(BaseModel):
    furnitureType: str
    attribute: str = ""
    recommendation: str


@router.get("/patterns/list")
def list_patterns(request: Request):
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, furniture_type, attribute, recommendation, created_by, "
            "EXTRACT(EPOCH FROM updated_at) FROM style_patterns ORDER BY furniture_type, attribute"
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0], "furnitureType": r[1], "attribute": r[2], "recommendation": r[3],
            "createdBy": r[4], "updatedAt": float(r[5]),
        }
        for r in rows
    ]


@router.post("/patterns")
def create_pattern(body: PatternCreate, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    furniture = body.furnitureType.strip()
    recommendation = body.recommendation.strip()
    if not furniture or not recommendation:
        raise HTTPException(400, "Tipo de móvel e recomendação são obrigatórios.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO style_patterns (furniture_type, attribute, recommendation, created_by) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (furniture, body.attribute.strip(), recommendation, user["username"]),
        )
        pattern_id = cur.fetchone()[0]
    return {"id": pattern_id}


@router.put("/patterns/{pattern_id}")
def update_pattern(pattern_id: int, body: PatternCreate, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    furniture = body.furnitureType.strip()
    recommendation = body.recommendation.strip()
    if not furniture or not recommendation:
        raise HTTPException(400, "Tipo de móvel e recomendação são obrigatórios.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT furniture_type, attribute, recommendation FROM style_patterns WHERE id = %s",
            (pattern_id,),
        )
        current = cur.fetchone()
        if not current:
            raise HTTPException(404, "Padrão não encontrado.")
        cur.execute(
            "INSERT INTO style_pattern_versions (pattern_id, furniture_type, attribute, recommendation) "
            "VALUES (%s, %s, %s, %s)",
            (pattern_id, current[0], current[1], current[2]),
        )
        cur.execute(
            "UPDATE style_patterns SET furniture_type = %s, attribute = %s, recommendation = %s, "
            "updated_at = now() WHERE id = %s",
            (furniture, body.attribute.strip(), recommendation, pattern_id),
        )
    return {"ok": True}


@router.post("/patterns/{pattern_id}/undo")
def undo_pattern(pattern_id: int, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, furniture_type, attribute, recommendation FROM style_pattern_versions "
            "WHERE pattern_id = %s ORDER BY saved_at DESC LIMIT 1",
            (pattern_id,),
        )
        version = cur.fetchone()
        if not version:
            raise HTTPException(404, "Não há histórico de edições pra desfazer.")
        cur.execute(
            "UPDATE style_patterns SET furniture_type = %s, attribute = %s, recommendation = %s, "
            "updated_at = now() WHERE id = %s",
            (version[1], version[2], version[3], pattern_id),
        )
        cur.execute("DELETE FROM style_pattern_versions WHERE id = %s", (version[0],))
    return {"ok": True}


@router.delete("/patterns/{pattern_id}")
def delete_pattern(pattern_id: int, request: Request):
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT furniture_type, attribute, recommendation, created_by FROM style_patterns WHERE id = %s",
            (pattern_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Padrão não encontrado.")
        cur.execute(
            "INSERT INTO deleted_style_patterns "
            "(furniture_type, attribute, recommendation, created_by, deleted_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (row[0], row[1], row[2], row[3], user["username"]),
        )
        cur.execute("DELETE FROM style_patterns WHERE id = %s", (pattern_id,))
        cur.execute("DELETE FROM style_pattern_versions WHERE pattern_id = %s", (pattern_id,))
    return {"ok": True}


@router.get("/patterns/deleted")
def list_deleted_patterns(request: Request):
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, furniture_type, attribute, recommendation, created_by, deleted_by, "
            "EXTRACT(EPOCH FROM deleted_at) FROM deleted_style_patterns "
            "WHERE restored = false ORDER BY deleted_at DESC"
        )
        rows = cur.fetchall()
    return [
        {
            "logId": r[0], "furnitureType": r[1], "attribute": r[2], "recommendation": r[3],
            "createdBy": r[4], "deletedBy": r[5], "deletedAt": float(r[6]),
        }
        for r in rows
    ]


@router.post("/patterns/deleted/{log_id}/restore")
def restore_pattern(log_id: int, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT furniture_type, attribute, recommendation, created_by, restored "
            "FROM deleted_style_patterns WHERE id = %s",
            (log_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Registro de exclusão não encontrado.")
        if row[4]:
            raise HTTPException(400, "Este padrão já foi restaurado.")
        cur.execute(
            "INSERT INTO style_patterns (furniture_type, attribute, recommendation, created_by) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (row[0], row[1], row[2], row[3]),
        )
        new_id = cur.fetchone()[0]
        cur.execute("UPDATE deleted_style_patterns SET restored = true WHERE id = %s", (log_id,))
    return {"ok": True, "id": new_id}


# --- Slides institucionais (deck fixo: loja + indústria) ---------------------
# Sempre os mesmos, em toda apresentação, editáveis por qualquer membro da
# equipe. Ficam na frente dos slides de ambientes de cada projeto de cliente.
@router.get("/institutional/slides")
def list_institutional_slides(request: Request):
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, caption, sort_order, created_by, EXTRACT(EPOCH FROM created_at) "
            "FROM institutional_slides ORDER BY sort_order"
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "caption": r[1], "sortOrder": r[2], "createdBy": r[3], "createdAt": float(r[4])}
        for r in rows
    ]


@router.post("/institutional/slides")
async def add_institutional_slide(request: Request, image: UploadFile = File(...), caption: str = Form("")):
    from app import storage
    from app.main import _db, _require_db, require_user

    user = require_user(request)
    _require_db()
    mime = image.content_type or "image/jpeg"
    if mime not in _MIME_OK:
        raise HTTPException(400, "Formato de imagem não suportado.")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(400, "Imagem vazia ou não enviada.")

    slide_id = "inst" + secrets.token_hex(8)
    ext = mime.split("/", 1)[1]
    storage_key = f"institutional/{slide_id}.{ext}"
    storage.put(storage_key, image_bytes, mime)

    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM institutional_slides")
        next_order = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO institutional_slides (id, storage_key, mime, caption, sort_order, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (slide_id, storage_key, mime, caption, next_order, user["username"]),
        )
    return {"id": slide_id, "sortOrder": next_order}


@router.get("/institutional/slides/{slide_id}/file")
def get_institutional_slide_file(slide_id: str, request: Request):
    from fastapi.responses import Response

    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT storage_key, mime FROM institutional_slides WHERE id = %s", (slide_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Slide não encontrado.")
    data = storage.get(row[0])
    if data is None:
        raise HTTPException(404, "Arquivo não disponível.")
    return Response(content=data, media_type=row[1])


class SlideUpdate(BaseModel):
    caption: str | None = None


@router.put("/institutional/slides/{slide_id}")
def update_institutional_slide(slide_id: str, body: SlideUpdate, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE institutional_slides SET caption = %s WHERE id = %s",
            (body.caption or "", slide_id),
        )
        cur.execute("SELECT 1 FROM institutional_slides WHERE id = %s", (slide_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Slide não encontrado.")
    return {"ok": True}


@router.delete("/institutional/slides/{slide_id}")
def delete_institutional_slide(slide_id: str, request: Request):
    from app import storage
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT storage_key FROM institutional_slides WHERE id = %s", (slide_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Slide não encontrado.")
        cur.execute("DELETE FROM institutional_slides WHERE id = %s", (slide_id,))
    storage.delete(row[0])
    return {"ok": True}


class SlideReorder(BaseModel):
    orderedIds: list[str]


@router.post("/institutional/slides/reorder")
def reorder_institutional_slides(body: SlideReorder, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        for position, slide_id in enumerate(body.orderedIds):
            cur.execute(
                "UPDATE institutional_slides SET sort_order = %s WHERE id = %s",
                (position, slide_id),
            )
    return {"ok": True}


# --- Montagem do deck completo (institucional + ambientes do cliente) -------
@router.get("/{project_id}/deck")
def get_deck(project_id: str, request: Request):
    from app.main import _db, _require_db, require_user

    require_user(request)
    _require_db()
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT client_name FROM client_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()
        if not project:
            raise HTTPException(404, "Projeto não encontrado.")

        cur.execute(
            "SELECT id, caption FROM institutional_slides ORDER BY sort_order"
        )
        slides = [
            {"kind": "institucional", "id": r[0], "caption": r[1], "fileUrl": f"/api/presentations/institutional/slides/{r[0]}/file"}
            for r in cur.fetchall()
        ]

        cur.execute(
            f"SELECT id, room_type FROM project_images WHERE project_id = %s "
            f"ORDER BY {_room_position_sql()}, created_at",
            (project_id,),
        )
        slides += [
            {
                "kind": "ambiente",
                "id": r[0],
                "caption": ROOM_LABELS.get(r[1], r[1]),
                "fileUrl": f"/api/presentations/{project_id}/images/{r[0]}/file",
            }
            for r in cur.fetchall()
        ]
    return {"projectId": project_id, "clientName": project[0], "slides": slides}
