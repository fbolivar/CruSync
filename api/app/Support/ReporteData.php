<?php

namespace App\Support;

use Illuminate\Support\Facades\DB;

/**
 * Construye los datos de los 4 reportes en una ESTRUCTURA NORMALIZADA que luego
 * renderizan CSV/XLSX/PDF por igual:
 *   ['titulo','subtitulo','kpis'=>[['label','valor']],'tablas'=>[['titulo','columnas','filas']]]
 */
class ReporteData
{
    private const RANGO_SEG = ['24h' => 86400, '7d' => 604800, '30d' => 2592000];
    private const RANGO_TXT = ['24h' => 'últimas 24 horas', '7d' => 'últimos 7 días', '30d' => 'últimos 30 días'];
    private const SNMP_TIPOS = ['servidor', 'switch_lan', 'switch_san', 'nas', 'ups'];
    private const PESO = ['down' => 5, 'degraded' => 4, 'unknown' => 3, 'maintenance' => 2, 'up' => 1];

    public static function rangoTexto(string $rango): string
    {
        return self::RANGO_TXT[$rango] ?? self::RANGO_TXT['7d'];
    }

    private static function rangoSeg(string $rango): int
    {
        return self::RANGO_SEG[$rango] ?? 604800;
    }

    private static function generado(): string
    {
        return now()->format('Y-m-d H:i');
    }

    /** Subtítulo con el rango de fechas REAL cubierto (aclara si hay menos datos). */
    private static function subtitulo(string $rango): string
    {
        $desdeSolic = now()->subSeconds(self::rangoSeg($rango));
        $viejo = DB::table('chequeos')->min('ts');
        $viejo = $viejo ? \Illuminate\Support\Carbon::parse($viejo) : null;
        $efectivo = $viejo && $viejo->gt($desdeSolic) ? $viejo : $desdeSolic;

        $s = 'Periodo: '.self::rangoTexto($rango).'  ·  del '.$efectivo->format('Y-m-d').
             ' al '.now()->format('Y-m-d');
        if ($viejo && $viejo->gt($desdeSolic)) {
            $s .= '  (solo hay datos desde '.$viejo->format('Y-m-d').')';
        }

        return $s.'  ·  Generado: '.self::generado();
    }

    /** Duración legible entre dos instantes (fin null = en curso, usa ahora). */
    private static function duracion($inicio, $fin): string
    {
        $i = \Illuminate\Support\Carbon::parse($inicio);
        $f = $fin ? \Illuminate\Support\Carbon::parse($fin) : now();
        $min = max(0, $i->diffInMinutes($f));
        $d = intdiv($min, 1440); $h = intdiv($min % 1440, 60); $m = $min % 60;
        if ($d > 0) return "{$d}d {$h}h {$m}m";
        if ($h > 0) return "{$h}h {$m}m";

        return "{$m}m";
    }

    // ── Disponibilidad por recurso (base de varios reportes) ───────────
    private static function disponibilidad(int $rangoSeg, ?int $sitioId = null, ?int $recursoId = null): array
    {
        $desde = now()->subSeconds($rangoSeg)->toDateTimeString();
        $cond = 'r.activo = true';
        $bind = [$desde, $desde];
        if ($recursoId) { $cond .= ' AND r.id = ?'; $bind[] = $recursoId; }
        elseif ($sitioId) { $cond .= ' AND r.sitio_id = ?'; $bind[] = $sitioId; }

        // Alcance del usuario: el EXPORT no puede saltarse el acotamiento del informe.
        // (Sin esto, un usuario acotado se descargaba en PDF/CSV toda la entidad.)
        $alc = Alcance::sitios();
        if ($alc !== null) {
            $cond .= ' AND r.sitio_id = ANY(?::int[])';
            $bind[] = '{'.implode(',', array_map('intval', $alc)).'}';
        }

        $rows = DB::select(
            "SELECT r.id, r.nombre, r.estado_actual, t.nombre AS tipo_nombre,
                    COALESCE(s.nombre,'—') AS sitio_nombre,
                    count(c.id) FILTER (WHERE c.estado='up')       AS up,
                    count(c.id) FILTER (WHERE c.estado='degraded') AS degraded,
                    count(c.id) FILTER (WHERE c.estado='down')     AS down,
                    count(c.id) FILTER (WHERE c.estado='unknown')  AS unknown,
                    (SELECT count(*) FROM incidencias i WHERE i.recurso_id=r.id AND i.abierta_at >= ?) AS incidencias
             FROM recursos r
             JOIN tipos_recurso t ON t.id = r.tipo_id
             LEFT JOIN sitios s ON s.id = r.sitio_id
             LEFT JOIN chequeos c ON c.recurso_id = r.id AND c.ts >= ?
             WHERE $cond
             GROUP BY r.id, t.nombre, s.nombre
             ORDER BY r.nombre",
            $bind
        );

        return array_map(function ($r) {
            $base = $r->up + $r->degraded + $r->down;
            $r->disponibilidad = $base > 0 ? round(($r->up + $r->degraded) / $base * 100, 2) : null;

            return $r;
        }, $rows);
    }

