"""Capa de acceso a datos: todas las consultas SQL del worker.

Importante: la lógica de negocio (evaluación de estado) vive en evaluacion.py;
aquí solo hay lectura/escritura. Los secretos se descifran con la MISMA función
pgcrypto que usa la API (`descifrar_secreto`), pasando la clave maestra.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from psycopg.types.json import Json

from .db import Database
from .models import Canal, Recurso, Regla, Umbral

log = logging.getLogger(__name__)


# ── Recursos ──────────────────────────────────────────────────────────
_SELECT_RECURSO = """
    SELECT r.id, r.nombre, r.hostname, r.parametros, r.intervalo_segundos,
           r.estado_actual, r.sitio_id, r.depende_de_id,
           r.estado_hard, r.estado_candidato, r.intentos_estado, r.max_check_attempts,
           t.codigo AS tipo_codigo, t.protocolo_default
    FROM recursos r
    JOIN tipos_recurso t ON t.id = r.tipo_id
"""


def _fila_a_recurso(row: dict[str, Any]) -> Recurso:
    return Recurso(
        id=row["id"],
        nombre=row["nombre"],
        hostname=row["hostname"],
        tipo_codigo=row["tipo_codigo"],
        protocolo_default=row["protocolo_default"],
        parametros=row["parametros"] or {},
        intervalo_segundos=row["intervalo_segundos"],
        estado_actual=row["estado_actual"],
        sitio_id=row["sitio_id"],
        depende_de_id=row.get("depende_de_id"),
        estado_hard=row.get("estado_hard") or row["estado_actual"],
        estado_candidato=row.get("estado_candidato") or row["estado_actual"],
        intentos_estado=row.get("intentos_estado") or 0,
        max_check_attempts=row.get("max_check_attempts"),
    )


def ancestro_caido(db: Database, recurso_id: int) -> str | None:
    """Nombre del ancestro (cadena depende_de_id) que está 'down', si lo hay.

    Sube por la cadena de dependencias del recurso; devuelve el nombre del
    ancestro más cercano caído (para suprimir alertas del hijo). El límite de
    nivel evita bucles si hubiera un ciclo en los datos.
    """
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH RECURSIVE cadena AS (
                SELECT id, depende_de_id, estado_actual, nombre, 1 AS nivel
                FROM recursos
                WHERE id = (SELECT depende_de_id FROM recursos WHERE id = %s)
                UNION ALL
                SELECT r.id, r.depende_de_id, r.estado_actual, r.nombre, c.nivel + 1
                FROM recursos r JOIN cadena c ON r.id = c.depende_de_id
                WHERE c.nivel < 20
            )
            SELECT nombre FROM cadena WHERE estado_actual = 'down' ORDER BY nivel LIMIT 1
            """,
            (recurso_id,),
        )
        row = cur.fetchone()
        return row["nombre"] if row else None


def cargar_recursos_activos(db: Database) -> list[Recurso]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO + " WHERE r.activo = true ORDER BY r.id")
        return [_fila_a_recurso(r) for r in cur.fetchall()]


def cargar_recurso(db: Database, recurso_id: int) -> Recurso | None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO + " WHERE r.id = %s AND r.activo = true", (recurso_id,))
        row = cur.fetchone()
        return _fila_a_recurso(row) if row else None


def recursos_por_tipo(db: Database, tipo_codigo: str) -> list[Recurso]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO + " WHERE r.activo = true AND t.codigo = %s ORDER BY r.id",
                    (tipo_codigo,))
        return [_fila_a_recurso(r) for r in cur.fetchall()]


def recursos_switches(db: Database) -> list[Recurso]:
    """Switches activos (LAN/SAN) — candidatos a topología LLDP por SNMP."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO +
                    " WHERE r.activo = true AND t.codigo IN ('switch_lan','switch_san') ORDER BY r.id")
        return [_fila_a_recurso(r) for r in cur.fetchall()]


def guardar_vecinos_lldp(db: Database, recurso_id: int, vecinos: list[dict]) -> None:
    """Reemplaza el snapshot de vecinos LLDP. Resuelve el recurso remoto por IP de
    gestión (hostname del recurso) y, si no, por sysName."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lldp_vecinos WHERE recurso_id = %s", (recurso_id,))
        if vecinos:
            cur.executemany(
                """
                INSERT INTO lldp_vecinos
                    (recurso_id, local_port_num, local_port, remote_sysname, remote_chassis,
                     remote_port, remote_sysdesc, remote_mgmt, recurso_remoto_id, ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        COALESCE(
                          %s::bigint,
                          (SELECT id FROM recursos
                            WHERE split_part(hostname, ':', 1) = %s::text AND %s::text <> ''
                            ORDER BY id LIMIT 1),
                          (SELECT id FROM recursos
                            WHERE lower(nombre) = lower(%s::text)
                            ORDER BY id LIMIT 1)),
                        now())
                """,
                [(recurso_id, v.get("local_port_num"), v.get("local_port"),
                  v.get("remote_sysname"), v.get("remote_chassis"), v.get("remote_port"),
                  v.get("remote_sysdesc"), v.get("remote_mgmt"),
                  v.get("recurso_remoto_id"),
                  v.get("remote_mgmt") or "", v.get("remote_mgmt") or "", v.get("remote_sysname"))
                 for v in vecinos],
            )


def recursos_backup_ssh(db: Database) -> list[Recurso]:
    """Recursos activos que optaron por respaldo de config por SSH (parametros.backup.metodo='ssh')."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO +
                    " WHERE r.activo = true AND r.parametros #>> '{backup,metodo}' = 'ssh' ORDER BY r.id")
        return [_fila_a_recurso(r) for r in cur.fetchall()]


# ── Respaldos de configuración ────────────────────────────────────────
def ultimo_respaldo(db: Database, recurso_id: int) -> dict[str, Any] | None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT hash, contenido FROM config_respaldos WHERE recurso_id = %s ORDER BY ts DESC LIMIT 1",
            (recurso_id,),
        )
        return cur.fetchone()


def guardar_respaldo(db: Database, recurso_id: int, hash_: str, bytes_: int,
                     cambio: bool, diff: str | None, contenido: str) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO config_respaldos (recurso_id, hash, bytes, cambio, diff, contenido)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (recurso_id, hash_, bytes_, cambio, diff, contenido),
        )


def descifrar_secretos(db: Database, recurso_id: int, clave: str) -> dict[str, Any] | None:
    """Descifra los secretos del recurso vía pgcrypto (igual que la API)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT descifrar_secreto(secretos, %s) AS s FROM recursos WHERE id = %s",
            (clave, recurso_id),
        )
        row = cur.fetchone()
        return row["s"] if row and row["s"] is not None else None


