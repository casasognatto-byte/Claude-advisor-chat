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

## Estado em 07/07/2026 (continuação — confidencialidade em nível "meta")

- **Ajuste na persona da Neusa**: Davi deixou explícito que nem a *existência* de uma regra
  de confidencialidade pode transparecer pros usuários — antes o prompt instruía ela a
  dizer algo como "isso não é algo que eu compartilho", o que já é uma admissão indireta.
  Reescrito `DEFAULT_SYSTEM_PROMPT` em `app/main.py` pra ela desviar com charme e
  naturalidade, sem frases que sugiram que há uma política/instrução por trás. Testado com
  chamada real (chave de teste local): perguntada sobre qual IA usa, respondeu algo no
  estilo "Sou só a Neusa... uma mente singular não revela todos os seus segredos — faz
  parte do charme" — Davi aprovou. Detalhe completo em `../memory/persona_neusa.md` e
  `../memory/feedback_confidencialidade_stack_ia.md`.

## Estado em 07/07/2026 (continuação — geração de imagem real, ainda pendente)

- **Luma**: crédito adicionado pelo Davi na conta (`platform.lumalabs.ai`) — confirmado por
  ele ("luma ok"). Ainda falta trocar `VIDEO_ENGINE` de `stub` pra `luma` no Render e testar
  geração de vídeo real de ponta a ponta.
- **Google/Nano Banana — EM ANDAMENTO, NÃO FUNCIONA AINDA**: Davi configurou
  `IMAGE_ENGINE=nanobanana` no Render (confirmado "Deploy live" às 8:58 do dia 07/07) e
  disse ter adicionado `GOOGLE_API_KEY` também, mas **testei em produção e deu erro**.
  Confirmado direto no log do Render (`/logs`): `[image job ...] falha do fornecedor
  (nanobanana): GOOGLE_API_KEY não configurada.` — ou seja, apesar do Davi achar que salvou,
  a variável `GOOGLE_API_KEY` **não está presente** (ou o nome está diferente do exato
  `GOOGLE_API_KEY`, com espaço/typo/case errado) no ambiente do serviço `advisor-chat` no
  Render. Pedi pra ele conferir de novo — ainda sem resposta/confirmação de correção.
  - A chave que ele forneceu no chat (não repetida aqui por segurança — nunca colar chaves
    reais neste arquivo) foi validada e funciona (testei via curl local: `GET
    /v1beta/models` retornou 200 e o modelo `gemini-2.5-flash-image` está disponível pra
    essa chave). O problema não é a chave em si, é ela não estar chegando no ambiente de
    produção.
  - Rota de teste usada (útil pra repetir): logar como diretor, criar conversa via
    `POST /api/conversations`, depois `POST /api/image/jobs` com uma imagem (multipart,
    campos `image`+`prompt`+`conversation_id`), poll em `GET /api/image/jobs/{id}`,
    conferir tamanho do arquivo em `GET /api/image/file/{id}` — 40 bytes exatos = ainda é
    o stub; erro no log do Render (`/logs`, filtro "Application logs") mostra a causa real
    sem vazar isso pro usuário final (mensagem genérica "Falha ao gerar a imagem" no chat).
  - **Próximo passo**: conferir com o Davi se a variável `GOOGLE_API_KEY` está mesmo salva
    no painel (nome exato, sem espaços) e testar de novo.
- Davi também subiu 5 imagens reais de render elementar (Promob, cozinha) direto no chat
  desta sessão — coladas na conversa, não ficam acessíveis como arquivo pra mim reusar
  depois (só existem dentro do histórico da conversa). Se for testar de novo, pedir uma
  imagem nova ou usar uma qualquer local.
- ✅ **RESOLVIDO na sessão seguinte (07/07/2026)**: o botão 🖼️ do chat principal já
  aceita múltiplas imagens de uma vez (commit `95be5a7`) — ver seção mais abaixo.
- Convites da equipe: Davi quer testar o envio de e-mail primeiro, antes de decidir sobre
  convites reais — continua represado, sem novidade.

## Ideia registrada (07/07/2026): botão "Limpar" no composer de imagem/vídeo