    private static function dispTxt($d): string
    {
        return $d === null ? 'sin datos' : number_format($d, 2).'%';
    }

    private static function conteoEstados(): array
    {
        $c = ['up' => 0, 'degraded' => 0, 'down' => 0, 'unknown' => 0, 'maintenance' => 0];
        foreach (Alcance::filtrarPorSitio(DB::table('recursos')->where('activo', true))
            ->select('estado_actual', DB::raw('count(*) as n'))->groupBy('estado_actual')->get() as $r) {
            $c[$r->estado_actual] = (int) $r->n;
        }

        return $c;
    }

    // ── Análisis de servicios (mismo criterio que ServicioController) ──
    private static function serviciosAnalisis(): array
    {
        // Alcance: si el usuario esta acotado, solo los servicios que tocan SUS recursos.
        $ids = Alcance::recursos();
        $servicios = DB::table('servicios')
            ->when($ids !== null, fn ($q) => $q->whereExists(fn ($e) => $e->from('servicio_componentes as sc')
                ->whereColumn('sc.servicio_id', 'servicios.id')
                ->whereIn('sc.recurso_id', $ids ?: [-1])))
            ->orderBy('nombre')->get();
        $out = [];
        foreach ($servicios as $s) {
            $comps = DB::table('servicio_componentes as c')
                ->leftJoin('recursos as r', 'r.id', '=', 'c.recurso_id')
                ->leftJoin('tipos_recurso as t', 't.id', '=', 'r.tipo_id')
                ->where('c.servicio_id', $s->id)->orderBy('c.orden')
                ->get(['c.nombre', 'c.recurso_id', 'r.estado_actual', 't.codigo as tipo_codigo']);

            $peor = 'up'; $exp = null; $cuello = null; $cuelloEstado = 'up'; $cuelloLat = -1;
            foreach ($comps as $c) {
                $estado = $c->estado_actual ?? 'unknown';
                $infra = in_array($c->tipo_codigo, self::SNMP_TIPOS, true);
                $lat = $infra || ! $c->recurso_id ? null : DB::table('chequeos')->where('recurso_id', $c->recurso_id)
                    ->orderByDesc('ts')->value('latencia_ms');
                if (self::PESO[$estado] > self::PESO[$peor]) $peor = $estado;
                if ($lat !== null && $exp === null) $exp = (int) $lat;
                // cuello: peor estado, luego mayor latencia
                if (self::PESO[$estado] > self::PESO[$cuelloEstado]
                    || ($estado === $cuelloEstado && (int) $lat > $cuelloLat)) {
                    $cuello = $c->nombre; $cuelloEstado = $estado; $cuelloLat = (int) $lat;
                }
            }
            $alto = ($exp !== null && $exp > $s->objetivo_ms) || in_array($peor, ['down', 'degraded'], true);
            $out[] = [
                'nombre' => $s->nombre, 'estado' => $peor, 'experiencia_ms' => $exp,
                'objetivo_ms' => $s->objetivo_ms, 'cuello' => $cuello, 'alto_impacto' => $alto,
            ];
        }

        return $out;
    }

