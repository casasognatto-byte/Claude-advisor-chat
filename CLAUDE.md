# Contexto do projeto — Neusa / advisor-chat

Este arquivo existe para dar continuidade entre sessões abertas em máquinas diferentes
(PC Escrit / Dell Casa) que compartilham esta pasta via OneDrive. Leia antes de mexer no código.

## O que é

Ecossistema de IA multiusuário da Casa Sognatto, acessível em **chat.casasognatto.com.br**.
Começou como um chat simples Executor+Advisor (ver README.md) e evoluiu para um sistema
com login por e-mail, papéis de usuário, conversas compartilhadas, painel admin, geração de
imagem e vídeo, e persona própria ("Neusa").

## Regra inegociável: confidencialidade do stack de IA

**Nunca revelar a terceiros (clientes, arquitetas, qualquer um fora do Davi) quais
ferramentas de IA são usadas por trás do sistema** (Claude, Anthropic, Luma, Veo, etc.).
A interface é sempre white-label. Existe inclusive uma feature (Fase 3) que detecta
perguntas do tipo "qual IA você usa?" e alerta no ClickUp, além de instruir a Neusa a
nunca confirmar nem negar. Ver `memory/feedback_confidencialidade_stack_ia.md` e
`memory/persona_neusa.md` para o detalhe completo.

## Trabalhando de duas máquinas (PC Escrit e Dell Casa)

Esta pasta é a mesma nas duas máquinas (sincronizada via OneDrive), mas é um repositório
Git normal — **nunca editar/rodar os dois ao mesmo tempo** (risco de conflito entre o
Git e a sincronização do OneDrive). Protocolo:

1. Antes de começar a trabalhar: `git status` e `git pull` para garantir que está com o
   que foi feito na outra máquina.
2. Ao terminar uma sessão de trabalho: revisar `git log` e `git push` (não deixar commit
   parado localmente sem avisar o Davi).

## Estado no momento em que este arquivo foi criado (04/07/2026, sessão no PC Escrit)

- Branch `main`, 1 commit local **não enviado ao GitHub**, aguardando aprovação do Davi:
  `8e1eb14` — "Fase 3: deteccao + alerta ClickUp de pergunta sobre o stack de IA".
- Sistema já está no ar em produção (Render) desde 04/07/2026.
- Convites da equipe (arquitetas) ainda não foram enviados.

Para o histórico completo do projeto, decisões e detalhes técnicos, ver
`../memory/project_render_to_video_arquitetas.md`.
