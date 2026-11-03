"""Emisores por canal (E/S aislada). Cada uno devuelve (ok, error, destino).

Config (no sensible) y secretos (descifrados) viven en el objeto Canal:
- email:    config{smtp_host, smtp_port, from, destinatarios[]}  secretos{smtp_user, smtp_pass}
- telegram: config{chat_id}                                      secretos{bot_token}
- webhook:  config{url}                                          secretos{token}
- teams:    config{webhook_url} (o secretos{webhook_url})        — Incoming Webhook de Teams
- whatsapp: proveedor 'meta' (WhatsApp Cloud API) o 'twilio':
    * meta:   config{proveedor:'meta', phone_number_id, destinatarios[],
                     template_name?, template_lang?='es', api_version?='v22.0'}
              secretos{access_token}
    * twilio: config{proveedor:'twilio', account_sid, from:'whatsapp:+14155238886',
                     destinatarios[]}            secretos{auth_token}
  NOTA WhatsApp: fuera de la ventana de 24 h, Meta exige un MENSAJE DE PLANTILLA
  aprobado (template_name). Si no se define template_name, se envía texto plano
  (solo válido dentro de una sesión / sandbox).
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..models import Canal

log = logging.getLogger(__name__)


def _smtp_enviar(canal: Canal, remitente: str, destinatarios: list[str], mensaje) -> None:
    """E/S SMTP común (STARTTLS o SSL según puerto)."""
    cfg = canal.config or {}
    sec = canal.secretos or {}
    host = cfg.get("smtp_host")
    port = int(cfg.get("smtp_port", 587))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            if sec.get("smtp_user"):
                s.login(sec["smtp_user"], sec.get("smtp_pass", ""))
            s.sendmail(remitente, destinatarios, mensaje.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            if sec.get("smtp_user"):
                s.login(sec["smtp_user"], sec.get("smtp_pass", ""))
            s.sendmail(remitente, destinatarios, mensaje.as_string())


def enviar_email_adjunto(canal: Canal, destinatarios: list[str], asunto: str, cuerpo: str,
                         nombre_adjunto: str, datos: bytes,
                         subtype: str) -> tuple[bool, str | None, str | None]:
    """Envía un correo con un adjunto (PDF/CSV) por el canal email indicado, a
    `destinatarios` (los del reporte, no los del canal). subtype: 'pdf'|'csv'."""
    cfg = canal.config or {}
    sec = canal.secretos or {}
    remitente = cfg.get("from") or sec.get("smtp_user")
    destino = ", ".join(destinatarios)
    if not cfg.get("smtp_host") or not destinatarios or not remitente:
        return False, "config de email incompleta (smtp_host/from/destinatarios)", destino

    mime = MIMEMultipart()
    mime["Subject"] = asunto
    mime["From"] = remitente
    mime["To"] = destino
    mime.attach(MIMEText(cuerpo, "plain", "utf-8"))
    adj = MIMEApplication(datos, _subtype=subtype)
    adj.add_header("Content-Disposition", "attachment", filename=nombre_adjunto)
    mime.attach(adj)

    try:
        _smtp_enviar(canal, remitente, destinatarios, mime)
        return True, None, destino
    except Exception as e:  # noqa: BLE001
        return False, str(e), destino


def enviar(canal: Canal, msg: dict) -> tuple[bool, str | None, str | None]:
    if canal.tipo == "email":
        return _email(canal, msg)
    if canal.tipo == "telegram":
        return _telegram(canal, msg)
    if canal.tipo == "webhook":
        return _webhook(canal, msg)
    if canal.tipo == "teams":
        return _teams(canal, msg)
    if canal.tipo == "whatsapp":
        return _whatsapp(canal, msg)
    if canal.tipo == "glpi":
        return _glpi(canal, msg)
    return False, f"tipo de canal no soportado: {canal.tipo}", None


def enviar_push(suscripciones: list[dict], msg: dict, settings) -> None:
    """Envía una notificación Web Push (PWA) a cada suscripción (#11). Best-effort:
    los errores se registran pero no rompen el ciclo. Las suscripciones caducadas
    (404/410) las limpia la API cuando el navegador re-suscribe."""
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.warning("pywebpush no instalado; push deshabilitado.")
        return
    import json

    payload = json.dumps({"title": msg["asunto"], "body": msg["texto"],
                          "severidad": msg.get("severidad", "info")})
    claims = {"sub": settings.vapid_subject}
    for s in suscripciones:
        try:
            webpush(
                subscription_info={"endpoint": s["endpoint"],
                                   "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims=dict(claims),
            )
        except WebPushException as e:  # noqa: PERF203
            log.warning("Push falló (%s): %s", s.get("endpoint", "")[:40], e)
        except Exception as e:  # noqa: BLE001
            log.warning("Push error: %s", e)


def _glpi(canal: Canal, msg: dict):
    """Mesa de ayuda GLPI vía REST: crea un ticket por la incidencia. (Dejar lista:
    funciona en cuanto se configure un canal tipo 'glpi' con url + app_token + user_token.)
    config: {url}; secretos: {app_token, user_token, [urgencia]}."""
    import httpx

    cfg = canal.config or {}
    sec = canal.secretos or {}
    url = (cfg.get("url") or "").rstrip("/")
    app_token = sec.get("app_token")
    user_token = sec.get("user_token")
    if not url or not app_token or not user_token:
        return False, "config de GLPI incompleta (url/app_token/user_token)", None

    base = f"{url}/apirest.php"
    try:
        with httpx.Client(timeout=20, verify=cfg.get("verify_tls", True)) as cli:
            ini = cli.get(f"{base}/initSession",
                          headers={"Authorization": f"user_token {user_token}",
                                   "App-Token": app_token})
            ini.raise_for_status()
            session = ini.json().get("session_token")
            h = {"Session-Token": session, "App-Token": app_token}
            payload = {"input": {"name": msg["asunto"], "content": msg["texto"],
                                 "urgency": int(cfg.get("urgencia", 4))}}
            cr = cli.post(f"{base}/Ticket", headers=h, json=payload)
            cr.raise_for_status()
            ticket = cr.json().get("id")
            cli.get(f"{base}/killSession", headers=h)
            return True, None, f"GLPI#{ticket}"
    except Exception as e:  # noqa: BLE001
        return False, str(e), None


def _email(canal: Canal, msg: dict):
    cfg = canal.config or {}
    sec = canal.secretos or {}
    host = cfg.get("smtp_host")
    port = int(cfg.get("smtp_port", 587))
    remitente = cfg.get("from") or sec.get("smtp_user")
    destinatarios = cfg.get("destinatarios") or []
    if not host or not destinatarios or not remitente:
        return False, "config de email incompleta (smtp_host/from/destinatarios)", None

    mime = MIMEText(msg["texto"], "plain", "utf-8")
    mime["Subject"] = msg["asunto"]
    mime["From"] = remitente
    mime["To"] = ", ".join(destinatarios)
    destino = ", ".join(destinatarios)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                if sec.get("smtp_user"):
                    s.login(sec["smtp_user"], sec.get("smtp_pass", ""))
                s.sendmail(remitente, destinatarios, mime.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                if sec.get("smtp_user"):
                    s.login(sec["smtp_user"], sec.get("smtp_pass", ""))
                s.sendmail(remitente, destinatarios, mime.as_string())
        return True, None, destino
    except Exception as e:  # noqa: BLE001
        return False, str(e), destino


def _telegram(canal: Canal, msg: dict):
    import httpx

    cfg = canal.config or {}
    sec = canal.secretos or {}
    token = sec.get("bot_token")
    chat = cfg.get("chat_id")
    if not token or not chat:
        return False, "config de telegram incompleta (bot_token/chat_id)", None

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    texto = f"{msg['asunto']}\n{msg['texto']}"
    try:
        r = httpx.post(url, json={"chat_id": chat, "text": texto}, timeout=15)
        r.raise_for_status()
        return True, None, str(chat)
    except Exception as e:  # noqa: BLE001
        return False, str(e), str(chat)


def payload_whatsapp_meta(to: str, texto: str, template_name: str | None,
                          lang: str = "es") -> dict:
    """Arma el cuerpo JSON para WhatsApp Cloud API (función pura, testeable). Con
    `template_name` usa un mensaje de plantilla (obligatorio fuera de la ventana de
    24 h) con el texto como parámetro {{1}} del body; sin él, texto plano."""
    if template_name:
        return {
            "messaging_product": "whatsapp", "to": str(to), "type": "template",
            "template": {"name": template_name, "language": {"code": lang},
                         "components": [{"type": "body",
                                         "parameters": [{"type": "text", "text": texto}]}]},
        }
    return {"messaging_product": "whatsapp", "to": str(to),
            "type": "text", "text": {"body": texto}}


def _whatsapp(canal: Canal, msg: dict):
    """WhatsApp por Meta Cloud API (por defecto) o Twilio. Envía a cada número de
    `config.destinatarios` (E.164, p.ej. '573001234567'). Devuelve ok si TODOS los
    envíos salieron bien; si alguno falla, (False, errores, destino)."""
    import httpx

    cfg = canal.config or {}
    sec = canal.secretos or {}
    destinatarios = cfg.get("destinatarios") or []
    if not destinatarios:
        return False, "config de whatsapp incompleta (destinatarios)", None
    texto = f"{msg['asunto']}\n{msg['texto']}"
    proveedor = (cfg.get("proveedor") or "meta").lower()
    destino = ", ".join(str(d) for d in destinatarios)
    errores: list[str] = []

    if proveedor == "twilio":
        sid = cfg.get("account_sid")
        token = sec.get("auth_token")
        remitente = cfg.get("from")  # 'whatsapp:+14155238886'
        if not sid or not token or not remitente:
            return False, "config de whatsapp/twilio incompleta (account_sid/from/auth_token)", destino
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        for to in destinatarios:
            num = str(to) if str(to).startswith("whatsapp:") else f"whatsapp:{to}"
            try:
                r = httpx.post(url, data={"From": remitente, "To": num, "Body": texto},
                               auth=(sid, token), timeout=20)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001, PERF203
                errores.append(f"{to}: {e}")
    else:  # meta WhatsApp Cloud API
        phone_id = cfg.get("phone_number_id")
        token = sec.get("access_token")
        if not phone_id or not token:
            return False, "config de whatsapp/meta incompleta (phone_number_id/access_token)", destino
        ver = cfg.get("api_version", "v22.0")
        plantilla = cfg.get("template_name")
        lang = cfg.get("template_lang", "es")
        url = f"https://graph.facebook.com/{ver}/{phone_id}/messages"
        headers = {"Authorization": f"Bearer {token}"}
        for to in destinatarios:
            cuerpo = payload_whatsapp_meta(to, texto, plantilla, lang)
            try:
                r = httpx.post(url, json=cuerpo, headers=headers, timeout=20)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001, PERF203
                errores.append(f"{to}: {e}")

    if errores:
        return False, "; ".join(errores), destino
    return True, None, destino


def _teams(canal: Canal, msg: dict):
    """Microsoft Teams vía Incoming Webhook (MessageCard). PROVISTO: listo para usar
    cuando se configure el webhook_url del canal; no requiere cambios de código."""
    import httpx

    cfg = canal.config or {}
    sec = canal.secretos or {}
    url = sec.get("webhook_url") or cfg.get("webhook_url")
    if not url:
        return False, "config de teams incompleta (webhook_url)", None

    color = {"info": "2E7D3A", "warning": "E0A400", "critical": "D11D1D"}.get(
        msg.get("severidad", "info"), "2E7D3A")
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": msg["asunto"],
        "title": msg["asunto"],
        "text": msg["texto"].replace("\n", "  \n"),  # saltos de línea en Teams
    }
    try:
        r = httpx.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return True, None, url
    except Exception as e:  # noqa: BLE001
        return False, str(e), url


def _webhook(canal: Canal, msg: dict):
    import httpx

    cfg = canal.config or {}
    sec = canal.secretos or {}
    url = cfg.get("url")
    if not url:
        return False, "config de webhook incompleta (url)", None

    headers = {}
    if sec.get("token"):
        headers["Authorization"] = f"Bearer {sec['token']}"
    try:
        r = httpx.post(url, json=msg, headers=headers, timeout=15)
        r.raise_for_status()
        return True, None, url
    except Exception as e:  # noqa: BLE001
        return False, str(e), url
