"""Planificación con APScheduler: un job por recurso según su intervalo, con
resincronización periódica y tareas de mantenimiento de datos."""
from __future__ import annotations

import logging

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import repository as repo
from .config import Settings
from .db import Database
from .notificaciones import reintentar_pendientes
from .runner import (
    correlacionar_incidencias,
    ejecutar_chequeo_por_id,
    enviar_reportes_programados,
    escalar_incidencias,
    evaluar_cumplimiento,
    latido_externo,
    marcar_obsoletos,
    medir_calidad_wan,
    procesar_descubrimientos,
    procesar_hardware,
    procesar_virtualizacion,
    pronosticar_capacidad,
    recolectar_rutas,
    recolectar_topologia,
    recalcular_baselines,
    refrescar_trafico_mpls,
    respaldar_configuraciones,
)

log = logging.getLogger(__name__)


def construir_scheduler(settings: Settings) -> BackgroundScheduler:
    return BackgroundScheduler(
        executors={"default": ThreadPoolExecutor(settings.scheduler_max_workers)},
        job_defaults={
            "coalesce": True,       # si se acumulan ejecuciones, corre una sola
            "max_instances": 1,     # nunca dos chequeos del mismo recurso a la vez
            "misfire_grace_time": settings.misfire_grace,
        },
        timezone="UTC",
    )


def _job_id(recurso_id: int) -> str:
    return f"recurso:{recurso_id}"


def sincronizar_jobs(scheduler: BackgroundScheduler, db: Database, settings: Settings) -> None:
    """Crea/actualiza/elimina jobs según los recursos activos en la BD."""
    recursos = repo.cargar_recursos_activos(db)
    # Pollers distribuidos: este worker solo atiende los sitios configurados.
    filtro = settings.sitios_filtro()
    if filtro:
        recursos = [r for r in recursos if r.sitio_id in filtro]
    activos = {_job_id(r.id) for r in recursos}

    # Altas y cambios de intervalo
    for r in recursos:
        jid = _job_id(r.id)
        existente = scheduler.get_job(jid)
        if existente is None:
            scheduler.add_job(
                ejecutar_chequeo_por_id,
                trigger=IntervalTrigger(seconds=r.intervalo_segundos),
                args=[db, settings, r.id],
                id=jid,
                name=f"{r.nombre} ({r.intervalo_segundos}s)",
                replace_existing=True,
            )
            log.info("Job alta: %s cada %ss", r.nombre, r.intervalo_segundos)
        else:
            # Si cambió el intervalo, reprogramar.
            interval = getattr(existente.trigger, "interval", None)
            if interval is not None and int(interval.total_seconds()) != r.intervalo_segundos:
                scheduler.reschedule_job(jid, trigger=IntervalTrigger(seconds=r.intervalo_segundos))
                log.info("Job reprogramado: %s -> %ss", r.nombre, r.intervalo_segundos)

    # Bajas (recursos desactivados/eliminados)
    for job in scheduler.get_jobs():
        if job.id.startswith("recurso:") and job.id not in activos:
            scheduler.remove_job(job.id)
            log.info("Job baja: %s", job.id)