# ── Umbrales ──────────────────────────────────────────────────────────
def cargar_umbrales(db: Database, recurso: Recurso) -> list[Umbral]:
    """Umbrales aplicables: específicos del recurso o por tipo. El específico
    de recurso prevalece sobre el de tipo para la misma métrica."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT metrica, operador, valor_warning, valor_critical,
                   duracion_segundos, recurso_id
            FROM umbrales
            WHERE activo = true
              AND (recurso_id = %s OR tipo_id = (
                    SELECT tipo_id FROM recursos WHERE id = %s))
            ORDER BY (recurso_id IS NOT NULL) DESC
            """,
            (recurso.id, recurso.id),
        )
        vistos: set[str] = set()
        umbrales: list[Umbral] = []
        for r in cur.fetchall():
            if r["metrica"] in vistos:  # ya hay uno específico de recurso
                continue
            vistos.add(r["metrica"])
            umbrales.append(Umbral(
                metrica=r["metrica"],
                operador=r["operador"],
                valor_warning=r["valor_warning"],
                valor_critical=r["valor_critical"],
                duracion_segundos=r["duracion_segundos"],
            ))
        return umbrales


# ── Reglas (triggers compuestos) ──────────────────────────────────────
def cargar_reglas(db: Database, recurso: Recurso) -> list[Regla]:
    """Reglas activas aplicables: específicas del recurso + las del tipo."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, nombre, descripcion, expresion, severidad, duracion_segundos
            FROM reglas
            WHERE activo = true
              AND (recurso_id = %s OR tipo_id = (
                    SELECT tipo_id FROM recursos WHERE id = %s))
            ORDER BY id
            """,
            (recurso.id, recurso.id),
        )
        return [
            Regla(
                id=r["id"],
                nombre=r["nombre"],
                expresion=r["expresion"] or {},
                severidad=r["severidad"],
                duracion_segundos=r["duracion_segundos"],
                descripcion=r["descripcion"],
            )
            for r in cur.fetchall()
        ]


# ── Mantenimientos ────────────────────────────────────────────────────
def en_mantenimiento(db: Database, recurso: Recurso, ahora: datetime) -> bool:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM mantenimientos
                WHERE %s BETWEEN inicio AND fin
                  AND (recurso_id = %s
                       OR sitio_id = %s
                       OR (recurso_id IS NULL AND sitio_id IS NULL))
            ) AS m
            """,
            (ahora, recurso.id, recurso.sitio_id),
        )
        return bool(cur.fetchone()["m"])


# ── Chequeos / métricas ───────────────────────────────────────────────
def guardar_chequeo(db: Database, recurso_id: int, estado: str,
                    latencia_ms: float | None, detalle: dict[str, Any],
                    ts: datetime) -> int:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chequeos (recurso_id, ts, estado, latencia_ms, detalle)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (recurso_id, ts, estado,
             int(latencia_ms) if latencia_ms is not None else None,
             Json(detalle)),
        )
        return cur.fetchone()["id"]


def guardar_metricas(db: Database, recurso_id: int,
                     muestras: list[tuple[str, float, str | None]],
                     ts: datetime) -> None:
    if not muestras:
        return
    with db.connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO metricas (recurso_id, metrica, valor, unidad, ts)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (recurso_id, metrica, ts) DO NOTHING
            """,
            [(recurso_id, nombre, valor, unidad, ts) for (nombre, valor, unidad) in muestras],
        )


def guardar_interfaces(db: Database, recurso_id: int, interfaces: list[dict]) -> None:
    """Upsert del snapshot de interfaces y borrado de las que ya no aparecen."""
    if not interfaces:
        return
    indices = [i["if_index"] for i in interfaces]
    with db.connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO interfaces (recurso_id, if_index, if_name, admin_estado, oper_estado,
                                    speed_mbps, in_mbps, out_mbps, util_in, util_out, in_err, out_err, ts)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (recurso_id, if_index) DO UPDATE SET
                if_name = EXCLUDED.if_name, admin_estado = EXCLUDED.admin_estado,
                oper_estado = EXCLUDED.oper_estado, speed_mbps = EXCLUDED.speed_mbps,
                in_mbps = EXCLUDED.in_mbps, out_mbps = EXCLUDED.out_mbps,
                util_in = EXCLUDED.util_in, util_out = EXCLUDED.util_out,
                in_err = EXCLUDED.in_err, out_err = EXCLUDED.out_err, ts = now()
            """,
            [(recurso_id, i["if_index"], i["if_name"], i["admin_estado"], i["oper_estado"],
              i["speed_mbps"], i["in_mbps"], i["out_mbps"], i["util_in"], i["util_out"],
              i["in_err"], i["out_err"]) for i in interfaces],
        )
        # Limpia interfaces que dejaron de estar admin-up (ya no se reportan).
        cur.execute(
            "DELETE FROM interfaces WHERE recurso_id = %s AND NOT (if_index = ANY(%s))",
            (recurso_id, indices),
        )


def guardar_interfaces_historico(db: Database, recurso_id: int, interfaces: list[dict]) -> None:
    """Inserta el throughput de las interfaces oper-up (con dato) para histórico/gráficas."""
    filas = [(recurso_id, i["if_index"], i["in_mbps"], i["out_mbps"])
             for i in interfaces
             if i["oper_estado"] == "up" and (i["in_mbps"] is not None or i["out_mbps"] is not None)]
    if not filas:
        return
    with db.connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO interfaces_historico (recurso_id, if_index, in_mbps, out_mbps, ts) "
            "VALUES (%s, %s, %s, %s, now())",
            filas,
        )


def nombre_interfaz(db: Database, recurso_id: int, if_index: int) -> str | None:
    """Nombre de una interfaz ya descubierta (snapshot), si existe."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT if_name FROM interfaces WHERE recurso_id = %s AND if_index = %s",
            (recurso_id, if_index),
        )
        row = cur.fetchone()
        return row["if_name"] if row else None


def interfaces_monitoreadas(db: Database, recurso_id: int) -> list[dict[str, Any]]:
    """Interfaces marcadas para alertar (monitorear=true) con su estado oper actual,
    su utilización/errores del último snapshot y el override de umbral por interfaz."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT if_index, if_name, oper_estado, util_in, util_out, in_err, out_err, "
            "       umbral_util_warning, umbral_util_critical "
            "FROM interfaces WHERE recurso_id = %s AND monitorear = true",
            (recurso_id,),
        )
        return cur.fetchall()


def incidencia_interfaz_abierta(db: Database, recurso_id: int, if_index: int,
                                componente: str | None = None) -> dict[str, Any] | None:
    """Incidencia de interfaz NO resuelta. `componente` distingue link-down (NULL)
    de saturación de banda ('saturacion') en el mismo puerto; se compara con
    IS NOT DISTINCT FROM para que NULL case con NULL."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, severidad FROM incidencias "
            "WHERE recurso_id = %s AND if_index = %s "
            "AND componente IS NOT DISTINCT FROM %s AND estado <> 'resuelta' LIMIT 1",
            (recurso_id, if_index, componente),
        )
        return cur.fetchone()