Davi viu várias mensagens de erro repetidas ("Falha ao gerar a imagem, tente novamente")
acumulando na conversa durante tentativas sucessivas, e perguntou se precisamos de um botão
"Limpar" (provavelmente pra limpar esses erros acumulados da tela, não as mensagens da
conversa em si — confirmar escopo exato quando for implementar). Não implementado ainda,
só registrado para avaliar em sessão futura.

## Sessão de 07/07/2026 (curta, sem mudança de código) — confirma bug antigo ainda ativo

Davi mostrou um screenshot com várias falhas seguidas de "Falha ao gerar a imagem, tente
novamente" em produção — **consistente com a pendência já documentada acima** (seção
"geração de imagem real, ainda pendente"): a suspeita de que `GOOGLE_API_KEY` não está
configurada corretamente no Render continua a explicação mais provável, mas **não foi
reinvestigada nesta sessão** (Davi não pediu, sessão foi majoritariamente sobre outro
projeto — configuração do Conta Azul). Nenhuma mudança de código ou de variável de ambiente
foi feita aqui. Próxima sessão que for mexer nisso: conferir de novo no painel do Render se
`GOOGLE_API_KEY` está salva com o nome exato, sem espaço/typo, antes de re-testar.

## Estado em 07/07/2026 (sessão seguinte — GOOGLE_API_KEY resolvido + 5 features novas)

**Push feito, `main` e `origin/main` sincronizados em `7e2b45c`.** Tudo testado localmente
(servidor real + Postgres real) antes do push, autorização de push confirmada verbalmente
pelo Davi durante a sessão. Ordem cronológica:

1. **GOOGLE_API_KEY resolvido de vez** (`79d0206`, feito pelo próprio Davi no painel do
   Render): a variável estava salva **sem caixa alta** (não era bug de código nem da
   chave). Depois de corrigir, apareceu um erro novo e esperado — `429 quota exceeded` do
   lado do Google (conta no nível gratuito). Davi resolveu ativando **"API Gemini —
   Pagamento por solicitação"** no Google AI Studio (não a assinatura mensal de
   consumidor, que não libera cota de API de servidor). **Nano Banana funcionando de
   verdade em produção agora.**
2. **Upload múltiplo no ícone 🖼️ do chat** (`95be5a7`).
3. **Troca do modelo de imagem padrão: Nano Banana → Nano Banana Pro** (`fdb0851`,
   `gemini-3-pro-image`, default em `app/image_engines.py`). Achado real: o modelo antigo
   (`gemini-2.5-flash-image`, "legado" segundo a própria Google) não seguiu bem nomes de
   material/marca específicos no prompt do Davi ("Suvinil crômio", "quartzito Taj Mahal",
   "MDF Nogueira Flórida") — o mesmo prompt, testado por ele direto no app do Gemini com
   modelo mais novo, funcionou certinho. Nano Banana Pro é anunciado com "consistência
   precisa de marca" como recurso principal; diferença de custo é pequena (~$0,13-0,24/
   imagem vs ~$0,07-0,10 do Nano Banana 2). **Atenção**: se existir `IMAGE_MODEL` explícito
   no painel do Render apontando pro modelo antigo, ele sobrescreve esse novo padrão do
   código — vale conferir se não ficou nada configurado lá antes desta sessão.
4. **Botão "🔁 Refazer" na geração de imagem** (`4d50020`, `app/image.py` +
   `app/static/index.html`) — reaproveita a mesma imagem de origem (agora persistida por
   job, colunas `source_path`/`source_mime` em `image_jobs`, migração aditiva — jobs
   antigos sem essas colunas simplesmente não oferecem o botão) com o prompt anterior
   pré-preenchido e editável antes de confirmar. Gera um job novo, não sobrescreve o
   anterior (dá pra comparar as duas versões).
5. **Botão "Gerar vídeo" direto de uma imagem já armazenada na Biblioteca de
   Apresentações** (`d53110b`) — sem precisar baixar/reenviar pelo chat principal. Se não
   vier prompt explícito, monta um automaticamente a partir do estilo já salvo daquela
   imagem (cor do MDF, iluminação geral, iluminação dos móveis, decoração).
   `app/video.py` ganhou `create_video_job()` extraído do endpoint `/jobs` original,
   reaproveitável por qualquer lugar que já tenha os bytes da imagem em mãos. **Bug real
   corrigido no caminho**: `asyncio.create_task` precisa de event loop rodando — a rota
   nova em `presentations.py` era `def` síncrona (FastAPI despacha rotas sync numa
   threadpool sem loop) e precisou virar `async def`.
