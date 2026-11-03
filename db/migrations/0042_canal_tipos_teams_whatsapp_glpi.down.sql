-- =====================================================================
-- 0042_canal_tipos_teams_whatsapp_glpi.down.sql
-- Revierte al conjunto de tipos original (0001). OJO: si hay canales de tipo
-- teams/whatsapp/glpi, hay que borrarlos antes o el ADD CONSTRAINT fallará.
-- =====================================================================
BEGIN;

ALTER TABLE canales_notificacion
  DROP CONSTRAINT IF EXISTS canales_notificacion_tipo_check;

ALTER TABLE canales_notificacion
  ADD CONSTRAINT canales_notificacion_tipo_check
  CHECK (tipo IN ('email','sms','webhook','slack','telegram'));

COMMIT;
