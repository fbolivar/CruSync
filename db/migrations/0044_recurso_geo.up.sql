-- =====================================================================
-- 0044_recurso_geo.up.sql
-- Georreferenciación por RECURSO (enlace): coordenadas propias para marcarlo
-- individualmente en el mapa. Hasta ahora solo las SEDES (sitios) tenían lat/lon
-- y los recursos heredaban la ubicación de su sede. Con esto cada enlace se puede
-- ubicar en su punto real; si no tiene coords propias, el mapa cae a las de su sede.
-- =====================================================================
BEGIN;

ALTER TABLE recursos
  ADD COLUMN IF NOT EXISTS latitud  numeric(9,6)
    CHECK (latitud  IS NULL OR (latitud  >= -90  AND latitud  <= 90)),
  ADD COLUMN IF NOT EXISTS longitud numeric(9,6)
    CHECK (longitud IS NULL OR (longitud >= -180 AND longitud <= 180));

COMMENT ON COLUMN recursos.latitud  IS 'Latitud propia del recurso (NULL = usa la de su sede en el mapa).';
COMMENT ON COLUMN recursos.longitud IS 'Longitud propia del recurso (NULL = usa la de su sede en el mapa).';

COMMIT;