    private static function ms($v): string
    {
        if ($v === null) return '—';
        return $v >= 1000 ? number_format($v / 1000, 2).' s' : round($v).' ms';
    }

    // ── 1) Reporte ejecutivo general ──────────────────────────────────
    public static function ejecutivo(string $rango): array
    {
        $disp = self::disponibilidad(self::rangoSeg($rango));
        $est = self::conteoEstados();
        $dispVals = array_values(array_filter(array_map(fn ($r) => $r->disponibilidad, $disp), fn ($x) => $x !== null));
        $prom = $dispVals ? round(array_sum($dispVals) / count($dispVals), 2) : null;
        $incPeriodo = array_sum(array_map(fn ($r) => (int) $r->incidencias, $disp));
        $incAbiertas = Alcance::filtrarPorRecurso(
            DB::table('incidencias')->where('estado', '<>', 'resuelta')
        )->count();
        $servicios = self::serviciosAnalisis();
        $svcAfectados = count(array_filter($servicios, fn ($s) => $s['alto_impacto']));

        // Agregado por sitio
        $porSitio = [];
        foreach ($disp as $r) {
            $k = $r->sitio_nombre;
            $porSitio[$k] ??= ['recursos' => 0, 'up' => 0, 'degraded' => 0, 'down' => 0, 'inc' => 0];
            $porSitio[$k]['recursos']++;
            $porSitio[$k]['up'] += $r->up; $porSitio[$k]['degraded'] += $r->degraded;
            $porSitio[$k]['down'] += $r->down; $porSitio[$k]['inc'] += (int) $r->incidencias;
        }
        $filasSitio = [];
        foreach ($porSitio as $sitio => $v) {
            $b = $v['up'] + $v['degraded'] + $v['down'];
            $filasSitio[] = [$sitio, $v['recursos'], self::dispTxt($b > 0 ? round(($v['up'] + $v['degraded']) / $b * 100, 2) : null), $v['inc']];
        }

        // Agregado por tipo
        $porTipo = [];
        foreach ($disp as $r) {
            $k = $r->tipo_nombre;
            $porTipo[$k] ??= ['recursos' => 0, 'up' => 0, 'degraded' => 0, 'down' => 0];
            $porTipo[$k]['recursos']++;
            $porTipo[$k]['up'] += $r->up; $porTipo[$k]['degraded'] += $r->degraded; $porTipo[$k]['down'] += $r->down;
        }
        $filasTipo = [];
        foreach ($porTipo as $tipo => $v) {
            $b = $v['up'] + $v['degraded'] + $v['down'];
            $filasTipo[] = [$tipo, $v['recursos'], self::dispTxt($b > 0 ? round(($v['up'] + $v['degraded']) / $b * 100, 2) : null)];
        }

        // Top recursos con peor disponibilidad / más incidencias
        $orden = $disp;
        usort($orden, fn ($a, $b) => ($a->disponibilidad ?? 101) <=> ($b->disponibilidad ?? 101) ?: $b->incidencias <=> $a->incidencias);
        $filasTop = array_map(fn ($r) => [
            $r->nombre, $r->tipo_nombre, $r->sitio_nombre, ucfirst($r->estado_actual),
            self::dispTxt($r->disponibilidad), (int) $r->incidencias,
        ], array_slice($orden, 0, 10));

        // Servicios
        $filasSvc = array_map(fn ($s) => [
            $s['nombre'], ucfirst($s['estado']), self::ms($s['experiencia_ms']),
            self::ms($s['objetivo_ms']), $s['cuello'] ?? '—', $s['alto_impacto'] ? 'Sí' : 'No',
        ], $servicios);

        return [
            'titulo' => 'Reporte ejecutivo de monitoreo',
            'subtitulo' => self::subtitulo($rango),
            'kpis' => [
                ['label' => 'Recursos monitoreados', 'valor' => count($disp)],
                ['label' => 'Disponibilidad promedio', 'valor' => self::dispTxt($prom)],
                ['label' => 'Operativos', 'valor' => $est['up']],
                ['label' => 'Degradados', 'valor' => $est['degraded']],
                ['label' => 'Caídos', 'valor' => $est['down']],
                ['label' => 'Incidencias abiertas', 'valor' => $incAbiertas],
                ['label' => 'Incidencias en el periodo', 'valor' => $incPeriodo],
                ['label' => 'Servicios con afectación', 'valor' => $svcAfectados.' / '.count($servicios)],
            ],
            'tablas' => [
                ['titulo' => 'Disponibilidad por sitio', 'columnas' => ['Sitio', 'Recursos', 'Disponibilidad', 'Incidencias'], 'filas' => $filasSitio],
                ['titulo' => 'Disponibilidad por tipo', 'columnas' => ['Tipo', 'Recursos', 'Disponibilidad'], 'filas' => $filasTipo],
                ['titulo' => 'Recursos que requieren atención (peor disponibilidad)', 'columnas' => ['Recurso', 'Tipo', 'Sitio', 'Estado', 'Disponibilidad', 'Incid.'], 'filas' => $filasTop],
                ['titulo' => 'Servicios (observabilidad)', 'columnas' => ['Servicio', 'Estado', 'Experiencia', 'Objetivo', 'Cuello de botella', 'Afectación'], 'filas' => $filasSvc],
            ],
        ];
    }

