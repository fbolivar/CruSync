"""Generación de reportes de disponibilidad/SLA (lógica pura, sin BD ni red).

- `reporte_due`: ¿toca enviar según la periodicidad y el último envío?
- `generar_csv` / `generar_pdf`: arman el archivo a adjuntar.
- `kpis`: resumen agregado para el cuerpo del correo y el encabezado.

El PDF usa fpdf2 (puro Python). Si no está instalado, `generar_pdf` devuelve
None y el runner cae a CSV.
"""
from __future__ import annotations

from datetime import datetime

RANGO_SEGUNDOS = {"24h": 86400, "7d": 604800, "30d": 2592000}
RANGO_ETIQUETA = {"24h": "últimas 24 horas", "7d": "últimos 7 días", "30d": "últimos 30 días"}


def rango_segundos(rango: str) -> int:
    return RANGO_SEGUNDOS.get(rango, 604800)


def reporte_due(periodo: str, ultimo_envio: datetime | None, ahora: datetime) -> bool:
    """¿Debe enviarse ahora? (primer envío si nunca se mandó; si no, según el periodo)."""
    if ultimo_envio is None:
        return True
    if periodo == "diario":
        return ahora.date() > ultimo_envio.date()
    if periodo == "semanal":
        return (ahora - ultimo_envio).days >= 7
    # mensual: cambió el (año, mes)
    return (ahora.year, ahora.month) != (ultimo_envio.year, ultimo_envio.month)


def evaluar_sla(disponibilidad: float | None, objetivo: float | None) -> bool | None:
    """¿La disponibilidad cumple el objetivo? (función pura)

    Devuelve None —ni cumple ni incumple— si falta el objetivo o NO HAY DATOS.
    Esto último es deliberado: **"sin datos" no es "incumple"**. Un enlace que no
    se puede medir no puede declararse incumplidor; marcarlo sería acusar en falso
    (ya pasó: el 0% de los enlaces MPLS era un artefacto de medición, no una caída).
    """
    if disponibilidad is None or objetivo is None:
        return None
    return disponibilidad >= objetivo


def alcance_texto(filas: list[dict], tipo_id: int | None, sitio_id: int | None) -> str:
    """Describe el ALCANCE del informe para su encabezado (función pura).

    Un informe acotado (p. ej. el que se manda al proveedor con solo sus enlaces)
    debe decir qué cubre, si no el destinatario asume que son todos los recursos.
    Sin filtros -> 'Todos los recursos'. Con filtro, el nombre sale de las propias
    filas (todas comparten tipo/sitio porque la query ya vino filtrada).
    """
    if not tipo_id and not sitio_id:
        return "Todos los recursos"
    primera = filas[0] if filas else {}
    partes: list[str] = []
    if tipo_id:
        partes.append(str(primera.get("tipo_nombre") or "tipo filtrado"))
    if sitio_id:
        partes.append(str(primera.get("sitio_nombre") or "sitio filtrado"))
    return " · ".join(partes)


def kpis(filas: list[dict]) -> dict:
    """Resumen: nº de recursos, disponibilidad promedio, incidencias y SLA.

    `incumplen` cuenta solo los que TIENEN objetivo y datos y quedan por debajo;
    `sin_datos` se reporta aparte para no disfrazar de incumplimiento lo que
    simplemente no se pudo medir.
    """
    disp = [f["disponibilidad"] for f in filas if f.get("disponibilidad") is not None]
    promedio = round(sum(disp) / len(disp), 3) if disp else None
    incidencias = sum(int(f.get("incidencias") or 0) for f in filas)
    incumplen = sum(1 for f in filas if f.get("cumple_sla") is False)
    con_objetivo = sum(1 for f in filas if f.get("sla_objetivo") is not None)
    sin_datos = sum(1 for f in filas if f.get("disponibilidad") is None)
    return {
        "recursos": len(filas), "disponibilidad_promedio": promedio,
        "incidencias": incidencias, "incumplen": incumplen,
        "con_objetivo": con_objetivo, "sin_datos": sin_datos,
    }


def _orden(filas: list[dict]) -> list[dict]:
    # Peor disponibilidad primero (los problemáticos arriba).
    return sorted(filas, key=lambda f: (f["disponibilidad"] if f.get("disponibilidad") is not None else 101.0))


