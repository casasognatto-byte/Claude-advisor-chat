"""Geração de imagem a partir de imagem elementar de projeto (planta/massa
simples → render fotorrealista), acionada de dentro de uma conversa — Fase 2
do plano. Espelha `app/video.py`, mas mais simples: a geração é rápida
(segundos, não minutos), então não há staging de imagem nem loop de polling
no fornecedor — só uma chamada e pronto.

Mesma regra inegociável do vídeo: o motor nunca é exposto ao cliente.
Imports de `app.main` ficam dentro das funções para evitar import circular.
"""

import asyncio
import json
import os
import secrets

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

router = APIRouter(prefix="/api/image")

GENERIC_ERROR = "Falha ao gerar a imagem, tente novamente."
DEFAULT_ENGINE = os.environ.get("IMAGE_ENGINE", "stub")

# Anexado a TODO prompt de render, não importa o que a arquiteta escreva —
# regra inegociável do Davi (08/07/2026): a IA nunca pode alterar o projeto
# de interiores por conta própria. Só muda o que for pedido explícita e
# pontualmente nas instruções abaixo dessa base.
FIDELITY_BASE_PROMPT = (
    "Transforme esta imagem em um render fotorrealista. Regra inegociável: não "
    "altere o projeto de interiores em nada além do que for pedido explicitamente "
    "nas instruções abaixo — preserve exatamente o mesmo layout, os mesmos móveis, "
    "as mesmas proporções e posições, e a mesma cor e textura de móveis, pedras e "
    "paredes do projeto original. Não invente cômodos, ambientes, portas, janelas, "
    "móveis, nichos, prateleiras, torres, colunas ou objetos que não estejam na "
    "imagem de referência — inclusive nas bordas da imagem: se um móvel, parede ou "
    "elemento aparece cortado/parcial na borda, mantenha ele exatamente cortado do "
    "mesmo jeito, NÃO complete, estenda nem imagine o que viria depois da borda. A "
    "composição, o enquadramento e os limites da cena devem ser idênticos ao "
    "original — apenas a qualidade visual (luz, textura, material, fotorrealismo) "
    "muda. Só mude cor, textura, material, iluminação ou decoração de algo "
    "específico se uma instrução abaixo pedir isso pontualmente."
)


def _build_prompt(architect_prompt: str) -> str:
    architect_prompt = (architect_prompt or "").strip()
    if not architect_prompt:
        return FIDELITY_BASE_PROMPT
    return f"{FIDELITY_BASE_PROMPT}\n\nInstruções específicas da arquiteta:\n{architect_prompt}"

_EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _image_key(job_id: str, mime: str, kind: str = "out") -> str:
    """Chave no storage (R2 com fallback local — ver app/storage.py). Antes disso
    (até 08/07/2026) as imagens eram salvas só no disco local do servidor, que o
    Render apaga a cada deploy — descoberto quando renders reais sumiram da tela
    logo após um deploy de rotina."""
    ext = _EXT_BY_MIME.get(mime, "png")
    suffix = "" if kind == "out" else f"_{kind}"
    return f"image/{job_id}{suffix}.{ext}"


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
                    source_path     TEXT,
                    source_mime     TEXT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            # Migração aditiva — jobs criados antes do botão "Refazer" existir
            # não têm a imagem de origem salva (não dá pra refazer esses).
            cur.execute("ALTER TABLE image_jobs ADD COLUMN IF NOT EXISTS source_path TEXT;")
            cur.execute("ALTER TABLE image_jobs ADD COLUMN IF NOT EXISTS source_mime TEXT;")
            # Painel "Inspetor" (08/07/2026) — parâmetros estruturados sugeridos
            # pelo Sogno a partir do prompt/estilo: luz, textura e ângulo de câmera.
            cur.execute("ALTER TABLE image_jobs ADD COLUMN IF NOT EXISTS param_light TEXT;")
            cur.execute("ALTER TABLE image_jobs ADD COLUMN IF NOT EXISTS param_texture TEXT;")
            cur.execute("ALTER TABLE image_jobs ADD COLUMN IF NOT EXISTS param_camera TEXT;")
            # Mime do resultado — precisa ficar salvo à parte porque, desde a
            # migração pra app.storage (08/07/2026), image_path virou uma chave
            # de storage (não mais um caminho de arquivo com extensão previsível).
            cur.execute("ALTER TABLE image_jobs ADD COLUMN IF NOT EXISTS image_mime TEXT;")
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
            "SELECT id, username, conversation_id, status, error_message, image_path, "
            "prompt, source_path, source_mime, engine, param_light, param_texture, param_camera, "
            "image_mime "
            "FROM image_jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "username": row[1], "conversationId": row[2],
        "status": row[3], "error": row[4], "imagePath": row[5],
        "prompt": row[6], "sourcePath": row[7], "sourceMime": row[8], "engine": row[9],
        "paramLight": row[10], "paramTexture": row[11], "paramCamera": row[12],
        "imageMime": row[13],
    }


