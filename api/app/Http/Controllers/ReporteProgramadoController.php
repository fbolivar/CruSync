<?php

namespace App\Http\Controllers;

use App\Models\ReporteProgramado;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;
use Illuminate\Validation\ValidationException;

/**
 * Reportes de disponibilidad/SLA programados. El worker los genera (PDF/CSV) y
 * los envía por correo según su periodicidad; aquí solo se gestionan.
 */
class ReporteProgramadoController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        return response()->json(
            ReporteProgramado::query()->orderBy('id')->paginate($this->perPage($request))
        );
    }

    public function show(int $id): JsonResponse
    {
        return response()->json(ReporteProgramado::findOrFail($id));
    }

    public function store(Request $request): JsonResponse
    {
        $data = $request->validate($this->rules());
        $data['destinatarios'] = $this->normalizarDestinatarios($data['destinatarios']);

        return response()->json(ReporteProgramado::create($data), 201);
    }

    public function update(Request $request, int $id): JsonResponse
    {
        $reporte = ReporteProgramado::findOrFail($id);
        $data = $request->validate($this->rules(true));
        if (array_key_exists('destinatarios', $data)) {
            $data['destinatarios'] = $this->normalizarDestinatarios($data['destinatarios']);
        }
        $reporte->update($data);

        return response()->json($reporte);
    }

    public function destroy(int $id): JsonResponse
    {
        ReporteProgramado::findOrFail($id)->delete();

        return response()->json(null, 204);
    }

    private function rules(bool $partial = false): array
    {
        $req = $partial ? 'sometimes' : 'required';

        return [
            'nombre'        => [$req, 'string', 'max:150'],
            'tipo'          => ['nullable', Rule::in(['disponibilidad', 'sla', 'banda', 'alertas'])],
            'periodo'       => [$req, Rule::in(['diario', 'semanal', 'mensual'])],
            'rango'         => [$req, Rule::in(['24h', '7d', '30d'])],
            'destinatarios' => [$req, 'string', 'max:1000'],
            'formato'       => ['nullable', Rule::in(['pdf', 'csv'])],
            'activo'        => ['boolean'],
            // Filtro opcional del informe (null = todos los recursos).
            'tipo_id'       => ['nullable', 'integer', 'exists:tipos_recurso,id'],
            'sitio_id'      => ['nullable', 'integer', 'exists:sitios,id'],
        ];
    }

    /** Limpia y valida la lista de correos separada por comas. */
    private function normalizarDestinatarios(string $valor): string
    {
        $correos = array_filter(array_map('trim', explode(',', $valor)));
        if (empty($correos)) {
            throw ValidationException::withMessages(['destinatarios' => ['Indica al menos un correo.']]);
        }
        foreach ($correos as $c) {
            if (! filter_var($c, FILTER_VALIDATE_EMAIL)) {
                throw ValidationException::withMessages(['destinatarios' => ["Correo inválido: $c"]]);
            }
        }

        return implode(', ', $correos);
    }
}
