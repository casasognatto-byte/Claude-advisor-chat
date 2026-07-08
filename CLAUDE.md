# Contexto do projeto — Sogno / advisor-chat

Este arquivo existe para dar continuidade entre sessões abertas em máquinas diferentes
(PC Escrit / Dell Casa) que compartilham esta pasta via OneDrive. Leia antes de mexer no código.

**Nota de rebrand (08/07/2026)**: a persona se chamava "Neusa"; agora é **"Sogno"**
(pronúncia "Sonho"), assistente de renderização e design da equipe de arquitetura. Menções
a "Neusa" em seções datadas abaixo são histórico da época — não precisam ser reescritas,
mas qualquer coisa nova deve usar "Sogno".

## O que é

Ecossistema de IA multiusuário da Casa Sognatto, acessível em **chat.casasognatto.com.br**.
Começou como um chat simples Executor+Advisor (ver README.md) e evoluiu para um sistema
com login por e-mail, papéis de usuário, conversas compartilhadas, painel admin, geração de
imagem (vídeo foi removido — ver seção datada 08/07/2026), e persona própria ("Sogno").

## Regra inegociável: confidencialidade do stack de IA

**Nunca revelar a terceiros (clientes, arquitetas, qualquer um fora do Davi) quais
ferramentas de IA são usadas por trás do sistema** (Claude, Anthropic, etc.).
A interface é sempre white-label. Existe inclusive uma feature (Fase 3) que detecta
perguntas do tipo "qual IA você usa?" e alerta no ClickUp, além de instruir o Sogno a
nunca confirmar nem negar. Ver `memory/feedback_confidencialidade_stack_ia.md` e
`memory/persona_neusa.md` (nome do arquivo é histórico) para o detalhe completo.

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

## Auditoria noturna (08/07/2026): Neusa testada como arquiteta de verdade

Enquanto o Davi dormia, pediu pra eu "virar um agente" e auditar a Neusa usando-a de
verdade — como uma arquiteta parceira usaria, não só lendo código. Rodei o servidor local
(perfil `advisor-chat-local`, porta 8001, banco `advisor_chat_dev` local) e usei o usuário
de teste "Nova Arquiteta" (papel `membro`) pra logar e navegar pela aplicação de verdade
via browser automatizado, com chamadas reais à Anthropic (chat + classificação de
ambiente) e engine de imagem em modo `stub` (sem `GOOGLE_API_KEY` real disponível esta
noite).

### Corrigidos nesta sessão (já commitados)

1. **Prompt não limpava após "Gerar"** (`app/static/index.html`) — depois de anexar
   imagem + escrever instruções + clicar "Gerar", o texto continuava no campo de
   mensagem. Se a arquiteta apertasse Enter/ENVIAR em seguida, esse texto virava uma
   mensagem de chat comum pra Neusa (duplicado, sem sentido, gastando uma chamada à
   Claude à toa). Corrigido: `input.value` é limpo assim que o prompt é lido.
2. **Placeholder "Comece uma nova conversa" ficava sobreposto ao resultado** — na
   primeira geração de uma conversa nova, o aviso de "conversa vazia" continuava visível
   ao lado do card de render, porque `startImageJob` inseria o resultado direto no DOM
   sem limpar o placeholder. Corrigido.
3. **"Ver referências" mostrava o próprio projeto como referência de si mesmo**
   (`app/presentations.py` + `apresentacoes.html`) — a busca de "referências de projetos
   anteriores" não excluía o projeto atual, então uma imagem recém-enviada aparecia como
   "referência" pra ela mesma. Adicionado `exclude_project_id` na busca.
4. **Mobile: aba "Padrões técnicos" ficava cortada e inacessível** na Biblioteca de
   Apresentações — `nav.tabs` não tinha `flex-wrap`, então em telas estreitas a terceira
   aba saía da tela sem nenhuma forma de rolar até ela. Corrigido com `flex-wrap: wrap`.

### Reportados, NÃO corrigidos (decisão ou investimento maior — ver com o Davi)

