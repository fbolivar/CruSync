-- =====================================================================
-- 0043_reporte_tipo.down.sql
-- =====================================================================
BEGIN;

ALTER TABLE reportes_programados DROP COLUMN IF EXISTS tipo;

COMMIT;
