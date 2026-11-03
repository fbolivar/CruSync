"""Ruta de red por salto (traceroute) — localiza dónde se degrada el camino.

Equivalente al hop-by-hop de SolarWinds / la herramienta de ruta de PRTG: para un
destino, lista los saltos (routers) con su RTT, de modo que una latencia/pérdida
alta se pueda atribuir a un tramo concreto (p.ej. el salto del ISP tras Starlink).

El parseo de la salida es PURO y testeable; la E/S (ejecutar traceroute/tracepath)
está aislada en `trazar`. Se usa `traceroute -n` si está disponible y, si no,
`tracepath -n` (iputils, casi siempre presente en Linux).
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess

log = logging.getLogger(__name__)

_IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_RTT = re.compile(r"(\d+(?:\.\d+)?)\s*ms")


def parse_traceroute(salida: str) -> list[dict]:
    """Parsea la salida de `traceroute -n` en saltos.

    Cada línea útil empieza por el nº de salto. Un salto sin respuesta ('* * *')
    queda con ip=None, rtt_ms=None, perdida=True. Se toma el PRIMER RTT de la línea.
    """
    saltos: list[dict] = []
    for linea in salida.splitlines():
        s = linea.strip()
        m = re.match(r"^(\d+)\s+(.*)$", s)
        if not m:
            continue
        hop_no = int(m.group(1))
        resto = m.group(2)
        ip_m = _IP.search(resto)
        rtt_m = _RTT.search(resto)
        ip = ip_m.group(1) if ip_m else None
        rtt = float(rtt_m.group(1)) if rtt_m else None
        saltos.append({
            "hop_no": hop_no,
            "ip": ip,
            "hostname": None,
            "rtt_ms": round(rtt, 2) if rtt is not None else None,
            "perdida": ip is None and rtt is None,
        })
    return saltos


def parse_tracepath(salida: str) -> list[dict]:
    """Parsea `tracepath -n`. Formato: ' 1:  192.168.1.1   0.123ms'.

    tracepath repite saltos y añade líneas de 'pmtu'/'asymm'; nos quedamos con la
    primera medición por nº de salto y descartamos 'no reply' como pérdida.
    """
    por_hop: dict[int, dict] = {}
    for linea in salida.splitlines():
        s = linea.strip()
        m = re.match(r"^(\d+):\s+(.*)$", s)
        if not m:
            continue
        hop_no = int(m.group(1))
        resto = m.group(2)
        if hop_no in por_hop:
            continue  # primera medición del salto
        if "no reply" in resto.lower():
            por_hop[hop_no] = {"hop_no": hop_no, "ip": None, "hostname": None,
                               "rtt_ms": None, "perdida": True}
            continue
        ip_m = _IP.search(resto)
        rtt_m = _RTT.search(resto)
        por_hop[hop_no] = {
            "hop_no": hop_no,
            "ip": ip_m.group(1) if ip_m else None,
            "hostname": None,
            "rtt_ms": round(float(rtt_m.group(1)), 2) if rtt_m else None,
            "perdida": ip_m is None,
        }
    return [por_hop[k] for k in sorted(por_hop)]


def trazar(host: str, max_hops: int = 30, timeout_seg: int = 2) -> list[dict]:
    """Ejecuta traceroute/tracepath hacia `host` y devuelve los saltos. Lanza
    RuntimeError si no hay ninguna herramienta disponible."""
    tr = shutil.which("traceroute")
    if tr:
        # -n sin DNS, -q 1 una sonda por salto (rápido), -w espera, -m máx saltos.
        cmd = [tr, "-n", "-q", "1", "-w", str(timeout_seg), "-m", str(max_hops), host]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=max_hops * timeout_seg + 15)
        return parse_traceroute(out.stdout)

    tp = shutil.which("tracepath")
    if tp:
        cmd = [tp, "-n", "-m", str(max_hops), host]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=max_hops * timeout_seg + 20)
        return parse_tracepath(out.stdout)

    raise RuntimeError("ni traceroute ni tracepath están instalados")