5. **Chat principal sem breakpoint mobile de verdade** — `app/static/index.html` não tem
   nenhuma `@media query`; a barra lateral é sempre 270px fixos. Numa tela de celular
   comum (~375-414px), isso deixa pouquíssimo espaço pro chat em si, e só dá pra ver o
   conteúdo tocando manualmente no ☰ pra recolher a barra (funciona, mas não é o padrão
   — a maioria dos apps de chat já abre recolhido/adaptado em tela pequena). Não mexi
   nisso por ser uma mudança de layout maior, não um bug pontual — melhor o Davi decidir
   se quer investir nisso ou se o uso real é sempre em desktop/tablet.
6. **Estado de navegação se perde ao recarregar a página** — se a arquiteta der F5 (ou o
   navegador restaurar a aba) dentro de um projeto da Biblioteca de Apresentações, ela
   volta pra lista de projetos (perde o "onde eu estava"). Não é perda de dado (tudo
   persiste no servidor, confirmado), só obriga clicar de novo no projeto. Não é único —
   o chat principal tem o mesmo padrão (sempre volta pra última conversa ativa salva
   localmente, então esse é menos crítico).
7. ~~Logo da tela de login retorna 404~~ — **falso alarme, verificado e descartado.** Vi
   `GET /static/logo.png → 404` no console e anotei como achado, mas ao checar o código
   (`login.html`) vi que é proposital: a tag `<img>` começa com `display:none` e só
   aparece via `onload` — se o arquivo não existir, o 404 é inofensivo e o fallback em
   texto (que já é o que aparece hoje) continua visível. Nenhuma ação necessária.
8. **Prompt-base de fidelidade (item 4 da seção anterior) não testado contra um
   fornecedor real esta noite** — confirmei por teste unitário direto e revisão de código
   que `_build_prompt()` está corretamente encanado como o único ponto de entrada antes
   de qualquer engine de imagem, mas como só há `IMAGE_ENGINE=stub` disponível aqui (sem
   `GOOGLE_API_KEY` real), não dá pra confirmar visualmente que o Nano Banana realmente
   respeita a instrução. Recomendo o Davi testar uma vez com uma chave real antes de
   confiar 100% nisso.

### Pontos fortes confirmados (sem achados)

- Persona da Neusa: saudação por nome/horário funcionando bem, tom consistente
  ("Boa noite, Nova Arquiteta!..."), resposta rápida (poucos segundos).
- Classificação automática de ambiente: 100% de acerto nos testes (2/2 imagens de
  cozinha real classificadas corretamente via visão computacional).
- Persistência de estilo (cor MDF, tom de luz, decoração): salva e recarrega
  corretamente.
- Biblioteca de padrões técnicos → sugestão automática no campo de iluminação: funciona
  ponta a ponta.
- Download em lote (.zip): testado, zip válido, todas as imagens presentes.
- Fluxo de "Refazer": mostra o prompt original (sem a instrução de fidelidade, como
  projetado) pra edição.
- Nenhum erro de JavaScript no console em nenhuma das telas testadas.
- Confirmado visualmente: nenhum ícone/botão/menção a vídeo restou em nenhuma tela.

### Ambiente de teste (limpo ao final)

Projeto de teste "Auditoria Neusa - Cozinha Teste", padrão técnico de teste e 2
conversas "Nova conversa" criadas durante a auditoria foram apagados ao final. Usuário
de teste "Nova Arquiteta" (não faz parte do roster oficial, já existia de sessão
anterior) devolvido ao estado `active=false` em que foi encontrado. Servidor local
parado. Nada disso toca produção — tudo rodou contra o banco `advisor_chat_dev` local.

## Rebrand + redesign completo (08/07/2026, madrugada): Neusa → Sogno

Pedido do Davi logo após a auditoria acima: abandonar o nome "Neusa", a paleta verde e a
tipografia antigas, e refazer o visual seguindo tendências atuais — apropriado pra quem
trabalha várias horas por dia julgando cor/material de render (arquitetas). Ele também
mandou um prompt do Gemini pedindo um redesign em React/Tailwind/Framer Motion/Lucide.