def abrir_incidencia_interfaz(db: Database, recurso_id: int, if_index: int, if_nombre: str,
                              severidad: str, titulo: str, descripcion: str | None,
                              ahora: datetime, componente: str | None = None) -> int | None:
    """Abre una incidencia de interfaz. El índice único
    (recurso, COALESCE(if_index,-1), COALESCE(componente,'')) evita duplicados y
    permite coexistir link-down (componente NULL) y saturación ('saturacion')."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incidencias
                (recurso_id, if_index, if_nombre, componente, estado, severidad,
                 titulo, descripcion, abierta_at)
            VALUES (%s, %s, %s, %s, 'abierta', %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (recurso_id, if_index, if_nombre, componente, severidad, titulo, descripcion, ahora),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def actualizar_estado_recurso(db: Database, recurso_id: int, estado: str, ts: datetime,
                              estado_hard: str | None = None, estado_candidato: str | None = None,
                              intentos: int | None = None) -> None:
    """Persiste el estado del recurso. Si se pasan los campos SOFT/HARD, también
    actualiza la máquina de confirmación (estado_hard/candidato/intentos)."""
    with db.connection() as conn, conn.cursor() as cur:
        if estado_hard is None:
            cur.execute(
                "UPDATE recursos SET estado_actual = %s, ultimo_chequeo_at = %s WHERE id = %s",
                (estado, ts, recurso_id),
            )
        else:
            cur.execute(
                "UPDATE recursos SET estado_actual = %s, ultimo_chequeo_at = %s, "
                "estado_hard = %s, estado_candidato = %s, intentos_estado = %s WHERE id = %s",
                (estado, ts, estado_hard, estado_candidato, intentos, recurso_id),
            )


def subredes_mpls(db: Database) -> list[tuple[str, int]]:
    """[(subred, recurso_id)] de los recursos opt-in al probe MPLS (metodo='mpls')."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, parametros->>'subred' AS subred FROM recursos "
            "WHERE activo AND parametros->>'metodo' = 'mpls' "
            "AND parametros->>'subred' IS NOT NULL"
        )
        return [(r["subred"], r["id"]) for r in cur.fetchall()]


def guardar_mpls_actividad(db: Database, activas: dict[str, int]) -> None:
    """Upsert de la actividad por subred (ultimo_activo=now) para las que tienen tráfico."""
    if not activas:
        return
    filas = [(subred, n) for subred, n in activas.items()]
    with db.connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO mpls_actividad (subred, ultimo_activo, ips_activas) "
            "VALUES (%s, now(), %s) "
            "ON CONFLICT (subred) DO UPDATE SET ultimo_activo = now(), ips_activas = EXCLUDED.ips_activas",
            filas,
        )


def cargar_mpls_actividad(db: Database) -> list[tuple[str, float]]:
    """[(subred, epoch)] para sembrar la caché del probe al arrancar el worker."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT subred, extract(epoch FROM ultimo_activo) AS e FROM mpls_actividad")
        return [(r["subred"], float(r["e"])) for r in cur.fetchall()]


def marcar_recursos_obsoletos(db: Database, factor: int, piso_seg: int,
                              sitios: list[int] | None = None) -> list[dict[str, Any]]:
    """Freshness/stale-data: marca 'unknown' (HARD) los recursos activos cuyo último
    chequeo es más viejo que max(factor×intervalo, piso_seg). Cubre el punto ciego de
    un job muerto o un recurso que dejó de responder sin disparar 'down'.

    Devuelve los recursos recién marcados (no re-marca los que ya estaban unknown HARD).
    No toca recursos en mantenimiento. Respeta el filtro de pollers distribuidos.
    """
    filtro_sitio = ""
    params: list[Any] = [factor, piso_seg]
    if sitios:
        filtro_sitio = " AND r.sitio_id = ANY(%s)"
        params.append(sitios)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            WITH obsoletos AS (
                SELECT r.id
                FROM recursos r
                WHERE r.activo = true
                  AND r.estado_hard <> 'maintenance'
                  AND r.estado_hard <> 'unknown'
                  AND r.ultimo_chequeo_at IS NOT NULL
                  AND r.ultimo_chequeo_at <
                      now() - make_interval(secs => GREATEST(r.intervalo_segundos * %s, %s))
                  {filtro_sitio}
                FOR UPDATE OF r SKIP LOCKED
            )
            UPDATE recursos r
            SET estado_actual = 'unknown', estado_hard = 'unknown',
                estado_candidato = 'unknown', intentos_estado = 0
            FROM obsoletos o
            WHERE r.id = o.id
            RETURNING r.id, r.nombre, r.ultimo_chequeo_at
            """,
            params,
        )
        return cur.fetchall()


# ── Incidencias ───────────────────────────────────────────────────────
def incidencia_abierta(db: Database, recurso_id: int) -> dict[str, Any] | None:
    """Incidencia abierta DEL RECURSO (no las de interfaz/componente, que llevan if_index/componente)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, severidad, estado FROM incidencias "
            "WHERE recurso_id = %s AND if_index IS NULL AND componente IS NULL "
            "AND estado <> 'resuelta' LIMIT 1",
            (recurso_id,),
        )
        return cur.fetchone()


# ── Incidencias por componente de hardware ────────────────────────────
def incidencia_componente_abierta(db: Database, recurso_id: int, componente: str) -> dict[str, Any] | None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, severidad FROM incidencias "
            "WHERE recurso_id = %s AND componente = %s AND estado <> 'resuelta' LIMIT 1",
            (recurso_id, componente),
        )
        return cur.fetchone()


def incidencias_componente_abiertas(db: Database, recurso_id: int) -> list[dict[str, Any]]:
    """Incidencias de componente de hardware abiertas del recurso."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, componente, severidad FROM incidencias "
            "WHERE recurso_id = %s AND componente IS NOT NULL AND estado <> 'resuelta'",
            (recurso_id,),
        )
        return cur.fetchall()


def abrir_incidencia_componente(db: Database, recurso_id: int, componente: str, severidad: str,
                                titulo: str, descripcion: str | None, ahora: datetime) -> int | None:
    """Abre una incidencia de componente. El índice único (recurso, -, componente) evita duplicados."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incidencias
                (recurso_id, componente, estado, severidad, titulo, descripcion, abierta_at)
            VALUES (%s, %s, 'abierta', %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (recurso_id, componente, severidad, titulo, descripcion, ahora),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def inicio_racha_no_up(db: Database, recurso_id: int, ahora: datetime) -> datetime:
    """Timestamp del primer chequeo de la racha actual de estados != up/maintenance.

    Sirve para respetar `duracion_segundos` (anti-flapping) antes de abrir
    una incidencia. Si no hay racha previa, devuelve `ahora`.
    """
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT min(ts) AS inicio FROM chequeos
            WHERE recurso_id = %s
              AND ts > COALESCE(
                    (SELECT max(ts) FROM chequeos
                     WHERE recurso_id = %s AND estado IN ('up', 'maintenance')),
                    '-infinity'::timestamptz)
            """,
            (recurso_id, recurso_id),
        )
        row = cur.fetchone()
        return row["inicio"] if row and row["inicio"] is not None else ahora


