"""Detecta perguntas sobre qual IA/fornecedor está por trás do Sogno e avisa
o diretor por mensagem de chat direta no ClickUp (não uma tarefa). Ver memória
"Confidencialidade do stack de IA": Davi quer ser avisado ativamente, não só
ver a pergunta recusada em silêncio.

Config (opcional — se ausente, só loga localmente, nunca quebra o chat):
  CLICKUP_TOKEN         — mesmo token já usado no ZapSignBridge (pk_...)
  CLICKUP_WORKSPACE_ID  — workspace "Casa Sognatto" (padrão: 90133031055)
  CLICKUP_ALERT_EMAIL   — e-mail do destinatário no ClickUp (padrão: davinogueira@casasognatto.com.br)

Mecanismo testado de ponta a ponta em 2026-07-04 com token real: resolve o
e-mail pro user id via `GET /team`, cria (ou reaproveita) um canal de
Direct Message via `POST .../chat/channels/direct_message` e manda a
mensagem via `POST .../chat/channels/{id}/messages`. A API de Chat do
ClickUp é marcada como "experimental" pela própria documentação deles —
funcionou no teste real, mas vale reconfirmar se o formato mudar no futuro.
"""

import os
import re

import httpx

CLICKUP_API = "https://api.clickup.com/api"
DEFAULT_WORKSPACE_ID = "90133031055"
DEFAULT_ALERT_EMAIL = "davinogueira@casasognatto.com.br"

# Termos que indicam tentativa de descobrir o fornecedor por trás da IA.
# Português, coloquial, cobrindo variações comuns — melhor over-alertar que
# deixar passar (Davi pediu pra ser avisado, não pra bloquear silenciosamente).
_PATTERNS = [
    r"\bqual\s+(ia|intelig[eê]ncia\s+artificial|modelo|llm)\b",
    r"\bque\s+(ia|modelo|tecnologia|llm)\s+(voc[eê]s?|voc[eê]|isso)\s+(usa|usam|roda|é)\b",
    r"\bvoc[eê]\s+(é|e)\s+(o\s+)?(chatgpt|gpt|gemini|claude|llama|copilot)\b",
    r"\bpowered\s+by\b",
    r"\bquem\s+(te\s+)?(criou|desenvolveu|programou|fez)\b(\s+voc[eê])?",
    r"\bvoc[eê]\s+(é|e)\s+da\s+(openai|anthropic|google|microsoft)\b",
    r"\b(usa|usam|roda|rodando)\s+(gemini|luma|veo|gpt|chatgpt|claude|llama)\b",
    r"\bvoc[eê]\s+é\s+(uma\s+)?ia\s+de\s+quem\b",
    r"\bqual\s+(empresa|fornecedor)\s+(está\s+)?por\s+tr[aá]s\b",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]


def is_vendor_inquiry(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _COMPILED)


def _find_user_id_by_email(client: httpx.Client, headers: dict, workspace_id: str, email: str) -> str | None:
    resp = client.get(f"{CLICKUP_API}/v2/team", headers=headers)
    resp.raise_for_status()
    for team in resp.json().get("teams", []):
        if str(team.get("id")) != str(workspace_id):
            continue
        for m in team.get("members", []):
            user = m.get("user") or {}
            if (user.get("email") or "").lower() == email.lower():
                return str(user.get("id"))
    return None


def _get_or_create_dm_channel(client: httpx.Client, headers: dict, workspace_id: str, user_id: str) -> str | None:
    resp = client.post(
        f"{CLICKUP_API}/v3/workspaces/{workspace_id}/chat/channels/direct_message",
        json={"user_ids": [user_id]},
        headers=headers,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("id") or (data.get("data") or {}).get("id")


def _send_chat_message(client: httpx.Client, headers: dict, workspace_id: str, channel_id: str, content: str) -> None:
    resp = client.post(
        f"{CLICKUP_API}/v3/workspaces/{workspace_id}/chat/channels/{channel_id}/messages",
        json={"type": "message", "content": content, "content_format": "text/md"},
        headers=headers,
    )
    resp.raise_for_status()


def send_clickup_dm(email: str, content: str) -> bool:
    """Manda uma mensagem de chat direta (DM) pro usuário do ClickUp com esse
    e-mail. Canal genérico e reaproveitável — usado tanto pro alerta de
    pergunta sobre IA quanto como via alternativa de entrega de link de
    convite/reset de senha (o SMTP direto do Render pra KingHost não
    funciona — ver memória do projeto, "Errno 101 Network is unreachable").
    Nunca lança exceção; retorna True se enviou, False se não deu por
    qualquer motivo (token ausente, e-mail não encontrado, erro de rede)."""
    token = os.environ.get("CLICKUP_TOKEN")
    if not token:
        print(f"[clickup_alert] CLICKUP_TOKEN não configurado — DM não enviado para {email!r}.")
        return False
    workspace_id = os.environ.get("CLICKUP_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=15) as client:
            user_id = _find_user_id_by_email(client, headers, workspace_id, email)
            if not user_id:
                print(f"[clickup_alert] e-mail {email!r} não encontrado no workspace {workspace_id}.")
                return False
            channel_id = _get_or_create_dm_channel(client, headers, workspace_id, user_id)
            if not channel_id:
                print("[clickup_alert] não consegui obter o id do canal de DM.")
                return False
            _send_chat_message(client, headers, workspace_id, channel_id, content)
        return True
    except httpx.HTTPStatusError as e:
        print(f"[clickup_alert] falha HTTP mandando DM pra {email!r}: {e.response.status_code} {e.response.text[:200]}")
    except Exception as e:
        print(f"[clickup_alert] falha inesperada mandando DM pra {email!r}: {e}")
    return False


def send_vendor_inquiry_alert(username: str, message_excerpt: str) -> None:
    """Nunca deve lançar exceção — é um efeito colateral, não pode derrubar o chat."""
    excerpt = (message_excerpt or "")[:300]
    email = os.environ.get("CLICKUP_ALERT_EMAIL", DEFAULT_ALERT_EMAIL)
    content = (
        f"🔔 **{username}** perguntou qual IA/tecnologia está por trás do Sogno.\n\n"
        f"Trecho da mensagem: _{excerpt}_"
    )
    if not send_clickup_dm(email, content) and not os.environ.get("CLICKUP_TOKEN"):
        print(f"{username} perguntou sobre o stack de IA: {excerpt!r}")