**Decisão de arquitetura** (aprovada pelo Davi antes de eu implementar): a stack hoje é
FastAPI + HTML/CSS/JS puro, sem build step. Migrar pra React seria reescrever o
frontend inteiro (dias de trabalho, risco de regressão em tudo que já funciona) — então
implementei a MESMA visão estética do prompt do Gemini em CSS puro sobre a stack atual:
dark mode com glassmorphism, acento cobre/ouro, tipografia limpa, layout de 3 colunas.
Zero risco de arquitetura, foi pro ar na mesma sessão.

**Nome**: "Neusa" → **"Sogno"** (pronúncia "Sonho"). Novo system prompt em `app/main.py`
(`DEFAULT_SYSTEM_PROMPT`) com a persona "Diretor de Arte" que o Davi escreveu — mantém a
mecânica de saudação por horário e a regra de confidencialidade (inegociável, só trocou
"Neusa" por "Sogno" no texto). Referências a "Neusa" em código/comentários trocadas por
"Sogno" (menções históricas datadas no CLAUDE.md foram deixadas como estão, são registro
do que era verdade na época).

**Visual**: `app/static/theme.css` (novo, compartilhado por todas as telas) — paleta
neutra escura tipo "estúdio criativo" (Figma/Adobe/DaVinci — fundo cinza-grafite neutro
de propósito, não colorido, porque quem julga cor de render o dia todo precisa de
referência neutra), acento cobre/ouro envelhecido, fonte Inter (Google Fonts) pro corpo,
Sackers/Benjamin (já carregadas) reaproveitadas pro wordmark. Aplicado em
`index.html`/`apresentacoes.html`/`admin.html`/`login.html`/`definir-senha.html`/`forgot.html`
trocando só os valores das variáveis `:root` de cada arquivo (nomes das variáveis
continuam os mesmos — `--green-800`, `--gold` etc. — só os valores mudaram, então o resto
de cada arquivo não precisou ser tocado).

**Chave/logo**: o Davi mandou o arquivo de identidade visual oficial
(`.../15 - PIN/AI/CASA SOGNATO pin de lapela de metal 3 x 6 cm.ai`) — é compatível com
PDF (`%PDF-1.6` no cabeçalho), então abri com PyMuPDF (`pip install pymupdf`, sem precisar
de Illustrator) e extraí o vetor exato em SVG. Path colado inline em todas as telas
(`fill="currentColor"`, herda a cor do tema em cada contexto) substituindo meu SVG
aproximado de antes. Cópia guardada em `app/static/brand/chave-casa-sognatto.svg` +
`NOTICE.md` com a origem.

**`app/static/index.html` — layout novo (index.html: 3 colunas)**:
- Sidebar (~280px): wordmark SOGNO + "CASA SOGNATTO" (mantém identificação da loja),
  botão "Novo render", lista de conversas — vira *overlay* deslizante em celular
  (< 768px), sempre visível em desktop.
- Centro: mensagens em cards de vidro (glassmorphism) com avatar circular (inicial do
  usuário / "S" do Sogno), chips de ação rápida acima do composer ("Ajustar Luz",
  "Humanizar", "Trocar MDF", "Nível do olhar" — inserem texto pronto no campo), composer
  flutuante com sombra profunda.
- **Inspetor de Render (coluna direita, ~320px, nova)**: galeria de referências (renders
  já gerados nesta conversa) + painel "Parâmetros atuais" com checklist (luz/textura/
  câmera). Vira overlay via botão 🎛 no header em telas < 1180px.
- Responsivo automático: sidebar e inspetor colapsam sozinhos em celular (script inline
  síncrono checa `window.innerWidth` antes do primeiro paint, sem "flash" visível).

**Parâmetros do Inspetor são de verdade, não decoração** — pedido explícito do Davi.
`app/image.py`: 3 colunas novas em `image_jobs` (`param_light`, `param_texture`,
`param_camera`); `_derive_render_params()` faz uma chamada rápida à Claude (mesmo modelo
do executor) que lê o prompt da arquiteta e devolve os 3 campos — resume o que ela já
especificou, ou sugere um padrão razoável e sinaliza como sugestão quando ela não disse
nada (ex: "Sugestão: nível do olhar frontal"). Roda em paralelo à geração da imagem
(`asyncio.create_task`, não atrasa nem derruba o render se falhar). Testado de ponta a
ponta com prompt real — funcionou (`luz quente direta`, `porcelanato cinza polido`,
`Sugestão: nível do olhar frontal`).

