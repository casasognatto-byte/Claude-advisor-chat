"""Geração de vídeo a partir de imagem (render estático → vídeo animado),
acionada de dentro de uma conversa. Ver plano em
C:\\Users\\user\\.claude\\plans\\logical-enchanting-parasol.md (Fase 1) e a
memória "Ecossistema IA multiusuário" para o desenho completo.

Regra inegociável: o motor escolhido (stub/luma/veo) nunca é exposto ao
cliente — nem no JSON de resposta, nem em mensagens de erro (sempre um texto
genérico fixo), nem em nenhuma URL que o navegador chegue a chamar (o vídeo
final é baixado pelo servidor e reservido pelo próprio domínio).

Todos os imports de `app.main` ficam dentro das funções (não no topo do
arquivo) para evitar import circular, já que `app.main` inclui este router.
"""

import asyncio
import os
import secrets
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/video")

GENERIC_ERROR = "Falha ao gerar o vídeo, tente novamente."
POLL_INTERVAL_SECONDS = int(os.environ.get("VIDEO_POLL_INTERVAL_SECONDS", "10"))
STAGE_TTL_SECONDS = int(os.environ.get("VIDEO_STAGE_TTL_SECONDS", "1200"))
DEFAULT_ENGINE = os.environ.get("VIDEO_ENGINE", "stub")


# --- Armazenamento local (staging de imagem + vídeo final) ------------------
def _storage_root() -> str:
    return os.environ.get("VIDEO_STORAGE_DIR") or os.path.join(tempfile.gettempdir(), "casasognatto_video")


def _staged_path(token: str) -> str:
    d = os.path.join(_storage_root(), "staged")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, token)


def _video_path(job_id: str) -> str:
    d = os.path.join(_storage_root(), "videos")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{job_id}.mp4")


def _stage_image(job_id: str, image_bytes: bytes, mime: str) -> str:
    """Salva a imagem localmente com um token imprevisível e registra a
    expiração no job — usado só pelo Luma, que exige URL pública."""
    from app.main import DB_ENABLED, _db

    token = secrets.token_urlsafe(32)
    with open(_staged_path(token), "wb") as f:
        f.write(image_bytes)
    if DB_ENABLED:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE video_jobs SET stage_token = %s, stage_mime = %s, "
                "stage_expires_at = now() + (%s || ' seconds')::interval WHERE id = %s",
                (token, mime, STAGE_TTL_SECONDS, job_id),
            )
    return token


def _cleanup_stage(job_id: str) -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT stage_token FROM video_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        token = row[0] if row else None
        cur.execute(
            "UPDATE video_jobs SET stage_token = NULL, stage_mime = NULL, "
            "stage_expires_at = NULL WHERE id = %s",
            (job_id,),
        )
    if token:
        try:
            os.remove(_staged_path(token))
        except OSError:
            pass


# --- Banco de dados -----------------------------------------------------
def init_video_db() -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS video_jobs (
                    id               TEXT PRIMARY KEY,
                    username         TEXT NOT NULL,
                    conversation_id  TEXT,
                    engine           TEXT NOT NULL,
                    prompt           TEXT NOT NULL DEFAULT '',
                    status           TEXT NOT NULL DEFAULT 'queued',
                    error_message    TEXT,
                    vendor_job_id    TEXT,
                    stage_token      TEXT,
                    stage_mime       TEXT,
                    stage_expires_at TIMESTAMPTZ,
                    video_path       TEXT,
                    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_video_jobs_user "
                "ON video_jobs (username, created_at DESC);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_video_jobs_stage_token "
                "ON video_jobs (stage_token) WHERE stage_token IS NOT NULL;"
            )
            # Jobs órfãos de uma queda/redeploy no meio do processamento nunca
            # ficam girando pra sempre — o próximo poll do cliente já vê erro.
            cur.execute(
                "UPDATE video_jobs SET status = 'error', error_message = %s "
                "WHERE status IN ('queued', 'processing') "
                "AND updated_at < now() - interval '15 minutes'",
                (GENERIC_ERROR,),
            )
    except Exception as e:
        print(f"[init_video_db] falha: {e}")


def _update_job(job_id: str, **fields) -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED or not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [job_id]
    with _db() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE video_jobs SET {sets}, updated_at = now() WHERE id = %s", params)


def _get_job(job_id: str) -> dict | None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return None
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, conversation_id, status, error_message, video_path, "
            "EXTRACT(EPOCH FROM created_at) FROM video_jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "username": row[1], "conversationId": row[2], "status": row[3],
        "error": row[4], "videoPath": row[5], "createdAt": float(row[6]),
    }


