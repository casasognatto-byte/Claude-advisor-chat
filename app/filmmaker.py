"""Filmmaker — modulo de producao de conteudo com IA para redes sociais.

Reaproveita autenticacao e banco do advisor-chat. Cada projeto de video
pertence a um usuario e contem roteiro, cenas (imagens/video curtos) e
configuracoes de montagem.

Imports de `app.main` ficam dentro das funcoes para evitar import circular.
Arquivos ficam em `app.storage` (R2 ou disco local).

Historico: modulo anterior `app/video.py` foi removido em 08/07/2026 por
infidelidade visual dos modelos de IA (Luma/Veo). Este modulo novo comeca
com esqueleto limpo, usando Creatomate como motor de montagem e focando em
fidelidade ao roteiro e ao projeto de interiores.
"""

import base64
import json
import os
import secrets
import shutil
import subprocess
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/filmmaker")

GENERIC_ERROR = "Falha ao processar o projeto, tente novamente."
DEFAULT_ENGINE = os.environ.get("FILMMAKER_ENGINE", "creatomate")


class CreateProjectRequest(BaseModel):
    title: str
    roteiro: str | None = None
    configuracoes: dict | None = None


class CreateJobRequest(BaseModel):
    project_id: str
    tipo: str  # "cena" | "montagem" | "legenda"
    prompt: str | None = None
    referencia_path: str | None = None


def _generate_id() -> str:
    return secrets.token_urlsafe(16)