**Bugs reais encontrados testando o layout novo (corrigidos na hora)**:
- O placeholder "Comece uma nova conversa" ficava sobreposto à primeira mensagem de
  texto de uma conversa nova (mesma classe de bug já corrigida pra render de imagem na
  auditoria — dessa vez no caminho de `send()`, que eu não tinha testado antes). Corrigido
  de forma centralizada: `renderItem()` agora sempre remove o placeholder `.empty` antes
  de inserir qualquer item, então nenhum caminho futuro pode reintroduzir esse bug.

**Testado em desktop (1440px) e mobile (375px)**: layout, geração de render com
Inspetor populando de verdade, persona nova respondendo como Sogno (testado inclusive o
desvio de confidencialidade — funcionou, nunca menciona Claude/Anthropic nem que existe
uma regra), painel admin, Biblioteca de Apresentações, tela de login — tudo com a paleta
nova, sem erro de console em nenhuma tela. Dados de teste limpos ao final (mesmo padrão
de sempre).

## Catálogo de cores Simonetto/Stimmo (08/07/2026, mesma madrugada)

Davi mandou a planilha real de cores de MDP/MDF das duas marcas do Grupo Simonetto
(`C:\Users\user\OneDrive\1. SOGNATTO AMBIENTES PLANEJADOS\CORES DAS LINHAS.xlsx`) e pediu
um botão que diferencie Simonetto/Stimmo com seleção de várias cores ao mesmo tempo.

**Estrutura real da planilha** (referência pra próximas importações): uma aba por ano
(2023/2024/2025...), cabeçalho na linha 1 com o nome da marca ("SIMONETTO", "STIMMO" —
numa aba aparece com erro de digitação "ESTIMMO") numa coluna, e abaixo dela pares (nome
da cor, fabricante da placa: ARAUCO/DURATEX/EUCATEX/BERNECK/GUARARAPES/GREEN PLAC) até a
lista acabar. Sempre pega a aba do ano mais recente.

**Backend novo** (`app/materials.py`): tabela `material_colors` (brand, name,
manufacturer). `POST /api/materials/import` (só diretor, multipart .xlsx) — localiza as
colunas de marca pelo TEXTO do cabeçalho (não posição fixa, tolera pequenas mudanças de
layout entre uma planilha e a próxima que o Davi mandar), substitui o catálogo inteiro
(DELETE + INSERT). `GET /api/materials/colors?brand=` lista pra qualquer membro logado.
Testado com a planilha real: 44 cores Simonetto + 30 Stimmo importadas corretamente,
incluindo nomes acentuados ("CRÔMIO", "ÉBANO CHESS") — a planilha original já tinha UTF-8
correto, um mojibake que vi no meu terminal bash era só limitação de exibição do
terminal, não um problema real do dado.

**Frontend**: novo ícone 🎨 no composer do chat principal, abre modal "Cores oficiais"
com abas Simonetto/Stimmo, busca por nome, grade de cores com checkbox — **seleção
persiste entre as duas abas** (dá pra marcar cores das duas marcas na mesma sessão antes
de confirmar), painel lateral mostra as selecionadas com chip removível. "Usar cores
selecionadas" insere `"Cores de referência: NOME1, NOME2, ..."` no campo de mensagem.

**Painel admin**: nova seção "Cores oficiais" com status (quantas cores, quando/quem
importou por último) + upload de nova planilha — pro Davi reimportar sozinho quando
mandar uma atualização, sem precisar de mim.

**Bug real encontrado e corrigido durante o teste**: a regra CSS `.colors-main input {
width: 100%; }` (pensada só pro campo de busca) estava afetando TODOS os `<input>` dentro
do modal por seletor descendente, inclusive os checkboxes da grade — cada checkbox virava
uma barra esticada até a borda do card, espremendo o nome da cor pra largura zero
(invisível). Só percebi porque o `preview_screenshot` deu timeout duas vezes e eu quase
segui confiando só no snapshot/DOM (que confirma que o texto existe, mas não pega bug
visual de layout) — insisti no screenshot depois de resolver o timeout e vi o problema.
Corrigido trocando pro seletor `#colorsSearch` (só o campo de busca). Lição: quando
`preview_screenshot` falha, não seguir só com verificação por texto/DOM — voltar e tirar
o screenshot de verdade antes de dar como testado.