    // ── 2) Reporte por sitio ──────────────────────────────────────────
    public static function porSitio(string $rango, ?int $sitioId): array
    {
        $disp = self::disponibilidad(self::rangoSeg($rango), $sitioId);
        $sitioNom = $sitioId ? (DB::table('sitios')->where('id', $sitioId)->value('nombre') ?? "Sitio #$sitioId") : 'Todos los sitios';

        // Agrupar por sitio
        $grupos = [];
        foreach ($disp as $r) { $grupos[$r->sitio_nombre][] = $r; }
        $tablas = [];
        foreach ($grupos as $sitio => $rs) {
            $filas = array_map(fn ($r) => [
                $r->nombre, $r->tipo_nombre, ucfirst($r->estado_actual),
                self::dispTxt($r->disponibilidad), (int) $r->incidencias,
            ], $rs);
            $tablas[] = ['titulo' => 'Sitio: '.$sitio.' ('.count($rs).' recursos)',
                'columnas' => ['Recurso', 'Tipo', 'Estado', 'Disponibilidad', 'Incidencias'], 'filas' => $filas];
        }

        $dispVals = array_values(array_filter(array_map(fn ($r) => $r->disponibilidad, $disp), fn ($x) => $x !== null));
        $prom = $dispVals ? round(array_sum($dispVals) / count($dispVals), 2) : null;

        return [
            'titulo' => 'Reporte por sitio — '.$sitioNom,
            'subtitulo' => self::subtitulo($rango),
            'kpis' => [
                ['label' => 'Sitios', 'valor' => count($grupos)],
                ['label' => 'Recursos', 'valor' => count($disp)],
                ['label' => 'Disponibilidad promedio', 'valor' => self::dispTxt($prom)],
                ['label' => 'Incidencias en el periodo', 'valor' => array_sum(array_map(fn ($r) => (int) $r->incidencias, $disp))],
            ],
            'tablas' => $tablas ?: [['titulo' => 'Sin datos', 'columnas' => ['—'], 'filas' => []]],
        ];
    }

