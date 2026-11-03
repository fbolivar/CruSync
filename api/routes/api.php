<?php

use App\Http\Controllers\AuditoriaController;
use App\Http\Controllers\AuthController;
use App\Http\Controllers\CanalNotificacionController;
use App\Http\Controllers\ChequeoController;
use App\Http\Controllers\ConfigLdapController;
use App\Http\Controllers\AgenteController;
use App\Http\Controllers\BackupController;
use App\Http\Controllers\HealthController;
use App\Http\Controllers\CorrelacionController;
use App\Http\Controllers\CumplimientoController;
use App\Http\Controllers\DescubrimientoController;
use App\Http\Controllers\DosFactorController;
use App\Http\Controllers\FlujoController;
use App\Http\Controllers\IngestController;
use App\Http\Controllers\PushController;
use App\Http\Controllers\RumController;
use App\Http\Controllers\RunbookController;
use App\Http\Controllers\VmController;
use App\Http\Controllers\ImportacionController;
use App\Http\Controllers\IncidenciaController;
use App\Http\Controllers\MapaController;
use App\Http\Controllers\MantenimientoController;
use App\Http\Controllers\MetricaController;
use App\Http\Controllers\PerfilController;
use App\Http\Controllers\PronosticoController;
use App\Http\Controllers\RecursoController;
use App\Http\Controllers\ReglaController;
use App\Http\Controllers\ReporteController;
use App\Http\Controllers\ReporteExportController;
use App\Http\Controllers\ReporteProgramadoController;
use App\Http\Controllers\ServicioController;
use App\Http\Controllers\SitioController;
use App\Http\Controllers\TopologiaController;
use App\Http\Controllers\TrapController;
use App\Http\Controllers\TipoRecursoController;
use App\Http\Controllers\UmbralController;
use App\Http\Controllers\WanCalidadController;
use Illuminate\Support\Facades\Route;

/*
|--------------------------------------------------------------------------
| API (prefijo /api)  — FASE 2: solo gestión
|--------------------------------------------------------------------------
| Autenticación: middleware 'auth.jwt' valida el JWT propio (HS256, local) y
| resuelve el perfil/rol local. Autorización por rol con 'role:...'.
|
| Matriz de permisos:
|   - POST /api/auth/login     -> público (autenticación local: email + contraseña)
|   - GET (lectura)            -> cualquier rol autenticado (admin/operador/viewer)
|   - POST/PUT/PATCH/DELETE de configuración -> admin, operador
|   - /usuarios (gestión de perfiles)        -> solo admin
*/

// Autenticación local (pública): devuelve un JWT propio.
Route::post('auth/login', [AuthController::class, 'login']);

// ── PÚBLICO (sin JWT) ────────────────────────────────────────────────
// Ingesta: agente ligero (#8, token propio) y APM/RUM (#13, beacon).
// Throttle anti-flood por IP (evita DoS por disco: INSERT por petición).
Route::middleware('throttle:300,1')->group(function () {
    Route::post('ingest/agente', [IngestController::class, 'agente']);
    Route::post('ingest/rum', [IngestController::class, 'rum']);
    Route::post('ingest/span', [IngestController::class, 'span']);
});
// Clave pública VAPID para Web Push (#11).
Route::get('push/vapid', [PushController::class, 'vapid']);

// Salud del sistema (público, sin JWT): nginx + php-fpm + API + PostgreSQL.
// Lo consume el chequeo sintético de SIMON sobre sí mismo (auto-monitoreo).
Route::get('health', [HealthController::class, 'check']);

// Recursos de configuración con CRUD completo.
$crud = [
    'tipos-recurso'        => TipoRecursoController::class,
    'sitios'               => SitioController::class,
    'recursos'             => RecursoController::class,
    'umbrales'             => UmbralController::class,
    'reglas'               => ReglaController::class,
    'reportes-programados' => ReporteProgramadoController::class,
    'servicios'            => ServicioController::class,
    'mantenimientos'       => MantenimientoController::class,
    'canales-notificacion' => CanalNotificacionController::class,
    'runbooks'             => RunbookController::class,
    'cumplimiento-politicas' => CumplimientoController::class,
];

