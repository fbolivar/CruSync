-- =====================================================================
-- 0041_rutas_traceroute.up.sql
-- Ruta de red por salto (traceroute) de un recurso opt-in (parametros.traceroute).
-- Localiza DÓNDE se introduce latencia/pérdida en el camino (Starlink -> ISP ->
-- destino) — equivalente al hop-by-hop de SolarWinds / la herramienta de PRTG.
--
-- Se guarda SOLO la última ruta por recurso (se reemplaza en cada corrida del job
-- recolectar_rutas): el camino cambia poco y lo que importa es el estado actual,
-- igual que el snapshot de `interfaces`.
-- =====================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS rutas (
  recurso_id bigint    NOT NULL REFERENCES recursos(id) ON DELETE CASCADE,
  hop_no     smallint  NOT NULL,            -- nº de salto (1..N)
  ip         text,                          -- IP del salto (null si no respondió)
  hostname   text,                          -- PTR si se resolvió
  rtt_ms     numeric(8,2),                  -- RTT del salto (null si '*')
  perdida    boolean   NOT NULL DEFAULT false, -- true = salto sin respuesta ('*')
  ts         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (recurso_id, hop_no)
);

COMMENT ON TABLE rutas IS
  'Última ruta de red (traceroute por salto) por recurso. La reemplaza el job recolectar_rutas del worker.';

COMMIT;