    // ── 3) Reporte por recurso ────────────────────────────────────────
    public static function porRecurso(string $rango, ?int $recursoId): array
    {
        if ($recursoId) {
            return self::recursoDetalle($rango, $recursoId);
        }

        // Todos los recursos: tabla general.
        $disp = self::disponibilidad(self::rangoSeg($rango));
        $filas = array_map(fn ($r) => [
            $r->nombre, $r->tipo_nombre, $r->sitio_nombre, ucfirst($r->estado_actual),
            self::dispTxt($r->disponibilidad), (int) $r->up, (int) $r->degraded, (int) $r->down, (int) $r->incidencias,
        ], $disp);

        return [
            'titulo' => 'Reporte por recurso — Todos los recursos',
            'subtitulo' => self::subtitulo($rango),
            'kpis' => [['label' => 'Recursos', 'valor' => count($disp)]],
            'tablas' => [['titulo' => 'Detalle por recurso',
                'columnas' => ['Recurso', 'Tipo', 'Sitio', 'Estado', 'Disponibilidad', 'Up', 'Degr.', 'Caído', 'Incid.'],
                'filas' => $filas]],
        ];
    }

    /** Reporte detallado de UN recurso: info + métricas + incidencias con motivo. */
    private static function recursoDetalle(string $rango, int $recursoId): array
    {
        $d = self::disponibilidad(self::rangoSeg($rango), null, $recursoId)[0] ?? null;
        $info = DB::table('recursos as r')
            ->join('tipos_recurso as t', 't.id', '=', 'r.tipo_id')
            ->leftJoin('sitios as s', 's.id', '=', 'r.sitio_id')
            ->where('r.id', $recursoId)
            ->first(['r.nombre', 'r.hostname', 'r.estado_actual', 'r.ultimo_chequeo_at',
                'r.intervalo_segundos', 't.nombre as tipo', 's.nombre as sitio']);
        $nom = $info->nombre ?? "Recurso #$recursoId";

        // Métricas actuales (último valor por métrica).
        $met = DB::table('vw_ultima_metrica')->where('recurso_id', $recursoId)
            ->orderBy('metrica')->get(['metrica', 'valor', 'unidad', 'ts']);
        $filasMet = $met->map(fn ($m) => [
            $m->metrica,
            round((float) $m->valor, 2).($m->unidad ? ' '.$m->unidad : ''),
            substr((string) $m->ts, 0, 16),
        ])->all();

        // Incidencias del periodo con detalle (motivo + duración).
        $desde = now()->subSeconds(self::rangoSeg($rango))->toDateTimeString();
        $inc = DB::table('incidencias')->where('recurso_id', $recursoId)
            ->where('abierta_at', '>=', $desde)->orderByDesc('abierta_at')
            ->get(['severidad', 'titulo', 'descripcion', 'abierta_at', 'resuelta_at', 'estado']);
        $filasInc = $inc->map(fn ($i) => [
            ucfirst($i->severidad), $i->titulo, $i->descripcion ?: '—',
            substr((string) $i->abierta_at, 0, 16),
            $i->resuelta_at ? substr((string) $i->resuelta_at, 0, 16) : 'en curso',
            self::duracion($i->abierta_at, $i->resuelta_at), ucfirst($i->estado),
        ])->all();

        return [
            'titulo' => 'Reporte por recurso — '.$nom,
            'subtitulo' => self::subtitulo($rango),
            'kpis' => [
                ['label' => 'Tipo', 'valor' => $info->tipo ?? '—'],
                ['label' => 'Sitio', 'valor' => $info->sitio ?? '—'],
                ['label' => 'Estado actual', 'valor' => ucfirst($info->estado_actual ?? 'unknown')],
                ['label' => 'Disponibilidad', 'valor' => self::dispTxt($d->disponibilidad ?? null)],
                ['label' => 'Host / IP', 'valor' => $info->hostname ?? '—'],
                ['label' => 'Intervalo', 'valor' => ($info->intervalo_segundos ?? '—').' s'],
                ['label' => 'Último chequeo', 'valor' => $info->ultimo_chequeo_at ? substr((string) $info->ultimo_chequeo_at, 0, 16) : '—'],
                ['label' => 'Incidencias', 'valor' => (int) ($d->incidencias ?? 0)],
            ],
            'tablas' => [
                ['titulo' => 'Métricas actuales', 'columnas' => ['Métrica', 'Valor', 'Medido'], 'filas' => $filasMet],
                ['titulo' => 'Incidencias del periodo', 'columnas' => ['Severidad', 'Título', 'Detalle / motivo', 'Inicio', 'Fin', 'Duración', 'Estado'], 'filas' => $filasInc],
                ['titulo' => 'Conteo de chequeos del periodo', 'columnas' => ['Operativo', 'Degradado', 'Caído', 'Desconocido'],
                    'filas' => [[(int) ($d->up ?? 0), (int) ($d->degraded ?? 0), (int) ($d->down ?? 0), (int) ($d->unknown ?? 0)]]],
            ],
        ];
    }

