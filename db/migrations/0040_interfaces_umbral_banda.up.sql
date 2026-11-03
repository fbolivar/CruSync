-- =====================================================================
-- 0040_interfaces_umbral_banda.up.sql
-- Alertas por ANCHO DE BANDA / saturación de interfaz (sensor estilo PRTG/
-- SolarWinds). El worker ya recolecta util_in/util_out (% de ifHighSpeed) y
-- errores por interfaz; faltaba ALERTAR cuando una interfaz monitoreada se
-- satura o acumula errores.
--
-- Override opcional por interfaz: un uplink/WAN suele querer un umbral distinto
-- al de un puerto de acceso. NULL = usa el umbral global del worker
-- (IF_UTIL_WARNING / IF_UTIL_CRITICAL / IF_ERR_*).
--
-- Las incidencias de saturación reutilizan la tabla `incidencias` por interfaz
-- (if_index) distinguiéndose de la de link-down por `componente='saturacion'`
-- (la columna `componente` ya existe de la ola de hardware). El índice único
-- (recurso, COALESCE(if_index,-1), COALESCE(componente,'')) permite una
-- incidencia de link-down y una de saturación coexistiendo en el mismo puerto.
-- =====================================================================
BEGIN;

ALTER TABLE interfaces
  ADD COLUMN IF NOT EXISTS umbral_util_warning  double precision
    CHECK (umbral_util_warning  IS NULL OR (umbral_util_warning  >= 0 AND umbral_util_warning  <= 100)),
  ADD COLUMN IF NOT EXISTS umbral_util_critical double precision
    CHECK (umbral_util_critical IS NULL OR (umbral_util_critical >= 0 AND umbral_util_critical <= 100));

COMMENT ON COLUMN interfaces.umbral_util_warning  IS
  'Override de utilización % (warning) de ESTA interfaz; NULL = usa el umbral global del worker.';
COMMENT ON COLUMN interfaces.umbral_util_critical IS
  'Override de utilización % (crítico) de ESTA interfaz; NULL = usa el umbral global del worker.';

COMMIT;