async def _derive_render_params(prompt: str) -> dict:
    """Pede ao Claude (mesmo modelo do executor, chamada curta e barata) pra
    extrair 3 parâmetros estruturados do pedido da arquiteta — luz, textura e
    ângulo de câmera — pro painel "Inspetor" do frontend. Se a arquiteta já
    especificou algo, resume o que ela pediu; se não, sugere um padrão
    razoável (seguindo o comportamento do Sogno de sempre confirmar
    iluminação e sugerir ângulos de câmera). Nunca derruba o job se falhar —
    o painel simplesmente fica sem esses dados."""
    from app.main import EXECUTOR_MODEL, client

    instruction = (
        "A partir do pedido de render abaixo, extraia 3 campos curtos (até 8 "
        "palavras cada) para um painel de parâmetros de uma ferramenta de "
        "renderização de móveis planejados:\n"
        "- light: iluminação natural/artificial. Se a arquiteta não especificou, "
        "sugira uma opção razoável e sinalize que é sugestão (ex: \"Sugestão: luz "
        "quente indireta\").\n"
        "- texture: textura/material em foco na cena (madeira, pedra, metal etc).\n"
        "- camera: ângulo de câmera sugerido (ex: \"nível do olhar\", \"detalhe em "
        "macro\").\n\n"
        "Responda SOMENTE com um JSON de uma linha, sem markdown, no formato "
        '{"light": "...", "texture": "...", "camera": "..."}.\n\n'
        f"Pedido da arquiteta: {prompt or '(nenhuma instrução específica, imagem só)'}"
    )
    resp = client.messages.create(
        model=EXECUTOR_MODEL, max_tokens=200,
        messages=[{"role": "user", "content": instruction}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    data = json.loads(text)
    return {
        "light": str(data.get("light") or "")[:120],
        "texture": str(data.get("texture") or "")[:120],
        "camera": str(data.get("camera") or "")[:120],
    }


async def _run_render_params(job_id: str, prompt: str) -> None:
    """Roda em paralelo à geração da imagem — nunca atrasa nem derruba o
    render principal se falhar (painel Inspetor simplesmente fica vazio)."""
    try:
        params = await _derive_render_params(prompt)
        _update_job(job_id, param_light=params["light"], param_texture=params["texture"], param_camera=params["camera"])
    except Exception as e:
        print(f"[image job {job_id}] falha ao derivar parâmetros do inspetor: {e}")


def _bridge_to_project_images(job_id: str, key: str, mime: str) -> None:
    """Se a conversa deste job pertence a um ambiente (Cliente > Ambiente,
    ver client_environments), o render também entra automaticamente na lista
    ordenável daquele ambiente em Apresentações — sem isso, o deck final não
    veria os renders feitos pelo chat. Reaproveita a mesma storage_key, sem
    reupload. Conversa sem ambiente (o padrão de sempre) não faz nada aqui."""
    from app.main import _db

    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.environment_id, ce.project_id FROM image_jobs j "
            "JOIN conversations c ON c.id = j.conversation_id "
            "JOIN client_environments ce ON ce.id = c.environment_id "
            "WHERE j.id = %s",
            (job_id,),
        )
        row = cur.fetchone()
        if not row:
            return
        environment_id, project_id = row
        cur.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM project_images WHERE environment_id = %s",
            (environment_id,),
        )
        next_order = cur.fetchone()[0]
        image_id = "pi" + secrets.token_hex(8)
        cur.execute(
            "INSERT INTO project_images (id, project_id, storage_key, mime, room_type, environment_id, sort_order) "
            "VALUES (%s, %s, %s, %s, 'outro', %s, %s)",
            (image_id, project_id, key, mime, environment_id, next_order),
        )


