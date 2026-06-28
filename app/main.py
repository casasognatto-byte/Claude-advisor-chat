"""Backend FastAPI para o chat Executor + Advisor da API da Anthropic.

A chave da API fica somente no servidor (variável de ambiente ANTHROPIC_API_KEY)
e nunca é exposta ao frontend. O endpoint /api/chat repassa o histórico da
conversa para a API da Anthropic usando o padrão Executor + Advisor.
"""

import os
from typing import Any

# Carrega .env em desenvolvimento local; em produção (Render) as variáveis
# já vêm do ambiente, então a ausência do .env é ignorada.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# --- Configuração (ajustável por variáveis de ambiente) ---------------------
EXECUTOR_MODEL = os.environ.get("EXECUTOR_MODEL", "claude-sonnet-4-6")
ADVISOR_MODEL = os.environ.get("ADVISOR_MODEL", "claude-opus-4-8")
ADVISOR_BETA = "advisor-tool-2026-03-01"
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
ADVISOR_MAX_USES = int(os.environ.get("ADVISOR_MAX_USES", "3"))
ADVISOR_MAX_TOKENS = int(os.environ.get("ADVISOR_MAX_TOKENS", "2048"))
# Adicione o contexto do Promob (ou qualquer instrução) via SYSTEM_PROMPT.
SYSTEM_PROMPT = (os.environ.get("SYSTEM_PROMPT") or "").strip()

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

# Lê ANTHROPIC_API_KEY do ambiente automaticamente.
client = anthropic.Anthropic()

app = FastAPI(title="Advisor Chat")


class ChatRequest(BaseModel):
    # Histórico completo da conversa (a API da Anthropic é stateless).
    messages: list[dict[str, Any]]


# --- Helpers ----------------------------------------------------------------
def _block_to_dict(block: Any) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return dict(block)


def _text_from_content(content: Any) -> str:
    """Extrai texto de um campo `content` que pode ser str ou lista de blocos."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for item in content:
            d = item if isinstance(item, dict) else _block_to_dict(item)
            if d.get("text"):
                parts.append(d["text"])
    return "\n".join(parts)


def _extract(content_blocks) -> tuple[list[str], list[dict]]:
    """Separa o texto do executor das consultas ao advisor."""
    text_parts: list[str] = []
    advisor_items: list[dict] = []
    for raw in content_blocks:
        b = _block_to_dict(raw)
        t = b.get("type")
        if t == "text":
            text_parts.append(b.get("text", ""))
        elif t == "server_tool_use" and b.get("name") == "advisor":
            # Pergunta que o executor fez ao advisor.
            advisor_items.append({"question": b.get("input") or {}, "advice": None})
        elif t in ("advisor_tool_result", "tool_result"):
            advice = _text_from_content(b.get("content"))
            if advisor_items and advisor_items[-1]["advice"] is None:
                advisor_items[-1]["advice"] = advice
            else:
                advisor_items.append({"question": None, "advice": advice})
    return text_parts, advisor_items


def _advisor_usage(raw_usage: dict | None) -> dict | None:
    """Tenta localizar a contagem de tokens do advisor no objeto usage.

    O formato exato do breakdown de tokens da advisor tool é beta; tentamos as
    chaves mais prováveis e devolvemos None se nenhuma existir (o frontend
    mostra "n/d" nesse caso). Verifique contra a saída real da API.
    """
    if not raw_usage:
        return None
    for key in ("advisor", "advisor_tool_use", "server_tool_use"):
        v = raw_usage.get(key)
        if isinstance(v, dict):
            return {
                "input_tokens": v.get("input_tokens"),
                "output_tokens": v.get("output_tokens"),
            }
    return None


def _api_error_detail(e: anthropic.APIStatusError) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or {}
        if err.get("message"):
            return err["message"]
    return getattr(e, "message", str(e))


# --- Rotas ------------------------------------------------------------------
@app.post("/api/chat")
def chat(req: ChatRequest):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY não está configurada no servidor.")

    working = list(req.messages)
    appended: list[dict] = []
    all_text: list[str] = []
    all_advisor: list[dict] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "raw": {}}

    try:
        # A advisor tool roda um loop server-side; em casos longos a API pode
        # devolver stop_reason="pause_turn". Reenviamos para continuar, com um
        # limite de segurança para não rodar indefinidamente.
        for _ in range(6):
            response = client.beta.messages.create(
                model=EXECUTOR_MODEL,
                max_tokens=MAX_TOKENS,
                betas=[ADVISOR_BETA],
                system=SYSTEM_PROMPT or anthropic.NOT_GIVEN,
                tools=[
                    {
                        "type": "advisor_20260301",
                        "name": "advisor",
                        "model": ADVISOR_MODEL,
                        "max_uses": ADVISOR_MAX_USES,
                        "max_tokens": ADVISOR_MAX_TOKENS,
                    }
                ],
                messages=working,
            )

            assistant_msg = {
                "role": "assistant",
                "content": [_block_to_dict(b) for b in response.content],
            }
            appended.append(assistant_msg)
            working.append(assistant_msg)

            texts, advisors = _extract(response.content)
            all_text.extend(texts)
            all_advisor.extend(advisors)

            u = response.usage.model_dump() if response.usage else {}
            usage["input_tokens"] += u.get("input_tokens") or 0
            usage["output_tokens"] += u.get("output_tokens") or 0
            usage["raw"] = u

            if response.stop_reason != "pause_turn":
                break
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=e.status_code, detail=_api_error_detail(e))
    except anthropic.APIConnectionError:
        raise HTTPException(503, "Não foi possível conectar à API da Anthropic.")

    return {
        # Mensagens do assistente a anexar ao histórico (preserva os blocos
        # advisor_tool_result, exigidos em conversas de múltiplos turnos).
        "append": appended,
        "text": "\n".join(t for t in all_text if t).strip(),
        "advisor": all_advisor,
        "usage": {
            "executor": {
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
            },
            "advisor": _advisor_usage(usage.get("raw")),
        },
    }


@app.get("/api/health")
def health():
    return {"ok": True, "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
