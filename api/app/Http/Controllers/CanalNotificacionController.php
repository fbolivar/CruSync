<?php

namespace App\Http\Controllers;

use App\Models\CanalNotificacion;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

class CanalNotificacionController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        $q = CanalNotificacion::query();

        if ($request->filled('tipo')) {
            $q->where('tipo', $request->query('tipo'));
        }
        if ($request->filled('activo')) {
            $q->where('activo', $request->boolean('activo'));
        }

        return response()->json($q->orderBy('nombre')->paginate($this->perPage($request)));
    }

    public function show(int $id): JsonResponse
    {
        $canal = CanalNotificacion::findOrFail($id);
        $data = $canal->toArray();
        $data['tiene_secretos'] = $canal->tieneSecretos();

        return response()->json($data);
    }

    public function store(Request $request): JsonResponse
    {
        $data = $request->validate($this->rules());
        $secretos = $data['secretos'] ?? null;
        unset($data['secretos']);

        $canal = new CanalNotificacion($data);
        if ($request->has('secretos')) {
            $canal->setSecretosPlanos($secretos);
        }
        $canal->save();

        return response()->json($canal, 201);
    }

    public function update(Request $request, int $id): JsonResponse
    {
        $canal = CanalNotificacion::findOrFail($id);
        $data = $request->validate($this->rules(true));

        if ($request->has('secretos')) {
            $canal->setSecretosPlanos($data['secretos'] ?? null);
        }
        unset($data['secretos']);

        $canal->update($data);

        return response()->json($canal);
    }

    public function destroy(int $id): JsonResponse
    {
        CanalNotificacion::findOrFail($id)->delete();

        return response()->json(null, 204);
    }

    private function rules(bool $partial = false): array
    {
        $req = $partial ? 'sometimes' : 'required';

        return [
            'tipo'     => [$req, Rule::in(['email', 'sms', 'webhook', 'slack', 'telegram', 'teams', 'whatsapp', 'glpi'])],
            'nombre'   => [$req, 'string', 'max:255'],
            'config'   => ['nullable', 'array'],
            'activo'   => ['boolean'],
            'secretos' => ['nullable', 'array'],

            // Enrutamiento del canal (todo opcional; vacío = sin filtro). Se valida
            // porque un typo aquí NO da error visible: simplemente el canal dejaría
            // de recibir alertas en silencio.
            'config.min_severidad'  => ['nullable', Rule::in(['info', 'warning', 'critical'])],
            'config.tipos'          => ['nullable', 'array'],
            'config.tipos.*'        => ['string', 'exists:tipos_recurso,codigo'],
            'config.sitios'         => ['nullable', 'array'],
            'config.sitios.*'       => ['integer', 'exists:sitios,id'],
            'config.horario'        => ['nullable', 'array'],
            'config.horario.dias'   => ['nullable', 'array'],
            'config.horario.dias.*' => ['integer', 'between:1,7'],
            'config.horario.desde'  => ['nullable', 'date_format:H:i'],
            'config.horario.hasta'  => ['nullable', 'date_format:H:i'],
        ];
    }
}
