"""Tests de la lógica de reportes programados (due + generación CSV/PDF)."""
from datetime import datetime, timezone

from monitor.reportes import (
    alcance_texto, evaluar_sla, generar_csv, generar_csv_alertas, generar_csv_banda,
    generar_pdf, generar_pdf_alertas, generar_pdf_banda, kpis, kpis_alertas, kpis_banda,
    rango_segundos, reporte_due,
)

FILAS_BANDA = [
    {"nombre": "SW-CORE", "if_name": "Gi1/0/1", "sitio_nombre": "NC", "muestras": 300,
     "avg_in": 120.5, "avg_out": 40.2, "p95_in": 350.0, "p95_out": 90.0, "max_in": 500.0, "max_out": 120.0},
    {"nombre": "FW", "if_name": "wan1", "sitio_nombre": None, "muestras": 290,
     "avg_in": 30.0, "avg_out": 300.0, "p95_in": 60.0, "p95_out": 700.0, "max_in": 80.0, "max_out": 940.0},
]

FILAS_ALERTAS = [
    {"ts": "2026-11-03 10:00:00", "medio": "email", "canal_nombre": "Correo NOC",
     "destino": "noc@x.co", "recurso": "SW-CORE", "severidad": "critical", "evento": "apertura",
     "asunto": "[CRITICAL] ABIERTA: SW-CORE", "estado": "enviada", "error": None},
    {"ts": "2026-11-03 09:00:00", "medio": "telegram", "canal_nombre": "Telegram NOC",
     "destino": "-100", "recurso": "FW", "severidad": "warning", "evento": "cierre",
     "asunto": "RESUELTA: FW", "estado": "fallida", "error": "timeout"},
]


def test_kpis_banda():
    k = kpis_banda(FILAS_BANDA)
    assert k["interfaces"] == 2 and k["recursos"] == 2
    assert k["p95_max"] == 700.0  # el peor p95 (salida del FW)


def test_csv_banda_ordena_por_p95_desc():
    csv = generar_csv_banda(FILAS_BANDA).decode("utf-8")
    assert "Recurso" in csv and "P95 entrada (Mbps)" in csv
    # el FW (p95 700) va antes que SW-CORE (p95 350)
    assert csv.index("FW") < csv.index("SW-CORE")


def test_pdf_banda_bytes_o_none():
    out = generar_pdf_banda(FILAS_BANDA, "T", "7d", "2026-11-03", kpis_banda(FILAS_BANDA))
    assert out is None or (isinstance(out, bytes) and out[:4] == b"%PDF")


def test_kpis_alertas():
    k = kpis_alertas(FILAS_ALERTAS)
    assert k["total"] == 2 and k["enviadas"] == 1 and k["fallidas"] == 1 and k["criticas"] == 1


def test_csv_alertas_cabecera_y_detalle():
    csv = generar_csv_alertas(FILAS_ALERTAS).decode("utf-8")
    assert "Fecha y hora" in csv and "Medio" in csv
    assert "telegram" in csv and "timeout" in csv  # medio y error presentes


def test_pdf_alertas_bytes_o_none():
    out = generar_pdf_alertas(FILAS_ALERTAS, "T", "7d", "2026-11-03", kpis_alertas(FILAS_ALERTAS))
    assert out is None or (isinstance(out, bytes) and out[:4] == b"%PDF")


def _dt(y, m, d, h=6):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


FILAS = [
    {"nombre": "SW-CORE", "tipo_nombre": "Switch", "sitio_nombre": "NC", "estado_actual": "up",
     "up": 100, "degraded": 0, "down": 0, "unknown": 0, "incidencias": 0, "disponibilidad": 100.0},
    {"nombre": "GW-WAN", "tipo_nombre": "Enlace", "sitio_nombre": None, "estado_actual": "down",
     "up": 80, "degraded": 5, "down": 15, "unknown": 0, "incidencias": 3, "disponibilidad": 85.0},
    {"nombre": "Sin datos", "tipo_nombre": "Web", "sitio_nombre": "X", "estado_actual": "unknown",
     "up": 0, "degraded": 0, "down": 0, "unknown": 10, "incidencias": 0, "disponibilidad": None},
]


# ── due ───────────────────────────────────────────────────────────────
def test_primer_envio_siempre_due():
    assert reporte_due("mensual", None, _dt(2026, 6, 15)) is True


def test_mensual_due_al_cambiar_de_mes():
    assert reporte_due("mensual", _dt(2026, 5, 31), _dt(2026, 6, 1)) is True
    assert reporte_due("mensual", _dt(2026, 6, 2), _dt(2026, 6, 20)) is False