Testado de ponta a ponta (import real via planilha, seleção multi-marca, inserção no
composer, reimportação pelo admin) em desktop e mobile, sem erro de console.

**Confirmado pelo Davi**: catálogo fechado (só as cores importadas da planilha oficial,
sem campo de texto livre) é o design certo — "a indústria não trabalha com cores não
oficiais", ou seja, móveis planejados só são fabricados nas cores que constam no
catálogo oficial de cada marca. Não adicionar no futuro nenhuma forma de digitar/inventar
uma cor fora da lista importada. Também confirmou que **não precisa de logo/ícone de
marca** nas abas Simonetto/Stimmo — texto simples já é suficiente, gostou do resultado
como está. Título do modal e da seção no admin simplificados de "Cores oficiais" pra só
"Cores" (pedido dele).

### Ajuste: distribuir cor por móvel quando há 2+ cores selecionadas

Davi levantou um problema real: com 2+ cores selecionadas (comum pedir 2 cores pra uma
cozinha, por exemplo), como o Sogno sabe qual cor vai em qual móvel? Cheguei a considerar
numerar os móveis na imagem pra arquiteta apontar, mas descartei — nenhuma IA de visão
aqui desenha marcações confiáveis sobre pixels específicos (exigiria um modelo de
detecção de objetos à parte, mais infraestrutura e mais chance de erro). Solução mais
simples e robusta, aprovada pelo Davi:

1. **Frontend**: com 1 cor selecionada, insere `"Cor de referência: NOME."` (sem
   ambiguidade, não precisa de nada a mais). Com 2+, insere um modelo pra completar:
   `"Cores de referência:\n- NOME1 no(s): ___\n- NOME2 no(s): ___"` — a arquiteta escreve
   o nome do móvel em cada linha antes de mandar.
2. **Rede de segurança no system prompt**: se ela mandar sem preencher os `___` (ou
   mencionar 2+ cores sem deixar claro a distribuição de outra forma), o Sogno **pergunta
   explicitamente** qual cor vai em qual móvel antes de seguir — nunca escolhe por conta
   própria. Testado de ponta a ponta com o modelo em branco: o Sogno pediu exatamente a
   distribuição certa, no tom da persona.

## Descartado (08/07/2026): voz (STT/TTS)

Davi decidiu não seguir com isso — item removido da lista de pendências. Se voltar a ser
cogitado no futuro, tratar como pedido novo, não como retomada de algo já planejado.

## Biblioteca de Apresentações: modelos (abertura/fechamento) + PDF + link animado (08/07/2026)

Davi foi dormir e pediu pra eu continuar com o que não depende dele. Concluído nesta
madrugada: "Slides Institucionais" (um conjunto único) virou **"Modelos de
Apresentação"** (vários — ex: Simonetto, Stimmo, por equipe), cada um com slides marcados
como abertura ou fechamento. Um projeto de cliente escolhe um modelo; o deck final fica
sempre **abertura do modelo → renders do cliente → fechamento do modelo**. Duas formas de
compartilhar: link público animado (token aleatório, sem login, mesmo padrão de segurança
já usado no staging do Luma, revogável a qualquer momento) e **PDF** (documento estático,
pra virar anexo de contrato — essa é a motivação real: apresentação pode virar parte do
contrato, precisa de arquivo fechado, não link/HTML). PDF gerado com Pillow (nova
dependência em `requirements.txt`), sem headless Chrome nem WeasyPrint.

