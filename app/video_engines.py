"""Integrações com os fornecedores de geração de vídeo (Luma, Veo) + um engine
"stub" usado em testes locais sem precisar de chave de API real.

Regra inegociável (ver memória "Confidencialidade do stack de IA"): nada aqui
pode vazar para o navegador. Toda chamada é feita pelo servidor; erros de
fornecedor nunca chegam crus ao cliente — `app/video.py` sempre captura
`VendorGenerationError` e devolve uma mensagem genérica.

Interface comum que cada engine implementa:
    async def start(job_id, image_bytes, mime, prompt, public_base_url) -> (vendor_job_id, stage_token)
    async def poll(vendor_job_id) -> bool                      # True = pronto
    async def download(vendor_job_id) -> bytes                 # bytes do mp4 final
`stage_token` é None quando o engine não precisa hospedar a imagem (caso do Veo,
que aceita base64 inline). Quando não é None, é o token gerado por
`app.video._stage_image`, usado só pelo Luma.
"""

import os
import time

import httpx


class VendorGenerationError(Exception):
    """Qualquer falha do lado do fornecedor — nunca deve vazar texto cru pro cliente."""


# --- Stub (testes locais, sem chave de API) ---------------------------------
class StubEngine:
    """Simula ~5s de processamento e devolve um mp4 minúsculo de mentirinha."""

    STUB_DELAY_SECONDS = 5

    async def start(self, job_id, image_bytes, mime, prompt, public_base_url):
        ready_at = time.time() + self.STUB_DELAY_SECONDS
        return f"stub-{ready_at}", None

    async def poll(self, vendor_job_id):
        ready_at = float(vendor_job_id.split("stub-", 1)[1])
        return time.time() >= ready_at

    async def download(self, vendor_job_id):
        # Não é um mp4 válido de verdade — só serve pra validar o encanamento
        # (job muda de estado, arquivo é salvo e servido pelo próprio domínio).
        return b"\x00\x00\x00\x18ftypmp42stub-video-content-for-local-testing"


# --- Google Veo 3.1 (Gemini API) --------------------------------------------
class VeoEngine:
    MODEL = "veo-3.1-fast-generate-preview"
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def _api_key(self):
        key = os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise VendorGenerationError("GOOGLE_API_KEY não configurada.")
        return key

    async def start(self, job_id, image_bytes, mime, prompt, public_base_url):
        import base64

        body = {
            "instances": [
                {
                    "prompt": prompt or "Anime esta imagem com um movimento de câmera sutil.",
                    "image": {
                        "inlineData": {
                            "mimeType": mime or "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                }
            ],
            "parameters": {"aspectRatio": "16:9", "resolution": "720p"},
        }
        headers = {"x-goog-api-key": self._api_key(), "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.BASE}/models/{self.MODEL}:predictLongRunning",
                json=body, headers=headers,
            )
        if resp.status_code >= 400:
            raise VendorGenerationError(f"Veo start falhou: {resp.status_code} {resp.text[:300]}")
        name = resp.json().get("name")
        if not name:
            raise VendorGenerationError("Veo start: resposta sem 'name' de operação.")
        return name, None

    async def poll(self, vendor_job_id):
        headers = {"x-goog-api-key": self._api_key()}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.BASE}/{vendor_job_id}", headers=headers)
        if resp.status_code >= 400:
            raise VendorGenerationError(f"Veo poll falhou: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        if data.get("error"):
            raise VendorGenerationError(f"Veo retornou erro: {data['error']}")
        return bool(data.get("done"))

    async def download(self, vendor_job_id):
        headers = {"x-goog-api-key": self._api_key()}
        async with httpx.AsyncClient(timeout=30) as client:
            status_resp = await client.get(f"{self.BASE}/{vendor_job_id}", headers=headers)
            data = status_resp.json()
            try:
                uri = data["response"]["generateVideoResponse"]["generatedSamples"][0]["video"]["uri"]
            except (KeyError, IndexError) as e:
                raise VendorGenerationError(f"Veo: não achei a URI do vídeo pronto ({e}).")
            video_resp = await client.get(uri, headers=headers)
        if video_resp.status_code >= 400:
            raise VendorGenerationError(f"Veo download falhou: {video_resp.status_code}")
        return video_resp.content


# --- Luma Ray (Dream Machine API) -------------------------------------------
class LumaEngine:
    MODEL = "ray-2"
    BASE = "https://api.lumalabs.ai/dream-machine/v1"

    def _headers(self):
        key = os.environ.get("LUMA_API_KEY")
        if not key:
            raise VendorGenerationError("LUMA_API_KEY não configurada.")
        return {"accept": "application/json", "authorization": f"Bearer {key}", "content-type": "application/json"}

    async def start(self, job_id, image_bytes, mime, prompt, public_base_url):
        from app.video import _stage_image  # import local: evita ciclo com app.video

        stage_token = _stage_image(job_id, image_bytes, mime)
        image_url = f"{public_base_url.rstrip('/')}/api/video/staged/{stage_token}"
        body = {
            "prompt": prompt or "Anime esta imagem com um movimento de câmera sutil.",
            "model": self.MODEL,
            "keyframes": {"frame0": {"type": "image", "url": image_url}},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{self.BASE}/generations", json=body, headers=self._headers())
        if resp.status_code >= 400:
            raise VendorGenerationError(f"Luma start falhou: {resp.status_code} {resp.text[:300]}")
        gen_id = resp.json().get("id")
        if not gen_id:
            raise VendorGenerationError("Luma start: resposta sem 'id' de geração.")
        return gen_id, stage_token

    async def poll(self, vendor_job_id):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.BASE}/generations/{vendor_job_id}", headers=self._headers())
        if resp.status_code >= 400:
            raise VendorGenerationError(f"Luma poll falhou: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        state = data.get("state")
        if state == "failed":
            raise VendorGenerationError(f"Luma reportou falha: {data.get('failure_reason')}")
        return state == "completed"

    async def download(self, vendor_job_id):
        async with httpx.AsyncClient(timeout=30) as client:
            status_resp = await client.get(f"{self.BASE}/generations/{vendor_job_id}", headers=self._headers())
            data = status_resp.json()
            video_url = (data.get("assets") or {}).get("video")
            if not video_url:
                raise VendorGenerationError("Luma: não achei a URL do vídeo pronto.")
            video_resp = await client.get(video_url)
        if video_resp.status_code >= 400:
            raise VendorGenerationError(f"Luma download falhou: {video_resp.status_code}")
        return video_resp.content


ENGINES = {
    "stub": StubEngine(),
    "veo": VeoEngine(),
    "luma": LumaEngine(),
}
