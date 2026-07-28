"""Roteador de modelos do chat Sogno (modo "Automático").

Quando o seletor de motor da tela está em "Automático", o /api/chat chama
`pick_engine` para decidir, a cada mensagem, qual modelo responde — a ideia é
economizar tokens mandando conversa simples para um modelo barato e reservando
o Claude (com advisor tool + web_search) para o que realmente precisa.

Como configurar (Davi: dá pra pedir esses ajustes direto ao Sogno Code):
- `SIMPLE_MODEL` / `CODE_MODEL`: modelos Kimi usados nas rotas baratas.
- `TOOL_KEYWORDS`: palavras que indicam necessidade de web search/advisor
  (sempre caem no Claude, que é o único caminho com essas ferramentas).
- `COMPLEX_KEYWORDS` e `LONG_MESSAGE_CHARS`: o que conta como "tarefa
  complexa" (também cai no Claude, pela qualidade do raciocínio).
- `CODE_KEYWORDS`: o que conta como pergunta de código (vai pro CODE_MODEL).

A decisão olha só a ÚLTIMA mensagem do usuário — regra simples, sem custo
extra de tokens com classificador.
"""

# --- Modelos de cada rota ----------------------------------------------------
# Rota barata para conversa geral / perguntas simples.
SIMPLE_MODEL = "kimi-k2.6"
# Rota para perguntas de código (scripts, fórmulas, HTML etc.).
CODE_MODEL = "kimi-k2.7-code"
# Tudo que precisa de ferramentas (web search/advisor) ou raciocínio pesado
# cai nesta rota, que é o fluxo Claude já existente no /api/chat.
CLAUDE_ROUTE = "claude"

# --- Regras (listas de palavras em minúsculas, sem acento importa: cubra as --
# --- duas grafias, como já feito abaixo) -------------------------------------

# Precisa de web search/advisor -> sempre Claude.
TOOL_KEYWORDS = [
    "preço", "preco", "quanto custa", "fornecedor", "onde comprar",
    "pesquise", "pesquisar", "busque", "buscar na internet", "procure na net",
    "notícia", "noticia", "hoje", "esta semana", "atual",
    "site da", "link", "http", "www.",
]

# Raciocínio pesado / tarefa grande -> Claude (qualidade máxima).
COMPLEX_KEYWORDS = [
    "arquitetura", "planeje", "planejar", "plano detalhado",
    "análise profunda", "analise profunda", "compare", "comparação", "comparacao",
    "passo a passo completo", "estratégia", "estrategia",
    "prós e contras", "pros e contras", "trade-off", "tradeoff",
    "otimize", "otimização", "otimizacao", "revisão completa", "revisao completa",
    "explique detalhadamente",
]

# Pergunta de código -> Kimi K2.7 Code.
CODE_KEYWORDS = [
    "código", "codigo", "função", "funcao", "def ", "class ", "import ",
    "debug", "depurar", "traceback", "exception", "erro de",
    "python", "javascript", "html", "css", "sql", "regex", "json",
    "script", "algoritmo", "compile", "compilar", "refatorar",
    "planilha", "fórmula", "formula", "api", "endpoint",
    ".py", ".js", ".html", ".css", ".sql", ".json", "git ",
]

# Mensagens a partir deste tamanho são tratadas como complexas.
LONG_MESSAGE_CHARS = 1200


def _last_user_text(messages: list[dict]) -> str:
    """Texto da última mensagem do usuário (content pode ser str ou blocos)."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
    return ""


def pick_engine(messages: list[dict]) -> str:
    """Decide quem responde esta mensagem.

    Retorna "claude" (fluxo Claude completo) ou "kimi:<modelo>" (motor Kimi
    com o modelo indicado). Chamado pelo /api/chat quando engine == "auto".
    """
    text = _last_user_text(messages)
    lowered = text.lower()

    # 1) Precisa de ferramentas (web/advisor)? Só o Claude tem.
    if any(k in lowered for k in TOOL_KEYWORDS):
        return CLAUDE_ROUTE

    # 2) Tarefa complexa ou mensagem muito longa? Melhor raciocínio = Claude.
    if len(text) >= LONG_MESSAGE_CHARS or any(k in lowered for k in COMPLEX_KEYWORDS):
        return CLAUDE_ROUTE

    # 3) Pergunta de código? Modelo Kimi especializado.
    if "```" in text or any(k in lowered for k in CODE_KEYWORDS):
        return f"kimi:{CODE_MODEL}"

    # 4) Resto = conversa simples -> rota mais barata.
    return f"kimi:{SIMPLE_MODEL}"
