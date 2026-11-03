<?php

namespace App\Http\Controllers;

use App\Models\Recurso;
use App\Support\Alcance;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

/**
 * Alta MASIVA de recursos (enlaces/equipos) desde un inventario. Pensado para
 * onboarding a escala (p.ej. 1200 enlaces de internet/MPLS con SNMP) sin crearlos
 * uno a uno. El frontend parsea el CSV y envía las filas como JSON; aquí se
 * validan, se resuelven tipo/sitio, se cifra la community y se hace UPSERT por
 * hostname (reimportar no duplica). Cada fila es independiente: una fila mala no
 * aborta el lote; se devuelve un resumen con los errores por fila.
 */
class ImportacionController extends Controller
{
    public function importar(Request $request): JsonResponse
    {
        $v = $request->validate([
            'filas'              => ['required', 'array', 'min:1', 'max:5000'],
            'filas.*.nombre'     => ['required', 'string', 'max:255'],
            'filas.*.hostname'   => ['required', 'string', 'max:255'],
            // Valores por defecto del lote (una fila puede pisarlos).
            'tipo'               => ['nullable', 'string'],
            'community'          => ['nullable', 'string'],
            'snmp_version'       => ['nullable', 'in:2c,v2c,3,v3'],
            'intervalo_segundos' => ['nullable', 'integer', 'between:5,86400'],
            'interfaces'         => ['nullable', 'boolean'],
            'activo'             => ['nullable', 'boolean'],
            'sitio'              => ['nullable', 'string'],
        ]);

        $defTipo     = $v['tipo'] ?? 'fibra_wan';
        $defComm     = $v['community'] ?? null;
        $defVer      = $this->normVer($v['snmp_version'] ?? '2c');
        $defIntervalo = (int) ($v['intervalo_segundos'] ?? 120);
        $defIfaces   = array_key_exists('interfaces', $v) ? (bool) $v['interfaces'] : true;
        $defActivo   = array_key_exists('activo', $v) ? (bool) $v['activo'] : true;
        $defSitio    = $v['sitio'] ?? null;

        // validate() recorta de cada fila las claves sin regla (sitio, community,
        // tipo, snmp_version... por fila). Se usa el input CRUDO para conservar
        // todas las columnas del CSV; la validación de arriba ya garantizó la
        // estructura (nombre/hostname presentes y límites del lote).
        $filas = $request->input('filas', []);

        // Catálogos en memoria (una sola consulta cada uno; nada por fila).
        $tipos  = DB::table('tipos_recurso')->pluck('id', 'codigo'); // codigo => id
        $sitios = [];
        foreach (DB::table('sitios')->get(['id', 'nombre']) as $s) {
            $sitios[mb_strtolower(trim($s->nombre))] = $s->id;
        }
        // Hostnames existentes (para UPSERT) -> id.
        $existentes = [];
        foreach (DB::table('recursos')->whereNotNull('hostname')->get(['id', 'hostname']) as $r) {
            $existentes[mb_strtolower(trim($r->hostname))] = $r->id;
        }

        $creados = 0; $actualizados = 0; $errores = [];

        foreach ($filas as $i => $fila) {
            $linea = $i + 1;
            try {
                $nombre = trim((string) $fila['nombre']);
                $hostname = trim((string) $fila['hostname']);

                // Tipo.
                $tipoCodigo = trim((string) ($fila['tipo'] ?? $defTipo));
                if (! isset($tipos[$tipoCodigo])) {
                    throw new \RuntimeException("tipo desconocido '$tipoCodigo'");
                }
                $tipoId = (int) $tipos[$tipoCodigo];

                // Sitio (opcional). Si se da un nombre y no existe -> error (probable typo).
                $sitioId = null;
                $sitioNom = trim((string) ($fila['sitio'] ?? $defSitio ?? ''));
                if ($sitioNom !== '') {
                    $k = mb_strtolower($sitioNom);
                    if (! isset($sitios[$k])) {
                        throw new \RuntimeException("sitio desconocido '$sitioNom'");
                    }
                    $sitioId = (int) $sitios[$k];
                }
                // Alcance: un operador acotado no puede importar fuera de sus sitios.
                if (! Alcance::permiteSitio($sitioId)) {
                    throw new \RuntimeException('sitio fuera de su alcance');
                }

                // SNMP: community (fila o default) obligatoria para medir por SNMP.
                $comm = trim((string) ($fila['community'] ?? $defComm ?? ''));
                if ($comm === '') {
                    throw new \RuntimeException('falta community SNMP');
                }
                $ver = $this->normVer((string) ($fila['snmp_version'] ?? $defVer));
                $intervalo = (int) ($fila['intervalo_segundos'] ?? $defIntervalo);
                $ifaces = array_key_exists('interfaces', $fila) ? (bool) $fila['interfaces'] : $defIfaces;

                // Georreferenciación (opcional): coma decimal tolerada ("4,6" -> 4.6).
                $lat = $this->coord($fila['latitud'] ?? null, -90, 90);
                $lon = $this->coord($fila['longitud'] ?? null, -180, 180);

                $parametros = ['metodo' => 'snmp', 'snmp_version' => $ver, 'interfaces' => $ifaces];
                $datos = [
                    'tipo_id'            => $tipoId,
                    'sitio_id'           => $sitioId,
                    'nombre'             => $nombre,
                    'hostname'           => $hostname,
                    'descripcion'        => isset($fila['descripcion']) ? trim((string) $fila['descripcion']) : null,
                    'parametros'         => $parametros,
                    'intervalo_segundos' => $intervalo,
                    'activo'             => $defActivo,
                    'latitud'            => $lat,
                    'longitud'           => $lon,
                ];

                $k = mb_strtolower($hostname);
                if (isset($existentes[$k])) {
                    $recurso = Recurso::find($existentes[$k]);
                    $recurso->fill($datos);
                    $recurso->setSecretosPlanos(['snmp_community' => $comm]);
                    $recurso->save();
                    $actualizados++;
                } else {
                    $recurso = new Recurso($datos);
                    $recurso->setSecretosPlanos(['snmp_community' => $comm]);
                    $recurso->save();
                    $existentes[$k] = $recurso->id; // evita duplicar si el hostname se repite en el CSV
                    $creados++;
                }
            } catch (\Throwable $e) {
                $errores[] = [
                    'fila'   => $linea,
                    'nombre' => (string) ($fila['nombre'] ?? ''),
                    'error'  => $e->getMessage(),
                ];
            }
        }

        return response()->json([
            'total'        => count($filas),
            'creados'      => $creados,
            'actualizados' => $actualizados,
            'con_error'    => count($errores),
            'errores'      => array_slice($errores, 0, 200), // tope para no devolver miles
        ]);
    }

    /** Coordenada opcional: null si vacía; tolera coma decimal; valida el rango. */
    private function coord($v, float $min, float $max): ?float
    {
        if ($v === null || trim((string) $v) === '') {
            return null;
        }
        $n = (float) str_replace(',', '.', trim((string) $v));
        if ($n < $min || $n > $max) {
            throw new \RuntimeException('coordenada fuera de rango');
        }
        return $n;
    }

    /** Normaliza la versión SNMP a '2c' o 'v3' como espera el worker. */
    private function normVer(string $v): string
    {
        $v = strtolower(trim($v));
        return in_array($v, ['3', 'v3'], true) ? 'v3' : '2c';
    }
}