# --- Orquestração assíncrona -------------------------------------------------
async def _run_job(job_id: str, image_bytes: bytes, mime: str, prompt: str, engine: str) -> None:
    from app.video_engines import ENGINES, VendorGenerationError

    public_base_url = (os.environ.get("PUBLIC_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    impl = ENGINES.get(engine)
    try:
        if impl is None:
            raise VendorGenerationError(f"Engine desconhecido: {engine}")
        _update_job(job_id, status="processing")
        vendor_job_id, _stage_token = await impl.start(job_id, image_bytes, mime, prompt, public_base_url)
        _update_job(job_id, vendor_job_id=vendor_job_id)
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            if await impl.poll(vendor_job_id):
                break
        video_bytes = await impl.download(vendor_job_id)
        path = _video_path(job_id)
        with open(path, "wb") as f:
            f.write(video_bytes)
        _update_job(job_id, status="done", video_path=path)
    except VendorGenerationError as e:
        print(f"[video job {job_id}] falha do fornecedor ({engine}): {e}")
        _update_job(job_id, status="error", error_message=GENERIC_ERROR)
    except Exception as e:  # nunca deixar uma task em background morrer silenciosa
        print(f"[video job {job_id}] falha inesperada: {e}")
        _update_job(job_id, status="error", error_message=GENERIC_ERROR)
    finally:
        _cleanup_stage(job_id)


def _resolve_engine(user: dict, variant: str | None) -> str:
    """Só o diretor pode escolher motor manualmente (rótulos neutros "a"/"b"
    no frontend) — todo o resto sempre usa o padrão configurado no servidor."""
    if user.get("role") == "diretor" and variant in ("a", "b"):
        return {"a": "luma", "b": "veo"}[variant]
    return DEFAULT_ENGINE


def create_video_job(user: dict, image_bytes: bytes, mime: str, prompt: str, conversation_id: str | None, variant: str | None) -> dict:
    """Núcleo da criação de job, reaproveitado tanto pelo upload manual (chat
    principal) quanto pelo botão "Gerar vídeo" em cima de uma imagem já
    armazenada na Biblioteca de Apresentações (`app/presentations.py`) —
    nesse segundo caso não existe upload nenhum, só bytes já em mãos."""
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        raise HTTPException(503, "Banco de dados não configurado.")
    if not image_bytes:
        raise HTTPException(400, "Imagem vazia ou não enviada.")
    engine = _resolve_engine(user, variant)
    job_id = "v" + secrets.token_hex(8)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO video_jobs (id, username, conversation_id, engine, prompt) "
            "VALUES (%s, %s, %s, %s, %s)",
            (job_id, user["username"], conversation_id, engine, prompt or ""),
        )
    asyncio.create_task(_run_job(job_id, image_bytes, mime or "image/jpeg", prompt or "", engine))
    return {"id": job_id, "status": "queued"}


# --- Rotas --------------------------------------------------------------
@router.post("/jobs")
async def create_job(
    request: Request,
    image: UploadFile = File(...),
    prompt: str = Form(""),
    conversation_id: str | None = Form(None),
    variant: str | None = Form(None),
):
    from app.main import require_user

    user = require_user(request)
    image_bytes = await image.read()
    return create_video_job(user, image_bytes, image.content_type or "image/jpeg", prompt or "", conversation_id, variant)


@router.get("/jobs")
def list_jobs(request: Request):
    from app.main import DB_ENABLED, _db, require_user

    user = require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, conversation_id, status, EXTRACT(EPOCH FROM created_at) "
            "FROM video_jobs WHERE username = %s ORDER BY created_at DESC LIMIT 100",
            (user["username"],),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "conversationId": r[1], "status": r[2], "createdAt": float(r[3])}
        for r in rows
    ]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    from app.main import require_user

    require_user(request)  # qualquer membro logado pode acompanhar (conversas são compartilhadas)
    job = _get_job(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")
    return {
        "id": job["id"],
        "status": job["status"],
        "error": job["error"],
        "ready": job["status"] == "done",
    }


@router.get("/file/{job_id}")
def get_file(job_id: str, request: Request):
    from app.main import require_user

    require_user(request)
    job = _get_job(job_id)
    if not job or job["status"] != "done" or not job["videoPath"] or not os.path.exists(job["videoPath"]):
        raise HTTPException(404, "Vídeo não disponível.")
    return FileResponse(job["videoPath"], media_type="video/mp4")


@router.get("/staged/{token}")
def get_staged_image(token: str):
    """Sem autenticação de propósito — é o fornecedor de vídeo que busca esta
    URL, sem cookie de sessão. A segurança vem da entropia do token (256 bits)
    e da expiração curta, não de login."""
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        raise HTTPException(404)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT stage_mime FROM video_jobs WHERE stage_token = %s AND stage_expires_at > now()",
            (token,),
        )
        row = cur.fetchone()
    path = _staged_path(token)
    if not row or not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type=row[0] or "application/octet-stream")
