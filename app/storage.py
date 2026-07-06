"""Armazenamento de arquivos da Biblioteca de Apresentações (projetos de
cliente): imagens do Promob, clipes gerados e vídeo final.

Usa Cloudflare R2 (compatível com S3, sem custo de egress) quando as
variáveis R2_* estão configuradas; cai para disco local senão — mesmo padrão
de fallback usado em app/video.py e app/image.py, útil pra dev/teste sem
custo e sem precisar de conta na nuvem.
"""

import os
import tempfile

_R2_BUCKET = os.environ.get("R2_BUCKET")
_R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
_R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
_R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")

R2_ENABLED = bool(_R2_BUCKET and _R2_ACCOUNT_ID and _R2_ACCESS_KEY_ID and _R2_SECRET_ACCESS_KEY)

_client = None


def _r2_client():
    global _client
    if _client is None:
        import boto3

        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=_R2_ACCESS_KEY_ID,
            aws_secret_access_key=_R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
    return _client


def _local_root() -> str:
    d = os.environ.get("PRESENTATIONS_STORAGE_DIR") or os.path.join(
        tempfile.gettempdir(), "casasognatto_presentations"
    )
    os.makedirs(d, exist_ok=True)
    return d


def _local_path(key: str) -> str:
    return os.path.join(_local_root(), key.replace("/", "__"))


def put(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    if R2_ENABLED:
        _r2_client().put_object(Bucket=_R2_BUCKET, Key=key, Body=data, ContentType=content_type)
        return
    with open(_local_path(key), "wb") as f:
        f.write(data)


def get(key: str) -> bytes | None:
    if R2_ENABLED:
        try:
            resp = _r2_client().get_object(Bucket=_R2_BUCKET, Key=key)
            return resp["Body"].read()
        except Exception:
            return None
    path = _local_path(key)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def delete(key: str) -> None:
    if R2_ENABLED:
        try:
            _r2_client().delete_object(Bucket=_R2_BUCKET, Key=key)
        except Exception:
            pass
        return
    path = _local_path(key)
    if os.path.exists(path):
        os.remove(path)
