-- =====================================================================
-- 0043_reporte_tipo.up.sql
-- Tipo de informe programado. Hasta ahora `reportes_programados` solo generaba
-- disponibilidad/SLA; se amplía a 4 tipos para la operación 24x7:
--   disponibilidad · sla · banda (consumo de ancho de banda) · alertas (enviadas).
-- Las filas existentes quedan como 'disponibilidad' (comportamiento previo).
-- =====================================================================
BEGIN;

ALTER TABLE reportes_programados
  ADD COLUMN IF NOT EXISTS tipo text NOT NULL DEFAULT 'disponibilidad'
    CHECK (tipo IN ('disponibilidad','sla','banda','alertas'));

COMMENT ON COLUMN reportes_programados.tipo IS
  'Tipo de informe: disponibilidad | sla | banda | alertas.';

COMMIT;
