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

**Cuidado com o `.venv`**: ele fica dentro desta pasta (sincronizada), mas um venv Python
é amarrado ao caminho absoluto da máquina que o criou (`pyvenv.cfg` grava o "home" do
Python usado). Quando a outra máquina roda `python -m venv .venv` aqui dentro, o OneDrive
sincroniza esses arquivos por cima e quebra o venv desta máquina (o `python.exe` do venv
vira um atalho que aponta pro caminho da outra pessoa). Se isso acontecer, o sintoma é
`preview_start`/rodar o servidor local falhando com "No Python at '...'" — solução é só
recriar: `rm -rf .venv && python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt`.
Isso não afeta produção (Render não usa esse `.venv`, só local).

## Estado no momento em que este arquivo foi criado (04/07/2026, sessão no PC Escrit)

- Branch `main`, 1 commit local **não enviado ao GitHub**, aguardando aprovação do Davi:
  `8e1eb14` — "Fase 3: deteccao + alerta ClickUp de pergunta sobre o stack de IA".
- Sistema já está no ar em produção (Render) desde 04/07/2026.
- Convites da equipe (arquitetas) ainda não foram enviados.

## Estado em 06/07/2026 (fim de sessão, Davi saindo — continuar em outra máquina)

- Branch `main`, **8 commits locais não enviados ao GitHub** (de `8e1eb14` até `55fa74f`,
  ver `git log origin/main..HEAD`) — nada foi pushado desde a sessão de 04/07. Não fazer
  `git push` sem confirmar com o Davi antes (protocolo de sempre).
- **Feature nova concluída nesta sessão: Biblioteca de prompts** (ícone 📝 no composer).
  Prompts pré-definidos por ambiente + prompts pessoais compartilhados. Mudança de regra
  a pedido do Davi: **pré-definidos agora são abertos a qualquer membro logado** (criar/
  editar/apagar — não é mais só o diretor). Como rede de segurança pra essa liberação:
  - "Desfazer última edição" (tipo ctrl+z) — pilha de versões em `prompt_versions`,
    endpoint `POST /api/prompts/{predefined|personal}/{id}/undo`.
  - Registro de exclusão recuperável — cópia completa em `deleted_prompts` antes de
    apagar de verdade, painel "🗑 Excluídos recentes" no modal, `POST
    /api/prompts/deleted/{log_id}/restore`. Exclusão/restauração de prompt **pessoal**
    continua restrita a quem criou; pré-definido é livre pra todos.
  - Arquivos: `app/prompts.py` (schema + rotas), `app/static/index.html` (ícone, modal,
    CSS, JS). Testado de ponta a ponta localmente via API (permissões, undo, delete→
    restore) e via browser real (login, cliques, screenshots) — sem push ainda.
  - Detalhe pra próxima sessão: ao subir essas mudanças em produção, `init_prompts_db()`
    cria as tabelas novas (`prompt_versions`, `deleted_prompts`) automaticamente no boot
    (mesmo padrão das outras tabelas) — não precisa migração manual.
