-- =====================================================================
-- 0044_recurso_geo.down.sql
-- =====================================================================
BEGIN;

ALTER TABLE recursos
  DROP COLUMN IF EXISTS latitud,
  DROP COLUMN IF EXISTS longitud;

COMMIT;
