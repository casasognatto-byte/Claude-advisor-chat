"""Integração com o fornecedor de geração de imagem (Nano Banana, via Gemini
API) + um engine "stub" para testes locais sem chave real.

Ao contrário do vídeo (Luma/Veo, que levam 1-3 minutos e exigem fila +
polling), a geração de imagem é rápida (segundos) — cada engine expõe um
único método `generate()` que já devolve os bytes prontos, sem precisar de
start/poll/download separados.

Escolhi a API `generateContent` (`models/{model}:generateContent`), que é a
forma bem documentada e amplamente confirmada de usar os modelos Gemini de
imagem — existem indícios de uma "Interactions API" mais nova para geração de
imagem, mas a documentação que encontrei sobre ela era inconsistente com as
convenções usuais da API do Gemini; prudente confirmar contra a doc oficial
antes de trocar, quando o Davi tiver uma GOOGLE_API_KEY real pra testar.
"""

import base64
import os

import httpx


class ImageGenerationError(Exception):
    """Qualquer falha do lado do fornecedor — nunca deve vazar texto cru pro cliente."""


class StubImageEngine:
    async def generate(self, image_bytes: bytes, mime: str, prompt: str) -> tuple[bytes, str]:
        import asyncio

        await asyncio.sleep(2)
        return b"\x89PNGstub-image-content-for-local-testing", "image/png"


class NanoBananaEngine:
    # Atualizado em 2026-07-07: "gemini-2.5-flash-image" é o Nano Banana
    # ORIGINAL, já chamado de "legado" pela própria Google — testamos e o
    # resultado não seguia bem nomes de material/marca específicos (ex.
    # "Suvinil crômio", "quartzito Taj Mahal"). O Nano Banana Pro
    # (gemini-3-pro-image) é anunciado com "consistência precisa de marca"
    # como recurso principal — é o que usamos por padrão agora. Alternativa
    # mais barata (~metade do preço, menos precisa): "gemini-3.1-flash-image"
    # (Nano Banana 2). Configurável via IMAGE_MODEL sem precisar mexer aqui.
    MODEL = os.environ.get("IMAGE_MODEL", "gemini-3-pro-image")
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def _api_key(self):
        key = os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ImageGenerationError("GOOGLE_API_KEY não configurada.")
        return key

    async def generate(self, image_bytes: bytes, mime: str, prompt: str) -> tuple[bytes, str]:
        body = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                            or "Transforme esta imagem em um render fotorrealista, "
                            "preservando composição, proporções e materiais indicados."
                        },
                        {
                            "inline_data": {
                                "mime_type": mime or "image/jpeg",
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                    ]
                }
            ]
        }
        headers = {"x-goog-api-key": self._api_key(), "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{self.BASE}/models/{self.MODEL}:generateContent", json=body, headers=headers
            )
        if resp.status_code >= 400:
            raise ImageGenerationError(f"Nano Banana falhou: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as e:
            raise ImageGenerationError(f"Resposta sem candidates/parts ({e}).")
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime_out = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                return base64.b64decode(inline["data"]), mime_out
        raise ImageGenerationError("Nenhuma imagem encontrada na resposta do Nano Banana.")


ENGINES = {
    "stub": StubImageEngine(),
    "nanobanana": NanoBananaEngine(),
}