Testado localmente de ponta a ponta (backend via `httpx` direto e via navegador real):
criar modelo, subir slide de abertura e de fechamento, criar projeto, atribuir modelo,
montar deck (ordem abertura→ambientes→fechamento confirmada), baixar PDF (`%PDF-1.4`
válido), gerar link público, acessar o deck e o arquivo da imagem **sem cookie de
sessão** (token puro), revogar o link e confirmar 404 depois. Encontrado e corrigido um
bug real de ordenação de rotas: `GET /templates` (1 segmento) ficava atrás de
`GET /{project_id}` no arquivo, e o FastAPI/Starlette casa rotas por ordem de registro —
qualquer request pra `/templates` caía no catch-all e devolvia 404 "Projeto não
encontrado". Rotas de modelo foram movidas pra antes do catch-all. Dados de teste
apagados do banco local ao final. Commit local feito, **sem push** — fica pra Davi
revisar e decidir quando subir.

Nota de ambiente (não é bug): a primeira chamada que usa Pillow em cada processo do
servidor local demora ~10s (import) + ~10s por formato (PNG, PDF) na primeira vez —
efeito do projeto estar dentro do OneDrive, não do código. Em produção (Render, fora do
OneDrive) isso não deve acontecer.

**Ainda pendente, precisa do Davi quando acordar**: revisar e decidir se quer dar push
nesse commit; conferir se o deploy de antes (push `5d92256`) subiu certo no Render —
visual novo + nome "Sogno" (se ainda aparecer "Neusa", existe uma variável
`SYSTEM_PROMPT` manual no painel sobrescrevendo o padrão do código, precisa apagar lá) —
e reimportar a planilha de cores em produção (importei só no banco de dev local; produção
é outro Postgres, banco lá ainda está vazio). Falta também construir a UI de fato pra
escolher slides de abertura/fechamento em produção (a interface já existe, só falta
popular os modelos reais — Simonetto/Stimmo — com os slides institucionais de verdade).

## Sessão 08/07/2026 (manhã): push via SSH, upgrade de plano, achado sério de perda de imagens

**Confirmado nesta sessão**: Davi já importou a planilha de cores em produção (74 cores,
44 Simonetto + 30 Stimmo — testado ao vivo no chat: modal abre, ambas as abas certas,
seleção múltipla funcionando, template de texto "no(s): ___" inserido certo).

**GitHub bloqueado por rede (porta 443)**: às 08h de hoje, `git push` parou de
funcionar — `Failed to connect to github.com port 443`, confirmado também no navegador
(`ERR_CONNECTION_TIMED_OUT` em github.com/login). Pesquisa apontou bloqueio nacional
reportado no Brasil em junho/2026 (suspeita de erro em ordem da Anatel). Porta 22 (SSH)
respondeu normalmente. **Contorno aplicado, permanente**: gerei uma chave SSH
(`~/.ssh/id_ed25519`), Davi cadastrou em github.com/settings/keys pelo 4G do celular, e
troquei o remote do repo local pra SSH (`git remote set-url origin
git@github.com:casasognatto-byte/Claude-advisor-chat.git`). Push por SSH funcionando
normalmente desde então — usar sempre esse remote, não precisa mais mexer nisso.

**Feature nova**: apagar conversas em lote no painel do diretor (checkbox por linha +
"selecionar todas", endpoint `POST /api/admin/conversations/bulk-delete`) — commit
`008c5d2`, testado e no ar.

**Feature nova**: atalho ⚙ no topo do chat pro Painel do Diretor, além do link que já
existia na sidebar — commit `7d52505`, testado e no ar.

**Upgrade de plano Render, Free → Starter (US$7/mês)**: pedido do Davi pra eliminar a
tela de "cold start" (~50s) que aparecia quando o serviço ficava 15min sem uso. Feito
pelo dashboard, confirmado "Instance type changed from Free to Starter", deploy seguinte
ficou live.

**ACHADO SÉRIO, parcialmente corrigido — precisa verificação ao retomar**: logo depois do
upgrade de plano, Davi reportou que os renders gerados no chat sumiram da tela (só
apareciam os botões "Baixar imagem"/"Refazer", sem a imagem). Investigado a fundo:

