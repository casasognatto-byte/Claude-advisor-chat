"""Envio de e-mail transacional (convite de cadastro, reset de senha).

Backend selecionável por env `EMAIL_BACKEND`:
  - "console" (padrão): NÃO envia nada — só escreve o e-mail (e o link) no log
    do servidor. Perfeito para desenvolvimento/teste sem credenciais reais.
  - "smtp": envia de verdade via SMTP (usa a caixa @casasognatto.com.br ou
    qualquer servidor SMTP). Precisa de SMTP_HOST/PORT/USER/PASSWORD/EMAIL_FROM.

Nunca levanta exceção para o chamador — falha de e-mail não pode derrubar o
cadastro/fluxo; retorna True/False e registra o erro no log.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "console").lower()
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Casa Sognatto <nao-responder@casasognatto.com.br>")

# Pedido do Davi (14/07/2026): como diretor, ele precisa conseguir completar a
# redefinição de senha de qualquer usuário (ex: alguém desligado da empresa) sem
# depender do e-mail pessoal dessa pessoa. O e-mail de "esqueci minha senha" vai em
# cópia oculta (BCC) pra essa caixa — o link funciona pra quem clicar primeiro,
# então o diretor tem uma via de acesso de backup real, não só uma notificação.
PASSWORD_RESET_BCC = os.environ.get("PASSWORD_RESET_BCC", "casasognatto@gmail.com")


def _send_smtp(to: str, subject: str, html_body: str, text_body: str, bcc: str | None = None) -> bool:
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    use_starttls = os.environ.get("SMTP_STARTTLS", "true").lower() != "false"
    if not host or not user or not password:
        print("[email] EMAIL_BACKEND=smtp mas faltam SMTP_HOST/USER/PASSWORD — e-mail não enviado.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    # bcc não vira header (fica de fora do "Para:" que o destinatário vê) — só
    # entra na lista de entrega passada explicitamente ao servidor SMTP abaixo.
    to_addrs = [to, bcc] if bcc and bcc.lower() != to.lower() else [to]

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as s:
                s.login(user, password)
                s.send_message(msg, to_addrs=to_addrs)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                if use_starttls:
                    s.starttls(context=ssl.create_default_context())
                s.login(user, password)
                s.send_message(msg, to_addrs=to_addrs)
        return True
    except Exception as e:
        print(f"[email] falha ao enviar via SMTP para {to}: {e}")
        return False


def send_email(to: str, subject: str, html_body: str, text_body: str | None = None, bcc: str | None = None) -> bool:
    """Envia (ou simula) um e-mail. Retorna True se foi entregue ao backend."""
    text_body = text_body or "Abra este e-mail em um cliente com suporte a HTML."
    if EMAIL_BACKEND == "smtp":
        return _send_smtp(to, subject, html_body, text_body, bcc=bcc)
    # console (padrão): só loga — inclui o corpo em texto para o link ficar visível.
    print(
        "\n========== [email:console] ==========\n"
        f"Para:     {to}\n"
        + (f"Cópia oculta: {bcc}\n" if bcc and bcc.lower() != to.lower() else "")
        + f"Assunto:  {subject}\n"
        f"---\n{text_body}\n"
        "=====================================\n"
    )
    return True


def _brand_wrapper(inner_html: str) -> str:
    """Moldura visual simples com as cores da marca (verde/dourado/creme)."""
    return f"""\
<div style="background:#152C1C;padding:32px;font-family:Arial,Helvetica,sans-serif;color:#ece9e1">
  <div style="max-width:520px;margin:0 auto;background:#0f2114;border:1px solid #2a4434;border-radius:14px;padding:32px">
    <div style="text-align:center;margin-bottom:24px">
      <div style="font-size:11px;letter-spacing:.4em;color:#ece9e1">CASA</div>
      <div style="font-size:26px;color:#ece9e1">SOGNATTO</div>
      <div style="font-size:9px;letter-spacing:.28em;color:#c2a06a;text-transform:uppercase;margin-top:4px">O luxo está no singular</div>
    </div>
    {inner_html}
  </div>
</div>"""


def _button(url: str, label: str) -> str:
    return (
        f'<div style="text-align:center;margin:28px 0">'
        f'<a href="{url}" style="background:#c2a06a;color:#1c1408;text-decoration:none;'
        f'padding:13px 26px;border-radius:10px;font-weight:bold;display:inline-block">{label}</a></div>'
    )


def send_invite_email(to: str, name: str, link: str) -> bool:
    subject = "Bem-vindo(a) à plataforma da Casa Sognatto — confirme seu cadastro"
    inner = (
        f'<p style="font-size:15px;line-height:1.6">Olá, {name}!</p>'
        f'<p style="font-size:15px;line-height:1.6">Seu acesso à plataforma interna da '
        f'Casa Sognatto foi criado. Para ativar sua conta e definir sua senha, clique '
        f'no botão abaixo:</p>'
        + _button(link, "Confirmar e definir senha")
        + '<p style="font-size:12px;color:#93a597;line-height:1.6">Se você não esperava '
        'este e-mail, pode ignorá-lo. Este link expira em 7 dias.</p>'
    )
    text = (
        f"Olá, {name}!\n\nSeu acesso à plataforma da Casa Sognatto foi criado. "
        f"Confirme sua conta e defina sua senha neste link (expira em 7 dias):\n\n{link}\n"
    )
    return send_email(to, subject, _brand_wrapper(inner), text)


def send_reset_email(to: str, name: str, link: str) -> bool:
    subject = "Redefinição de senha — Casa Sognatto"
    inner = (
        f'<p style="font-size:15px;line-height:1.6">Olá, {name}!</p>'
        f'<p style="font-size:15px;line-height:1.6">Recebemos um pedido para redefinir '
        f'a senha da sua conta. Para escolher uma nova senha, clique abaixo:</p>'
        + _button(link, "Redefinir senha")
        + '<p style="font-size:12px;color:#93a597;line-height:1.6">Se não foi você quem '
        'pediu, ignore este e-mail — sua senha atual continua valendo. Este link expira em 1 hora.</p>'
    )
    text = (
        f"Olá, {name}!\n\nRecebemos um pedido para redefinir sua senha. "
        f"Escolha uma nova senha neste link (expira em 1 hora):\n\n{link}\n\n"
        "Se não foi você, ignore este e-mail."
    )
    return send_email(to, subject, _brand_wrapper(inner), text, bcc=PASSWORD_RESET_BCC)