6. **Download em lote (.zip)** (`7e2b45c`) — botão "Baixar todas (.zip)" na tela do
   projeto (Biblioteca de Apresentações, todas as imagens daquele cliente, nomeadas por
   ordem+ambiente) e ícone ⬇ no cabeçalho do chat principal (renders da conversa atual).
   Endpoints `GET /api/presentations/{id}/images/download-all` e `GET
   /api/image/jobs/download-all?conversation_id=`, usando `zipfile` (builtin do Python,
   sem dependência nova). **Nota de rota**: ambos foram registrados ANTES das rotas
   `{job_id}`/`{image_id}` de mesmo prefixo, senão "download-all" seria capturado como um
   ID pelo catch-all — mesmo cuidado já documentado em `presentations.py` desde a Fase 4.

**Nota de ambiente recorrente**: o `.venv` foi quebrado de novo nesta sessão (a outra
máquina recriou por cima via OneDrive, mesmo sintoma já documentado no topo deste
arquivo). Também faltava `pillow` no venv recriado (só usado pra gerar imagens de teste
sintéticas nesta sessão, não é dependência real do projeto — não precisa entrar no
`requirements.txt`, só reinstalar no venv local se for gerar imagens de teste de novo).

**Testes em produção pedidos ao Davi, ainda sem confirmação de resultado** no momento em
que esta sessão foi encerrada: as 3 features de vídeo/download do item 4-6 acima, recém-
publicadas — pedir pra ele testar (ou testar direto, se a próxima sessão tiver como logar
em produção) antes de considerar essas três "confirmadas funcionando de verdade".

**Pendências que continuam abertas, nada novo além do que já estava**: confirmar login do
Davi em produção (`FORCE_RESET_DIRETOR_PASSWORD`), convites reais da equipe (aguardando
autorização), botão "Limpar" pra erros acumulados na tela (ver seção acima), voz
(STT/TTS) e montagem de vídeo final via Creatomate — ver
`../memory/project_neusa_apresentacoes_arquitetas.md` pro roadmap completo e atualizado.

## Estado em 07/07/2026 (continuação — botão "Gerar" no composer)

**Push feito, `main`/`origin/main` sincronizados em `ecfac25`.** Pedido do Davi: não queria
que anexar uma imagem nos ícones 🖼️/🎬 do composer disparasse a geração na hora (como era) —
queria poder ajustar o prompt com calma antes de confirmar.

Implementado: selecionar arquivo agora só "encena" (chip com nome + botão remover, numa
fileira acima do campo de mensagem); um botão **"Gerar"** (vira "Gerar vídeo" quando o tipo
encenado é vídeo) só aparece quando há algo na fileira, e é ele quem dispara a chamada de
verdade — usando o texto que estiver no campo de mensagem naquele momento como prompt.
Suporta múltiplas imagens encenadas de uma vez (reaproveita o `multiple` já existente no
input), cada uma removível antes de gerar; vídeo continua um arquivo por vez (mesma
capacidade de antes). Revisado (self-review, sem findings) e testado localmente antes do
push: anexar sem chamar API, múltiplas imagens com remoção individual (confirmado só 1
POST pra quem ficou), geração de vídeo mostrando o texto certo do botão.

**Nota de ambiente recorrente**: `.venv` quebrado de novo ao retomar nesta máquina (mesmo
sintoma documentado no topo deste arquivo) — recriado sem problema.

## Estado em 08/07/2026 — Vídeo-tour (N imagens → 1 vídeo com transições + trilha)

