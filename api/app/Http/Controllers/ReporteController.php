<?php

namespace App\Http\Controllers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use App\Support\Alcance;

class ReporteController extends Controller
{
    /**
     * Rangos LARGOS (en días). Se responden desde `disponibilidad_diaria` porque
     * `chequeos` solo guarda 30 días: sin el histórico consolidado, cualquier
     * pregunta de más de un mes no tendría datos.
     */
    private const RANGOS_LARGOS = ['90d' => 90, '6m' => 180, '12m' => 365];

    /**
     * Disponibilidad por recurso en un periodo.
     *
     * disponibilidad = (up + degraded) / (up + degraded + down) — sobre los
     * chequeos evaluables (excluye 'maintenance' y 'unknown'). Aproximación por
     * conteo de chequeos (intervalo casi uniforme por recurso).
     *
     * 24h/7d/30d se calculan en vivo desde `chequeos`; 90d/6m/12m desde el
     * histórico diario consolidado (misma fórmula, sumando los días).
     */
    public function disponibilidad(Request $request): JsonResponse
    {
        $rango = $request->query('rango', '7d');
        if (isset(self::RANGOS_LARGOS[$rango])) {
            return $this->desdeHistorico($rango, self::RANGOS_LARGOS[$rango]);
        }

        $segundos = ['24h' => 86400, '7d' => 604800, '30d' => 2592000][$rango] ?? 604800;
        $desde = now()->subSeconds($segundos);
        $desdeStr = $desde->toDateTimeString();
        $alc = $this->alcanceSql();

        $filas = DB::select(
            "SELECT r.id, r.nombre, r.tipo_id, r.sitio_id,
                    t.nombre AS tipo_nombre, s.nombre AS sitio_nombre,
                    r.estado_actual,
                    -- Objetivo efectivo de SLA: el del recurso pisa al del tipo.
                    COALESCE(r.sla_objetivo, t.sla_objetivo) AS sla_objetivo,
                    count(c.id) FILTER (WHERE c.estado <> 'maintenance') AS evaluables_total,
                    count(c.id) FILTER (WHERE c.estado = 'up')          AS up,
                    count(c.id) FILTER (WHERE c.estado = 'degraded')    AS degraded,
                    count(c.id) FILTER (WHERE c.estado = 'down')        AS down,
                    count(c.id) FILTER (WHERE c.estado = 'unknown')     AS unknown,
                    count(c.id) FILTER (WHERE c.estado = 'maintenance') AS mantenimiento,
                    (SELECT count(*) FROM incidencias i
                       WHERE i.recurso_id = r.id AND i.abierta_at >= ?) AS incidencias
             FROM recursos r
             JOIN tipos_recurso t ON t.id = r.tipo_id
             LEFT JOIN sitios s ON s.id = r.sitio_id
             LEFT JOIN chequeos c ON c.recurso_id = r.id AND c.ts >= ?
             WHERE (?::int[] IS NULL OR r.sitio_id = ANY(?::int[]))
             GROUP BY r.id, t.nombre, s.nombre, r.sla_objetivo, t.sla_objetivo
             ORDER BY r.nombre",
            [$desdeStr, $desdeStr, $alc, $alc]
        );

        return response()->json([
            'rango'    => $rango,
            'desde'    => $desde->toIso8601String(),
            'recursos' => $this->calcular($filas),
        ]);
    }

    /**
     * Consumo de ancho de banda por interfaz en un periodo: promedio, percentil 95
     * y máximo de Mbps in/out sobre interfaces_historico. (Fuente del informe de banda.)
     */
    public function banda(Request $request): JsonResponse
    {
        $rango = $request->query('rango', '7d');
        $segundos = ['24h' => 86400, '7d' => 604800, '30d' => 2592000][$rango] ?? 604800;
        $desde = now()->subSeconds($segundos)->toDateTimeString();
        $alc = $this->alcanceSql();

        $filas = DB::select(
            "SELECT r.nombre, t.nombre AS tipo_nombre, s.nombre AS sitio_nombre,
                    i.if_name, h.muestras, h.avg_in, h.avg_out, h.p95_in, h.p95_out,
                    h.max_in, h.max_out
             FROM interfaces i
             JOIN recursos r ON r.id = i.recurso_id
             JOIN tipos_recurso t ON t.id = r.tipo_id
             LEFT JOIN sitios s ON s.id = r.sitio_id
             JOIN LATERAL (
                 SELECT count(*) AS muestras,
                        round(avg(in_mbps)::numeric, 2)  AS avg_in,
                        round(avg(out_mbps)::numeric, 2) AS avg_out,
                        round(percentile_cont(0.95) within group (order by in_mbps)::numeric, 2)  AS p95_in,
                        round(percentile_cont(0.95) within group (order by out_mbps)::numeric, 2) AS p95_out,
                        round(max(in_mbps)::numeric, 2)  AS max_in,
                        round(max(out_mbps)::numeric, 2) AS max_out
                 FROM interfaces_historico hh
                 WHERE hh.recurso_id = i.recurso_id AND hh.if_index = i.if_index AND hh.ts >= ?
             ) h ON true
             WHERE r.activo = true AND h.muestras > 0
               AND (?::int[] IS NULL OR r.sitio_id = ANY(?::int[]))
             ORDER BY GREATEST(COALESCE(h.p95_in,0), COALESCE(h.p95_out,0)) DESC",
            [$desde, $alc, $alc]
        );

        return response()->json(['rango' => $rango, 'interfaces' => $filas]);
    }