async def _run_image_job(job_id: str, image_bytes: bytes, mime: str, prompt: str, engine: str) -> None:
    from app import storage
    from app.image_engines import ENGINES, ImageGenerationError

    impl = ENGINES.get(engine)
    try:
        if impl is None:
            raise ImageGenerationError(f"Engine desconhecido: {engine}")
        _update_job(job_id, status="processing")
        asyncio.create_task(_run_render_params(job_id, prompt))
        result_bytes, result_mime = await impl.generate(image_bytes, mime, _build_prompt(prompt))
        key = _image_key(job_id, result_mime)
        storage.put(key, result_bytes, result_mime)
        _update_job(job_id, status="done", image_path=key, image_mime=result_mime)
        _bridge_to_project_images(job_id, key, result_mime)
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
    from app import storage
    from app.main import DB_ENABLED, _db, require_user

    user = require_user(request)
    if not DB_ENABLED:
        raise HTTPException(503, "Banco de dados não configurado.")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(400, "Imagem vazia ou não enviada.")
    mime = image.content_type or "image/jpeg"
    job_id = "i" + secrets.token_hex(8)

    # Guarda a imagem original — sem isso não dá pra oferecer "Refazer" depois
    # (a chamada ao fornecedor consome o arquivo, não fica guardado em lugar
    # nenhum além daqui).
    source_key = _image_key(job_id, mime, kind="src")
    storage.put(source_key, image_bytes, mime)

    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO image_jobs (id, username, conversation_id, engine, prompt, source_path, source_mime) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (job_id, user["username"], conversation_id, DEFAULT_ENGINE, prompt or "", source_key, mime),
        )
    asyncio.create_task(_run_image_job(job_id, image_bytes, mime, prompt or "", DEFAULT_ENGINE))
    return {"id": job_id, "status": "queued"}


@router.post("/jobs/{job_id}/redo")
async def redo_job(job_id: str, request: Request, prompt: str | None = Form(None)):
    """Gera de novo a partir da MESMA imagem de origem de um job anterior,
    opcionalmente com um prompt novo/ajustado. Vira um job novo e independente
    (não sobrescreve o resultado anterior — a arquiteta pode comparar os dois)."""
    from app import storage
    from app.main import DB_ENABLED, _db, require_user

    user = require_user(request)  # conversas são compartilhadas — qualquer membro pode refazer
    if not DB_ENABLED:
        raise HTTPException(503, "Banco de dados não configurado.")
    original = _get_job(job_id)
    if not original:
        raise HTTPException(404, "Job original não encontrado.")
    image_bytes = storage.get(original["sourcePath"]) if original["sourcePath"] else None
    if image_bytes is None:
        raise HTTPException(400, "Imagem de origem não disponível pra refazer (job antigo demais).")

    mime = original["sourceMime"] or "image/jpeg"
    final_prompt = prompt if prompt is not None else (original["prompt"] or "")

    new_job_id = "i" + secrets.token_hex(8)
    new_source_key = _image_key(new_job_id, mime, kind="src")
    storage.put(new_source_key, image_bytes, mime)

    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO image_jobs (id, username, conversation_id, engine, prompt, source_path, source_mime) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                new_job_id, user["username"], original["conversationId"],
                DEFAULT_ENGINE, final_prompt, new_source_key, mime,
            ),
        )
    asyncio.create_task(_run_image_job(new_job_id, image_bytes, mime, final_prompt, DEFAULT_ENGINE))
    return {"id": new_job_id, "status": "queued", "prompt": final_prompt}


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


@router.get("/jobs/download-all")
def download_all_jobs(request: Request, conversation_id: str):
    """Baixa em lote (.zip) todas as imagens já prontas de uma conversa —
    registrado ANTES de /jobs/{job_id} de propósito, senão "download-all"
    seria interpretado como um job_id."""
    import io
    import zipfile

    from fastapi.responses import Response

    from app import storage
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        raise HTTPException(503, "Banco de dados não configurado.")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT image_path FROM image_jobs WHERE conversation_id = %s "
            "AND status = 'done' AND image_path IS NOT NULL ORDER BY created_at",
            (conversation_id,),
        )
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(404, "Nenhuma imagem pronta nesta conversa.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (key,) in enumerate(rows, start=1):
            if not key:
                continue
            data = storage.get(key)
            if data is None:
                continue
            ext = key.rsplit(".", 1)[-1] if "." in key else "png"
            zf.writestr(f"render_{i:02d}.{ext}", data)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="renders.zip"'},
    )


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
        "prompt": job["prompt"],
        "canRedo": bool(job["sourcePath"]),
        "paramLight": job["paramLight"],
        "paramTexture": job["paramTexture"],
        "paramCamera": job["paramCamera"],
    }


@router.get("/file/{job_id}")
def get_file(job_id: str, request: Request):
    from fastapi.responses import Response

    from app import storage
    from app.main import require_user

    require_user(request)
    job = _get_job(job_id)
    if not job or job["status"] != "done" or not job["imagePath"]:
        raise HTTPException(404, "Imagem não disponível.")
    data = storage.get(job["imagePath"])
    if data is None:
        raise HTTPException(404, "Imagem não disponível.")
    return Response(content=data, media_type=job["imageMime"] or "image/png")