Pedido do Davi após testar a geração de vídeo isolada: um projeto com várias imagens
(ex: 5 ângulos da mesma cozinha) devia virar **1 vídeo só**, não um clipe por imagem.
Como nenhuma ferramenta de vídeo por IA (Luma, Veo, Runway, Kling) aceita mais de 2
imagens numa chamada — confirmado tanto na pesquisa quanto no teste real —, a solução
foi: **N imagens → N-1 clipes de transição real** (par a par, usando `start_frame` +
`end_frame` do Luma) **→ concatenados em 1 vídeo → trilha de fundo instrumental por
cima**. Testado de ponta a ponta com 5 imagens reais (4 transições, ~20s final,
qualidade validada visualmente frame a frame) via túnel HTTPS temporário (cloudflared,
já que o Luma exige HTTPS pra buscar a imagem staged e localhost não serve).

**Arquivos novos/alterados**:
- `app/video_assembly.py` (novo) — concatenação e mixagem de áudio via `ffmpeg`
  (binário portátil do pacote `imageio-ffmpeg`, sem depender de apt/root — funciona
  igual no Render).
- `app/assets/vivaldi_inverno.mp3` + `NOTICE.md` — trilha padrão (Vivaldi, "Inverno",
  1º mov.), gravação de domínio público via Internet Archive (CC BY-SA 3.0, uso
  comercial permitido com atribuição — ver `NOTICE.md`).
- `app/video_engines.py` — `LumaEngine.start()` agora aceita `end_image_bytes`/`end_mime`
  opcionais (gera `video.end_frame` na chamada); retry automático com backoff em 429
  "Concurrent generation limit reached" (a conta tem um teto de gerações simultâneas —
  antes disso, um vídeo-tour com vários clipes ao mesmo tempo falhava direto).
  `StubEngine`/`VeoEngine` aceitam os mesmos parâmetros mas ignoram (só o Luma faz
  transição real entre 2 quadros hoje).
- `app/video.py` — nova tabela `video_tours` (id, project_id, job_ids[], status,
  video_path); `create_video_tour()` gera os N-1 jobs de transição e um job de tour que
  espera todos, concatena e mixa a trilha; rotas `GET /api/video/tours/{id}` e
  `GET /api/video/tours/{id}/file`. `video_jobs` ganhou `stage_token2`/`stage_mime2`
  (um job de transição tem 2 imagens staged ao mesmo tempo — `_stage_image` agora recebe
  `slot=1|2`, `_cleanup_stage` limpa os dois).
- `app/presentations.py` — `POST /{project_id}/video-tour` (body opcional
  `{imageIds: [...]}`; sem isso, usa todas as imagens do projeto na ordem de envio).
- `app/static/apresentacoes.html` — botão "🎬 Criar vídeo tour" na tela do projeto +
  checkbox "Incluir no tour" em cada imagem (nenhuma marcada = usa todas).

**Achado técnico registrado**: a busca no histórico completo da conversa (antes deste
pedido) não encontrou nenhuma decisão prévia sobre como o vídeo deveria ser produzido —
a menção a "múltiplas imagens de uma vez" de uma sessão anterior era sobre o upload em
lote na UI, não sobre a geração de vídeo em si. Vale não presumir que uma decisão foi
tomada antes sem confirmar com o Davi.

**Duração por transição**: Luma só aceita `"5s"` ou `"10s"` (testado direto contra a API
real mandando um valor inválido de propósito pra ela revelar o enum aceito — não dá pra
pedir um número arbitrário de segundos). A pedido do Davi, **não tem seletor na UI** —
fica fixo em `"5s"` internamente (`TOUR_ALLOWED_DURATIONS`/`ALLOWED_DURATIONS` em
`app/video.py` e `app/video_engines.py`, parâmetro `duration` já encanado em toda a
cadeia se um dia precisar expor). Vídeo final dura (N-1) × 5s.

## 🔴 PROBLEMA REAL ENCONTRADO — precisa resolver antes de liberar (08/07/2026)

Depois de rodar o teste de ponta a ponta com as 5 imagens reais da cozinha (vídeo salvo
em `Downloads/video-tour-teste-cozinha.mp4` na máquina do Davi), o feedback dele foi:

> "o vídeo está errado. Criou outros ambientes. Mudou a cor e textura de alguns
> materiais."