    // ── 4) Reporte de servicios (observabilidad) ──────────────────────
    public static function servicios(string $rango): array
    {
        $svc = self::serviciosAnalisis();
        usort($svc, fn ($a, $b) => self::PESO[$b['estado']] <=> self::PESO[$a['estado']]
            ?: ($b['alto_impacto'] <=> $a['alto_impacto']));
        $filas = array_map(fn ($s) => [
            $s['nombre'], ucfirst($s['estado']), self::ms($s['experiencia_ms']), self::ms($s['objetivo_ms']),
            $s['cuello'] ?? '—', $s['alto_impacto'] ? 'Sí' : 'No',
        ], $svc);

        return [
            'titulo' => 'Reporte de servicios (observabilidad)',
            'subtitulo' => 'Generado: '.self::generado(),
            'kpis' => [
                ['label' => 'Servicios', 'valor' => count($svc)],
                ['label' => 'Con afectación', 'valor' => count(array_filter($svc, fn ($s) => $s['alto_impacto']))],
                ['label' => 'Sanos', 'valor' => count(array_filter($svc, fn ($s) => ! $s['alto_impacto']))],
            ],
            'tablas' => [
                ['titulo' => 'Estado de los servicios', 'columnas' => ['Servicio', 'Estado', 'Experiencia', 'Objetivo', 'Cuello de botella', 'Afectación'], 'filas' => $filas],
            ],
        ];
    }

    // ── 5) Consumo de ancho de banda (por interfaz) ───────────────────
    public static function banda(string $rango): array
    {
        $desde = now()->subSeconds(self::rangoSeg($rango))->toDateTimeString();
        $cond = 'r.activo = true';
        $bind = [$desde];
        $alc = Alcance::sitios();
        if ($alc !== null) {
            $cond .= ' AND r.sitio_id = ANY(?::int[])';
            $bind[] = '{'.implode(',', array_map('intval', $alc)).'}';
        }

        $rows = DB::select(
            "SELECT r.nombre, COALESCE(s.nombre,'—') AS sitio, i.if_name,
                    h.muestras, h.avg_in, h.avg_out, h.p95_in, h.p95_out, h.max_in, h.max_out
             FROM interfaces i
             JOIN recursos r ON r.id = i.recurso_id
             LEFT JOIN sitios s ON s.id = r.sitio_id
             JOIN LATERAL (
                 SELECT count(*) AS muestras,
                        round(avg(in_mbps)::numeric,2)  AS avg_in,
                        round(avg(out_mbps)::numeric,2) AS avg_out,
                        round(percentile_cont(0.95) within group (order by in_mbps)::numeric,2)  AS p95_in,
                        round(percentile_cont(0.95) within group (order by out_mbps)::numeric,2) AS p95_out,
                        round(max(in_mbps)::numeric,2)  AS max_in,
                        round(max(out_mbps)::numeric,2) AS max_out
                 FROM interfaces_historico hh
                 WHERE hh.recurso_id = i.recurso_id AND hh.if_index = i.if_index AND hh.ts >= ?
             ) h ON true
             WHERE $cond AND h.muestras > 0
             ORDER BY GREATEST(COALESCE(h.p95_in,0),COALESCE(h.p95_out,0)) DESC",
            $bind
        );

        $p95max = 0.0;
        $filas = array_map(function ($r) use (&$p95max) {
            $p95max = max($p95max, (float) $r->p95_in, (float) $r->p95_out);
            return [$r->nombre, $r->if_name, $r->sitio,
                number_format((float) $r->avg_in, 2), number_format((float) $r->avg_out, 2),
                number_format((float) $r->p95_in, 2), number_format((float) $r->p95_out, 2),
                number_format((float) $r->max_in, 2), number_format((float) $r->max_out, 2)];
        }, $rows);

        return [
            'titulo'    => 'Reporte de consumo de ancho de banda',
            'subtitulo' => self::subtitulo($rango),
            'kpis'      => [
                ['label' => 'Interfaces', 'valor' => count($rows)],
                ['label' => 'Consumo p95 máximo', 'valor' => number_format($p95max, 2).' Mbps'],
            ],
            'tablas'    => [[
                'titulo'   => 'Consumo por interfaz (Mbps) — ordenado por p95',
                'columnas' => ['Recurso', 'Interfaz', 'Sitio', 'Prom. ↓', 'Prom. ↑',
                               'P95 ↓', 'P95 ↑', 'Máx ↓', 'Máx ↑'],
                'filas'    => $filas,
            ]],
        ];
    }