1. `app/image.py` salvava os arquivos (renders + imagem de origem) **só em disco local
   efêmero do servidor** — diferente da Biblioteca de Apresentações, que já usa
   `app/storage.py` (Cloudflare R2 com fallback local). Toda vez que o Render faz um
   deploy/restart, o disco local é apagado — e isso inclui **qualquer** deploy (todo
   `git push` já dispara um), não só trocas de plano. Ou seja, imagens geradas no chat
   provavelmente já vinham sumindo há muito tempo, não só hoje.
2. Achado relacionado: `SECRET_KEY` (assina o cookie de sessão) não era uma variável de
   ambiente fixa — o código cai num valor aleatório gerado a cada boot
   (`secrets.token_hex(32)`, ver `app/main.py`), então cada deploy também derrubava o
   login de todo mundo. Foi isso que explicou a sessão cair sozinha no meio dos testes
   desta manhã.

**Correção aplicada e commitada** (`6fbb6fd`, já com push feito via SSH):
- `app/image.py` migrado pra usar `app.storage` (mesmo padrão R2/local da Biblioteca de
  Apresentações) em todos os pontos: criar job, "Refazer", download em lote, servir
  arquivo. Nova coluna `image_mime` (a chave de storage não carrega mais extensão
  previsível do jeito que o caminho de arquivo antigo carregava).
- `render.yaml`: `SECRET_KEY` com `generateValue: true` (Render gera um valor uma vez e
  mantém fixo entre deploys — resolve o logout forçado). `plan: starter` sincronizado no
  arquivo (estava `free`) pra não reverter o upgrade manual num próximo sync do blueprint.
- `/api/health` ganhou o campo `r2_enabled`, pra dar visibilidade sem precisar caçar no
  painel do Render se R2 está configurado ou não.
- Testado localmente de ponta a ponta (bytes idênticos entrada/saída em cada etapa).

**PENDENTE — não confirmado ainda, retomar daqui**: o Render só aplica variáveis/plano
declarados no `render.yaml` através de um "sync" do Blueprint (painel
`dashboard.render.com/blueprint/exs-d90ou777f7vs73cr9870/syncs`), separado do
auto-deploy de código que já roda a cada push. O último sync registrado ali era de
**antes** de todos os commits de hoje (10h atrás no momento). Cliquei em "Manual sync"
várias vezes tentando forçar a aplicação do `SECRET_KEY` novo, mas **nenhuma nova
entrada apareceu na lista de syncs nem disparou uma requisição de rede visível** —
parece que o clique não estava registrando de verdade (não confirmado se é bug da
extensão do navegador, elemento sobreposto por algo, ou preciso de outro caminho, tipo
mexer direto pela CLI/API do Render). Sessão foi interrompida aqui porque o Davi
precisou sair.

**Passos exatos pra retomar**:
1. Confirmar se o Manual sync já rodou nesse meio tempo (checar
   `dashboard.render.com/blueprint/exs-d90ou777f7vs73cr9870/syncs` — deve aparecer uma
   entrada nova do commit `6fbb6fd`). Se não tiver rodado, tentar de novo (talvez direto
   pelo navegador do Davi, não só via automação) ou considerar que o próximo deploy
   normal (qualquer novo `git push`) pode aplicar as env vars do blueprint de qualquer
   jeito — vale testar antes de insistir no sync manual.
2. Checar `https://chat.casasognatto.com.br/api/health` → campo `r2_enabled`. Se
   `true`: os renders do chat já devem persistir daqui pra frente. Se `false`: a
   migração de código está certa mas R2 ainda não está configurado em produção — vai
   continuar perdendo imagem a cada deploy até as variáveis `R2_ACCOUNT_ID` /
   `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` serem configuradas de
   verdade no painel do Render (conta Cloudflare R2 grátis, se ainda não existir uma).
3. Gerar um render de teste no chat de produção depois de confirmar o R2 (ou depois de
   um deploy novo) e recarregar a página, pra confirmar visualmente que a imagem
   continua aparecendo — esse é o teste real que prova que o bug foi corrigido.
4. Confirmar que o login não cai mais sozinho depois de um deploy (sinal de que o
   `SECRET_KEY` fixo pegou).

Para o histórico completo do projeto, decisões e detalhes técnicos, ver
`../memory/project_render_to_video_arquitetas.md`.