- Ambiente de dev local (Postgres `advisor_chat_dev`, venv, `.env`) existe só nesta
  máquina — não sincroniza via OneDrive (fica fora da pasta do projeto). Se a próxima
  sessão for em outra máquina, pode ser necessário recriar esse ambiente local do zero
  (ver `../memory/project_render_to_video_arquitetas.md`, seção "Ambiente de dev local
  criado nesta sessão", pra reproduzir: Python 3.12 + Postgres 17 via winget, venv, etc.)
  — ou simplesmente pular o teste local e ir direto pra revisão de código + deploy.
- Pendências antigas que continuam em aberto: confirmar se o login do Davi em produção
  já funciona após o reset forçado de senha (e então remover `FORCE_RESET_DIRETOR_PASSWORD`
  do Render); adicionar créditos na conta Luma pra testar geração de vídeo de verdade;
  enviar convites reais aos 4 membros da equipe (aguardando autorização explícita do Davi).

## Estado em 07/07/2026 (push feito — main atualizado no GitHub)

- **Push realizado**: `main` local e `origin/main` estão sincronizados em `ca05783`. O
  Render faz auto-deploy em push — se o Davi for conferir, o deploy dessas mudanças deve
  ter disparado automaticamente (não precisa fazer nada manual no painel do Render pra
  isso, só pra variáveis de ambiente novas, ver abaixo).
- **Nova feature encontrada nesta sessão, vinda de outra máquina**: Biblioteca de
  Apresentações (Fase 4) — projetos de cliente com upload de imagens do Promob,
  classificação automática de ambiente, deck institucional fixo + apresentação em tela
  cheia, biblioteca de padrões técnicos de iluminação/decoração (com desfazer/lixeira,
  mesmo padrão da Biblioteca de Prompts). Nova página `/apresentacoes`, link na barra
  lateral visível a qualquer membro. Arquivos: `app/presentations.py`, `app/storage.py`
  (Cloudflare R2 com fallback pra disco local), `app/static/apresentacoes.html`.
  - **Variável de ambiente nova pra configurar no Render** (opcional — sem ela, cai em
    disco local, que não persiste entre deploys): `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
    `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` (Cloudflare R2, já declaradas em `render.yaml`
    como secret, mas sem valor ainda).
  - **Achado e corrigido nesta sessão**: XSS armazenado em `apresentacoes.html` — nome de
    cliente, campos da biblioteca de padrões técnicos e notas de estilo eram inseridos via
    `innerHTML` sem escapar. Corrigido com `escapeHtml()` (commit `ca05783`), testado
    localmente com payloads reais antes do push.
- Tarefa "Fase 3: alerta ClickUp sobre pergunta de stack de IA" confirmada como já
  implementada (estava marcada como pendente por desatualização de tracking, não porque
  faltava fazer).
- Pendências antigas continuam abertas: confirmar login do Davi em produção (pra remover
  `FORCE_RESET_DIRETOR_PASSWORD`), créditos na conta Luma, `GOOGLE_API_KEY` real, convites
  da equipe (aguardando autorização explícita).

## Estado em 07/07/2026 (continuação — Biblioteca de Referências + decisão sobre domínio)

- **Duas features novas enviadas ao GitHub nesta sessão** (`main` sincronizado em `7ec76a4`):
  - Correção do rodapé da sidebar (`5d7222a`): os botões Sair/Apresentações/Painel
    estouravam a largura da sidebar (270px) e o último ficava cortado sem quebrar linha —
    era por isso que o Davi não achava o "Sair". Reordenado (Sair primeiro) + rodapé quebra
    em duas linhas agora.
  - **Biblioteca de referências entre projetos anteriores** (`7ec76a4`): botão "🔍 Ver
    referências" no painel de estilo de cada imagem, abre busca (filtro por ambiente +
    nome de cliente) em TODAS as imagens de TODOS os projetos, com "Usar como base" que
    copia o estilo (MDF/iluminação/decoração) pra imagem atual. Contador `usage_count` em
    `project_images` (incrementado a cada uso), ordena a lista por mais usado primeiro.
    Endpoints: `GET /api/presentations/references/search`, `POST
    /api/presentations/references/{image_id}/use`. Detalhe completo em
    `../memory/project_neusa_apresentacoes_arquitetas.md`.
- **Decisão sobre domínio (não implementar por enquanto)**: o Davi perguntou se dava pra
  expor isso em `casasognatto.com.br/projetos` (domínio raiz, onde já roda o WordPress
  institucional da empresa). Investigação (com acesso real ao wp-admin via browser):
  - DNS do domínio raiz é gerenciado pela **KingHost**, não Cloudflare — descarta proxy via
    Cloudflare Worker.
  - Um caminho por path (`/projetos`) exigiria um plugin WordPress-ponte (reverse proxy em
    PHP, mesmo padrão do plugin custom "Casa Sognatto Ponto de Equilíbrio" que já existe
    nesse WP) **e** ensinar o app a funcionar sob um prefixo de caminho (hoje os paths
    `/api/...`/`/static/...` são absolutos a partir da raiz — quebram se servidos sob
    `/projetos` sem essa adaptação).
  - **Decisão do Davi: manter como está.** A Biblioteca de Apresentações já vive em
    `chat.casasognatto.com.br/apresentacoes`, com o mesmo login que já existe — não requer
    nenhum trabalho de infraestrutura novo. Se o assunto voltar numa sessão futura, essa
    investigação já está pronta, não precisa refazer.
  - Nota lateral sem relação com o trabalho técnico: vi 3 cópias duplicadas do plugin
    "Casa Sognatto Ponto de Equilíbrio" na lista de plugins do WordPress — parecem sobras
    de teste, não mexi em nada.

## Estado em 07/07/2026 (fim de sessão — confirmado deploy, Davi saindo de novo)

- **Tudo enviado e confirmado no ar**: `main` e `origin/main` sincronizados em `5346c7e`.
  Conferido direto no painel do Render (Events do serviço `advisor-chat`) — os 3 deploys
  mais recentes (`5346c7e`, `7ec76a4`, `5d7222a`) aparecem como **"Deploy live"**, sem erro.
  Não precisa reconferir isso na próxima sessão a menos que algo pareça errado no site.
- **Autorização temporária de push** (registrada só na minha memória local desta máquina,
  não sincroniza): Davi autorizou fazer `git push` sem confirmar cada vez, **até
  2026-07-08**. Se uma sessão nova abrir na outra máquina antes dessa data e ele repetir
  algo do tipo "pode fazer tudo", isso é consistente com o que já valeu aqui — mas depois
  de 2026-07-08 essa liberação expira e volta o protocolo padrão (confirmar cada push).
  Isso **não** cobre convites reais da equipe nem ações de credencial/pagamento — essas
  continuam exigindo autorização nomeada especificamente, sempre.
- Pendências que continuam abertas, nenhuma nova hoje: confirmar créditos na conta Luma
  (pra testar geração de vídeo de verdade e trocar `VIDEO_ENGINE` de `stub` pra `luma`),
  `GOOGLE_API_KEY` real (geração de imagem, hoje em `stub`), convites reais aos 4 membros
  da equipe (aguardando autorização explícita).

Para o histórico completo do projeto, decisões e detalhes técnicos, ver
`../memory/project_render_to_video_arquitetas.md`.
