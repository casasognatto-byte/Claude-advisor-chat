"""Detecta perguntas sobre qual IA/fornecedor está por trás da Neusa e avisa
o diretor no ClickUp. Ver memória "Confidencialidade do stack de IA": Davi
quer ser avisado ativamente, não só ver a pergunta recusada em silêncio.

Config (opcional — se ausente, só loga localmente, nunca quebra o chat):
  CLICKUP_TOKEN          — mesmo token já usado no ZapSignBridge
  CLICKUP_ALERT_LIST_ID  — lista do ClickUp onde a tarefa de alerta deve cair
  CLICKUP_ALERT_ASSIGNEE — ID do usuário do Davi no ClickUp (opcional, atribui a tarefa)
"""

import os
import re

import httpx

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


def send_vendor_inquiry_alert(username: str, message_excerpt: str) -> None:
    """Nunca deve lançar exceção — é um efeito colateral, não pode derrubar o chat."""
    try:
        token = os.environ.get("CLICKUP_TOKEN")
        list_id = os.environ.get("CLICKUP_ALERT_LIST_ID")
        excerpt = (message_excerpt or "")[:300]
        if not token or not list_id:
            print(
                "[clickup_alert] CLICKUP_TOKEN/CLICKUP_ALERT_LIST_ID não configurados — "
                f"alerta não enviado. {username} perguntou sobre o stack de IA: {excerpt!r}"
            )
            return
        body = {
            "name": f"Alerta: {username} perguntou sobre a IA por trás da Neusa",
            "description": f"Mensagem: {excerpt}",
        }
        assignee = os.environ.get("CLICKUP_ALERT_ASSIGNEE")
        if assignee:
            body["assignees"] = [int(assignee)]
        headers = {"Authorization": token, "Content-Type": "application/json"}
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"https://api.clickup.com/api/v2/list/{list_id}/task", json=body, headers=headers
            )
        if resp.status_code >= 400:
            print(f"[clickup_alert] falha ao criar tarefa: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[clickup_alert] falha inesperada: {e}")
