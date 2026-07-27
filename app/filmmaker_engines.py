"""Integracao com o motor de montagem de video Creatomate.

O Filmmaker trabalha com EDICAO de videos reais (upload do usuario),
nao com geracao de video por IA a partir de imagens (isso foi abandonado
em 08/07/2026 por infidelidade visual do Luma).

Fluxo completo (a implementar por etapas):
1. Upload + compressao do video original (ffmpeg: 4K -> 1080p, 15s)
2. Extracao de frames (5-6 frames por clip, nao 3 como na versao anterior)
3. Analise da IA (Claude Opus) nos frames -> sequencia com trim_start/trim_end
4. Montagem no Creatomate usando a sequencia da IA
5. Download do video final
6. Geracao de roteiro/legendas/hashtags (Claude API)

Este arquivo comeca com stub + esqueleto Creatomate. A logica de
compressao/extracao ficara em app/filmmaker.py (ffmpeg via subprocess).
"""

import os

import httpx


class FilmmakerError(Exception):
    """Qualquer falha do motor — nunca vaza texto cru pro cliente."""


class StubFilmmakerEngine:
    """Engine de teste local. Nao chama API externa."""

    async def render(self, sequence: list[dict]) -> tuple[bytes, str]:
        import asyncio

        await asyncio.sleep(3)
        # Retorna um MP4 dummy (header de arquivo MP4 invalido, so pra teste)
        return b"\x00\x00\x00\x20ftypisom", "video/mp4"


class CreatomateEngine:
    """Motor de montagem Creatomate (API REST).

    Documentacao: https://creatomate.com/docs/api
    Endpoint base: https://api.creatomate.com/v1
    Autenticacao: Bearer token (CREATOMATE_API_KEY)

    O Creatomate recebe um JSON de "source" descrevendo o video:
    - clips: lista de elementos (video, imagem, texto)
    - transicoes: entre clips (crossfade, etc.)
    - audio: trilha de fundo
    - texto: legendas/sobreposicoes

    Exemplo de payload minimo:
    {
      "source": {
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "elements": [
          {
            "type": "video",
            "source": "https://.../clip1.mp4",
            "trim_start": 2.5,
            "trim_end": 7.0
          },
          {
            "type": "video",
            "source": "https://.../clip2.mp4",
            "trim_start": 0.0,
            "trim_end": 5.0,
            "transition": {"type": "crossfade", "duration": 0.5}
          }
        ]
      }
    }

    Resposta: {"id": "render_xxx", "status": "rendering", ...}
    Polling: GET /renders/{id}
    Quando status == "succeeded", video em "url".
    """

    BASE = "https://api.creatomate.com/v1"
    TIMEOUT = int(os.environ.get("CREATOMATE_TIMEOUT", "300"))

    def _api_key(self):
        key = os.environ.get("CREATOMATE_API_KEY")
        if not key:
            raise FilmmakerError("CREATOMATE_API_KEY nao configurada.")
        return key

    async def start_render(self, source: dict) -> str:
        """Inicia um render no Creatomate. Retorna o render ID."""
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(f"{self.BASE}/renders", json={"source": source}, headers=headers)
        if resp.status_code >= 400:
            raise FilmmakerError(f"Creatomate falhou ao iniciar: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        render_id = data.get("id")
        if not render_id:
            raise FilmmakerError("Creatomate nao retornou render id.")
        return render_id

    async def poll_render(self, render_id: str) -> dict:
        """Consulta status de um render. Retorna dict completo da API."""
        headers = {"Authorization": f"Bearer {self._api_key()}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.BASE}/renders/{render_id}", headers=headers)
        if resp.status_code >= 400:
            raise FilmmakerError(f"Creatomate falhou no poll: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    async def download_video(self, url: str) -> bytes:
        """Baixa o video final da URL fornecida pelo Creatomate."""
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            raise FilmmakerError(f"Falha ao baixar video: {resp.status_code} {resp.text[:300]}")
        return resp.content

    async def render(self, sequence: list[dict]) -> tuple[bytes, str]:
        """Caminho completo: monta source, inicia render, faz poll, baixa video.

        sequence = lista de dicts com:
          - source_url (str): URL publica do clip no storage
          - trim_start (float): segundo inicial
          - trim_end (float): segundo final
          - transition (dict, opcional): ex. {"type": "crossfade", "duration": 0.5}
        """
        # TODO: implementar montagem do source JSON, start, poll loop, download
        raise NotImplementedError("render() completo ainda nao implementado — use start_render + poll_render manualmente.")


ENGINES = {
    "stub": StubFilmmakerEngine(),
    "creatomate": CreatomateEngine(),
}