def _fmt_disp(v) -> str:
    return f"{v:.3f}%" if v is not None else "sin datos"


# Las fuentes base de fpdf2 (Helvetica) solo cubren latin-1. Los acentos españoles
# (á,é,í,ó,ú,ñ) sí entran; el em-dash y las comillas tipográficas no -> se mapean.
_REEMPLAZOS = {"—": "-", "–": "-", "…": "...", "‘": "'",
               "’": "'", "“": '"', "”": '"', "•": "*", " ": " "}


def _latin1(texto: str) -> str:
    """Hace el texto seguro para las fuentes base de fpdf2 (latin-1)."""
    for k, v in _REEMPLAZOS.items():
        texto = texto.replace(k, v)
    return texto.encode("latin-1", "replace").decode("latin-1")


def generar_csv(filas: list[dict]) -> bytes:
    """CSV (UTF-8 con BOM) con la tabla de disponibilidad. Mismo orden que la UI."""
    cab = ["Recurso", "Tipo", "Sitio", "Estado", "Disponibilidad %",
           "Objetivo SLA %", "Cumple SLA",
           "Up", "Degradado", "Caido", "Desconocido", "Incidencias"]
    lineas = [cab]
    for f in _orden(filas):
        cumple = f.get("cumple_sla")
        lineas.append([
            f.get("nombre", ""), f.get("tipo_nombre", ""), f.get("sitio_nombre") or "",
            f.get("estado_actual", ""),
            "" if f.get("disponibilidad") is None else f"{f['disponibilidad']:.3f}",
            "" if f.get("sla_objetivo") is None else f"{f['sla_objetivo']:.2f}",
            # Sin objetivo o sin datos -> vacío, NO "NO" (no se acusa sin medir).
            "" if cumple is None else ("SI" if cumple else "NO"),
            f.get("up", 0), f.get("degraded", 0), f.get("down", 0),
            f.get("unknown", 0), f.get("incidencias", 0),
        ])
    cuerpo = "\r\n".join(
        ",".join(f'"{str(c).replace(chr(34), chr(34) * 2)}"' for c in fila) for fila in lineas
    )
    return ("﻿" + cuerpo).encode("utf-8")


def _num(v, dec: int = 2) -> str:
    return f"{v:.{dec}f}" if isinstance(v, (int, float)) else ""


# ── Informe de CONSUMO DE ANCHO DE BANDA ──────────────────────────────
def kpis_banda(filas: list[dict]) -> dict:
    """Resumen del informe de banda: nº de interfaces y el p95 máximo observado."""
    p95s = [max(f.get("p95_in") or 0, f.get("p95_out") or 0) for f in filas]
    return {
        "interfaces": len(filas),
        "p95_max": round(max(p95s), 2) if p95s else None,
        "recursos": len({f.get("nombre") for f in filas}),
    }


def _orden_banda(filas: list[dict]) -> list[dict]:
    # Mayor consumo (p95) primero: los enlaces más cargados arriba.
    return sorted(filas, key=lambda f: -max(f.get("p95_in") or 0, f.get("p95_out") or 0))


def generar_csv_banda(filas: list[dict]) -> bytes:
    cab = ["Recurso", "Interfaz", "Sitio", "Prom. entrada (Mbps)", "Prom. salida (Mbps)",
           "P95 entrada (Mbps)", "P95 salida (Mbps)", "Max entrada (Mbps)",
           "Max salida (Mbps)", "Muestras"]
    lineas = [cab]
    for f in _orden_banda(filas):
        lineas.append([
            f.get("nombre", ""), f.get("if_name", ""), f.get("sitio_nombre") or "",
            _num(f.get("avg_in")), _num(f.get("avg_out")),
            _num(f.get("p95_in")), _num(f.get("p95_out")),
            _num(f.get("max_in")), _num(f.get("max_out")), f.get("muestras", 0),
        ])
    cuerpo = "\r\n".join(
        ",".join(f'"{str(c).replace(chr(34), chr(34) * 2)}"' for c in fila) for fila in lineas)
    return ("﻿" + cuerpo).encode("utf-8")


