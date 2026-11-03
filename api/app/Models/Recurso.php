<?php

namespace App\Models;

use App\Models\Concerns\TieneSecretos;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Recurso extends Model
{
    use TieneSecretos;

    protected $table = 'recursos';

    // `secretos` NO es asignable de forma masiva; se maneja vía setSecretosPlanos().
    // `estado_actual`/`ultimo_chequeo_at` los escriben los workers, no la API de gestión.
    protected $fillable = [
        'tipo_id', 'sitio_id', 'nombre', 'hostname', 'descripcion',
        'parametros', 'intervalo_segundos', 'activo', 'depende_de_id',
        'max_check_attempts',
        // Objetivo de disponibilidad % (pisa al del tipo; NULL = hereda).
        'sla_objetivo',
        // Georreferenciación propia del recurso (NULL = usa la de su sede).
        'latitud', 'longitud',
    ];

    // La columna binaria cifrada nunca se serializa.
    protected $hidden = ['secretos'];

    protected $casts = [
        'parametros'         => 'array',
        'intervalo_segundos' => 'integer',
        'activo'             => 'boolean',
        'ultimo_chequeo_at'  => 'datetime',
        'max_check_attempts' => 'integer',
        'intentos_estado'    => 'integer',
        'latitud'            => 'float',
        'longitud'           => 'float',
    ];

    protected $attributes = [
        'parametros' => '{}',
    ];

    public function tipo(): BelongsTo
    {
        return $this->belongsTo(TipoRecurso::class, 'tipo_id');
    }

    public function sitio(): BelongsTo
    {
        return $this->belongsTo(Sitio::class, 'sitio_id');
    }

    public function dependeDe(): BelongsTo
    {
        return $this->belongsTo(Recurso::class, 'depende_de_id');
    }

    public function chequeos(): HasMany
    {
        return $this->hasMany(Chequeo::class, 'recurso_id');
    }

    public function metricas(): HasMany
    {
        return $this->hasMany(Metrica::class, 'recurso_id');
    }

    public function incidencias(): HasMany
    {
        return $this->hasMany(Incidencia::class, 'recurso_id');
    }

    public function umbrales(): HasMany
    {
        return $this->hasMany(Umbral::class, 'recurso_id');
    }
}