Ou seja: o Luma, ao gerar a transição entre 2 imagens (`start_frame`/`end_frame`), **não
está sendo fiel ao projeto real** — inventa ambientes que não existem nas imagens de
referência e altera cor/textura de material (o mesmo tipo de problema que o Davi já tinha
avisado ser inegociável desde o início do projeto: "não alterar nada no projeto, layout,
de interiores"). Isso é mais grave do que o efeito de "sobreposição/fantasma" registrado
acima (que era só um artefato visual passageiro) — aqui o conteúdo em si fica infiel.

**Hipóteses a investigar na próxima sessão** (nenhuma testada ainda):
1. O prompt de transição (`TRANSITION_PROMPT` em `app/video.py`) pode não ser forte o
   suficiente pra restringir o Luma — talvez precise ser bem mais explícito/repetitivo
   sobre "não inventar nada, não mudar material nenhum, só mover a câmera".
2. Pode ser uma limitação real do modelo `ray-3.2` em manter fidelidade entre 2 imagens
   muito diferentes de ângulo — nesse caso, talvez a abordagem de transição encadeada
   (que o Davi pediu) não seja viável com qualidade aceitável, e valha reconsiderar as
   outras opções já levantadas (1 clipe por imagem isolado, ou 1 clipe início+fim só).
3. Vale testar com pares de imagens mais próximas entre si (ângulos parecidos) pra ver se
   o problema é proporcional à diferença entre as duas imagens do par.
4. Conferir se existe algum parâmetro do Luma pra aumentar a aderência às imagens de
   referência (ex: "guidance" mais alto, ou usar `end_frame` de um jeito diferente).

**Estado do código**: a funcionalidade toda (transições encadeadas + montagem + trilha)
está implementada e tecnicamente funcionando (sem erros, roda ponta a ponta) — o problema
é de **qualidade/fidelidade do resultado gerado pelo Luma**, não um bug de encanamento.

## Decisão (08/07/2026): geração de vídeo REMOVIDA da Neusa

Depois do problema acima, Davi decidiu: **abandonar o Luma e a geração de vídeo por
completo** — "não agrega o suficiente". Foco do produto passa a ser só **renders de
imagem + apresentações**. Ação tomada:

1. As mudanças de vídeo-tour (ainda não commitadas) foram revertidas via `git checkout`
   (nunca chegaram a entrar no histórico).
2. A funcionalidade de vídeo que já estava em produção foi removida por completo:
   `app/video.py` e `app/video_engines.py` apagados; router/init de vídeo tirados de
   `app/main.py`; endpoint `POST /{project_id}/images/{image_id}/video` tirado de
   `app/presentations.py`; ícone 🎬 + fluxo de staging de vídeo tirados de
   `app/static/index.html` (chat principal); botão "🎬 Gerar vídeo" tirado de
   `app/static/apresentacoes.html`; variáveis `VIDEO_ENGINE`/`LUMA_API_KEY` tiradas de
   `render.yaml`/`.env.example` (mantido `GOOGLE_API_KEY`/`PUBLIC_BASE_URL`, que também
   servem pra imagem e pra links de convite/senha, respectivamente).
3. A classe CSS compartilhada `.video-card` (usada tanto por vídeo quanto por imagem)
   virou `.render-card` — nome que já refletia melhor o que sobrou.
4. **Prompt-base de fidelidade** (pedido explícito do Davi): todo render agora recebe uma
   instrução fixa, **antes** de qualquer texto que a arquiteta escreva — não alterar
   layout, móveis, proporções, cor/textura de móveis/pedras/paredes do projeto original,
   e não inventar ambientes/objetos, exceto quando a própria instrução da arquiteta pedir
   uma mudança específica e pontual. Implementado em `app/image.py`
   (`FIDELITY_BASE_PROMPT` + `_build_prompt()`), aplicado no único ponto onde todo job de
   imagem passa antes de chamar o fornecedor (`_run_image_job`) — cobre tanto criação
   nova (`POST /jobs`) quanto "Refazer" (`POST /jobs/{id}/redo`). O prompt bruto da
   arquiteta continua salvo sem alteração no banco (pro campo de edição do "Refazer"
   continuar mostrando só o texto dela, não a instrução de base).
5. Não commitado ainda no momento em que este parágrafo foi escrito — ver estado do
   `git status` na sessão seguinte.

Para o histórico completo do projeto, decisões e detalhes técnicos, ver
`../memory/project_render_to_video_arquitetas.md`.
