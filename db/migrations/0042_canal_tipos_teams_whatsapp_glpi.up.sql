-- =====================================================================
-- 0042_canal_tipos_teams_whatsapp_glpi.up.sql
-- Amplía los tipos de canal de notificación permitidos.
--
-- El CHECK original (0001) solo admitía email/sms/webhook/slack/telegram, por lo
-- que los senders de 'teams' y 'glpi' (ya implementados) y el nuevo 'whatsapp'
-- NO se podían dar de alta en BD (el INSERT fallaba). Se amplía el CHECK para
-- cubrir los tres medios de la operación 24x7: correo, Telegram y WhatsApp
-- (más teams/glpi que ya existían en código).
-- =====================================================================
BEGIN;

ALTER TABLE canales_notificacion
  DROP CONSTRAINT IF EXISTS canales_notificacion_tipo_check;

ALTER TABLE canales_notificacion
  ADD CONSTRAINT canales_notificacion_tipo_check
  CHECK (tipo IN ('email','sms','webhook','slack','telegram','teams','whatsapp','glpi'));

COMMIT;