def ultimo_ha_primary(db: Database, recurso_id: int) -> str | None:
    """Primario del clúster en el último chequeo (para detectar failover)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT detalle->>'ha_primary' AS p FROM chequeos "
            "WHERE recurso_id = %s AND detalle ? 'ha_primary' "
            "ORDER BY ts DESC LIMIT 1",
            (recurso_id,),
        )
        row = cur.fetchone()
        return row["p"] if row and row["p"] is not None else None


def abrir_incidencia(db: Database, recurso_id: int, severidad: str, titulo: str,
                     descripcion: str | None, chequeo_id: int, ahora: datetime) -> int | None:
    """Abre una incidencia. El índice único parcial garantiza una sola abierta
    por recurso; ante conflicto, no hace nada."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incidencias
                (recurso_id, estado, severidad, titulo, descripcion,
                 chequeo_apertura_id, abierta_at)
            VALUES (%s, 'abierta', %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (recurso_id, severidad, titulo, descripcion, chequeo_id, ahora),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def actualizar_severidad_incidencia(db: Database, incidencia_id: int, severidad: str) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE incidencias SET severidad = %s WHERE id = %s",
            (severidad, incidencia_id),
        )


def cerrar_incidencia(db: Database, incidencia_id: int, ahora: datetime) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE incidencias SET estado = 'resuelta', resuelta_at = %s WHERE id = %s",
            (ahora, incidencia_id),
        )


def incidencias_para_escalar(db: Database, minutos: int) -> list[dict[str, Any]]:
    """Incidencias 'abierta' (no reconocidas), más viejas que `minutos` y sin escalar."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.id, i.severidad, i.titulo, i.if_nombre,
                   r.id AS rid, r.nombre, r.hostname, t.codigo AS tipo_codigo
            FROM incidencias i
            JOIN recursos r ON r.id = i.recurso_id
            JOIN tipos_recurso t ON t.id = r.tipo_id
            WHERE i.estado = 'abierta'
              AND i.escalada_at IS NULL
              AND i.abierta_at < now() - make_interval(mins => %s)
            """,
            (minutos,),
        )
        return cur.fetchall()


def marcar_escalada(db: Database, incidencia_id: int, ahora: datetime) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE incidencias SET escalada_at = %s WHERE id = %s", (ahora, incidencia_id))


# ── SNMP traps ────────────────────────────────────────────────────────
def recurso_id_por_host(db: Database, ip: str) -> int | None:
    # Empareja por la IP ignorando el puerto del hostname (p.ej. '192.168.50.1:25443'
    # del API FortiGate). Útil para vincular exportadores NetFlow y traps al recurso.
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM recursos WHERE split_part(hostname, ':', 1) = %s ORDER BY id LIMIT 1",
            (ip,),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def guardar_trap(db: Database, source_ip: str | None, recurso_id: int | None, trap_oid: str | None,
                 nombre: str | None, severidad: str, descripcion: str | None,
                 varbinds: dict) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO traps (source_ip, recurso_id, trap_oid, nombre, severidad, descripcion, varbinds)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (source_ip, recurso_id, trap_oid, nombre, severidad, descripcion, Json(varbinds)),
        )


# ── Hardware físico (Redfish / IPMI) ──────────────────────────────────
def recursos_hardware(db: Database) -> list[Recurso]:
    """Recursos activos que optaron por monitoreo de hardware (parametros.hardware)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO +
                    " WHERE r.activo = true AND r.parametros ? 'hardware' ORDER BY r.id")
        return [_fila_a_recurso(r) for r in cur.fetchall()]


def estados_hardware_previos(db: Database, recurso_id: int) -> dict[tuple[str, str], str]:
    """Mapa {(categoria, nombre): estado} del snapshot actual, para comparar cambios."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT categoria, nombre, estado FROM hardware_componentes WHERE recurso_id = %s",
            (recurso_id,),
        )
        return {(r["categoria"], r["nombre"]): r["estado"] for r in cur.fetchall()}


def guardar_hardware_componentes(db: Database, recurso_id: int, comps: list[dict]) -> None:
    """Reemplaza el snapshot de componentes del recurso (borra + inserta, atómico)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM hardware_componentes WHERE recurso_id = %s", (recurso_id,))
        if comps:
            cur.executemany(
                """
                INSERT INTO hardware_componentes
                    (recurso_id, categoria, nombre, estado, lectura, unidad, detalle, actualizado_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                """,
                [(recurso_id, c["categoria"], c["nombre"], c["estado"], c.get("lectura"),
                  c.get("unidad"), Json(c.get("detalle") or {})) for c in comps],
            )


def guardar_hardware_inventario(db: Database, recurso_id: int, inv: dict) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO hardware_inventario
                (recurso_id, fabricante, modelo, serial, sku, bios_version, bmc_firmware,
                 cpu_modelo, cpu_cantidad, memoria_gb, power_state, salud_global, protocolo,
                 detalle, actualizado_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (recurso_id) DO UPDATE SET
                fabricante = EXCLUDED.fabricante, modelo = EXCLUDED.modelo,
                serial = EXCLUDED.serial, sku = EXCLUDED.sku,
                bios_version = EXCLUDED.bios_version, bmc_firmware = EXCLUDED.bmc_firmware,
                cpu_modelo = EXCLUDED.cpu_modelo, cpu_cantidad = EXCLUDED.cpu_cantidad,
                memoria_gb = EXCLUDED.memoria_gb, power_state = EXCLUDED.power_state,
                salud_global = EXCLUDED.salud_global, protocolo = EXCLUDED.protocolo,
                detalle = EXCLUDED.detalle, actualizado_at = now()
            """,
            (recurso_id, inv.get("fabricante"), inv.get("modelo"), inv.get("serial"),
             inv.get("sku"), inv.get("bios_version"), inv.get("bmc_firmware"),
             inv.get("cpu_modelo"), inv.get("cpu_cantidad"), inv.get("memoria_gb"),
             inv.get("power_state"), inv.get("salud_global"), inv.get("protocolo"),
             Json(inv.get("detalle") or {})),
        )


# ── Auto-descubrimiento de red ────────────────────────────────────────
def escaneos_pendientes(db: Database, clave: str) -> list[dict[str, Any]]:
    """Escaneos en cola, con la community SNMP ya descifrada."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, subred, snmp_version, descifrar_secreto(secretos, %s) AS secretos "
            "FROM descubrimiento_escaneos WHERE estado = 'pendiente' ORDER BY id",
            (clave,),
        )
        return cur.fetchall()


def marcar_escaneo(db: Database, escaneo_id: int, estado: str, mensaje: str | None = None) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE descubrimiento_escaneos SET estado = %s, mensaje = COALESCE(%s, mensaje) WHERE id = %s",
            (estado, mensaje, escaneo_id),
        )


def completar_escaneo(db: Database, escaneo_id: int, vivos: int, candidatos: int) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE descubrimiento_escaneos SET estado='completado', total_vivos=%s, "
            "total_candidatos=%s, completado_at=now() WHERE id=%s",
            (vivos, candidatos, escaneo_id),
        )


def guardar_candidato(db: Database, escaneo_id: int, ip: str, sysname: str | None,
                      sysdescr: str | None, sysobjectid: str | None, tipo: str | None,
                      responde_snmp: bool, latencia_ms: int | None, estado: str,
                      recurso_id: int | None) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO descubrimiento_candidatos
                (escaneo_id, ip, sysname, sysdescr, sysobjectid, tipo_sugerido,
                 responde_snmp, latencia_ms, estado, recurso_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (escaneo_id, ip, sysname, sysdescr, sysobjectid, tipo,
             responde_snmp, latencia_ms, estado, recurso_id),
        )


# ── Mantenimiento de datos (rollup / purga / particiones) ─────────────
def asegurar_particiones(db: Database, fechas: list) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        for f in fechas:
            cur.execute("SELECT fn_crear_particion_metricas(%s)", (f,))


# ── Notificaciones (FASE 5) ───────────────────────────────────────────
def canales_activos(db: Database, clave: str) -> list[Canal]:
    """Canales activos con sus secretos descifrados (igual que la API)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, tipo, nombre, config, descifrar_secreto(secretos, %s) AS secretos "
            "FROM canales_notificacion WHERE activo = true",
            (clave,),
        )
        return [
            Canal(id=r["id"], tipo=r["tipo"], nombre=r["nombre"],
                  config=r["config"] or {}, secretos=r["secretos"])
            for r in cur.fetchall()
        ]