    // ── 6) Alertas enviadas (notificaciones) ──────────────────────────
    public static function alertas(string $rango): array
    {
        $desde = now()->subSeconds(self::rangoSeg($rango))->toDateTimeString();
        $cond = '1 = 1';
        $bind = [$desde];
        $alc = Alcance::sitios();
        if ($alc !== null) {
            $cond .= ' AND r.sitio_id = ANY(?::int[])';
            $bind[] = '{'.implode(',', array_map('intval', $alc)).'}';
        }

        $rows = DB::select(
            "SELECT to_char(n.created_at,'YYYY-MM-DD HH24:MI:SS') AS ts,
                    cn.tipo AS medio, n.destino, r.nombre AS recurso,
                    n.payload->>'severidad' AS severidad, n.payload->>'evento' AS evento,
                    n.payload->>'asunto' AS asunto, n.estado, n.error
             FROM notificaciones n
             JOIN canales_notificacion cn ON cn.id = n.canal_id
             JOIN incidencias ic ON ic.id = n.incidencia_id
             JOIN recursos r ON r.id = ic.recurso_id
             WHERE n.created_at >= ? AND $cond
             ORDER BY n.created_at DESC LIMIT 5000",
            $bind
        );

        $enviadas = 0; $fallidas = 0; $criticas = 0;
        foreach ($rows as $r) {
            $enviadas += $r->estado === 'enviada' ? 1 : 0;
            $fallidas += $r->estado === 'fallida' ? 1 : 0;
            $criticas += $r->severidad === 'critical' ? 1 : 0;
        }
        $filas = array_map(fn ($r) => [
            $r->ts, $r->medio, $r->recurso, ucfirst($r->severidad ?? '—'),
            $r->evento ?? '—', $r->asunto ?? '—', ucfirst($r->estado),
        ], $rows);

        return [
            'titulo'    => 'Reporte de alertas enviadas',
            'subtitulo' => self::subtitulo($rango),
            'kpis'      => [
                ['label' => 'Alertas', 'valor' => count($rows)],
                ['label' => 'Enviadas', 'valor' => $enviadas],
                ['label' => 'Fallidas', 'valor' => $fallidas],
                ['label' => 'Críticas', 'valor' => $criticas],
            ],
            'tablas'    => [[
                'titulo'   => 'Detalle de alertas (más recientes primero)',
                'columnas' => ['Fecha y hora', 'Medio', 'Recurso', 'Severidad',
                               'Evento', 'Alerta', 'Estado'],
                'filas'    => $filas,
            ]],
        ];
    }

    /** Despacha por tipo de reporte. */
    public static function construir(string $tipo, string $rango, ?int $id): array
    {
        return match ($tipo) {
            'ejecutivo' => self::ejecutivo($rango),
            'sitio'     => self::porSitio($rango, $id),
            'recurso'   => self::porRecurso($rango, $id),
            'servicios' => self::servicios($rango),
            'banda'     => self::banda($rango),
            'alertas'   => self::alertas($rango),
            default     => self::ejecutivo($rango),
        };
    }
}
