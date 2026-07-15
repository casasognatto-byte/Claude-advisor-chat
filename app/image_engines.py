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
    async def generate(
        self, image_bytes: bytes, mime: str, prompt: str, reference_images: list[dict] | None = None
    ) -> tuple[bytes, str]:
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

    async def generate(
        self, image_bytes: bytes, mime: str, prompt: str, reference_images: list[dict] | None = None
    ) -> tuple[bytes, str]:
        parts = [
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
        # Fotos reais de swatch (recortadas do catálogo oficial do fabricante,
        # ver app/materials.py) — dão ao modelo a cor/textura exata em vez de
        # só o nome em texto, que ele podia interpretar de forma imprecisa.
        # Auditoria em 15/07/2026 (Davi pediu análise de todas as 51 imagens
        # cadastradas): 30 delas têm um texto de marca d'água do catálogo
        # original gravado na própria foto ("Padrão ampliado", geralmente num
        # canto superior) — não dá pra confiar que todo swatch novo que o
        # Davi mandar no futuro venha limpo, então a instrução abaixo sempre
        # avisa pra ignorar texto/marca d'água na referência, independente da
        # imagem específica.
        for ref in reference_images or []:
            target = (ref.get("target") or "").strip()
            # Com o móvel-alvo preenchido (modal de Cores, ver index.html),
            # a instrução aponta exatamente onde aplicar — sem isso o modelo
            # tinha que adivinhar qual móvel recebe qual cor em ambientes com
            # mais de um (achado real do Davi, 14/07/2026).
            where = f"no(s) seguinte(s) móvel(is): {target}" if target else "onde a instrução acima indicar"
            parts.append({
                "text": f"Referência exata de cor/material — {ref['name']} (linha {ref['brand']}). "
                        f"Aplique esta cor/textura precisamente {where}. Esta foto de referência pode "
                        "conter texto, marca d'água, legenda ou logotipo do catálogo original — "
                        "IGNORE completamente qualquer texto/marca/logotipo visível nela; use só a cor, "
                        "o padrão e a textura do material, nunca reproduza texto nenhum no render final."
            })
            parts.append({
                "inline_data": {
                    "mime_type": ref.get("mime") or "image/png",
                    "data": base64.b64encode(ref["bytes"]).decode("ascii"),
                }
            })
        if reference_images:
            # A instrução de fidelidade já vem no texto principal (ver
            # app/image.py, FIDELITY_CLOSING_REMINDER), mas essas imagens de
            # referência de cor entram DEPOIS dela na sequência — sem isso, a
            # última coisa que o modelo lê antes de gerar é "aplique esta
            # cor/textura", não "não invente nada". Repete o essencial em uma
            # frase curta, de propósito depois de tudo.
            parts.append({
                "text": "Reforçando: use as referências de cor/material só onde indicado; "
                        "não adicione nenhum móvel, objeto ou padrão de parede novo; ignore "
                        "qualquer texto/marca d'água/logotipo que apareça nas fotos de referência "
                        "de cor — nunca escreva ou reproduza texto nenhum no render final."
            })
        body = {"contents": [{"parts": parts}]}
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
