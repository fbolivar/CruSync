<?php

namespace App\Http\Controllers;

use App\Support\Alcance;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\DB;

/**
 * Datos para el mapa geográfico (ligero, pensado para miles de enlaces). Devuelve
 * cada recurso activo con su estado y coordenadas PROPIAS (si las tiene), más las
 * sedes con sus coordenadas. El frontend ubica cada enlace en su punto; si el
 * recurso no tiene coords propias, cae a las de su sede. Respeta el alcance del
 * usuario (un perfil acotado solo ve sus sedes).
 */
class MapaController extends Controller
{
    public function index(): JsonResponse
    {
        $alc = Alcance::sitios(); // array de sitio_id permitidos, o null = todos

        $sitios = DB::table('sitios')
            ->when($alc !== null, fn ($q) => $q->whereIn('id', $alc ?: [-1]))
            ->orderBy('nombre')
            ->get(['id', 'nombre', 'latitud', 'longitud']);

        $enlaces = DB::table('recursos as r')
            ->join('tipos_recurso as t', 't.id', '=', 'r.tipo_id')
            ->where('r.activo', true)
            ->when($alc !== null, fn ($q) => $q->whereIn('r.sitio_id', $alc ?: [-1]))
            ->orderBy('r.nombre')
            ->get([
                'r.id', 'r.nombre', 't.codigo as tipo_codigo', 'r.sitio_id',
                'r.estado_actual', 'r.latitud', 'r.longitud',
            ]);

        return response()->json(['sitios' => $sitios, 'enlaces' => $enlaces]);
    }
}