def generar_pdf_banda(filas: list[dict], titulo: str, periodo_txt: str,
                      generado: str, resumen: dict) -> bytes | None:
    try:
        from fpdf import FPDF
    except ImportError:
        return None
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _latin1(titulo), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _latin1(f"Periodo: {periodo_txt}  -  Generado: {generado}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _latin1(f"Interfaces: {resumen['interfaces']}  -  "
                           f"Consumo p95 maximo: {_num(resumen.get('p95_max'))} Mbps"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    cols = [("Recurso", 58), ("Interfaz", 34), ("Sitio", 38), ("Prom. ent.", 26),
            ("Prom. sal.", 26), ("P95 ent.", 24), ("P95 sal.", 24), ("Max ent.", 24),
            ("Max sal.", 24)]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(232, 240, 233)
    pdf.set_text_color(20, 20, 20)
    for nombre, w in cols:
        pdf.cell(w, 7, _latin1(nombre), border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    for f in _orden_banda(filas):
        valores = [
            (str(f.get("nombre", ""))[:34], "L"), (str(f.get("if_name", ""))[:20], "L"),
            (str(f.get("sitio_nombre") or "-")[:22], "L"),
            (_num(f.get("avg_in")), "R"), (_num(f.get("avg_out")), "R"),
            (_num(f.get("p95_in")), "R"), (_num(f.get("p95_out")), "R"),
            (_num(f.get("max_in")), "R"), (_num(f.get("max_out")), "R"),
        ]
        for (texto, align), (_n, w) in zip(valores, cols):
            pdf.cell(w, 6, _latin1(texto), border=1, align=align)
        pdf.ln()
    return bytes(pdf.output())


# ── Informe de ALERTAS ENVIADAS ───────────────────────────────────────
def kpis_alertas(filas: list[dict]) -> dict:
    enviadas = sum(1 for f in filas if f.get("estado") == "enviada")
    fallidas = sum(1 for f in filas if f.get("estado") == "fallida")
    criticas = sum(1 for f in filas if f.get("severidad") == "critical")
    return {"total": len(filas), "enviadas": enviadas, "fallidas": fallidas,
            "criticas": criticas}


def generar_csv_alertas(filas: list[dict]) -> bytes:
    cab = ["Fecha y hora", "Medio", "Canal", "Destino", "Recurso",
           "Severidad", "Evento", "Alerta", "Estado", "Error"]
    lineas = [cab]
    for f in filas:  # ya vienen ordenadas por fecha desc de la query
        lineas.append([
            f.get("ts", ""), f.get("medio", ""), f.get("canal_nombre", ""),
            f.get("destino") or "", f.get("recurso") or "", f.get("severidad") or "",
            f.get("evento") or "", f.get("asunto") or "", f.get("estado") or "",
            f.get("error") or "",
        ])
    cuerpo = "\r\n".join(
        ",".join(f'"{str(c).replace(chr(34), chr(34) * 2)}"' for c in fila) for fila in lineas)
    return ("﻿" + cuerpo).encode("utf-8")


def generar_pdf_alertas(filas: list[dict], titulo: str, periodo_txt: str,
                        generado: str, resumen: dict) -> bytes | None:
    try:
        from fpdf import FPDF
    except ImportError:
        return None
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _latin1(titulo), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _latin1(f"Periodo: {periodo_txt}  -  Generado: {generado}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _latin1(f"Alertas: {resumen['total']}  -  Enviadas: {resumen['enviadas']}  -  "
                           f"Fallidas: {resumen['fallidas']}  -  Criticas: {resumen['criticas']}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    cols = [("Fecha y hora", 34), ("Medio", 22), ("Recurso", 52), ("Sev.", 18),
            ("Evento", 24), ("Alerta", 86), ("Estado", 20)]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(232, 240, 233)
    pdf.set_text_color(20, 20, 20)
    for nombre, w in cols:
        pdf.cell(w, 7, _latin1(nombre), border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_font("Helvetica", "", 7)
    for f in filas:
        fallida = f.get("estado") == "fallida"
        pdf.set_fill_color(253, 235, 235)
        valores = [
            (str(f.get("ts", ""))[:19], "L"), (str(f.get("medio", "")), "L"),
            (str(f.get("recurso") or "-")[:30], "L"), (str(f.get("severidad") or "-"), "C"),
            (str(f.get("evento") or "-")[:14], "L"), (str(f.get("asunto") or "-")[:54], "L"),
            (str(f.get("estado") or "-"), "C"),
        ]
        for (texto, align), (_n, w) in zip(valores, cols):
            pdf.cell(w, 6, _latin1(texto), border=1, align=align, fill=fallida)
        pdf.ln()
    return bytes(pdf.output())


def generar_pdf(filas: list[dict], titulo: str, periodo_txt: str,
                generado: str, resumen: dict) -> bytes | None:
    """PDF tabular con fpdf2. Devuelve None si fpdf2 no está disponible."""
    try:
        from fpdf import FPDF
    except ImportError:
        return None

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _latin1(titulo), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _latin1(f"Periodo: {periodo_txt}  -  Generado: {generado}"),
             new_x="LMARGIN", new_y="NEXT")
    prom = resumen.get("disponibilidad_promedio")
    pdf.cell(0, 5, _latin1(f"Recursos: {resumen['recursos']}  -  "
                           f"Disponibilidad promedio: {_fmt_disp(prom)}  -  "
                           f"Incidencias en el periodo: {resumen['incidencias']}"),
             new_x="LMARGIN", new_y="NEXT")
    # Línea de cumplimiento: el dato que convierte el informe en exigible. Se
    # declara también cuántos no se pudieron medir, para no inflar el reclamo.
    if resumen.get("con_objetivo"):
        incumplen = resumen.get("incumplen", 0)
        pdf.set_text_color(200, 30, 30) if incumplen else pdf.set_text_color(20, 120, 50)
        texto = (f"INCUMPLEN el objetivo de SLA: {incumplen} de {resumen['con_objetivo']} "
                 f"con objetivo definido")
        if resumen.get("sin_datos"):
            texto += f"  -  Sin datos (no evaluables): {resumen['sin_datos']}"
        pdf.cell(0, 5, _latin1(texto), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(90, 90, 90)
    pdf.ln(3)

    cols = [("Recurso", 62), ("Tipo", 34), ("Sitio", 40), ("Estado", 24),
            ("Disponib.", 24), ("Objetivo", 22), ("Cumple", 18),
            ("Up", 14), ("Degr.", 14), ("Caido", 14), ("Incid.", 14)]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(232, 240, 233)
    pdf.set_text_color(20, 20, 20)
    for nombre, w in cols:
        pdf.cell(w, 7, _latin1(nombre), border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for f in _orden(filas):
        d = f.get("disponibilidad")
        cumple = f.get("cumple_sla")
        obj = f.get("sla_objetivo")
        # Resaltar la fila que INCUMPLE: es lo que se va a reclamar.
        if cumple is False:
            pdf.set_fill_color(253, 235, 235)
            relleno = True
        else:
            relleno = False
        valores = [
            (str(f.get("nombre", ""))[:36], "L"),
            (str(f.get("tipo_nombre", ""))[:20], "L"),
            (str(f.get("sitio_nombre") or "-")[:24], "L"),
            (str(f.get("estado_actual", "")), "C"),
            (_fmt_disp(d), "R"),
            ("-" if obj is None else f"{obj:.2f}%", "R"),
            # Sin objetivo o sin datos -> "-", nunca "NO": no se acusa sin medir.
            ("-" if cumple is None else ("SI" if cumple else "NO"), "C"),
            (str(f.get("up", 0)), "R"),
            (str(f.get("degraded", 0)), "R"),
            (str(f.get("down", 0)), "R"),
            (str(f.get("incidencias", 0)), "R"),
        ]
        for i, ((texto, align), (_n, w)) in enumerate(zip(valores, cols)):
            # Columna 'Cumple': verde/rojo; el resto en negro.
            if i == 6 and cumple is not None:
                pdf.set_text_color(*((200, 30, 30) if cumple is False else (20, 120, 50)))
            else:
                pdf.set_text_color(20, 20, 20)
            pdf.cell(w, 6, _latin1(texto), border=1, align=align, fill=relleno)
        pdf.ln()
    pdf.set_text_color(20, 20, 20)

    salida = pdf.output()  # fpdf2 devuelve bytearray
    return bytes(salida)
