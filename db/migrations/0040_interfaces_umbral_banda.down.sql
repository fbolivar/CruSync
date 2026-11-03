-- =====================================================================
-- 0040_interfaces_umbral_banda.down.sql
-- =====================================================================
BEGIN;

ALTER TABLE interfaces
  DROP COLUMN IF EXISTS umbral_util_warning,
  DROP COLUMN IF EXISTS umbral_util_critical;

COMMIT;
