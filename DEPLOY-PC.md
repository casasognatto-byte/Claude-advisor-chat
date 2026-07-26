# Sogno no PC-servidor (acesso local + remoto + celular)

Guia para rodar a plataforma Sogno (Chat + Code) no PC da loja/casa como
servidor, acessível de qualquer dispositivo seu — com segurança, sem abrir
portas no roteador.

## 1. O que é o Tailscale (a peça de segurança)

Tailscale é uma **rede privada criptografada** entre os seus dispositivos (uma
"VPN mesh" sobre WireGuard). Na prática:

- Cada dispositivo (PC-servidor, notebook, PCs da loja, celulares) instala o
  app do Tailscale e entra na **sua** conta. Só dispositivos da sua conta se
  enxergam — nada fica exposto na internet aberta.
- Cada dispositivo ganha um nome fixo (ex.: `pc-loja`) e um IP privado da sua
  rede (`100.x.y.z`). Você acessa o Sogno por `http://pc-loja:8000` de
  qualquer um deles — na loja, em casa, na rua pelo celular.
- **Não precisa** abrir porta no roteador, IP fixo ou DDNS. O tráfego é
  criptografado de ponta a ponta e costuma furar NAT sozinho.
- Plano gratuito cobre dezenas de dispositivos — de sobra para a loja.

Site: <https://tailscale.com> (baixe o app para Windows/Android/iOS de lá).

## 2. Preparar o PC-servidor (uma vez só)

1. **O projeto já está no PC** se ele sincroniza a mesma pasta OneDrive
   (`OneDrive\4. Claude Code\advisor-chat`). Se não sincronizar, copie a pasta
   ou clone o repositório.
2. Instale o **Python 3.10+** (<https://python.org>, marque "Add to PATH").
   O `.venv` da pasta é por máquina — se der erro de "No Python at...", recrie:
   ```bat
   cd "OneDrive\4. Claude Code\advisor-chat"
   rmdir /s /q .venv
   C:\Users\<SEU-USUARIO>\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
3. Confira o `.env`: precisa ter `DATABASE_URL`, `ANTHROPIC_API_KEY` (Chat),
   `MOONSHOT_API_KEY` (Code) e `SECRET_KEY`. Se o projeto veio pela OneDrive,
   o `.env` já viajou junto com tudo preenchido.
   - ⚠️ Lembrete de segurança: o `.env` com as chaves sincroniza pela
     OneDrive. É o arranjo atual do projeto — ok para uso próprio, mas não
     compartilhe a pasta com ninguém.

## 3. Subir o servidor

Teste manual primeiro:

```bat
cd "OneDrive\4. Claude Code\advisor-chat"
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abra `http://localhost:8000` no PC — deve aparecer a tela de login do Sogno.

### Auto-start com o Windows (Agendador de Tarefas)

Para o servidor voltar sozinho depois de reiniciar/desligar:

```bat
schtasks /create /tn "SognoServer" /sc onlogon /rl highest /tr "\"C:\Users\<SEU-USUARIO>\OneDrive\4. Claude Code\advisor-chat\.venv\Scripts\python.exe\" -m uvicorn app.main:app --host 0.0.0.0 --port 8000" /f
```

(Depois, no Agendador de Tarefas, marque "Executar estando o usuário conectado
ou não" se quiser que rode sem login. Para remover: `schtasks /delete /tn
"SognoServer" /f`.)

## 4. Rede: Tailscale em todos os dispositivos

1. Crie a conta em <https://login.tailscale.com> (pode entrar com Google).
2. Instale o Tailscale **no PC-servidor** e conecte. Anote o nome da máquina
   no painel admin (ex.: `pc-loja`) — é o endereço que você vai usar.
3. Instale e conecte o Tailscale **em cada dispositivo** que vai acessar:
   notebook, PCs da loja, seu celular (app oficial Android/iOS).
4. De qualquer um deles, abra: `http://pc-loja:8000` — login normal do Sogno.
   - Chat da equipe: `http://pc-loja:8000/`
   - Sogno Code (só Davi): `http://pc-loja:8000/code`

> Sem Tailscale, só dentro do Wi-Fi local funciona (`http://<IP-do-PC>:8000`)
> — e ainda assim é preciso liberar a porta 8000 no Firewall do Windows
> (`netsh advfirewall firewall add rule name="Sogno" dir=in action=allow
> protocol=TCP localport=8000`). Com Tailscale, nada disso é necessário e
> funciona de fora também.

## 5. E o Render?

O deploy atual (chat.casasognatto.com.br) **continua no ar** — a equipe não
perde acesso em momento nenhum. Quando o PC-servidor estiver redondo, você
decide: manter os dois (Render como reserva) ou migrar de vez. Se quiser o
Sogno Code também na URL pública do Render, adicione `MOONSHOT_API_KEY` como
variável secreta no painel do Render (o código já está preparado).

## 6. Solução de problemas

| Sintoma | Provável causa |
|---|---|
| `No Python at 'C:\Users\davin\...'` | `.venv` veio de outra máquina — recrie (passo 2) |
| Login carrega mas conversas somem | `DATABASE_URL` ausente/errada no `.env` |
| Code responde "MOONSHOT_API_KEY não está configurada" | falta a variável no `.env` (passo 2.3) |
| `/code` dá 403 | você não está logado com o e-mail master (davinogueira@…) |
| Celular não abre `http://pc-loja:8000` | Tailscale do celular desconectado, ou nome da máquina diferente no painel |
