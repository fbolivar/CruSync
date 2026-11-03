"""Evaluación de saturación / errores de una interfaz de red (función pura).

Sensor de ancho de banda al estilo PRTG/SolarWinds: sobre una interfaz
monitoreada se compara la utilización (% de la velocidad del enlace, el mayor
entre entrada y salida) y los errores del intervalo contra umbrales. Devuelve la
severidad (critical/warning) y el motivo, o (None, None) si la interfaz está sana.

Trivaluada: una métrica ausente (None) NO dispara — igual que los umbrales de
recurso, para no inventar alarmas cuando aún no hay dato (p.ej. primer ciclo tras
reiniciar el worker, cuando todavía no hay delta de contadores).

Un umbral en 0 significa "desactivado" (no se evalúa esa condición).
"""
from __future__ import annotations


def _peor(a: float | None, b: float | None) -> float | None:
    vals = [v for v in (a, b) if v is not None]
    return max(vals) if vals else None


def evaluar_banda(
    util_in: float | None,
    util_out: float | None,
    in_err: float | None,
    out_err: float | None,
    util_warning: float,
    util_critical: float,
    err_warning: float,
    err_critical: float,
) -> tuple[str | None, str | None]:
    """(severidad, motivo) si la interfaz excede algún umbral; (None, None) si sana.

    `severidad` es 'critical' o 'warning' (critical gana). Los umbrales de util van
    en %; los de error en nº de errores por intervalo. Cualquier umbral <= 0 se
    ignora (desactivado).
    """
    severidad: str | None = None
    motivos: list[str] = []

    util = _peor(util_in, util_out)
    if util is not None:
        if util_critical > 0 and util >= util_critical:
            severidad = "critical"
            motivos.append(f"utilización {util}% ≥ {util_critical}%")
        elif util_warning > 0 and util >= util_warning:
            severidad = "warning"
            motivos.append(f"utilización {util}% ≥ {util_warning}%")

    err = _peor(in_err, out_err)
    if err is not None:
        if err_critical > 0 and err >= err_critical:
            if severidad != "critical":
                motivos.insert(0, f"errores {int(err)} ≥ {int(err_critical)}")
            else:
                motivos.append(f"errores {int(err)} ≥ {int(err_critical)}")
            severidad = "critical"
        elif err_warning > 0 and err >= err_warning:
            motivos.append(f"errores {int(err)} ≥ {int(err_warning)}")
            if severidad is None:
                severidad = "warning"

    if severidad is None:
        return None, None
    return severidad, "; ".join(motivos)