def canal_por_id(db: Database, canal_id: int, clave: str) -> Canal | None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, tipo, nombre, config, descifrar_secreto(secretos, %s) AS secretos "
            "FROM canales_notificacion WHERE id = %s AND activo = true",
            (clave, canal_id),
        )
        r = cur.fetchone()
        return Canal(id=r["id"], tipo=r["tipo"], nombre=r["nombre"],
                     config=r["config"] or {}, secretos=r["secretos"]) if r else None


def ya_notificado(db: Database, incidencia_id: int, canal_id: int, evento: str) -> bool:
    """Dedup por (incidencia, canal, evento): evita reenviar el mismo evento."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM notificaciones "
            "WHERE incidencia_id = %s AND canal_id = %s "
            "AND payload->>'evento' = %s AND estado = 'enviada') AS e",
            (incidencia_id, canal_id, evento),
        )
        return bool(cur.fetchone()["e"])


def apertura_reciente(db: Database, recurso_id: int, cooldown_seg: int) -> bool:
    """Anti-flapping: ¿se envió una 'apertura' para este recurso dentro del cooldown?"""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM notificaciones n
                JOIN incidencias i ON i.id = n.incidencia_id
                WHERE i.recurso_id = %s
                  AND n.payload->>'evento' = 'apertura'
                  AND n.estado = 'enviada'
                  AND n.created_at > now() - make_interval(secs => %s)
            ) AS e
            """,
            (recurso_id, cooldown_seg),
        )
        return bool(cur.fetchone()["e"])


def registrar_notificacion(db: Database, incidencia_id: int, canal_id: int, estado: str,
                           destino: str | None, payload: dict, intentos: int,
                           error: str | None) -> int:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notificaciones
                (incidencia_id, canal_id, estado, destino, payload, intentos, error, enviada_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s = 'enviada' THEN now() ELSE NULL END)
            RETURNING id
            """,
            (incidencia_id, canal_id, estado, destino, Json(payload), intentos, error, estado),
        )
        return cur.fetchone()["id"]


def notificaciones_para_reintentar(db: Database, max_intentos: int) -> list[dict]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, incidencia_id, canal_id, destino, payload, intentos "
            "FROM notificaciones WHERE estado = 'fallida' AND intentos < %s "
            "ORDER BY id LIMIT 100",
            (max_intentos,),
        )
        return cur.fetchall()


def marcar_notificacion(db: Database, notif_id: int, estado: str, error: str | None,
                        intentos: int) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE notificaciones SET estado = %s, error = %s, intentos = %s, "
            "enviada_at = CASE WHEN %s = 'enviada' THEN now() ELSE enviada_at END "
            "WHERE id = %s",
            (estado, error, intentos, estado, notif_id),
        )


def series_capacidad(db: Database, ventana_dias: int) -> dict[tuple, dict]:
    """Series diarias de las métricas de capacidad (disco_*, mem) por recurso.

    Devuelve {(recurso_id, nombre, metrica, unidad): [valor_avg ordenado por día]}
    para alimentar la regresión del forecasting."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id AS recurso_id, r.nombre, d.metrica, d.unidad, d.valor_avg
            FROM metricas_rollup_diario d
            JOIN recursos r ON r.id = d.recurso_id AND r.activo = true
            WHERE d.bucket >= (now() - make_interval(days => %s))::date
              AND d.unidad = '%%'
              AND (d.metrica LIKE 'disco%%' OR d.metrica = 'mem')
            ORDER BY r.id, d.metrica, d.bucket
            """,
            (ventana_dias,),
        )
        series: dict[tuple, list[float]] = {}
        for row in cur.fetchall():
            clave = (row["recurso_id"], row["nombre"], row["metrica"], row["unidad"])
            series.setdefault(clave, []).append(float(row["valor_avg"]))
        return series


def pronostico_dias_previo(db: Database, recurso_id: int, metrica: str) -> float | None:
    """dias_restantes del último pronóstico guardado (para detectar cruces de umbral)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT dias_restantes FROM pronosticos WHERE recurso_id = %s AND metrica = %s",
            (recurso_id, metrica),
        )
        row = cur.fetchone()
        return row["dias_restantes"] if row else None


def guardar_pronostico(db: Database, recurso_id: int, metrica: str, valor_actual: float,
                       pendiente_dia: float, dias_restantes: float | None, techo: float,
                       r2: float | None, muestras: int) -> None:
    """Upsert del último pronóstico por (recurso, métrica)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pronosticos
                (recurso_id, metrica, ts, valor_actual, pendiente_dia, dias_restantes, techo, r2, muestras)
            VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s)
            ON CONFLICT (recurso_id, metrica) DO UPDATE SET
                ts = now(), valor_actual = EXCLUDED.valor_actual,
                pendiente_dia = EXCLUDED.pendiente_dia, dias_restantes = EXCLUDED.dias_restantes,
                techo = EXCLUDED.techo, r2 = EXCLUDED.r2, muestras = EXCLUDED.muestras
            """,
            (recurso_id, metrica, valor_actual, pendiente_dia, dias_restantes, techo, r2, muestras),
        )