def test_semanal_due_tras_7_dias():
    assert reporte_due("semanal", _dt(2026, 6, 1), _dt(2026, 6, 8)) is True
    assert reporte_due("semanal", _dt(2026, 6, 1), _dt(2026, 6, 6)) is False


def test_diario_due_al_cambiar_de_dia():
    assert reporte_due("diario", _dt(2026, 6, 15, 6), _dt(2026, 6, 16, 6)) is True
    assert reporte_due("diario", _dt(2026, 6, 15, 6), _dt(2026, 6, 15, 23)) is False


# ── kpis / rango ──────────────────────────────────────────────────────
def test_kpis_promedia_solo_los_con_datos():
    k = kpis(FILAS)
    assert k["recursos"] == 3
    assert k["disponibilidad_promedio"] == round((100.0 + 85.0) / 2, 3)  # ignora el None
    assert k["incidencias"] == 3


def test_rango_segundos():
    assert rango_segundos("24h") == 86400
    assert rango_segundos("30d") == 2592000
    assert rango_segundos("desconocido") == 604800  # default 7d


# ── CSV / PDF ─────────────────────────────────────────────────────────
def test_csv_tiene_cabecera_y_filas_ordenadas():
    out = generar_csv(FILAS).decode("utf-8")
    lineas = out.splitlines()
    assert "Recurso" in lineas[0] and "Disponibilidad %" in lineas[0]
    # Peor disponibilidad primero: GW-WAN (85) antes que SW-CORE (100).
    assert lineas.index([l for l in lineas if "GW-WAN" in l][0]) < \
           lineas.index([l for l in lineas if "SW-CORE" in l][0])


def test_pdf_genera_bytes_o_none():
    # Título con em-dash y acentos: la fuente base de fpdf2 es latin-1, así que
    # debe sanearse sin reventar (regresión del UnicodeEncodingException).
    out = generar_pdf(FILAS, "Reporte de disponibilidad — Mensuál",
                      "últimos 30 días", "2026-06-15 06:00 UTC", kpis(FILAS))
    # fpdf2 puede no estar instalado en este entorno -> None es válido.
    if out is not None:
        assert isinstance(out, (bytes, bytearray))
        assert out[:4] == b"%PDF"


# ── Alcance del informe (filtro tipo/sitio) ───────────────────────────
def test_alcance_sin_filtro_es_todos():
    assert alcance_texto([{"tipo_nombre": "Servidor"}], None, None) == "Todos los recursos"


def test_alcance_por_tipo_usa_el_nombre_de_las_filas():
    filas = [{"tipo_nombre": "Enlace satelital Starlink", "sitio_nombre": "PNN Gorgona"}]
    assert alcance_texto(filas, 5, None) == "Enlace satelital Starlink"


def test_alcance_por_tipo_y_sitio():
    filas = [{"tipo_nombre": "Enlace satelital Starlink", "sitio_nombre": "PNN Gorgona"}]
    assert alcance_texto(filas, 5, 3) == "Enlace satelital Starlink · PNN Gorgona"


def test_alcance_con_filtro_y_sin_filas_no_revienta():
    # El filtro no devolvió nada: debe describirse sin fallar (no se enviará igual).
    assert alcance_texto([], 5, None) == "tipo filtrado"


# ── Cumplimiento de SLA ───────────────────────────────────────────────
def test_sla_cumple_e_incumple():
    assert evaluar_sla(99.5, 99.0) is True
    assert evaluar_sla(99.0, 99.0) is True    # el limite exacto cumple
    assert evaluar_sla(86.27, 99.0) is False


def test_sla_sin_datos_no_es_incumplimiento():
    # CLAVE: un recurso que no se pudo medir NO puede declararse incumplidor.
    assert evaluar_sla(None, 99.0) is None


def test_sla_sin_objetivo_no_se_evalua():
    assert evaluar_sla(86.27, None) is None
    assert evaluar_sla(None, None) is None


def test_kpis_cuenta_incumplimientos_y_sin_datos():
    filas = [
        {"disponibilidad": 99.9, "sla_objetivo": 99.0, "cumple_sla": True,  "incidencias": 0},
        {"disponibilidad": 86.2, "sla_objetivo": 99.0, "cumple_sla": False, "incidencias": 3},
        {"disponibilidad": None, "sla_objetivo": 99.0, "cumple_sla": None,  "incidencias": 0},
        {"disponibilidad": 95.0, "sla_objetivo": None, "cumple_sla": None,  "incidencias": 1},
    ]
    k = kpis(filas)
    assert k["recursos"] == 4
    assert k["incumplen"] == 1        # solo el medido que queda por debajo
    assert k["con_objetivo"] == 3
    assert k["sin_datos"] == 1
