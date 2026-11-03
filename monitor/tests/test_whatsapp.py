"""Tests del sender de WhatsApp (payload puro + guardas de config, sin red)."""
from monitor.models import Canal
from monitor.notificaciones.senders import enviar, payload_whatsapp_meta

MSG = {"asunto": "[CRITICAL] Incidencia ABIERTA: SW-CORE", "texto": "Puerto down",
       "severidad": "critical", "evento": "apertura"}


def test_payload_meta_texto_plano():
    p = payload_whatsapp_meta("573001234567", "hola", None)
    assert p["type"] == "text"
    assert p["to"] == "573001234567"
    assert p["text"]["body"] == "hola"


def test_payload_meta_plantilla():
    p = payload_whatsapp_meta("573001234567", "hola", "alerta_simon", "es")
    assert p["type"] == "template"
    assert p["template"]["name"] == "alerta_simon"
    assert p["template"]["language"]["code"] == "es"
    # el texto va como parámetro {{1}} del body
    param = p["template"]["components"][0]["parameters"][0]
    assert param["type"] == "text" and param["text"] == "hola"


def _canal(tipo, config, secretos=None):
    c = Canal.__new__(Canal)
    c.tipo = tipo
    c.config = config
    c.secretos = secretos or {}
    return c


def test_whatsapp_sin_destinatarios_falla_sin_red():
    ok, err, _ = enviar(_canal("whatsapp", {"proveedor": "meta", "phone_number_id": "1"},
                               {"access_token": "x"}), MSG)
    assert ok is False and "destinatarios" in err


def test_whatsapp_meta_incompleto_falla_sin_red():
    ok, err, _ = enviar(_canal("whatsapp", {"proveedor": "meta", "destinatarios": ["573001234567"]},
                               {}), MSG)
    assert ok is False and "meta" in err


def test_whatsapp_twilio_incompleto_falla_sin_red():
    ok, err, _ = enviar(_canal("whatsapp", {"proveedor": "twilio", "destinatarios": ["573001234567"]},
                               {}), MSG)
    assert ok is False and "twilio" in err