def rollup_disponibilidad_diaria(db: Database, dias: int = 2) -> int:
    """Consolida la disponibilidad por recurso y día en `disponibilidad_diaria`.

    Se ejecuta cada noche ANTES de la purga: `chequeos` solo guarda 30 días, así
    que sin esto el histórico de SLA se perdía a diario y era imposible comparar
    meses o sostener un reclamo contractual con evidencia.

    Es IDEMPOTENTE (UPSERT): se puede reprocesar sin duplicar. `dias` es cuánto
    recalcular hacia atrás — 2 en la corrida diaria (por si llegaron chequeos
    tarde) y hasta 31 para rellenar de golpe lo que aún quede en `chequeos`.
    Devuelve el nº de filas (recurso-día) consolidadas.
    """
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH chq AS (
                SELECT recurso_id, ts::date AS dia,
                       count(*) FILTER (WHERE estado = 'up')          AS up,
                       count(*) FILTER (WHERE estado = 'degraded')    AS degraded,
                       count(*) FILTER (WHERE estado = 'down')        AS down,
                       count(*) FILTER (WHERE estado = 'unknown')     AS unknown,
                       count(*) FILTER (WHERE estado = 'maintenance') AS mantenimiento
                FROM chequeos
                WHERE ts >= (current_date - make_interval(days => %s))
                GROUP BY 1, 2
            ), inc AS (
                SELECT recurso_id, abierta_at::date AS dia, count(*) AS incidencias
                FROM incidencias
                WHERE abierta_at >= (current_date - make_interval(days => %s))
                GROUP BY 1, 2
            )
            INSERT INTO disponibilidad_diaria AS d
                (recurso_id, dia, up, degraded, down, unknown, mantenimiento,
                 disponibilidad, incidencias)
            SELECT c.recurso_id, c.dia, c.up, c.degraded, c.down, c.unknown, c.mantenimiento,
                   -- Sin evaluables -> NULL (sin datos), nunca cero por ciento.
                   -- (ojo: no usar el simbolo de porcentaje aqui; psycopg parsea
                   --  los comentarios y lo tomaria por un placeholder invalido)
                   CASE WHEN (c.up + c.degraded + c.down) > 0
                        THEN round((c.up + c.degraded)::numeric
                                   / (c.up + c.degraded + c.down) * 100, 3)
                   END,
                   COALESCE(i.incidencias, 0)
            FROM chq c
            LEFT JOIN inc i ON i.recurso_id = c.recurso_id AND i.dia = c.dia
            ON CONFLICT (recurso_id, dia) DO UPDATE SET
                up = EXCLUDED.up, degraded = EXCLUDED.degraded, down = EXCLUDED.down,
                unknown = EXCLUDED.unknown, mantenimiento = EXCLUDED.mantenimiento,
                disponibilidad = EXCLUDED.disponibilidad, incidencias = EXCLUDED.incidencias
            """,
            (dias, dias),
        )
        return cur.rowcount


# ── Reportes programados (SLA por correo) ─────────────────────────────
def disponibilidad(db: Database, rango_seg: int, tipo_id: int | None = None,
                   sitio_id: int | None = None) -> list[dict[str, Any]]:
    """Disponibilidad por recurso en el periodo (réplica del ReporteController).
    disponibilidad = (up+degraded)/(up+degraded+down) sobre chequeos evaluables.

    `tipo_id`/`sitio_id` acotan el informe (None = todos). Permite dirigir un
    reporte a una audiencia concreta sin exponer el resto de la infraestructura
    (p. ej. enviar al proveedor solo la disponibilidad de sus enlaces).
    """
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.nombre, t.nombre AS tipo_nombre, s.nombre AS sitio_nombre,
                   r.estado_actual,
                   -- Objetivo efectivo: el del recurso pisa al del tipo.
                   COALESCE(r.sla_objetivo, t.sla_objetivo) AS sla_objetivo,
                   count(c.id) FILTER (WHERE c.estado = 'up')       AS up,
                   count(c.id) FILTER (WHERE c.estado = 'degraded') AS degraded,
                   count(c.id) FILTER (WHERE c.estado = 'down')     AS down,
                   count(c.id) FILTER (WHERE c.estado = 'unknown')  AS unknown,
                   (SELECT count(*) FROM incidencias i
                      WHERE i.recurso_id = r.id
                        AND i.abierta_at >= now() - make_interval(secs => %s)) AS incidencias
            FROM recursos r
            JOIN tipos_recurso t ON t.id = r.tipo_id
            LEFT JOIN sitios s ON s.id = r.sitio_id
            LEFT JOIN chequeos c ON c.recurso_id = r.id
                 AND c.ts >= now() - make_interval(secs => %s)
            WHERE r.activo = true
              AND (%s::smallint IS NULL OR r.tipo_id  = %s::smallint)
              AND (%s::integer  IS NULL OR r.sitio_id = %s::integer)
            GROUP BY r.id, t.nombre, s.nombre, r.sla_objetivo, t.sla_objetivo
            ORDER BY r.nombre
            """,
            (rango_seg, rango_seg, tipo_id, tipo_id, sitio_id, sitio_id),
        )
        from .reportes import evaluar_sla

        filas = []
        for r in cur.fetchall():
            d = dict(r)
            base = (d["up"] or 0) + (d["degraded"] or 0) + (d["down"] or 0)
            d["disponibilidad"] = round((d["up"] + d["degraded"]) / base * 100, 3) if base > 0 else None
            d["sla_objetivo"] = float(d["sla_objetivo"]) if d["sla_objetivo"] is not None else None
            d["cumple_sla"] = evaluar_sla(d["disponibilidad"], d["sla_objetivo"])
            filas.append(d)
        return filas


def datos_banda(db: Database, rango_seg: int, tipo_id: int | None = None,
                sitio_id: int | None = None) -> list[dict[str, Any]]:
    """Consumo de ancho de banda por interfaz en el periodo (réplica del
    ReporteController::banda): promedio, percentil 95 y máximo de Mbps in/out
    sobre interfaces_historico. Base del informe de banda."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.nombre, t.nombre AS tipo_nombre, s.nombre AS sitio_nombre,
                   i.if_name, h.*
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
                WHERE hh.recurso_id = i.recurso_id AND hh.if_index = i.if_index
                  AND hh.ts >= now() - make_interval(secs => %s)
            ) h ON true
            WHERE r.activo = true AND h.muestras > 0
              AND (%s::smallint IS NULL OR r.tipo_id  = %s::smallint)
              AND (%s::integer  IS NULL OR r.sitio_id = %s::integer)
            ORDER BY GREATEST(COALESCE(h.p95_in,0), COALESCE(h.p95_out,0)) DESC
            """,
            (rango_seg, tipo_id, tipo_id, sitio_id, sitio_id),
        )
        salida = []
        for r in cur.fetchall():
            salida.append({
                "nombre": r["nombre"], "tipo_nombre": r["tipo_nombre"],
                "sitio_nombre": r["sitio_nombre"], "if_name": r["if_name"],
                "muestras": r["muestras"],
                "avg_in": float(r["avg_in"]) if r["avg_in"] is not None else None,
                "avg_out": float(r["avg_out"]) if r["avg_out"] is not None else None,
                "p95_in": float(r["p95_in"]) if r["p95_in"] is not None else None,
                "p95_out": float(r["p95_out"]) if r["p95_out"] is not None else None,
                "max_in": float(r["max_in"]) if r["max_in"] is not None else None,
                "max_out": float(r["max_out"]) if r["max_out"] is not None else None,
            })
        return salida


