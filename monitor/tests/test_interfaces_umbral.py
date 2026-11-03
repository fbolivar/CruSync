"""Tests de la evaluación pura de saturación/errores de interfaz."""
from monitor.interfaces_umbral import evaluar_banda

# Umbrales típicos: warning 80%, crítico 95%; errores desactivados (0).
UW, UC, EW, EC = 80.0, 95.0, 0, 0


def test_interfaz_sana_no_dispara():
    assert evaluar_banda(10.0, 20.0, 0, 0, UW, UC, EW, EC) == (None, None)


def test_warning_por_utilizacion():
    sev, motivo = evaluar_banda(85.0, 10.0, None, None, UW, UC, EW, EC)
    assert sev == "warning"
    assert "85.0%" in motivo and "80.0%" in motivo


def test_critical_por_utilizacion():
    sev, motivo = evaluar_banda(10.0, 97.0, None, None, UW, UC, EW, EC)
    assert sev == "critical"
    assert "97.0%" in motivo


def test_usa_el_peor_de_entrada_y_salida():
    # salida alta aunque entrada baja -> dispara por salida
    assert evaluar_banda(5.0, 96.0, None, None, UW, UC, EW, EC)[0] == "critical"


def test_metrica_ausente_no_dispara():
    # util desconocida (primer ciclo sin delta) y errores off -> sana
    assert evaluar_banda(None, None, None, None, UW, UC, EW, EC) == (None, None)


def test_umbral_cero_desactiva():
    # con warning y critical en 0, una interfaz al 99% no dispara por util
    assert evaluar_banda(99.0, 99.0, None, None, 0, 0, EW, EC) == (None, None)


def test_errores_disparan_cuando_estan_activos():
    sev, motivo = evaluar_banda(5.0, 5.0, 150, 0, UW, UC, 10, 100)
    assert sev == "critical"
    assert "errores 150" in motivo


def test_errores_warning():
    sev, motivo = evaluar_banda(5.0, 5.0, 20, 0, UW, UC, 10, 100)
    assert sev == "warning"
    assert "errores 20" in motivo


def test_critical_de_util_gana_sobre_warning_de_errores():
    sev, _ = evaluar_banda(99.0, 5.0, 20, 0, UW, UC, 10, 100)
    assert sev == "critical"


def test_override_por_interfaz_mas_estricto():
    # un uplink con warning 50/critical 70 dispara critical al 75% aunque el
    # global (80/95) no lo haría
    assert evaluar_banda(75.0, 5.0, None, None, 50.0, 70.0, EW, EC)[0] == "critical"