    /**
     * Alertas (notificaciones) enviadas en un periodo con su detalle: fecha/hora,
     * medio, canal, destino, recurso, severidad, evento, alerta, estado y error.
     */
    public function alertas(Request $request): JsonResponse
    {
        $rango = $request->query('rango', '7d');
        $segundos = ['24h' => 86400, '7d' => 604800, '30d' => 2592000][$rango] ?? 604800;
        $desde = now()->subSeconds($segundos)->toDateTimeString();
        $alc = $this->alcanceSql();

        $filas = DB::select(
            "SELECT to_char(n.created_at, 'YYYY-MM-DD HH24:MI:SS') AS ts,
                    cn.tipo AS medio, cn.nombre AS canal_nombre, n.destino,
                    r.nombre AS recurso,
                    n.payload->>'severidad' AS severidad,
                    n.payload->>'evento'    AS evento,
                    n.payload->>'asunto'    AS asunto,
                    n.estado, n.error
             FROM notificaciones n
             JOIN canales_notificacion cn ON cn.id = n.canal_id
             JOIN incidencias ic ON ic.id = n.incidencia_id
             JOIN recursos r ON r.id = ic.recurso_id
             WHERE n.created_at >= ?
               AND (?::int[] IS NULL OR r.sitio_id = ANY(?::int[]))
             ORDER BY n.created_at DESC
             LIMIT 5000",
            [$desde, $alc, $alc]
        );

        return response()->json(['rango' => $rango, 'alertas' => $filas]);
    }

    /**
     * Rangos de más de 30 días: se suman los días del histórico consolidado
     * (`disponibilidad_diaria`), que sobrevive a la purga de `chequeos`.
     * Es la misma fórmula: solo cambia de dónde salen los conteos.
     */
    private function desdeHistorico(string $rango, int $dias): JsonResponse
    {
        $desde = now()->subDays($dias)->startOfDay();
        $alc = $this->alcanceSql();

        $filas = DB::select(
            "SELECT r.id, r.nombre, r.tipo_id, r.sitio_id,
                    t.nombre AS tipo_nombre, s.nombre AS sitio_nombre,
                    r.estado_actual,
                    COALESCE(r.sla_objetivo, t.sla_objetivo) AS sla_objetivo,
                    COALESCE(sum(d.up), 0)            AS up,
                    COALESCE(sum(d.degraded), 0)      AS degraded,
                    COALESCE(sum(d.down), 0)          AS down,
                    COALESCE(sum(d.unknown), 0)       AS unknown,
                    COALESCE(sum(d.mantenimiento), 0) AS mantenimiento,
                    COALESCE(sum(d.incidencias), 0)   AS incidencias,
                    COALESCE(sum(d.up + d.degraded + d.down + d.unknown), 0) AS evaluables_total,
                    count(d.dia) AS dias_con_datos
             FROM recursos r
             JOIN tipos_recurso t ON t.id = r.tipo_id
             LEFT JOIN sitios s ON s.id = r.sitio_id
             LEFT JOIN disponibilidad_diaria d ON d.recurso_id = r.id AND d.dia >= ?
             WHERE r.activo = true
               AND (?::int[] IS NULL OR r.sitio_id = ANY(?::int[]))
             GROUP BY r.id, t.nombre, s.nombre, r.sla_objetivo, t.sla_objetivo
             ORDER BY r.nombre",
            [$desde->toDateString(), $alc, $alc]
        );

        $datos = array_map(function ($f) {
            $f->dias_con_datos = (int) $f->dias_con_datos;

            return $f;
        }, $this->calcular($filas));

        return response()->json([
            'rango'    => $rango,
            'desde'    => $desde->toIso8601String(),
            'fuente'   => 'historico',   // el cliente puede advertir que son días consolidados
            'recursos' => $datos,
        ]);
    }

    /** Disponibilidad y cumplimiento de SLA a partir de los conteos (común a ambas fuentes). */
    private function calcular(array $filas): array
    {
        return array_map(function ($f) {
            foreach (['evaluables_total', 'up', 'degraded', 'down', 'unknown', 'mantenimiento', 'incidencias'] as $k) {
                $f->$k = (int) $f->$k;
            }
            $base = $f->up + $f->degraded + $f->down;
            $f->disponibilidad = $base > 0 ? round(($f->up + $f->degraded) / $base * 100, 3) : null;

            $f->sla_objetivo = $f->sla_objetivo !== null ? (float) $f->sla_objetivo : null;
            // Sin objetivo o sin datos -> null (ni cumple ni incumple). "Sin datos"
            // NO es incumplimiento: no se puede acusar a lo que no se pudo medir.
            $f->cumple_sla = ($f->disponibilidad !== null && $f->sla_objetivo !== null)
                ? $f->disponibilidad >= $f->sla_objetivo
                : null;

            return $f;
        }, $filas);
    }

    /**
     * Alcance del usuario como array literal de Postgres (o null si no esta acotado),
     * para filtrar con `r.sitio_id = ANY(?)` sin interpolar nada en el SQL.
     */
    private function alcanceSql(): ?string
    {
        $sitios = Alcance::sitios();

        return $sitios === null ? null : '{'.implode(',', array_map('intval', $sitios)).'}';
    }
}
