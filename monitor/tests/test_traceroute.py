"""Tests del parseo puro de traceroute / tracepath."""
from monitor.traceroute import parse_traceroute, parse_tracepath

SALIDA_TRACEROUTE = """\
traceroute to 1.1.1.1 (1.1.1.1), 30 hops max, 60 byte packets
 1  192.168.50.1  0.431 ms
 2  10.0.0.1  3.210 ms
 3  *
 4  200.14.25.1  12.004 ms
 5  1.1.1.1  11.550 ms
"""

SALIDA_TRACEPATH = """\
 1:  192.168.50.1                                          0.521ms
 1:  192.168.50.1                                          0.402ms
 2:  no reply
 3:  200.14.25.1                                          12.300ms asymm  4
 4:  1.1.1.1                                              11.900ms reached
"""


def test_parse_traceroute_saltos():
    saltos = parse_traceroute(SALIDA_TRACEROUTE)
    assert len(saltos) == 5
    assert saltos[0] == {"hop_no": 1, "ip": "192.168.50.1", "hostname": None,
                         "rtt_ms": 0.43, "perdida": False}
    assert saltos[4]["ip"] == "1.1.1.1" and saltos[4]["rtt_ms"] == 11.55


def test_parse_traceroute_salto_sin_respuesta():
    saltos = parse_traceroute(SALIDA_TRACEROUTE)
    perdido = saltos[2]
    assert perdido["hop_no"] == 3
    assert perdido["ip"] is None and perdido["rtt_ms"] is None and perdido["perdida"] is True


def test_parse_traceroute_ignora_cabecera():
    # La línea "traceroute to ..." no debe producir un salto.
    assert all(s["hop_no"] >= 1 for s in parse_traceroute(SALIDA_TRACEROUTE))


def test_parse_tracepath_dedup_y_perdida():
    saltos = parse_tracepath(SALIDA_TRACEPATH)
    assert [s["hop_no"] for s in saltos] == [1, 2, 3, 4]
    assert saltos[0]["ip"] == "192.168.50.1" and saltos[0]["rtt_ms"] == 0.52  # 1ª medición
    assert saltos[1]["perdida"] is True and saltos[1]["ip"] is None           # no reply
    assert saltos[3]["ip"] == "1.1.1.1" and saltos[3]["rtt_ms"] == 11.9


def test_parse_vacio():
    assert parse_traceroute("") == []
    assert parse_tracepath("") == []