def datos_alertas(db: Database, rango_seg: int, tipo_id: int | None = None,
                  sitio_id: int | None = None, limite: int = 5000) -> list[dict[str, Any]]:
    """Alertas (notificaciones) enviadas en el periodo con su detalle: fecha/hora,
    medio (canal), destino, recurso, severidad, evento, asunto, estado y error.
    Base del informe de alertas enviadas."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT to_char(n.created_at, 'YYYY-MM-DD HH24:MI:SS') AS ts,
                   cn.tipo AS medio, cn.nombre AS canal_nombre, n.destino,
                   r.nombre AS recurso, r.tipo_id,
                   n.payload->>'severidad' AS severidad,
                   n.payload->>'evento'    AS evento,
                   n.payload->>'asunto'    AS asunto,
                   n.estado, n.error
            FROM notificaciones n
            JOIN canales_notificacion cn ON cn.id = n.canal_id
            JOIN incidencias ic ON ic.id = n.incidencia_id
            JOIN recursos r ON r.id = ic.recurso_id
            WHERE n.created_at >= now() - make_interval(secs => %s)
              AND (%s::smallint IS NULL OR r.tipo_id  = %s::smallint)
              AND (%s::integer  IS NULL OR r.sitio_id = %s::integer)
            ORDER BY n.created_at DESC
            LIMIT %s
            """,
            (rango_seg, tipo_id, tipo_id, sitio_id, sitio_id, limite),
        )
        return cur.fetchall()


def reportes_activos(db: Database) -> list[dict[str, Any]]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, nombre, tipo, periodo, rango, destinatarios, formato, ultimo_envio_at, "
            "       tipo_id, sitio_id "
            "FROM reportes_programados WHERE activo = true ORDER BY id"
        )
        return cur.fetchall()


def marcar_reporte_enviado(db: Database, reporte_id: int, ts: datetime) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE reportes_programados SET ultimo_envio_at = %s WHERE id = %s",
                    (ts, reporte_id))


# ── Línea base / anomalías ────────────────────────────────────────────
def recalcular_baselines(db: Database, ventana_dias: int) -> int:
    """Recalcula la línea base (media/σ por recurso+métrica+hora-UTC) desde el
    rollup horario. Idempotente (upsert). Devuelve nº de franjas actualizadas."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO baselines AS b (recurso_id, metrica, hora, media, desviacion, muestras, actualizado_at)
            SELECT recurso_id, metrica,
                   EXTRACT(HOUR FROM bucket AT TIME ZONE 'UTC')::smallint AS hora,
                   avg(valor_avg),
                   COALESCE(stddev_samp(valor_avg), 0),
                   count(*)::int,
                   now()
            FROM metricas_rollup_horario
            WHERE bucket >= now() - make_interval(days => %s)
            GROUP BY recurso_id, metrica, EXTRACT(HOUR FROM bucket AT TIME ZONE 'UTC')
            ON CONFLICT (recurso_id, metrica, hora) DO UPDATE SET
                media = EXCLUDED.media, desviacion = EXCLUDED.desviacion,
                muestras = EXCLUDED.muestras, actualizado_at = now()
            """,
            (ventana_dias,),
        )
        return cur.rowcount


def cargar_baselines_hora(db: Database, recurso_id: int, hora: int) -> dict[str, tuple]:
    """Líneas base del recurso para una hora-del-día: {metrica: (media, desviacion, muestras)}."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT metrica, media, desviacion, muestras FROM baselines "
            "WHERE recurso_id = %s AND hora = %s",
            (recurso_id, hora),
        )
        return {r["metrica"]: (r["media"], r["desviacion"], r["muestras"]) for r in cur.fetchall()}


def rollup_horario(db: Database) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT fn_rollup_metricas_horario()")


def rollup_diario(db: Database) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT fn_rollup_metricas_diario()")


# Retención de métricas crudas (días). Debe coincidir con el default de
# fn_purgar_datos(p_ret_metricas_dias): con ella se decide qué particiones ya
# quedaron completamente fuera de la ventana y se pueden dropear.
RET_METRICAS_DIAS = 15


def purgar_datos(db: Database, interfaces_hist_dias: int = 35) -> dict[str, Any]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT fn_purgar_datos() AS r")
        r = cur.fetchone()["r"]
        # Histórico de interfaces: retención configurable. Se mantiene ≥30 días para
        # poder calcular el PERCENTIL 95 de ancho de banda del periodo de facturación
        # (métrica ISP, estilo SolarWinds) sobre las muestras crudas.
        dias = max(1, int(interfaces_hist_dias))
        cur.execute(
            "DELETE FROM interfaces_historico WHERE ts < now() - make_interval(days => %s)",
            (dias,),
        )
        # Flujos de tráfico (NetFlow): retención corta (7 días).
        cur.execute("DELETE FROM flujos WHERE ventana_fin < now() - interval '7 days'")
        cur.execute("DELETE FROM flujo_totales WHERE ventana_fin < now() - interval '7 days'")
        # Calidad WAN: retención media (30 días).
        cur.execute("DELETE FROM wan_calidad WHERE ts < now() - interval '30 days'")

        # Particiones de métricas ya fuera de retención: DROP.
        # Ojo: borrar filas NO devuelve el espacio al disco (quedan páginas muertas);
        # en una tabla particionada solo el DROP de la partición lo libera. Sin esto,
        # cada mes dejaba un cascarón vacío de GB (medido: metricas_2026_06 con 0 filas
        # ocupaba 1.4 GB). Se pasa `hoy - retención`: la función solo dropea el mes
        # cuyo rango COMPLETO ya expiró, así que el mes en curso (y el anterior si aún
        # tiene datos vigentes) nunca se tocan.
        cur.execute(
            "SELECT fn_drop_particiones_metricas("
            "(current_date - make_interval(days => %s))::date) AS n",
            (RET_METRICAS_DIAS,),
        )
        dropeadas = cur.fetchone()["n"] or 0
        if dropeadas:
            log.info("Purga: %s partición(es) de métricas dropeadas (espacio liberado).", dropeadas)
        if isinstance(r, dict):
            r["particiones_dropeadas"] = dropeadas
        return r


# ── Flujos de tráfico (NetFlow/IPFIX) ─────────────────────────────────
def guardar_flujos(db: Database, filas: list[tuple]) -> None:
    """Inserta el TOP de conversaciones agregadas de una ventana.

    Cada fila: (exporter_ip, recurso_id, ventana_inicio, ventana_fin,
                src_ip, dst_ip, src_port, dst_port, protocolo, app, bytes, paquetes)
    """
    if not filas:
        return
    with db.connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO flujos (exporter_ip, recurso_id, ventana_inicio, ventana_fin, "
            "src_ip, dst_ip, src_port, dst_port, protocolo, app, bytes, paquetes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            filas,
        )


def guardar_flujo_totales(db: Database, filas: list[tuple]) -> None:
    """Inserta los totales agregados de una ventana (TODO el tráfico, no solo el top-N).

    Cada fila: (exporter_ip, recurso_id, ventana_inicio, ventana_fin, app,
                protocolo, bytes, paquetes, flujos)
    """
    if not filas:
        return
    with db.connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO flujo_totales (exporter_ip, recurso_id, ventana_inicio, ventana_fin, "
            "app, protocolo, bytes, paquetes, flujos) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            filas,
        )


# ── Calidad de enlace WAN (medición activa) ───────────────────────────
def recursos_wan_calidad(db: Database) -> list[Recurso]:
    """Recursos activos que optaron por medición de calidad WAN (parametros.wan_calidad)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO +
                    " WHERE r.activo = true AND r.parametros ? 'wan_calidad' ORDER BY r.id")
        return [_fila_a_recurso(r) for r in cur.fetchall()]