Route::middleware('auth.jwt')->group(function () use ($crud) {

    // Perfil propio (cualquier rol).
    Route::get('me', [PerfilController::class, 'me']);

    // 2FA (TOTP) del usuario autenticado.
    Route::post('2fa/iniciar', [DosFactorController::class, 'iniciar']);
    Route::post('2fa/activar', [DosFactorController::class, 'activar']);
    Route::post('2fa/desactivar', [DosFactorController::class, 'desactivar']);

    // ── LECTURA: cualquier rol autenticado ───────────────────────────
    foreach ($crud as $uri => $controller) {
        Route::get($uri, [$controller, 'index']);
        Route::get($uri.'/{id}', [$controller, 'show'])->whereNumber('id');
    }

    // Interfaces de red (IF-MIB) de un recurso (lectura).
    Route::get('recursos/{id}/interfaces', [RecursoController::class, 'interfaces'])->whereNumber('id');
    Route::get('recursos/{id}/interfaces/{ifIndex}/historico',
        [RecursoController::class, 'interfazHistorico'])->whereNumber('id')->whereNumber('ifIndex');
    // Percentil 95 de ancho de banda de una interfaz (facturación ISP).
    Route::get('recursos/{id}/interfaces/{ifIndex}/percentil',
        [RecursoController::class, 'interfazPercentil'])->whereNumber('id')->whereNumber('ifIndex');
    // Ruta de red (traceroute por salto) de un recurso.
    Route::get('recursos/{id}/ruta', [RecursoController::class, 'ruta'])->whereNumber('id');
    // Mapa geográfico: enlaces (con coords y estado) + sedes. Ligero, para miles de puntos.
    Route::get('mapa', [MapaController::class, 'index']);

    // Reportes (lectura): disponibilidad/SLA por recurso en un periodo.
    Route::get('reportes/disponibilidad', [ReporteController::class, 'disponibilidad']);
    // Reporte de consumo de ancho de banda (por interfaz) y de alertas enviadas.
    Route::get('reportes/banda', [ReporteController::class, 'banda']);
    Route::get('reportes/alertas', [ReporteController::class, 'alertas']);

    // Exportación de reportes (ejecutivo/sitio/recurso/servicios/banda/alertas) en CSV/XLSX/PDF.
    Route::get('reportes/export/{tipo}', [ReporteExportController::class, 'export'])
        ->whereIn('tipo', ['ejecutivo', 'sitio', 'recurso', 'servicios', 'banda', 'alertas']);

    // Pronósticos de capacidad (lectura): los calcula el worker.
    Route::get('pronosticos', [PronosticoController::class, 'index']);

    // Línea base estacional / anomalías de un recurso (lectura).
    Route::get('recursos/{id}/baselines', [RecursoController::class, 'baselines'])->whereNumber('id');

    // Hardware físico (Redfish/IPMI) de un recurso: inventario + componentes (lectura).
    Route::get('recursos/{id}/hardware', [RecursoController::class, 'hardware'])->whereNumber('id');

    // Topología L2 (LLDP): vecinos de un switch + grafo global (lectura).
    Route::get('recursos/{id}/vecinos', [RecursoController::class, 'vecinos'])->whereNumber('id');
    Route::get('topologia', [TopologiaController::class, 'index']);

    // Observabilidad de servicios: analisis de correlacion de una transaccion.
    Route::get('servicios/{id}/analisis', [ServicioController::class, 'analisis'])->whereNumber('id');

    // SNMP traps recibidos (lectura).
    Route::get('traps', [TrapController::class, 'index']);

    // Flujos de tráfico (NetFlow/IPFIX): top hablantes/destinos/apps/conversaciones.
    Route::get('flujos', [FlujoController::class, 'index']);
    Route::get('flujos/overview', [FlujoController::class, 'overview']);  // tablero NetFlow

    // Calidad activa de enlace WAN/Starlink de un recurso (lectura).
    Route::get('recursos/{id}/wan-calidad', [WanCalidadController::class, 'index'])->whereNumber('id');

    // Virtualización (#9): inventario de VMs de un host (lectura).
    Route::get('recursos/{id}/vms', [VmController::class, 'index'])->whereNumber('id');

    // Cumplimiento de configuración (#7): resultados (lectura).
    Route::get('cumplimiento/resultados', [CumplimientoController::class, 'resultados']);

    // AIOps (#14): correlaciones de incidencias (lectura).
    Route::get('correlaciones', [CorrelacionController::class, 'index']);

    // APM/RUM (#13): experiencia real del usuario (lectura).
    Route::get('rum', [RumController::class, 'index']);

    // Web Push (#11): registrar/quitar la suscripción del navegador.
    Route::post('push/suscribir', [PushController::class, 'suscribir']);
    Route::post('push/desuscribir', [PushController::class, 'desuscribir']);

    // Auto-descubrimiento de red (lectura): escaneos y candidatos.
    Route::get('descubrimiento', [DescubrimientoController::class, 'index']);
    Route::get('descubrimiento/tipos', [DescubrimientoController::class, 'tiposSugeridos']);
    Route::get('descubrimiento/{id}', [DescubrimientoController::class, 'show'])->whereNumber('id');

    // Solo lectura (telemetría / eventos) con filtros.
    Route::get('chequeos', [ChequeoController::class, 'index']);
    Route::get('chequeos/{id}', [ChequeoController::class, 'show'])->whereNumber('id');
    Route::get('metricas', [MetricaController::class, 'index']);          // sin show (PK compuesta)
    Route::get('incidencias', [IncidenciaController::class, 'index']);
    Route::get('incidencias/{id}', [IncidenciaController::class, 'show'])->whereNumber('id');
    // Bitácora del operador sobre la incidencia (lectura para cualquier rol).
    Route::get('incidencias/{id}/notas', [IncidenciaController::class, 'notas'])->whereNumber('id');

    // ── ESCRITURA de configuración: admin + operador ─────────────────
    Route::middleware('role:admin,operador')->group(function () use ($crud) {
        // Respaldos de configuración: el contenido es la running-config completa
        // (claves, communities SNMP, PSK) → NO debe verlo un viewer. Lectura
        // restringida a admin/operador.
        Route::get('recursos/{id}/respaldos', [RecursoController::class, 'respaldos'])->whereNumber('id');
        Route::get('recursos/{id}/respaldos/{respaldoId}', [RecursoController::class, 'respaldoContenido'])
            ->whereNumber('id')->whereNumber('respaldoId');

        foreach ($crud as $uri => $controller) {
            Route::post($uri, [$controller, 'store']);
            Route::match(['put', 'patch'], $uri.'/{id}', [$controller, 'update'])->whereNumber('id');
            Route::delete($uri.'/{id}', [$controller, 'destroy'])->whereNumber('id');
        }

        // Marcar interfaz como monitoreada (alertar si cae).
        Route::match(['put', 'patch'], 'recursos/{id}/interfaces/{ifIndex}',
            [RecursoController::class, 'actualizarInterfaz'])->whereNumber('id')->whereNumber('ifIndex');

        // Alta MASIVA de recursos desde inventario (CSV→JSON). Onboarding a escala.
        Route::post('recursos/importar', [ImportacionController::class, 'importar']);

        // Gestión de incidencias (reconocer / resolver).
        Route::post('incidencias/{id}/reconocer', [IncidenciaController::class, 'reconocer'])->whereNumber('id');
        Route::post('incidencias/{id}/resolver', [IncidenciaController::class, 'resolver'])->whereNumber('id');
        Route::post('incidencias/{id}/notas', [IncidenciaController::class, 'agregarNota'])->whereNumber('id');

        // Auto-descubrimiento: encolar barrido, alta/descartar candidatos.
        Route::post('descubrimiento', [DescubrimientoController::class, 'store']);
        Route::delete('descubrimiento/{id}', [DescubrimientoController::class, 'destroy'])->whereNumber('id');
        Route::post('descubrimiento/candidatos/{candidatoId}/agregar',
            [DescubrimientoController::class, 'agregar'])->whereNumber('candidatoId');
        Route::post('descubrimiento/candidatos/{candidatoId}/descartar',
            [DescubrimientoController::class, 'descartar'])->whereNumber('candidatoId');
    });

    // ── USUARIOS (perfiles) y AUDITORÍA: solo admin ──────────────────
    Route::middleware('role:admin')->group(function () {
        Route::get('auditoria', [AuditoriaController::class, 'index']);

        // Respaldos .pnnc (formato propio PNNC): generar y EXPORTAR backups de la BD.
        Route::get('backups', [BackupController::class, 'index']);
        Route::post('backups/generar', [BackupController::class, 'generar']);
        Route::get('backups/{id}/descargar', [BackupController::class, 'descargar']);
        Route::delete('backups/{id}', [BackupController::class, 'eliminar']);

        // Agentes ligeros (#8): el token se muestra una sola vez al crear.
        Route::get('agentes', [AgenteController::class, 'index']);
        Route::post('agentes', [AgenteController::class, 'store']);
        Route::delete('agentes/{id}', [AgenteController::class, 'destroy'])->whereNumber('id');

        // Configuración de SSO LDAP/AD.
        Route::get('config/ldap', [ConfigLdapController::class, 'mostrar']);
        Route::match(['put', 'patch'], 'config/ldap', [ConfigLdapController::class, 'guardar']);
        Route::post('config/ldap/probar', [ConfigLdapController::class, 'probar']);

        Route::get('usuarios', [PerfilController::class, 'index']);
        // Alcance por usuario: a que sitios (territoriales) puede acceder.
        Route::get('usuarios/{id}/sitios', [PerfilController::class, 'sitios']);
        Route::put('usuarios/{id}/sitios', [PerfilController::class, 'asignarSitios']);
        Route::get('usuarios/{id}', [PerfilController::class, 'show']);
        Route::post('usuarios', [PerfilController::class, 'store']);
        Route::match(['put', 'patch'], 'usuarios/{id}', [PerfilController::class, 'update']);
        Route::delete('usuarios/{id}', [PerfilController::class, 'destroy']);
    });
});