def _sign_public_token(path: str) -> str:
    """Gera um token temporario para acesso publico a um arquivo no storage.
    O token eh valido por 1 hora e depende do SECRET_KEY do ambiente.
    """
    import hashlib
    import time

    secret = os.environ.get("SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError("SECRET_KEY nao configurada — necessaria para tokens publicos.")
    ts = str(int(time.time() // 3600))  # janela de 1h
    raw = f"{path}:{ts}:{secret}"
    sig = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"{ts}.{sig}.{base64.urlsafe_b64encode(path.encode()).decode().rstrip('=')}"


def _verify_public_token(token: str) -> str | None:
    """Valida um token publico e retorna o path se valido."""
    import hashlib
    import time

    secret = os.environ.get("SECRET_KEY", "").strip()
    if not secret:
        return None
    try:
        ts_str, sig, b64path = token.split(".", 2)
        # Recria assinatura
        path = base64.urlsafe_b64decode(b64path + "==").decode()
        raw = f"{path}:{ts_str}:{secret}"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:24]
        if not secrets.compare_digest(sig, expected):
            return None
        # Verifica expiracao (max 2 janelas de 1h para tolerancia)
        now = int(time.time() // 3600)
        if abs(now - int(ts_str)) > 2:
            return None
        return path
    except Exception:
        return None


def _ffmpeg_available() -> bool:
    """Verifica se ffmpeg esta instalado e no PATH."""
    return shutil.which("ffmpeg") is not None


def _compress_video(input_bytes: bytes) -> bytes:
    """Comprime video para 1080p, max 15s, usando ffmpeg.
    Requer ffmpeg instalado. Retorna bytes do MP4 comprimido.
    """
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg nao encontrado. Instale o ffmpeg e adicione ao PATH.")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.mp4")
        output_path = os.path.join(tmpdir, "output.mp4")
        with open(input_path, "wb") as f:
            f.write(input_bytes)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-vf", "scale=-2:1080",
            "-t", "15",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg falhou: {result.stderr[:500]}")

        with open(output_path, "rb") as f:
            return f.read()


def _extract_frames(video_bytes: bytes, num_frames: int = 5) -> list[bytes]:
    """Extrai N frames uniformemente distribuidos do video.
    Requer ffmpeg instalado. Retorna lista de bytes JPEG.
    """
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg nao encontrado. Instale o ffmpeg e adicione ao PATH.")

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, "video.mp4")
        with open(video_path, "wb") as f:
            f.write(video_bytes)

        # Extrai frames nos timestamps calculados
        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-vf", f"select='not(mod(n\\,{max(1, 30 // num_frames)}))',scale=480:-1",
            "-vsync", "vfr",
            "-q:v", "2",
            "-frames:v", str(num_frames),
            os.path.join(tmpdir, "frame_%03d.jpg"),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg falhou na extracao de frames: {result.stderr[:500]}")

        frames = []
        for fname in sorted(os.listdir(tmpdir)):
            if fname.startswith("frame_") and fname.endswith(".jpg"):
                with open(os.path.join(tmpdir, fname), "rb") as f:
                    frames.append(f.read())
        return frames


def init_filmmaker_db() -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS filmmaker_projects (
                    id          TEXT PRIMARY KEY,
                    username    TEXT NOT NULL,
                    title       TEXT NOT NULL DEFAULT 'Novo projeto',
                    status      TEXT NOT NULL DEFAULT 'draft',
                    roteiro     TEXT,
                    configuracoes JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS filmmaker_jobs (
                    id          TEXT PRIMARY KEY,
                    project_id  TEXT NOT NULL REFERENCES filmmaker_projects(id) ON DELETE CASCADE,
                    username    TEXT NOT NULL,
                    tipo        TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'queued',
                    engine      TEXT NOT NULL DEFAULT 'creatomate',
                    prompt      TEXT,
                    error_message TEXT,
                    media_path  TEXT,
                    referencia_path TEXT,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            # Migração aditiva — media (video comprimido + frames) do projeto
            cur.execute("ALTER TABLE filmmaker_projects ADD COLUMN IF NOT EXISTS media JSONB NOT NULL DEFAULT '{}'::jsonb;")
            # Migração aditiva — render_id do Creatomate para polling
            cur.execute("ALTER TABLE filmmaker_jobs ADD COLUMN IF NOT EXISTS render_id TEXT;")
    except Exception as e:
        print(f"[init_filmmaker_db] falha: {e}")


def _require_user(request: Request) -> str:
    """Retorna username da sessao ou levanta 401."""
    from app.main import require_user

    user = require_user(request)
    return user["username"]


@router.get("/projects")
async def list_projects(request: Request):
    """Lista projetos do usuario logado."""
    username = _require_user(request)
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return {"projects": []}
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, status, created_at, updated_at
                FROM filmmaker_projects
                WHERE username = %s
                ORDER BY updated_at DESC
                """,
                (username,),
            )
            rows = cur.fetchall()
            return {
                "projects": [
                    {
                        "id": r[0],
                        "title": r[1],
                        "status": r[2],
                        "created_at": r[3].isoformat() if r[3] else None,
                        "updated_at": r[4].isoformat() if r[4] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        print(f"[filmmaker/list_projects] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.post("/projects")
async def create_project(request: Request, body: CreateProjectRequest):
    """Cria um novo projeto de video."""
    username = _require_user(request)
    from app.main import DB_ENABLED, _db

    project_id = _generate_id()
    if not DB_ENABLED:
        return {"id": project_id, "title": body.title, "status": "draft"}
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO filmmaker_projects (id, username, title, roteiro, configuracoes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (project_id, username, body.title, body.roteiro or "", json.dumps(body.configuracoes or {})),
            )
            conn.commit()
            return {"id": project_id, "title": body.title, "status": "draft"}
    except Exception as e:
        print(f"[filmmaker/create_project] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    """Retorna detalhes de um projeto e seus jobs."""
    username = _require_user(request)
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, status, roteiro, configuracoes, created_at, updated_at
                FROM filmmaker_projects
                WHERE id = %s AND username = %s
                """,
                (project_id, username),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Projeto nao encontrado")

            cur.execute(
                """
                SELECT id, tipo, status, engine, prompt, media_path, created_at, updated_at
                FROM filmmaker_jobs
                WHERE project_id = %s
                ORDER BY created_at ASC
                """,
                (project_id,),
            )
            jobs = cur.fetchall()

            return {
                "id": row[0],
                "title": row[1],
                "status": row[2],
                "roteiro": row[3],
                "configuracoes": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
                "updated_at": row[6].isoformat() if row[6] else None,
                "jobs": [
                    {
                        "id": j[0],
                        "tipo": j[1],
                        "status": j[2],
                        "engine": j[3],
                        "prompt": j[4],
                        "media_path": j[5],
                        "created_at": j[6].isoformat() if j[6] else None,
                        "updated_at": j[7].isoformat() if j[7] else None,
                    }
                    for j in jobs
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[filmmaker/get_project] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.post("/jobs")
async def create_job(request: Request, body: CreateJobRequest):
    """Cria um job de geracao dentro de um projeto."""
    username = _require_user(request)
    from app.main import DB_ENABLED, _db

    job_id = _generate_id()
    if not DB_ENABLED:
        return {"id": job_id, "status": "queued"}
    try:
        with _db() as conn, conn.cursor() as cur:
            # Verifica se projeto existe e pertence ao usuario
            cur.execute(
                "SELECT 1 FROM filmmaker_projects WHERE id = %s AND username = %s",
                (body.project_id, username),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Projeto nao encontrado")

            cur.execute(
                """
                INSERT INTO filmmaker_jobs (id, project_id, username, tipo, prompt, referencia_path)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (job_id, body.project_id, username, body.tipo, body.prompt or "", body.referencia_path),
            )
            conn.commit()
            return {"id": job_id, "status": "queued"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[filmmaker/create_job] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    """Retorna status de um job."""
    username = _require_user(request)
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return {"id": job_id, "status": "queued"}
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT j.id, j.tipo, j.status, j.engine, j.prompt, j.media_path,
                       j.error_message, j.created_at, j.updated_at, p.id, p.title
                FROM filmmaker_jobs j
                JOIN filmmaker_projects p ON p.id = j.project_id
                WHERE j.id = %s AND j.username = %s
                """,
                (job_id, username),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job nao encontrado")
            return {
                "id": row[0],
                "tipo": row[1],
                "status": row[2],
                "engine": row[3],
                "prompt": row[4],
                "media_path": row[5],
                "error_message": row[6],
                "created_at": row[7].isoformat() if row[7] else None,
                "updated_at": row[8].isoformat() if row[8] else None,
                "project_id": row[9],
                "project_title": row[10],
            }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[filmmaker/get_job] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.post("/projects/{project_id}/upload")
async def upload_video(project_id: str, request: Request, file: UploadFile = File(...)):
    """Recebe video original, comprime (1080p/15s), extrai frames e salva no storage.
    Requer ffmpeg instalado no servidor. Atualiza a coluna 'media' do projeto.
    """
    username = _require_user(request)
    from app.main import DB_ENABLED, _db
    from app import storage

    if not DB_ENABLED:
        raise HTTPException(status_code=503, detail="Banco de dados nao configurado.")

    # Valida mime type basico
    mime = (file.content_type or "application/octet-stream").lower()
    if not mime.startswith("video/"):
        raise HTTPException(status_code=400, detail="Arquivo nao e um video.")

    try:
        raw_bytes = await file.read()
        if len(raw_bytes) == 0:
            raise HTTPException(status_code=400, detail="Arquivo vazio.")

        # Compressao
        try:
            compressed = _compress_video(raw_bytes)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

        # Extracao de frames (5 frames por padrao — mais que os 3 da versao anterior)
        try:
            frames = _extract_frames(compressed, num_frames=5)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

        # Salva no storage
        base_key = f"filmmaker/{project_id}"
        video_key = f"{base_key}/compressed.mp4"
        storage.put(video_key, compressed, content_type="video/mp4")

        frame_keys = []
        for idx, frame_bytes in enumerate(frames, start=1):
            frame_key = f"{base_key}/frame_{idx:03d}.jpg"
            storage.put(frame_key, frame_bytes, content_type="image/jpeg")
            frame_keys.append(frame_key)

        # Atualiza banco
        media = {
            "original": {"mime": mime, "size_bytes": len(raw_bytes)},
            "compressed": {"path": video_key, "mime": "video/mp4", "size_bytes": len(compressed)},
            "frames": [{"path": k, "mime": "image/jpeg"} for k in frame_keys],
        }
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE filmmaker_projects
                SET media = %s, status = 'uploaded', updated_at = now()
                WHERE id = %s AND username = %s
                RETURNING 1
                """,
                (json.dumps(media), project_id, username),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
            conn.commit()

        return {
            "project_id": project_id,
            "status": "uploaded",
            "compressed": {"path": video_key, "size_bytes": len(compressed)},
            "frames_count": len(frame_keys),
            "frames": frame_keys,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[filmmaker/upload_video] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.get("/projects/{project_id}/download")
async def download_video(project_id: str, request: Request):
    """Serve o video comprimido de um projeto."""
    username = _require_user(request)
    from app.main import DB_ENABLED, _db
    from app import storage

    if not DB_ENABLED:
        raise HTTPException(status_code=503, detail="Banco de dados nao configurado.")

    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT media FROM filmmaker_projects WHERE id = %s AND username = %s",
            (project_id, username),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="Video nao encontrado.")

        media = row[0]
        video_key = media.get("compressed", {}).get("path")
        if not video_key:
            raise HTTPException(status_code=404, detail="Video nao processado ainda.")

        data = storage.get(video_key)
        if data is None:
            raise HTTPException(status_code=404, detail="Video nao disponivel no storage.")

        return Response(content=data, media_type="video/mp4")


@router.get("/projects/{project_id}/frames/{frame_index}")
async def download_frame(project_id: str, frame_index: int, request: Request):
    """Serve um frame especifico do projeto."""
    username = _require_user(request)
    from app.main import DB_ENABLED, _db
    from app import storage

    if not DB_ENABLED:
        raise HTTPException(status_code=503, detail="Banco de dados nao configurado.")

    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT media FROM filmmaker_projects WHERE id = %s AND username = %s",
            (project_id, username),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="Projeto nao encontrado.")

        media = row[0]
        frames = media.get("frames", [])
        if frame_index < 1 or frame_index > len(frames):
            raise HTTPException(status_code=404, detail="Frame nao encontrado.")

        frame_key = frames[frame_index - 1].get("path")
        data = storage.get(frame_key)
        if data is None:
            raise HTTPException(status_code=404, detail="Frame nao disponivel no storage.")

        return Response(content=data, media_type="image/jpeg")


@router.post("/projects/{project_id}/analyze")
async def analyze_project(project_id: str, request: Request):
    """Analisa os frames do projeto com Claude Opus e gera sequencia de montagem.
    Retorna a sequencia sugerida (JSON) e a salva no projeto.
    """
    username = _require_user(request)
    from app.main import DB_ENABLED, _db
    from app import storage

    if not DB_ENABLED:
        raise HTTPException(status_code=503, detail="Banco de dados nao configurado.")

    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY nao configurada.")

    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT media, roteiro FROM filmmaker_projects WHERE id = %s AND username = %s",
                (project_id, username),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Projeto nao encontrado.")

            media = row[0] or {}
            roteiro = row[1] or ""
            frames_meta = media.get("frames", [])
            if not frames_meta:
                raise HTTPException(status_code=400, detail="Nenhum frame encontrado. Faca o upload do video primeiro.")

            # Carrega frames do storage e converte para base64
            content = []
            content.append({
                "type": "text",
                "text": (
                    "Voce e um editor de video profissional. Analise os frames abaixo "
                    "de um video original e sugira uma sequencia de clips para montagem.\n\n"
                    f"Roteiro fornecido pelo usuario:\n{roteiro}\n\n"
                    "Para cada frame, indique:\n"
                    "- trim_start: segundo inicial no video original\n"
                    "- trim_end: segundo final no video original\n"
                    "- descricao: o que aparece na cena\n"
                    "- transition: tipo de transicao para o proximo clip (crossfade, cut, none)\n\n"
                    "Regras:\n"
                    "- Cada clip deve ter entre 2 e 5 segundos.\n"
                    "- A sequencia deve seguir o roteiro fornecido.\n"
                    "- Use transicoes suaves (crossfade) entre clips.\n"
                    "- Nao invente conteudo que nao apareca nos frames.\n\n"
                    "Responda APENAS com um JSON valido no formato:\n"
                    '{"clips": [{"trim_start": 0.0, "trim_end": 3.5, "descricao": "...", "transition": "crossfade"}, ...]}'
                ),
            })

            for fm in frames_meta:
                frame_data = storage.get(fm.get("path"))
                if not frame_data:
                    continue
                b64 = base64.b64encode(frame_data).decode("ascii")
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64,
                    },
                })

            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=4096,
                messages=[{"role": "user", "content": content}],
            )

            # Extrai texto da resposta
            text = ""
            for block in resp.content:
                if block.type == "text":
                    text += block.text

            # Tenta extrair JSON da resposta
            sequencia = None
            try:
                # Procura JSON entre chaves
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1:
                    sequencia = json.loads(text[start:end+1])
                else:
                    sequencia = {"raw": text}
            except Exception:
                sequencia = {"raw": text}

            # Salva no banco
            cur.execute(
                """
                UPDATE filmmaker_projects
                SET configuracoes = configuracoes || %s, status = 'analyzed', updated_at = now()
                WHERE id = %s AND username = %s
                """,
                (json.dumps({"sequencia": sequencia}), project_id, username),
            )
            conn.commit()

            return {"project_id": project_id, "status": "analyzed", "sequencia": sequencia}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[filmmaker/analyze] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.post("/projects/{project_id}/render")
async def render_project(project_id: str, request: Request):
    """Inicia a montagem do video final no Creatomate usando a sequencia analisada.
    Cria um job de montagem e retorna o job_id para acompanhamento.
    """
    username = _require_user(request)
    from app.main import DB_ENABLED, _db
    from app import storage

    if not DB_ENABLED:
        raise HTTPException(status_code=503, detail="Banco de dados nao configurado.")

    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT media, configuracoes FROM filmmaker_projects WHERE id = %s AND username = %s",
                (project_id, username),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Projeto nao encontrado.")

            media = row[0] or {}
            configuracoes = row[1] or {}
            sequencia = configuracoes.get("sequencia", {})
            clips = sequencia.get("clips", [])
            if not clips:
                raise HTTPException(status_code=400, detail="Nenhuma sequencia analisada. Execute /analyze primeiro.")

            video_key = media.get("compressed", {}).get("path")
            if not video_key:
                raise HTTPException(status_code=400, detail="Video comprimido nao encontrado. Faca o upload primeiro.")

            # Verifica se o video existe no storage
            if storage.get(video_key) is None:
                raise HTTPException(status_code=404, detail="Video nao disponivel no storage.")

            # Constroi URL publica do video (token temporario para Creatomate)
            public_base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
            if not public_base:
                raise HTTPException(status_code=503, detail="PUBLIC_BASE_URL nao configurada. Necessaria para URL publica do video.")
            try:
                token = _sign_public_token(video_key)
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            video_url = f"{public_base}/api/filmmaker/public/{token}"

            # Monta payload do Creatomate
            elements = []
            for i, clip in enumerate(clips):
                el = {
                    "type": "video",
                    "source": video_url,
                    "trim_start": float(clip.get("trim_start", 0)),
                    "trim_end": float(clip.get("trim_end", 5)),
                }
                transition = clip.get("transition")
                if transition and transition != "none" and i < len(clips) - 1:
                    el["transition"] = {"type": transition, "duration": 0.5}
                elements.append(el)

            source = {
                "output_format": "mp4",
                "width": 1080,
                "height": 1920,
                "elements": elements,
            }

            # Inicia render no Creatomate
            from app.filmmaker_engines import ENGINES, FilmmakerError
            engine_name = os.environ.get("FILMMAKER_ENGINE", "stub")
            engine = ENGINES.get(engine_name, ENGINES["stub"])

            if engine_name == "stub":
                # Modo stub: simula render sem chamar API externa
                render_id = _generate_id()
            else:
                try:
                    render_id = await engine.start_render(source)
                except FilmmakerError as exc:
                    raise HTTPException(status_code=502, detail=str(exc))

            # Cria job de montagem no banco
            job_id = _generate_id()
            cur.execute(
                """
                INSERT INTO filmmaker_jobs (id, project_id, username, tipo, status, engine, prompt, render_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (job_id, project_id, username, "montagem", "rendering", engine_name, json.dumps(source), render_id),
            )
            conn.commit()

            return {
                "project_id": project_id,
                "job_id": job_id,
                "render_id": render_id,
                "status": "rendering",
                "engine": engine_name,
            }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[filmmaker/render] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.post("/jobs/{job_id}/poll")
async def poll_job(job_id: str, request: Request):
    """Consulta status de um job de montagem no Creatomate.
    Se o render terminou, baixa o video final e salva no storage.
    """
    username = _require_user(request)
    from app.main import DB_ENABLED, _db
    from app import storage

    if not DB_ENABLED:
        raise HTTPException(status_code=503, detail="Banco de dados nao configurado.")

    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT j.id, j.project_id, j.tipo, j.status, j.engine, j.prompt, j.media_path
                FROM filmmaker_jobs j
                JOIN filmmaker_projects p ON p.id = j.project_id
                WHERE j.id = %s AND j.username = %s
                """,
                (job_id, username),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job nao encontrado")

            _jid, project_id, tipo, status, engine_name, prompt_json, media_path = row

            # So processa jobs de montagem que ainda estao rendering
            if tipo != "montagem" or status != "rendering":
                return {"job_id": job_id, "status": status, "media_path": media_path}

            # Stub: simula conclusao imediata
            if engine_name == "stub":
                final_key = f"filmmaker/{project_id}/final.mp4"
                dummy_video = b"\x00\x00\x00\x20ftypisom"
                storage.put(final_key, dummy_video, content_type="video/mp4")
                cur.execute(
                    "UPDATE filmmaker_jobs SET status = 'done', media_path = %s, updated_at = now() WHERE id = %s",
                    (final_key, job_id),
                )
                conn.commit()
                return {"job_id": job_id, "status": "done", "media_path": final_key}

            # Creatomate: consulta API
            from app.filmmaker_engines import ENGINES, FilmmakerError
            engine = ENGINES.get(engine_name)
            if not engine:
                raise HTTPException(status_code=500, detail="Engine desconhecido.")

            render_id = row[7]  # indice da coluna render_id
            if not render_id:
                raise HTTPException(status_code=500, detail="render_id nao encontrado no job.")

            try:
                render_status = await engine.poll_render(render_id)
            except FilmmakerError as exc:
                raise HTTPException(status_code=502, detail=str(exc))

            cm_status = render_status.get("status", "unknown")
            if cm_status == "succeeded":
                video_url = render_status.get("url")
                if video_url:
                    try:
                        final_bytes = await engine.download_video(video_url)
                    except FilmmakerError as exc:
                        raise HTTPException(status_code=502, detail=f"Creatomate gerou o video, mas falhou ao baixar: {exc}")
                    final_key = f"filmmaker/{project_id}/final.mp4"
                    storage.put(final_key, final_bytes, content_type="video/mp4")
                    cur.execute(
                        "UPDATE filmmaker_jobs SET status = 'done', media_path = %s, updated_at = now() WHERE id = %s",
                        (final_key, job_id),
                    )
                    conn.commit()
                    return {"job_id": job_id, "status": "done", "media_path": final_key}
                else:
                    cur.execute(
                        "UPDATE filmmaker_jobs SET status = 'done', updated_at = now() WHERE id = %s",
                        (job_id,),
                    )
                    conn.commit()
                    return {"job_id": job_id, "status": "done", "note": "Video pronto, mas URL de download nao retornada."}
            elif cm_status in ("failed", "error"):
                error_msg = render_status.get("error", "Erro desconhecido no Creatomate")
                cur.execute(
                    "UPDATE filmmaker_jobs SET status = 'failed', error_message = %s, updated_at = now() WHERE id = %s",
                    (error_msg, job_id),
                )
                conn.commit()
                return {"job_id": job_id, "status": "failed", "error": error_msg}
            else:
                # Ainda rendering ou queued
                return {"job_id": job_id, "status": "rendering", "creatomate_status": cm_status}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[filmmaker/poll_job] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.post("/projects/{project_id}/roteiro")
async def gerar_roteiro(project_id: str, request: Request):
    """Gera roteiro, legendas e hashtags para o projeto usando Claude API.
    Salva o resultado no campo 'roteiro' do projeto.
    """
    username = _require_user(request)
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        raise HTTPException(status_code=503, detail="Banco de dados nao configurado.")

    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY nao configurada.")

    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT title, configuracoes FROM filmmaker_projects WHERE id = %s AND username = %s",
                (project_id, username),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Projeto nao encontrado.")

            title = row[0]
            configuracoes = row[1] or {}
            sequencia = configuracoes.get("sequencia", {})
            clips = sequencia.get("clips", [])

            prompt = (
                f"Crie um roteiro curto para um video de Instagram/YouTube sobre: {title}\n\n"
                "O roteiro deve ter:\n"
                "1. Gancho inicial (primeiros 3 segundos)\n"
                "2. Desenvolvimento (meio)\n"
                "3. Call-to-action (final)\n\n"
                "Tambem forneca:\n"
                "- 3 opcoes de legenda para o post\n"
                "- 10 hashtags relevantes\n\n"
                "Responda APENAS com JSON valido no formato:\n"
                '{"roteiro": "...", "legendas": ["...", "...", "..."], "hashtags": ["..."]}'
            )

            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )

            text = ""
            for block in resp.content:
                if block.type == "text":
                    text += block.text

            try:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1:
                    resultado = json.loads(text[start:end+1])
                else:
                    resultado = {"raw": text}
            except Exception:
                resultado = {"raw": text}

            roteiro_texto = resultado.get("roteiro", text)
            cur.execute(
                "UPDATE filmmaker_projects SET roteiro = %s, updated_at = now() WHERE id = %s",
                (roteiro_texto, project_id),
            )
            conn.commit()

            return {"project_id": project_id, "roteiro": resultado}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[filmmaker/roteiro] erro: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)


@router.get("/public/{token}")
async def public_media(token: str):
    """Serve um arquivo do storage via token publico temporario.
    Usado pelo Creatomate (ou outros servicos externos) para acessar clips.
    Nao requer autenticacao — a seguranca vem do token assinado e expiravel.
    """
    from app import storage

    path = _verify_public_token(token)
    if not path:
        raise HTTPException(status_code=403, detail="Token invalido ou expirado.")

    data = storage.get(path)
    if data is None:
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")

    # Detecta mime type pelo path
    mime = "application/octet-stream"
    if path.endswith(".mp4"):
        mime = "video/mp4"
    elif path.endswith(".jpg") or path.endswith(".jpeg"):
        mime = "image/jpeg"
    elif path.endswith(".png"):
        mime = "image/png"

    return Response(content=data, media_type=mime)