def guardar_wan_calidad(db: Database, recurso_id: int, datos: dict) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wan_calidad (recurso_id, latency_ms, jitter_ms, loss_pct, "
            "down_mbps, up_mbps, mos, calidad) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (recurso_id, datos.get("latency_ms"), datos.get("jitter_ms"),
             datos.get("loss_pct"), datos.get("down_mbps"), datos.get("up_mbps"),
             datos.get("mos"), datos.get("calidad")),
        )


# ── Traceroute / ruta de red por salto ────────────────────────────────
def recursos_traceroute(db: Database) -> list[Recurso]:
    """Recursos activos que optaron por traceroute (parametros.traceroute)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO +
                    " WHERE r.activo = true AND r.parametros ? 'traceroute' ORDER BY r.id")
        return [_fila_a_recurso(r) for r in cur.fetchall()]


def guardar_ruta(db: Database, recurso_id: int, saltos: list[dict], ahora: datetime) -> None:
    """Reemplaza la ruta del recurso con los saltos dados (una transacción)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM rutas WHERE recurso_id = %s", (recurso_id,))
        for h in saltos:
            cur.execute(
                "INSERT INTO rutas (recurso_id, hop_no, ip, hostname, rtt_ms, perdida, ts) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (recurso_id, h["hop_no"], h.get("ip"), h.get("hostname"),
                 h.get("rtt_ms"), bool(h.get("perdida")), ahora),
            )


# ── Auto-remediación / runbooks (#5) ──────────────────────────────────
def cargar_runbooks_activos(db: Database, clave: str) -> list[dict]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, nombre, activo, trigger_tipo_id, trigger_severidad, trigger_match, "
            "accion, cooldown_seg, descifrar_secreto(secretos, %s) AS secretos "
            "FROM runbooks WHERE activo = true ORDER BY id",
            (clave,),
        )
        return cur.fetchall()


def ultima_ejecucion_runbook(db: Database, runbook_id: int, recurso_id: int) -> datetime | None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT max(ts) AS ts FROM runbook_ejecuciones WHERE runbook_id = %s AND recurso_id = %s",
            (runbook_id, recurso_id),
        )
        row = cur.fetchone()
        return row["ts"] if row else None


def registrar_ejecucion_runbook(db: Database, runbook_id: int, incidencia_id: int | None,
                                recurso_id: int | None, exito: bool, salida: str | None) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO runbook_ejecuciones (runbook_id, incidencia_id, recurso_id, exito, salida) "
            "VALUES (%s, %s, %s, %s, %s)",
            (runbook_id, incidencia_id, recurso_id, exito, (salida or "")[:4000]),
        )


# ── Cumplimiento de configuración (#7) ────────────────────────────────
def cargar_politicas_cumplimiento(db: Database) -> list[dict]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, nombre, tipo, patron, severidad, aplica_tipo_id "
            "FROM cumplimiento_politicas WHERE activo = true ORDER BY id"
        )
        return cur.fetchall()


def ultimo_respaldo_texto(db: Database, recurso_id: int) -> str | None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT contenido FROM config_respaldos WHERE recurso_id = %s ORDER BY id DESC LIMIT 1",
            (recurso_id,),
        )
        row = cur.fetchone()
        return row["contenido"] if row else None


def guardar_resultado_cumplimiento(db: Database, recurso_id: int, politica_id: int,
                                   cumple: bool, detalle: str) -> bool | None:
    """Upsert del resultado; devuelve el valor PREVIO de `cumple` (None si no había)."""
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cumple FROM cumplimiento_resultados WHERE recurso_id = %s AND politica_id = %s",
            (recurso_id, politica_id),
        )
        row = cur.fetchone()
        previo = row["cumple"] if row else None
        cur.execute(
            "INSERT INTO cumplimiento_resultados (recurso_id, politica_id, cumple, detalle, ts) "
            "VALUES (%s, %s, %s, %s, now()) "
            "ON CONFLICT (recurso_id, politica_id) DO UPDATE SET "
            "cumple = EXCLUDED.cumple, detalle = EXCLUDED.detalle, ts = now()",
            (recurso_id, politica_id, cumple, detalle),
        )
        return previo


# ── Virtualización (#9) ───────────────────────────────────────────────
def recursos_virtualizacion(db: Database) -> list[Recurso]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_RECURSO +
                    " WHERE r.activo = true AND r.parametros ? 'virtualizacion' ORDER BY r.id")
        return [_fila_a_recurso(r) for r in cur.fetchall()]


def guardar_vms(db: Database, host_recurso_id: int, vms: list[dict]) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        for v in vms:
            cur.execute(
                "INSERT INTO vm_inventario (host_recurso_id, vm_id, nombre, power_state, "
                "cpu_count, memoria_mb, guest_os, ts) VALUES (%s,%s,%s,%s,%s,%s,%s, now()) "
                "ON CONFLICT (host_recurso_id, vm_id) DO UPDATE SET nombre=EXCLUDED.nombre, "
                "power_state=EXCLUDED.power_state, cpu_count=EXCLUDED.cpu_count, "
                "memoria_mb=EXCLUDED.memoria_mb, guest_os=EXCLUDED.guest_os, ts=now()",
                (host_recurso_id, v.get("vm_id"), v.get("nombre"), v.get("power_state"),
                 v.get("cpu_count"), v.get("memoria_mb"), v.get("guest_os")),
            )


# ── Web Push (#11) y GLPI (#3) ────────────────────────────────────────
def push_suscripciones(db: Database) -> list[dict]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT endpoint, p256dh, auth FROM push_suscripciones")
        return cur.fetchall()


def set_ticket_externo(db: Database, incidencia_id: int, ticket: str) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE incidencias SET ticket_externo = %s WHERE id = %s AND ticket_externo IS NULL",
            (ticket, incidencia_id),
        )


# ── AIOps: correlación de alertas (#14) ───────────────────────────────
def incidencias_abiertas_correlacion(db: Database) -> list[dict]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT i.id, i.abierta_at AS inicio, i.correlacion_id, r.sitio_id, r.id AS recurso_id, "
            "r.depende_de_id "
            "FROM incidencias i JOIN recursos r ON r.id = i.recurso_id "
            "WHERE i.estado = 'abierta' ORDER BY i.abierta_at"
        )
        return cur.fetchall()


def crear_correlacion(db: Database, sitio_id, causa_incidencia_id, resumen: str,
                      incidencia_ids: list[int]) -> int:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO correlaciones (sitio_id, causa_incidencia_id, resumen, n_incidencias) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (sitio_id, causa_incidencia_id, resumen, len(incidencia_ids)),
        )
        cid = cur.fetchone()["id"]
        cur.execute("UPDATE incidencias SET correlacion_id = %s WHERE id = ANY(%s)",
                    (cid, incidencia_ids))
        return cid


def tipo_id_de_recurso(db: Database, recurso_id: int) -> int | None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT tipo_id FROM recursos WHERE id = %s", (recurso_id,))
        row = cur.fetchone()
        return row["tipo_id"] if row else None
