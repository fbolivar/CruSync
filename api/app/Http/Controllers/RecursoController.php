<?php

namespace App\Http\Controllers;

use App\Models\Recurso;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\ValidationException;
use App\Support\Alcance;

class RecursoController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        // Alcance: un perfil acotado solo ve los recursos de SUS sitios.
        $q = Alcance::filtrarPorSitio(Recurso::query())->with([
            'tipo:id,codigo,nombre', 'sitio:id,codigo,nombre', 'dependeDe:id,nombre',
        ]);

        if ($request->filled('tipo_id')) {
            $q->where('tipo_id', $request->integer('tipo_id'));
        }
        if ($request->filled('sitio_id')) {
            $q->where('sitio_id', $request->integer('sitio_id'));
        }
        if ($request->filled('estado')) {
            $q->where('estado_actual', $request->query('estado'));
        }
        if ($request->filled('activo')) {
            $q->where('activo', $request->boolean('activo'));
        }
        if ($request->filled('buscar')) {
            $term = '%'.$request->query('buscar').'%';
            $q->where(fn ($w) => $w->where('nombre', 'ilike', $term)->orWhere('hostname', 'ilike', $term));
        }

        return response()->json($q->orderBy('nombre')->paginate($this->perPage($request)));
    }

    public function show(int $id): JsonResponse
    {
        $this->exigirAlcance($id);
        $recurso = Recurso::with(['tipo', 'sitio', 'dependeDe:id,nombre'])->findOrFail($id);

        // Informa SI hay secretos, sin exponerlos nunca.
        $data = $recurso->toArray();
        $data['tiene_secretos'] = $recurso->tieneSecretos();

        return response()->json($data);
    }

    /** Snapshot de interfaces de red (IF-MIB) del recurso, si las monitorea. */
    public function interfaces(int $id): JsonResponse
    {
        $this->exigirAlcance($id);
        Recurso::findOrFail($id);

        $rows = DB::table('interfaces')
            ->where('recurso_id', $id)
            ->orderBy('if_index')
            ->get();

        return response()->json($rows);
    }

    /**
     * Configura una interfaz (admin/operador): marca para alertar y/o fija el
     * umbral de utilización (% de ancho de banda) propio de esa interfaz.
     * Todos los campos son opcionales; un umbral en null = usar el umbral global
     * del worker (IF_UTIL_WARNING / IF_UTIL_CRITICAL).
     */
    public function actualizarInterfaz(Request $request, int $id, int $ifIndex): JsonResponse
    {
        $this->exigirAlcance($id);
        $data = $request->validate([
            'monitorear'           => ['sometimes', 'boolean'],
            'umbral_util_warning'  => ['sometimes', 'nullable', 'numeric', 'min:0', 'max:100'],
            'umbral_util_critical' => ['sometimes', 'nullable', 'numeric', 'min:0', 'max:100'],
        ]);
        Recurso::findOrFail($id);

        if (empty($data)) {
            return response()->json(['message' => 'Nada que actualizar.'], 422);
        }
        // Coherencia: si vienen ambos umbrales, el crítico no puede ser menor al warning.
        $w = $data['umbral_util_warning'] ?? null;
        $c = $data['umbral_util_critical'] ?? null;
        if ($w !== null && $c !== null && $c < $w) {
            return response()->json(
                ['message' => 'El umbral crítico no puede ser menor que el de warning.'], 422);
        }

        $afectadas = DB::table('interfaces')
            ->where('recurso_id', $id)->where('if_index', $ifIndex)
            ->update($data);

        if ($afectadas === 0) {
            return response()->json(['message' => 'Interfaz no encontrada.'], 404);
        }

        return response()->json($data);
    }

    /** Versiones de configuración respaldadas del recurso (sin contenido). */
    public function respaldos(int $id): JsonResponse
    {
        $this->exigirAlcance($id);
        Recurso::findOrFail($id);
        $rows = DB::table('config_respaldos')
            ->where('recurso_id', $id)
            ->orderByDesc('ts')
            ->get(['id', 'ts', 'bytes', 'cambio']);

        return response()->json($rows);
    }

    /** Contenido (y diff) de una versión de configuración. */
    public function respaldoContenido(int $id, int $respaldoId): JsonResponse
    {
        $this->exigirAlcance($id);
        $row = DB::table('config_respaldos')
            ->where('recurso_id', $id)->where('id', $respaldoId)
            ->first(['id', 'ts', 'bytes', 'cambio', 'diff', 'contenido']);
        abort_unless($row, 404);

        return response()->json($row);
    }

    /** Hardware físico (Redfish/IPMI): inventario + componentes, sondeado por el worker. */
    public function hardware(int $id): JsonResponse
    {
        $this->exigirAlcance($id);
        Recurso::findOrFail($id);

        $inventario = DB::table('hardware_inventario')->where('recurso_id', $id)->first();
        $componentes = DB::table('hardware_componentes')
            ->where('recurso_id', $id)
            ->orderByRaw("CASE estado WHEN 'down' THEN 0 WHEN 'degraded' THEN 1 WHEN 'unknown' THEN 2 ELSE 3 END")
            ->orderBy('categoria')->orderBy('nombre')
            ->get(['categoria', 'nombre', 'estado', 'lectura', 'unidad', 'detalle', 'actualizado_at']);

        $componentes->transform(function ($c) {
            $c->detalle = $c->detalle ? json_decode($c->detalle) : null;

            return $c;
        });

        return response()->json([
            'inventario'  => $inventario,
            'componentes' => $componentes,
        ]);
    }

    /** Vecinos LLDP del switch (topología L2), recolectados por el worker. */
    public function vecinos(int $id): JsonResponse
    {
        $this->exigirAlcance($id);
        Recurso::findOrFail($id);

        $rows = DB::table('lldp_vecinos as v')
            ->leftJoin('recursos as rr', 'rr.id', '=', 'v.recurso_remoto_id')
            ->where('v.recurso_id', $id)
            ->orderBy('v.local_port_num')
            ->get([
                'v.local_port', 'v.local_port_num', 'v.remote_sysname', 'v.remote_port',
                'v.remote_chassis', 'v.remote_sysdesc', 'v.remote_mgmt', 'v.recurso_remoto_id',
                'rr.nombre as remoto_nombre', 'v.ts',
            ]);

        return response()->json($rows);
    }

    /** Línea base estacional (media/σ por métrica y hora) calculada por el worker. */
    public function baselines(int $id): JsonResponse
    {
        $this->exigirAlcance($id);
        Recurso::findOrFail($id);

        $rows = DB::table('baselines')
            ->where('recurso_id', $id)
            ->orderBy('metrica')->orderBy('hora')
            ->get(['metrica', 'hora', 'media', 'desviacion', 'muestras', 'actualizado_at']);

        return response()->json($rows);
    }

    /** Histórico de throughput (Mbps in/out) de una interfaz para graficar. */
    public function interfazHistorico(Request $request, int $id, int $ifIndex): JsonResponse
    {
        $this->exigirAlcance($id);
        $rango = $request->query('rango', '24h');
        $segundos = ['1h' => 3600, '24h' => 86400, '7d' => 604800][$rango] ?? 86400;
        $desde = now()->subSeconds($segundos)->toDateTimeString();

        $rows = DB::table('interfaces_historico')
            ->where('recurso_id', $id)->where('if_index', $ifIndex)
            ->where('ts', '>=', $desde)
            ->orderBy('ts')
            ->get(['ts', 'in_mbps', 'out_mbps']);

        return response()->json($rows);
    }

    public function store(Request $request): JsonResponse
    {
        $data = $request->validate($this->rules());
        // Un perfil acotado no puede crear recursos en sitios ajenos.
        if (! Alcance::permiteSitio(isset($data['sitio_id']) ? (int) $data['sitio_id'] : null)) {
            abort(403, 'Fuera de su alcance.');
        }
        $this->validarDependencia(null, $data['depende_de_id'] ?? null);
        $secretos = $data['secretos'] ?? null;
        unset($data['secretos']);

        $recurso = new Recurso($data);
        if ($request->has('secretos')) {
            $recurso->setSecretosPlanos($secretos);
        }
        $recurso->save();

        return response()->json($recurso->fresh(['tipo', 'sitio']), 201);
    }

    public function update(Request $request, int $id): JsonResponse
    {
        $this->exigirAlcance($id);
        $recurso = Recurso::findOrFail($id);
        $data = $request->validate($this->rules(true));

        if (array_key_exists('depende_de_id', $data)) {
            $this->validarDependencia($id, $data['depende_de_id']);
        }

        // Si viene la clave 'secretos' (incluso null), se actualiza el secreto.
        if ($request->has('secretos')) {
            $recurso->setSecretosPlanos($data['secretos'] ?? null);
        }
        unset($data['secretos']);

        $recurso->update($data);

        return response()->json($recurso->fresh(['tipo', 'sitio']));
    }

    public function destroy(int $id): JsonResponse
    {
        $this->exigirAlcance($id);
        Recurso::findOrFail($id)->delete();

        return response()->json(null, 204);
    }

    private function rules(bool $partial = false): array
    {
        $req = $partial ? 'sometimes' : 'required';

        return [
            'tipo_id'            => [$req, 'integer', 'exists:tipos_recurso,id'],
            'sitio_id'           => ['nullable', 'integer', 'exists:sitios,id'],
            'nombre'             => [$req, 'string', 'max:255'],
            'hostname'           => ['nullable', 'string', 'max:255'],
            'descripcion'        => ['nullable', 'string'],
            'parametros'         => ['nullable', 'array'],
            'intervalo_segundos' => ['nullable', 'integer', 'between:5,86400'],
            'activo'             => ['boolean'],
            'depende_de_id'      => ['nullable', 'integer', 'exists:recursos,id'],
            // Confirmaciones SOFT/HARD antes de consolidar un estado malo (NULL = default global).
            'max_check_attempts' => ['nullable', 'integer', 'between:1,10'],
            // Objetivo de disponibilidad % (NULL = hereda el del tipo).
            'sla_objetivo'       => ['nullable', 'numeric', 'between:0,100'],
            // Secretos en claro (jsonb). Se cifran de forma transparente. Nunca se devuelven.
            'secretos'           => ['nullable', 'array'],
        ];
    }

    /**
     * Evita autodependencia y ciclos en la cadena depende_de_id.
     * $id es el recurso que se edita (null al crear); $padreId el padre propuesto.
     */
    private function validarDependencia(?int $id, $padreId): void
    {
        if (!$padreId) {
            return;
        }
        $padreId = (int) $padreId;
        if ($id && $padreId === $id) {
            throw ValidationException::withMessages(
                ['depende_de_id' => 'Un recurso no puede depender de sí mismo.']);
        }

        // Sube por la cadena del padre; si reaparece $id (o se repite un nodo) hay ciclo.
        $actual = $padreId;
        $vistos = [];
        while ($actual && !in_array($actual, $vistos, true)) {
            if ($id && $actual === $id) {
                throw ValidationException::withMessages(
                    ['depende_de_id' => 'La dependencia crearía un ciclo.']);
            }
            $vistos[] = $actual;
            $actual = (int) (DB::table('recursos')->where('id', $actual)->value('depende_de_id') ?? 0);
        }
    }

    /**
     * Corta el acceso a un recurso fuera del alcance del usuario. Se responde 404
     * (no 403) para no confirmar siquiera que el recurso existe.
     */
    private function exigirAlcance(int $id): void
    {
        if (! Alcance::permiteRecurso($id)) {
            abort(404);
        }
    }
}
