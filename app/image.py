"""Geração de imagem a partir de imagem elementar de projeto (planta/massa
simples → render fotorrealista), acionada de dentro de uma conversa — Fase 2
do plano. Espelha `app/video.py`, mas mais simples: a geração é rápida
(segundos, não minutos), então não há staging de imagem nem loop de polling
no fornecedor — só uma chamada e pronto.

Mesma regra inegociável do vídeo: o motor nunca é exposto ao cliente.
Imports de `app.main` ficam dentro das funções para evitar import circular.
"""

import asyncio
import os
import secrets
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/image")

GENERIC_ERROR = "Falha ao gerar a imagem, tente novamente."
DEFAULT_ENGINE = os.environ.get("IMAGE_ENGINE", "stub")

_EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _storage_root() -> str:
    return os.environ.get("IMAGE_STORAGE_DIR") or os.path.join(tempfile.gettempdir(), "casasognatto_image")


def _image_path(job_id: str, mime: str) -> str:
    d = _storage_root()
    os.makedirs(d, exist_ok=True)
    ext = _EXT_BY_MIME.get(mime, "png")
    return os.path.join(d, f"{job_id}.{ext}")


def init_image_db() -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS image_jobs (
                    id              TEXT PRIMARY KEY,
                    username        TEXT NOT NULL,
                    conversation_id TEXT,
                    engine          TEXT NOT NULL,
                    prompt          TEXT NOT NULL DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'queued',
                    error_message   TEXT,
                    image_path      TEXT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_image_jobs_user "
                "ON image_jobs (username, created_at DESC);"
            )
            # Geração de imagem é rápida — se um job ficou "preso" por mais de
            # 5 minutos, algo deu errado (queda/redeploy); não deixar girando.
            cur.execute(
                "UPDATE image_jobs SET status = 'error', error_message = %s "
                "WHERE status IN ('queued', 'processing') "
                "AND updated_at < now() - interval '5 minutes'",
                (GENERIC_ERROR,),
            )
    except Exception as e:
        print(f"[init_image_db] falha: {e}")


def _update_job(job_id: str, **fields) -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED or not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [job_id]
    with _db() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE image_jobs SET {sets}, updated_at = now() WHERE id = %s", params)


def _get_job(job_id: str) -> dict | None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return None
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, conversation_id, status, error_message, image_path "
            "FROM image_jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "username": row[1], "conversationId": row[2],
        "status": row[3], "error": row[4], "imagePath": row[5],
    }


async def _run_image_job(job_id: str, image_bytes: bytes, mime: str, prompt: str, engine: str) -> None:
    from app.image_engines import ENGINES, ImageGenerationError

    impl = ENGINES.get(engine)
    try:
        if impl is None:
            raise ImageGenerationError(f"Engine desconhecido: {engine}")
        _update_job(job_id, status="processing")
        result_bytes, result_mime = await impl.generate(image_bytes, mime, prompt)
        path = _image_path(job_id, result_mime)
        with open(path, "wb") as f:
            f.write(result_bytes)
        _update_job(job_id, status="done", image_path=path)
    except ImageGenerationError as e:
        print(f"[image job {job_id}] falha do fornecedor ({engine}): {e}")
        _update_job(job_id, status="error", error_message=GENERIC_ERROR)
    except Exception as e:
        print(f"[image job {job_id}] falha inesperada: {e}")
        _update_job(job_id, status="error", error_message=GENERIC_ERROR)


@router.post("/jobs")
async def create_job(
    request: Request,
    image: UploadFile = File(...),
    prompt: str = Form(""),
    conversation_id: str | None = Form(None),
):
    from app.main import DB_ENABLED, _db, require_user

    user = require_user(request)
    if not DB_ENABLED:
        raise HTTPException(503, "Banco de dados não configurado.")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(400, "Imagem vazia ou não enviada.")
    job_id = "i" + secrets.token_hex(8)
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO image_jobs (id, username, conversation_id, engine, prompt) "
            "VALUES (%s, %s, %s, %s, %s)",
            (job_id, user["username"], conversation_id, DEFAULT_ENGINE, prompt or ""),
        )
    asyncio.create_task(
        _run_image_job(job_id, image_bytes, image.content_type or "image/jpeg", prompt or "", DEFAULT_ENGINE)
    )
    return {"id": job_id, "status": "queued"}


@router.get("/jobs")
def list_jobs(request: Request):
    from app.main import DB_ENABLED, _db, require_user

    user = require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, conversation_id, status, EXTRACT(EPOCH FROM created_at) "
            "FROM image_jobs WHERE username = %s ORDER BY created_at DESC LIMIT 100",
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

    require_user(request)  # conversas são compartilhadas — qualquer membro pode acompanhar
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
    if not job or job["status"] != "done" or not job["imagePath"] or not os.path.exists(job["imagePath"]):
        raise HTTPException(404, "Imagem não disponível.")
    return FileResponse(job["imagePath"])