def registrar_tareas_internas(scheduler: BackgroundScheduler, db: Database, settings: Settings) -> None:
    # Resincronización de jobs con la BD.
    scheduler.add_job(
        sincronizar_jobs,
        trigger=IntervalTrigger(seconds=settings.sync_interval_seg),
        args=[scheduler, db, settings],
        id="sync-jobs",
        replace_existing=True,
    )

    # Freshness/stale-data: marca 'unknown' los recursos sin chequeo reciente.
    if settings.freshness_enabled:
        scheduler.add_job(
            marcar_obsoletos,
            trigger=IntervalTrigger(seconds=settings.freshness_check_seg),
            args=[db, settings],
            id="freshness",
            replace_existing=True,
        )
        log.info("Freshness activo (cada %ss, factor %s, piso %ss).",
                 settings.freshness_check_seg, settings.freshness_factor, settings.freshness_min_seg)

    # Topología L2 (LLDP): camina los switches y registra vecinos.
    if settings.topologia_enabled:
        scheduler.add_job(
            recolectar_topologia,
            trigger=IntervalTrigger(seconds=settings.topologia_check_seg),
            args=[db, settings],
            id="topologia",
            replace_existing=True,
        )
        log.info("Topología LLDP activa (cada %ss).", settings.topologia_check_seg)

    # Calidad activa de enlaces WAN/Starlink: mide latencia/jitter/pérdida + throughput.
    if settings.wan_calidad_enabled:
        scheduler.add_job(
            medir_calidad_wan,
            trigger=IntervalTrigger(seconds=settings.wan_calidad_check_seg),
            args=[db, settings],
            id="wan-calidad",
            replace_existing=True,
        )
        log.info("Calidad WAN activa (cada %ss).", settings.wan_calidad_check_seg)

    # Traceroute por salto: ruta de red de los recursos opt-in (parametros.traceroute).
    if settings.traceroute_enabled:
        scheduler.add_job(
            recolectar_rutas,
            trigger=IntervalTrigger(seconds=settings.traceroute_check_seg),
            args=[db, settings],
            id="traceroute",
            replace_existing=True,
        )
        log.info("Traceroute activo (cada %ss).", settings.traceroute_check_seg)

    # Virtualización (#9): inventario por-VM de hosts vCenter opt-in.
    if settings.virtualizacion_enabled:
        scheduler.add_job(
            procesar_virtualizacion,
            trigger=IntervalTrigger(seconds=settings.virtualizacion_check_seg),
            args=[db, settings], id="virtualizacion", replace_existing=True,
        )
        log.info("Virtualización activa (cada %ss).", settings.virtualizacion_check_seg)

    # Cumplimiento de configuración (#7): evalúa políticas contra la última config.
    if settings.cumplimiento_enabled:
        scheduler.add_job(
            evaluar_cumplimiento,
            trigger=IntervalTrigger(seconds=settings.cumplimiento_check_seg),
            args=[db, settings], id="cumplimiento", replace_existing=True,
        )
        log.info("Cumplimiento de config activo (cada %ss).", settings.cumplimiento_check_seg)

    # AIOps: correlación de alertas (#14): agrupa incidencias relacionadas.
    if settings.correlacion_enabled:
        scheduler.add_job(
            correlacionar_incidencias,
            trigger=IntervalTrigger(seconds=settings.correlacion_check_seg),
            args=[db, settings], id="correlacion", replace_existing=True,
        )
        log.info("Correlación de alertas activa (cada %ss, ventana %ss).",
                 settings.correlacion_check_seg, settings.correlacion_ventana_seg)

    # Hardware físico (Redfish/IPMI): sondeo de los recursos opt-in.
    if settings.hardware_enabled:
        scheduler.add_job(
            procesar_hardware,
            trigger=IntervalTrigger(seconds=settings.hardware_check_seg),
            args=[db, settings],
            id="hardware",
            replace_existing=True,
        )
        log.info("Monitoreo de hardware activo (cada %ss).", settings.hardware_check_seg)

    # Auto-descubrimiento: ejecuta los escaneos de subred en cola.
    if settings.descubrimiento_enabled:
        scheduler.add_job(
            procesar_descubrimientos,
            trigger=IntervalTrigger(seconds=settings.descubrimiento_check_seg),
            args=[db, settings],
            id="descubrimiento",
            replace_existing=True,
        )
        log.info("Auto-descubrimiento activo (cola cada %ss).", settings.descubrimiento_check_seg)

    # Tráfico MPLS: muestrea las sesiones del FortiGate para evaluar enlaces de
    # sede cuyo gateway no responde ICMP (probe 'mpls').
    if settings.mpls_trafico_enabled:
        from .probes import mpls_trafico
        try:
            mpls_trafico.sembrar_cache(repo.cargar_mpls_actividad(db))
        except Exception:  # noqa: BLE001
            log.exception("No se pudo sembrar la caché de tráfico MPLS")
        scheduler.add_job(
            refrescar_trafico_mpls,
            trigger=IntervalTrigger(seconds=settings.mpls_sesion_seg),
            args=[db, settings],
            id="mpls-trafico",
            replace_existing=True,
        )
        log.info("Tráfico MPLS activo (cada %ss, ventana %ss, iface %s).",
                 settings.mpls_sesion_seg, settings.mpls_actividad_seg, settings.mpls_fgt_iface)

    # Dead-man's switch: latido a un servicio externo.
    if settings.deadman_url:
        scheduler.add_job(
            latido_externo,
            trigger=IntervalTrigger(seconds=settings.deadman_interval_seg),
            args=[db, settings],
            id="deadman",
            replace_existing=True,
        )
        log.info("Dead-man's switch activo (latido cada %ss).", settings.deadman_interval_seg)

    # Reintento de notificaciones fallidas.
    if settings.notif_enabled:
        scheduler.add_job(
            reintentar_pendientes,
            trigger=IntervalTrigger(seconds=settings.notif_retry_interval_seg),
            args=[db, settings],
            id="notif-retry",
            replace_existing=True,
        )
        # Escalado por tiempo (on-call): incidencias sin reconocer.
        if settings.escalation_min and settings.escalation_min > 0:
            scheduler.add_job(
                escalar_incidencias,
                trigger=IntervalTrigger(seconds=settings.escalation_check_seg),
                args=[db, settings],
                id="escalado",
                replace_existing=True,
            )

    # Reportes programados de SLA por correo (revisa a diario qué toca enviar).
    if settings.reporte_enabled:
        scheduler.add_job(
            enviar_reportes_programados,
            trigger=CronTrigger(hour=settings.reporte_hora, minute=0),
            args=[db, settings],
            id="reportes-programados",
            replace_existing=True,
        )
        log.info("Reportes programados activos (chequeo diario a las %02d:00 UTC).", settings.reporte_hora)

    if not settings.tareas_mantenimiento:
        return

    # Rollup horario (al minuto 5 de cada hora) y diario (00:15).
    scheduler.add_job(repo.rollup_horario, CronTrigger(minute=5), args=[db],
                      id="rollup-horario", replace_existing=True)
    scheduler.add_job(repo.rollup_diario, CronTrigger(hour=0, minute=15), args=[db],
                      id="rollup-diario", replace_existing=True)
    # Histórico de disponibilidad (00:20). CRÍTICO que corra ANTES de la purga
    # (03:30): consolida desde `chequeos`, que solo guarda 30 días. Sin esto el
    # histórico de SLA se perdía a diario y no había con qué sostener un reclamo.
    scheduler.add_job(_rollup_disponibilidad, CronTrigger(hour=0, minute=20), args=[db],
                      id="rollup-disponibilidad", replace_existing=True)
    # Forecasting de capacidad (00:30, tras el rollup diario). Usa el rollup diario.
    if settings.forecast_enabled:
        scheduler.add_job(pronosticar_capacidad, CronTrigger(hour=0, minute=30), args=[db, settings],
                          id="forecast", replace_existing=True)

    # Línea base estacional / anomalías (00:45, tras el rollup). Usa el rollup horario.
    if settings.baseline_enabled:
        scheduler.add_job(recalcular_baselines, CronTrigger(hour=0, minute=45), args=[db, settings],
                          id="baselines", replace_existing=True)

    # Purga según retención (03:30).
    scheduler.add_job(repo.purgar_datos, CronTrigger(hour=3, minute=30),
                      args=[db, settings.interfaces_hist_retencion_dias],
                      id="purga", replace_existing=True)
    # Respaldo de configuración de firewalls (02:00). Guarda solo si cambió.
    scheduler.add_job(respaldar_configuraciones, CronTrigger(hour=2, minute=0), args=[db, settings],
                      id="respaldo-config", replace_existing=True)
    # Asegurar partición del mes siguiente (día 25 de cada mes).
    scheduler.add_job(_asegurar_particion_proximo_mes, CronTrigger(day=25, hour=1), args=[db],
                      id="particion-mes", replace_existing=True)
    log.info("Tareas de mantenimiento de datos registradas (rollup/purga/particiones).")


def _rollup_disponibilidad(db: Database) -> None:
    """Consolida el histórico de disponibilidad del día anterior (y el previo, por
    si llegaron chequeos tarde). Ver repo.rollup_disponibilidad_diaria."""
    filas = repo.rollup_disponibilidad_diaria(db, dias=2)
    log.info("Histórico de disponibilidad consolidado: %s recurso-día.", filas)


def _asegurar_particion_proximo_mes(db: Database) -> None:
    from datetime import date, timedelta
    hoy = date.today()
    repo.asegurar_particiones(db, [hoy, hoy + timedelta(days=31)])
