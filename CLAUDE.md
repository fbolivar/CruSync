# CLAUDE.md — SIMON · Sistema Integral de Monitoreo

> Nombre del producto: **SIMON** ("Sistema Integral de Monitoreo"), con identidad
> corporativa de **Parques Nacionales Naturales de Colombia** (tema claro verde,
> logo, favicon, tipografía GOV.CO Montserrat/Work Sans). Antes "Sistema de
> Monitoreo de Disponibilidad de TI".

## Objetivo del proyecto
Aplicación web para monitorear en tiempo casi-real la DISPONIBILIDAD y el
estado de salud de los recursos de tecnología de la entidad. Debe detectar
caídas, degradaciones y recuperaciones, registrar histórico, y notificar.

## Recursos a monitorear (tipos)
- Firewalls (FortiGate)
- Servidores (físicos y virtuales)
- Switches de red (LAN)
- Esquemas de almacenamiento NAS
- Switches de fibra (SAN / Fibre Channel)
- UPS (sistemas de respaldo de energía)
- Enlaces satelitales Starlink
- Enlaces de fibra óptica (WAN)
- Sitios web (internos y públicos)

## Stack y separación de responsabilidades (NO mezclar capas)
- **Frontend:** Angular (última LTS). SPA. Consume la API PHP por REST y refresca
  el estado por **polling** al API (no Supabase Realtime). NO accede a la BD directo.
- **API:** PHP con Laravel. Expone REST. Responsable de: CRUD de recursos,
  autenticación/autorización, configuración, umbrales, reportes. Conecta a
  PostgreSQL vía PDO/Eloquent. **Autenticación LOCAL**: emite y valida su propio JWT
  (HS256, AUTH_JWT_SECRET); contraseñas bcrypt en `perfiles`. (Sin Supabase.)

> **Cambio de arquitectura (2026-06-10):** se descartó Supabase. La autenticación es
> local (JWT propio de la API, contraseñas en `perfiles.password_hash`) y el "en vivo"
> del dashboard es por polling. La BD es el Postgres del servidor, no Supabase.
- **Workers de monitoreo:** Python. Procesos headless que leen los recursos
  activos, ejecutan los chequeos según su intervalo, y escriben resultados en
  la BD (chequeos, métricas, incidencias). Usan APScheduler para la
  planificación. NO exponen API pública (solo un endpoint /health opcional).
- **Base de datos:** PostgreSQL gestionado por Supabase en la fase inicial.
  Diseñar TODO (esquema, queries, migraciones) para ser portable a un Postgres
  estándar en servidor virtual después. NO usar features propietarias de
  Supabase que no existan en Postgres puro, salvo Auth y Realtime que se
  aíslan en su propia capa.

## Estructura del repositorio (monorepo)
```
monitoreo/
├── frontend/   # SPA Angular (LTS). REST + Supabase Realtime. NO accede a la BD.
├── api/        # REST PHP/Laravel. CRUD, auth (valida JWT Supabase), umbrales, reportes.
├── monitor/    # Workers Python + APScheduler. Probes → chequeos, metricas, incidencias.
├── db/         # Esquema PostgreSQL: migrations/ (NNNN_*.up.sql / .down.sql) + seeds/.
├── infra/      # docker-compose (Postgres local dev) + .env + initdb/.
└── docs/       # Documentación, incl. modelo-datos.md (diagrama ER + flujo).
```

## Catálogo de estados (aprobado 2026-06-10)
- **recurso / chequeo:** `up` (operativo) · `degraded` (responde pero fuera de umbral / warning) ·
  `down` (caído / critical) · `unknown` (sin datos o no evaluable) · `maintenance` (ventana de mantenimiento, alertas silenciadas).
- **incidencia:** `abierta` · `reconocida` · `resuelta`.
- **severidad:** `info` · `warning` · `critical`.
- **notificación:** `pendiente` · `enviada` · `fallida`.

## Cifrado de secretos (aprobado)
- Parámetros NO sensibles en `parametros`/`config` (jsonb en claro).
- Secretos (community SNMP, api_key, password, tokens) en columna `secretos` (bytea),
  cifrados con **pgcrypto `pgp_sym_encrypt` (AES-256)** vía `cifrar_secreto()` / `descifrar_secreto()`.
- La clave maestra `APP_CRYPTO_KEY` vive en la API (Laravel `.env`), **NUNCA en la BD**.

## Política de retención escalonada (aprobada)
| Dato | Tabla | Retención |
|---|---|---|
| Chequeos crudos | `chequeos` | 30 días |
| Métricas crudas | `metricas` (particionada por mes) | 15 días |
| Agregado horario | `metricas_rollup_horario` | 90 días |
| Agregado diario | `metricas_rollup_diario` | 730 días |
| Incidencias | `incidencias` | indefinido (histórico) |

Funciones SQL: `fn_rollup_metricas_horario`, `fn_rollup_metricas_diario`, `fn_purgar_datos`,
`fn_crear_particion_metricas`, `fn_drop_particiones_metricas`. Las invoca el worker (APScheduler) o `pg_cron` donde exista.

## Estado de fases
- ✅ FASE 0 (estructura + Postgres local Docker) y FASE 1 (modelo de datos) — completas y aprobadas (2026-06-10).
- ✅ FASE 2 (API Laravel 11 en /api) — completa y aprobada (2026-06-10). Solo gestión:
  auth por JWT de Supabase, CRUD de los 6 recursos de configuración, lectura con filtros
  de chequeos/metricas/incidencias, autorización por rol (viewer/operador/admin),
  cifrado transparente de secretos vía pgcrypto, tests de endpoints críticos.
  Incidencias quedan en solo-lectura hasta los workers. Se añadió /api/usuarios (solo admin).
- ✅ FASE 3 (Workers Python en /monitor) — completa y aprobada (2026-06-10). Probes
  ICMP / HTTP-HTTPS (incl. días de cert SSL) / TCP; APScheduler con un job por recurso;
  evaluación de estado por umbrales (up/degraded/down/unknown); máquina de incidencias
  con anti-flapping (down inmediato, degraded respeta duracion_segundos); respeto de
  mantenimientos; secretos descifrados vía pgcrypto igual que la API; tareas de
  rollup/purga/particiones. Recursos SNMP/Starlink cubiertos por ICMP mientras tanto.
- ✅ FASE 3b (probes nativos, uno por uno):
  - ✅ Paso 1 SNMP v2c/v3 (servidor/switch_lan/switch_san/nas/ups, UPS-MIB) — aprobado (2026-06-10).
  - ✅ Paso 2 Starlink gRPC con fallback ICMP — aprobado (2026-06-10).
  - ✅ Paso 3 FortiGate API REST (firewalls; clúster HA como un recurso; estado
    operativo/degradado/caído + detección de failover) — aprobado (2026-06-10).
  Nota: la E/S de red de los 3 probes (pysnmp/grpcio+yagrc/httpx) NO se validó
  contra equipos reales (solo compileall + runtime de funciones puras). La lógica HA
  de FortiGate se propuso (CLAUDE.md no la definía en detalle).
- ✅ FASE 4 (Frontend Angular 20 en /frontend) — completa, validada con `ng build` (sin errores):
  - Base: Supabase Auth (login/sesión/guard/interceptor JWT), capa de servicios a la API,
    layout NOC denso, autorización por rol (viewer solo lectura), tema oscuro con semáforo.
  - Pantalla 1 Dashboard: semáforo agrupado por sitio y tipo + Supabase Realtime (estado en vivo).
  - Pantalla 2 Detalle de recurso: gráficas SVG históricas por métrica (rango 1h/24h/7d),
    último chequeo, línea de tiempo de incidencias con duración.
  - Pantalla 3 Gestión de recursos: CRUD completo (parámetros + secretos write-only), gated por rol.
  - Pantalla 4 Incidencias: activas/histórico, severidad, duración.
  - Pantalla 5 Configuración: umbrales, mantenimientos y canales (CRUD, gated por rol).
  Stack: Angular 20.3 standalone + signals; @supabase/supabase-js. Node 24.13 no soporta Angular 22
  (requiere ≥24.15), por eso se fijó Angular 20. NO ejecutado contra API/Supabase reales (solo build).
- ✅ FASE 5 (Motor de notificaciones en /monitor) — completa, compile + runtime de lógica pura:
  al abrir/cerrar incidencia (y en escalamientos de severidad) notifica por canales activos
  (email SMTP / Telegram / webhook). Deduplicación por (incidencia,canal,evento) + anti-flapping
  (cooldown de 'apertura' por recurso). Escalamiento por severidad: `config.min_severidad` por canal
  + evento de escalada al subir severidad. Respeto de mantenimiento (heredado del runner). Cada
  envío se registra en `notificaciones` (enviada/fallida/intentos/error) con job de reintentos.
  E/S de red (SMTP/httpx) NO validada contra servicios reales (solo compileall + funciones puras).

- ✅ FASE 6 (Despliegue en servidor 192.168.50.54, Debian 12) — en PRODUCCIÓN. nginx
  (HTTPS autofirmado + redirección HTTP→443, SPA en / y /api → php8.2-fpm), worker como
  servicio systemd, ufw, backups diarios (pg_dump, ~02:30). Auth LOCAL (JWT propio, sin
  Supabase) y "en vivo" del dashboard por polling. Monitorea 3 equipos reales: FortiGate-Principal
  (HA), SW-CORE-01 (Dell OS9), PNNCSRVNCFHV2 (Windows). Notificaciones por correo (Gmail/Workspace)
  ACTIVAS. Rebranding a SIMON / Parques Nacionales. Pantallas añadidas: Sitios (CRUD),
  reconocer/resolver incidencias.

- ✅ MEJORAS DE OPERACIÓN (roadmap de mercado, 2026-06-11) — todas en producción y verificadas:
  - **Interfaces SNMP (IF-MIB)** [migr. 0004]: snapshot por puerto (estado oper/admin, Mbps in/out
    por delta de contadores HC64, util %, errores, velocidad). Opt-in `parametros.interfaces=true`;
    filtra a tipos físicos (ethernet/lag). Tabla `interfaces`; GET /recursos/{id}/interfaces; sección
    "Interfaces" en el detalle.
  - **Dependencias padre→hijo (anti-tormenta)** [migr. 0005]: `recursos.depende_de_id` (self-FK).
    Si un ancestro (CTE recursivo) está down, el worker suprime incidencia+notificación del hijo
    (registra `dependencia_caida`). API valida ciclos/autodependencia. UI: selector "Depende de".
  - **Mapa + reportes SLA**: GET /reportes/disponibilidad?rango=24h|7d|30d (disponibilidad =
    (up+degraded)/evaluables). Pantalla "Reportes" (tabla + KPIs + CSV) y pantalla "Mapa" (contorno
    SVG de Colombia embebido, offline sin tiles, marcadores por sede según peor estado).
  - **Bitácora de auditoría** [migr. 0006]: tabla `auditoria`; AuditObserver de Eloquent en el CRUD
    de 8 entidades (con diff antes/después) + login; GET /auditoria (solo admin); pantalla "Auditoría".
  - **Interfaces Fase 2** [migr. 0007]: `interfaces_historico` (serie temporal Mbps, solo oper-up,
    purga 7 días), `interfaces.monitorear`, incidencias por interfaz (`if_index`/`if_nombre`, índice
    único ampliado a (recurso, COALESCE(if_index,-1))). Worker abre/cierra incidencia "puerto X caído"
    + notifica para interfaces monitoreadas (respeta mantenimiento y supresión por dependencia).
    API: PUT /recursos/{id}/interfaces/{ifIndex} (monitorear) y GET .../historico. UI: checkbox
    "Monitorear" + gráficas entrada/salida por puerto.
  - Canales: Telegram (motor Fase 5; falta configurar bot_token/chat_id) y Teams (sender provisto,
    Incoming Webhook MessageCard; tipo 'teams' permitido) — implementados, sin configurar aún.

- ✅ MEJORAS 2ª OLA (mercado, 2026-06-11) — todas en producción y verificadas (commit 6b831a2):
  - **Escalado por tiempo (on-call)** [migr. 0008]: `incidencias.escalada_at`; job APScheduler
    `escalar_incidencias` (cada `ESCALATION_CHECK_SEG`); si una incidencia 'abierta' supera
    `ESCALATION_MIN` (def 15) sin reconocerse, reenvía evento `escalada_tiempo`. Reconocer la detiene.
  - **Tablero NOC (wallboard)**: ruta `/wallboard` a pantalla completa (fuera del Shell), tema oscuro,
    autorefresco, KPIs + tiles por sede coloreados (parpadeo en caídas). Para sala de operaciones.
  - **Grafana**: instalado en `:3000` (script `19_grafana.sh`); rol Postgres RO `grafana_ro`
    (clave en `GRAFANA_RO_PW`); datasource + dashboard autoprovisionados (`infra/grafana/`). ufw 3000.
  - **Receptor de SNMP traps** [migr. 0009]: servicio systemd `simon-traps` (`monitor/trap_listener.py`,
    pysnmp ntfrcv UDP/162, community `TRAP_COMMUNITY`); mapea IP→recurso; clasifica
    linkDown/linkUp/cold-warmStart/authFailure; tabla `traps`; GET `/api/traps`; pantalla "Traps".
    Pasa de sondeo a TIEMPO REAL en eventos de red. ufw 162/udp.
  - **SSO AD/LDAP** (env-gated) [migr. 0010, `origen`]: `config/ldap.php` + `App\Support\Ldap` (bind
    simple); `AuthController` intenta local y luego LDAP si `AUTH_LDAP_ENABLED`; crea perfil
    `origen='ldap'` al primer ingreso. Requiere `php8.2-ldap` (instalado). Sin configurar (sin AD).
  - **2FA TOTP** [migr. 0010, `totp_secret`/`totp_activo`]: `App\Support\Totp` (RFC 6238, sin deps);
    `DosFactorController` (`/api/2fa/iniciar|activar|desactivar`); login pide `codigo` y responde
    `{requiere_2fa:true}` si falta; pantalla "Seguridad". Solo cuentas locales (LDAP usa el 2FA del AD).
  Guía operativa de todo en `docs/funcionalidades-avanzadas.md`.

- ✅ MEJORAS 3ª OLA (mercado, 2026-06-11) — en producción y verificadas (commits 337797e, 324a65f):
  - **Traps → incidencias (tiempo real)**: el receptor `simon-traps` ya no solo registra; un trap
    **linkDown** abre una incidencia de interfaz (reusa el modelo de incidencias por `if_index`) y
    notifica; **linkUp** la cierra. Más rápido que el sondeo.
  - **Dead-man's switch**: `runner.latido_externo` + job; envs `DEADMAN_URL` (vacío=off),
    `DEADMAN_INTERVAL_SEG`. Hace `db.ping()` y un GET a la URL; si el worker/BD cae, el servicio
    externo (healthchecks.io/UptimeRobot…) alerta. "¿Quién vigila al vigilante?".
  - **Pollers distribuidos (base)**: env `WORKER_SITIOS="3,7"` → el worker solo atiende esos sitios.
    Permite un worker por sede/parque remoto (tras NAT/Starlink) que escribe en la BD central.
    Guía: `docs/pollers-distribuidos.md`. Fleet mgmt completo = follow-up.
  - **Respaldo de configuración** [migr. 0012 `config_respaldos`]: job diario (02:00)
    `respaldar_configuraciones`; baja la config del FortiGate (POST `/api/v2/monitor/system/config/backup`
    — OJO POST, GET da 405 en FortiOS 7.6). Guarda **solo si cambió** (hash sha256) con **diff**
    unificado y **avisa** del cambio (`motor.notificar_simple`, sin incidencia). API
    `GET /recursos/{id}/respaldos[/{rid}]`; UI: sección "Respaldos de configuración" en el detalle.
    Backup de switches por SSH = follow-up.

- ✅ MEJORAS 4ª OLA — Endurecimiento de seguridad/cumplimiento (2026-06-11, commit 5b0e254), verificado:
  - **Bloqueo por fuerza bruta**: tras `AUTH_MAX_INTENTOS` (def 5) login_fallido del mismo usuario en
    `AUTH_LOCKOUT_MIN` (def 15) min, el login responde **429** (temporal, por usuario). Reusa la tabla
    `auditoria` (no hay tabla nueva). AuthController::intentosFallidos.
  - **Política de contraseñas** (cuentas locales): `Password::min(12)->mixedCase()->numbers()->symbols()`
    en PerfilController store/update. Los usuarios LDAP usan la política del AD.
  - **Cierre por inactividad** (frontend): `IdleService` cierra sesión tras `environment.idleMinutes`
    (def 30) sin actividad; activo en el `Shell` (NO en el wallboard). Login muestra aviso
    (?motivo=inactividad).
  - **Cert de CA interna** (quita el warning HTTPS): guiado. `infra/deploy/cert_csr.sh` genera clave+CSR
    para firmar con la CA de AD (los PCs del dominio ya la confían por GPO); luego instalar .crt +
    ajustar nginx (ssl_certificate, server_name bc360.pnnc.local). NO ejecutado (requiere la CA del usuario).

- ✅ MEJORAS 5ª OLA — Profundidad técnica del monitoreo (Tier 1) (2026-06-15), worker verificado (67 tests) + `ng build` OK:
  - **Estados SOFT/HARD (anti-falsos-positivos)** [migr. 0013]: un estado "malo" (down/degraded/unknown)
    solo se confirma como HARD tras N chequeos consecutivos (`MAX_CHECK_ATTEMPTS`, def 3; override por
    recurso en `recursos.max_check_attempts`); solo las transiciones HARD abren/cierran incidencias y
    notifican. Recuperación a 'up' configurable (`RECOVERY_ATTEMPTS`, def 1 = inmediata). `recursos.estado_actual`
    pasa a reflejar el HARD (dashboard estable); `chequeos` guarda el estado CRUDO + `detalle.soft`
    (candidato/intentos). Máquina pura `evaluacion.confirmar_estado`. Mata los falsos positivos por un
    timeout/paquete perdido puntual (clave con Starlink).
  - **Triggers compuestos (multi-condición)** [migr. 0014, tabla `reglas`]: expresión booleana AST en jsonb
    sobre varias métricas (`and`/`or`/`not` + hojas `{metrica,op,valor}`), evaluada por un intérprete puro
    seguro (`monitor/reglas.py`, sin `eval`); al cumplirse, degrada con la severidad indicada (peor de
    umbrales+reglas). Lógica trivaluada: una métrica ausente no dispara (sin falsas alarmas). API
    `ReglaController` (CRUD + validación del AST, espejo en PHP), rutas en `$crud`, auditada. UI: pestaña
    "Reglas" en Configuración (editor de expresión JSON con ejemplo).
  - **Freshness / stale-data** [sin migración]: job `marcar_obsoletos` (`FRESHNESS_CHECK_SEG`); si un recurso
    activo lleva más de `FRESHNESS_FACTOR`×intervalo (piso `FRESHNESS_MIN_SEG`) sin chequeo, se marca
    'unknown' (cubre un job muerto o un recurso que dejó de responder en silencio). Respeta mantenimiento y
    pollers distribuidos. No abre incidencia (política de 'unknown').
  Nota: el motor (Python) se validó con tests puros; la E/S contra equipos reales y la API/UI las verifica
  el usuario en el servidor (sin php/ng aquí salvo `ng build`).

- ✅ MEJORAS 6ª OLA — Profundidad técnica (Tier 2) (2026-06-15), worker verificado (77 tests) + `ng build` OK,
  DESPLEGADO en producción:
  - **ICMP enriquecido** [sin migración]: el probe ICMP emite además `jitter`, `rtt_min`, `rtt_max`
    (antes solo latency+loss). Distingue "enlace degradado" (pérdida/jitter alto) de "caído" en WAN/Starlink
    vía umbrales/reglas. Helper puro `construir_muestras_icmp` (testeable).
  - **Forecasting de capacidad** [migr. 0015, tabla `pronosticos`]: job diario `pronosticar_capacidad`
    (00:30, tras el rollup) que ajusta una **regresión lineal pura** (`monitor/forecast.py`, sin numpy)
    sobre el rollup diario de métricas % (disco_*/mem) y proyecta los **días hasta el 100%**. Avisa
    (sin incidencia, `notificar_simple`) al cruzar por debajo de `FORECAST_ALERT_DIAS` (def 14); solo si
    el ajuste tiene confianza `r2 >= FORECAST_MIN_R2` (def 0.5) y ≥ `FORECAST_MIN_DIAS` (def 5) de historia.
    API `GET /pronosticos` (lectura; los calcula el worker). UI: panel "Pronóstico de capacidad" en Reportes.
  - **Ajuste de scheduler** (de la 5ª ola, consolidado en repo): `SCHEDULER_MAX_WORKERS=50`, `MISFIRE_GRACE=90`
    (evita que sondas SNMP lentas descarten jobs web por misfire).
  - **Baselining estacional / anomalías** (Tier 2 #5) [migr. 0016, tabla `baselines`] (2026-06-15):
    job diario (00:45) `recalcular_baselines` calcula media/σ por (recurso, métrica, hora-del-día UTC)
    desde el rollup horario (SQL `stddev_samp`). En el chequeo vivo, `_detectar_anomalias` degrada si una
    métrica supera su banda normal `media + max(k·σ, piso)` de esa hora. Guardas anti-ruido: **opt-in** por
    recurso (`parametros.baseline_metricas`, p.ej. `["cpu","mem"]`), `BASELINE_K=3` (3σ), piso absoluto
    `BASELINE_MIN_DESVIACION=5`, mínimo `BASELINE_MIN_MUESTRAS=7` días por franja, solo desviación hacia
    arriba, y confirmación SOFT/HARD (un pico aislado no alerta). Lógica pura `monitor/baseline.py`.
    API `GET /recursos/{id}/baselines`; UI: panel "Línea base · anomalías" en el detalle. Madura en días.

- ✅ RENDIMIENTO SNMP — GETBULK en los walks (2026-06-15, commit 35ba95d), medido en producción:
  El walk usa **GETBULK** (bulkWalkCmd, maxRepetitions 25) en v2c/v3 en vez de GETNEXT; cae a GETNEXT
  en v1. Benchmark (`infra/deploy/bench_snmp.py`): construir un SnmpEngine = 0.10s (no era el cuello);
  el paralelismo por hebras topa en ~1.5x porque pysnmp decodifica varbinds en Python puro y el **GIL**
  lo serializa. GETBULK reduce round-trips → en LAN no cambia, pero en **WAN/alta latencia es ~8×**
  (servidor remoto 76s → 9s); por eso los servidores remotos volvieron de 300s a 120s de intervalo.
  Pendiente (decisión del usuario) para los switches LAN, limitados por el decode (GIL): desacoplar/
  reducir el walk IF-MIB, librería SNMP en C (easysnmp), o multiprocessing.

- ✅ REPORTES PROGRAMADOS (SLA por correo) (2026-06-16) [migr. 0017, tabla `reportes_programados`]:
  job diario del worker (`enviar_reportes_programados`, a las `REPORTE_HORA` UTC) que detecta qué
  reportes toca enviar según su periodicidad (diario/semanal/mensual, vía `reporte_due`), calcula la
  disponibilidad/SLA (réplica del ReporteController en `repository.disponibilidad`), genera **PDF**
  (fpdf2, puro Python; cae a CSV si falta) y lo envía por el **canal email** activo a los destinatarios
  del reporte (`senders.enviar_email_adjunto`, MIME multipart). Lógica pura en `monitor/reportes.py`.
  API `ReporteProgramadoController` (CRUD, valida correos, auditado), rutas en `$crud`. UI: sección
  "Programación de reportes" en la pantalla Reportes (gated por rol). Cierra el ciclo de informe a gerencia.

- ✅ OBSERVABILIDAD DE SERVICIOS (Camino A) (2026-06-16) [migr. 0018, tablas `servicios` + `servicio_componentes`]:
  pasa de "el servidor está UP" a "por qué el usuario percibe lentitud y dónde está el cuello de botella".
  Una **transacción observable** es una cadena ordenada de componentes (Web→API Gateway→Catálogo→BD), cada
  uno enlazado a un recurso que SIMON ya mide; toma su latencia (último `chequeos.latencia_ms`) y estado.
  `ServicioController` CRUD (componentes anidados) + `GET /servicios/{id}/analisis` que correlaciona:
  experiencia (latencia del salto de entrada) vs `objetivo_ms`, **cuello de botella** (peor estado, luego
  mayor latencia) marcado como causa raíz (con el motivo de su incidencia abierta si la hay), suma de la
  cadena, alto_impacto e impacto al negocio. UI: pantalla "Servicios" (lista + detalle con experiencia,
  flujo de correlación, waterfall por salto, causa raíz e impacto; CRUD con editor de cadena, gated por rol).
  NOTA: es observabilidad "desde afuera" con los datos que SIMON ya recoge — NO instrumenta las apps del
  cliente. Camino B (pendiente, decisión del usuario): endpoint de ingesta `POST /ingest/rum|/span` + beacon
  RUM/OTel para experiencia real del usuario y trazas distribuidas reales.

- ✅ AUTO-DESCUBRIMIENTO DE RED (2026-06-17) [migr. 0019, tablas `descubrimiento_escaneos` +
  `descubrimiento_candidatos`] — DESPLEGADO y verificado en producción (escaneo real 192.168.10.0/24):
  el alta de recursos deja de ser 100% manual. Un **barrido de subred** (ping sweep + SNMP
  sysDescr/sysObjectID/sysName) **propone equipos candidatos** para darlos de alta con un clic.
  - **Worker**: `monitor/descubrimiento.py` (puro): `expandir_subred` (CIDR→IPs, tope /22=1024) y
    `clasificar` (keyword en sysDescr → enterprise OID → tipo sugerido). Job `procesar_descubrimientos`
    (cada `DESCUBRIMIENTO_CHECK_SEG`, def 15s) toma los escaneos 'pendiente', hace `icmplib.multiping`
    y a los vivos les pide SNMP sysinfo; deduplica contra recursos por hostname (`recurso_id_por_host`)
    marcando 'existente'. 16 tests nuevos (114 worker en verde).
  - **API**: `DescubrimientoController` (index/show/store/destroy + `agregar`/`descartar` candidatos +
    `tipos`); la community viaja cifrada en `secretos` (pgcrypto, modelo `DescubrimientoEscaneo` usa
    `TieneSecretos`). Lectura para auth; escritura admin/operador; auditado. Rutas explícitas en api.php.
  - **UI**: pantalla "Descubrimiento" (form de barrido + maestro-detalle de candidatos con autorefresco
    mientras corre, alta inline editable —tipo/nombre/sitio/intervalo/community— y descartar). Nav y ruta
    gated a admin/operador.
  - NOTA: sin community solo detecta hosts vivos (ping). FortiSwitch puede clasificar como 'firewall' e
    iDRAC como 'switch_lan' (enterprise OID Dell/Fortinet ambiguo); el tipo es editable en el alta.
  - Es la **1ª de 4 mejoras** pedidas en secuencia.

- ✅ HARDWARE FÍSICO (Redfish + fallback IPMI) (2026-06-17) [migr. 0020, tablas `hardware_inventario` +
  `hardware_componentes`] — DESPLEGADO; plumbing verificado (124 tests + `ng build` + job activo +
  Redfish ServiceRoot confirmado en los iDRAC .10.34/.10.35). **2ª de 4 mejoras.** Salud del equipo
  **fuera de banda** (habla con el BMC, NO instrumenta el SO): fuentes, temperaturas, ventiladores,
  RAID/discos e **inventario** (fabricante/modelo/serial/SKU/BIOS/firmware BMC/CPU/memoria).
  - **Worker**: `probes/redfish.py` (parsers puros `parse_system`/`parse_thermal`/`parse_power`/
    `parse_storage` + `estado_de` que mapea Status.Health OK/Warning/Critical→up/degraded/down; I/O httpx
    Basic Auth recorre Systems→Storage/Drives, Chassis→Thermal/Power, Managers→firmware). `probes/ipmi_probe.py`
    (fallback con `ipmitool sensor`+`fru`, parsers puros). `hardware.py` orquesta (auto: Redfish→IPMI) y
    normaliza a (inventario, componentes). Job `procesar_hardware` (sweep cada `HARDWARE_CHECK_SEG`, def
    300s) persiste el snapshot y **avisa** (`notificar_simple`, sin incidencia) cuando un componente EMPEORA
    a degraded/down (respeta mantenimiento). Opt-in por recurso (`parametros.hardware` =
    `{protocolo:'auto'|'redfish'|'ipmi', bmc_host?, verify_tls?}`); credenciales BMC en `secretos`
    (`bmc_user`/`bmc_password`), cifradas con pgcrypto.
  - **API**: `GET /recursos/{id}/hardware` → `{inventario, componentes}` (componentes peor-estado primero).
  - **UI**: sección "Hardware físico" en el detalle del recurso (tarjeta de inventario + componentes por
    categoría —chasis/energía/temperatura/ventiladores/almacenamiento— con semáforo y lectura numérica).
  - VERIFICADO EN VIVO (2026-06-17): activado en PNNCSRVNCFHV2 (id 24, iDRAC .10.35) con Redfish —
    Dell R640, serial CNCMS00175000K, BIOS 2.26.1, BMC fw 7.00.00.184, 2× Xeon Silver 4210, 192 GB,
    16 ventiladores, 2 fuentes, 4 térmicos, RAID (BOSS-S1 + PERC H330) con SSDs y volúmenes, todo `up`.
    Fixes durante la verificación: `desambiguar` nombres repetidos ('Temp'), timeout amplio 30s (iDRAC lento,
    caía a IPMI), y tolerar `Volumes`/`Drives` como REFERENCIA (no lista inline) expandiéndolos.
  - INCIDENCIAS POR COMPONENTE [migr. 0022] (2026-06-17): el aviso (`notificar_simple`) se reemplazó por
    INCIDENCIAS FORMALES por componente. `incidencias.componente` (texto, p.ej. 'power:PSU1') + índice único
    ampliado a (recurso, COALESCE(if_index,-1), COALESCE(componente,'')); `incidencia_abierta` filtra
    `componente IS NULL`. `_gestionar_incidencias_hardware` abre (down→critical, degraded→warning), escala
    (degraded↔down) y cierra al recuperarse, notificando por el motor de incidencias (reconocible/resoluble,
    sale en Incidencias/wallboard). Respeta mantenimiento.
  - MÁS SERVIDORES (2026-06-17): hardware activado también en PNNCSRVNCFHV1 (id 76, iDRAC .10.34, Dell R640
    serial CNCMS0017400YT, vía Redfish, salud up). Como su iDRAC no responde SNMP, su estado base se vigila
    por ping con el nuevo override `parametros.metodo='icmp'` (en `seleccionar_probe`; útil para BMC/hosts sin
    SNMP). PENDIENTE: el resto de servidores requiere sus IP de iDRAC (solo se conocen .10.34/.35).
  - FortiSwitches de piso: backup SSH VERIFICADO EN VIVO (2026-06-17) — los 14 (.10.41-.54) respaldados por
    SSH con `admin`/clave propia (vendor 'fortiswitch'). Requirió soporte FortiOS en `ssh_config`: el paginador
    se desactiva con la secuencia `config system console / set output standard / end` (enviada línea a línea),
    el comando es `show full-configuration`, y el prompt FortiOS ('NOMBRE # ') se reconoce por no-indentación.
    Cada config ~126-173 KB; el job tarda ~2.5 min para los 14 (diario a las 02:00, aceptable).
  - Pendiente de la secuencia (decisión del usuario): (4) **Backup config por SSH
    (switches) + topología L2 automática (LLDP)**.

- ✅ CHEQUEOS SINTÉTICOS MULTIPASO (2026-06-17) — DESPLEGADO (sin migración; worker + frontend).
  **3ª de 4 mejoras.** Monitoreo de transacción de caja-negra (NO intrusivo): una secuencia de pasos
  HTTP como un usuario sintético (p.ej. login→consulta), con aserciones por paso y encadenamiento de
  variables (extraer un token del paso 1 y usarlo en el 2). Reusa TODO el pipeline existente
  (estado/incidencias/métricas) — no hay entidad nueva.
  - **Worker**: `probes/sintetico.py`. Helpers PUROS testeables (`json_path_get`, `interpolar` con
    `{{var}}`, `evaluar_paso` aserciones status/contiene/no_contiene/json_path/max_ms, `extraer_variables`
    de `json:ruta`/`header:Nombre`, `resumir` → up/degraded/down). I/O con un `httpx.Client` que mantiene
    cookies entre pasos (login→query) + `medir_fases` (DNS/TCP/TLS por socket). Estado: down si un paso
    falla una aserción (transacción rota), degraded si todo pasa pero algún paso fue lento (max_ms).
    Métricas emitidas: latency(total), dns_ms/tcp_ms/tls_ms, ttfb_ms, pasos_ok/pasos_total → se grafican
    e historizan solas. Opt-in: `parametros.pasos` (no vacío) → `SinteticoProbe` (precede a HttpProbe).
    25 tests nuevos (139 worker en verde).
  - **UI**: sección "Transacción sintética" en el detalle del recurso (fases DNS/TCP/TLS + tabla de pasos
    con status/tiempo/resultado y motivo del fallo). Ayuda con ejemplo de `pasos` en el form de Recursos.
  - **Config** (ejemplo): `parametros.pasos = [{"nombre":"Login","metodo":"POST","path":"/login",
    "cuerpo":{...},"extraer":{"tok":"json:token"}}, {"nombre":"Consulta","path":"/api",
    "headers":{"Authorization":"Bearer {{tok}}"},"contiene":"ok","max_ms":2000}]`. Credenciales en
    `secretos` (interpolables como `{{...}}` y como basic_auth_user/api_key).
  - Pendiente de la secuencia (decisión del usuario): (4) **Backup config por SSH (switches) + topología
    L2 automática (LLDP)**.

- ✅ BACKUP DE CONFIG POR SSH (switches) (2026-06-17) — DESPLEGADO (sin migración; worker + frontend).
  **4ª mejora, parte A** (la B es topología LLDP). Extiende el respaldo de config (que hoy solo cubre
  FortiGate por API) a switches por SSH: se conecta, deshabilita la paginación y vuelca la config
  (`show running-config`). Reusa la tabla `config_respaldos` + diff + aviso + la sección "Respaldos" del
  detalle (los respaldos SSH aparecen ahí sin cambios de API/UI).
  - **Worker**: `probes/ssh_config.py` (paramiko). Helpers PUROS testeables: `comando_backup`
    (explícito → por vendor/tipo: dell_os9/force10→`show running-configuration`, cisco/arista→
    `show running-config`, fortiswitch→`show full-configuration`), `comando_sin_paginacion`
    (`terminal length 0`), `limpiar_salida` (quita eco/paginador/prompt). I/O `obtener_config` con shell
    interactivo (invoke_shell) y lectura hasta inactividad. El job `respaldar_configuraciones` ahora hace
    FortiGate (API) **+** los recursos opt-in `parametros.backup.metodo='ssh'`; helper común
    `_guardar_respaldo_si_cambio`. 8 tests nuevos (148 worker en verde).
  - **Config**: `parametros.backup = {metodo:'ssh', vendor?, comando?, puerto?:22, sin_paginacion?}` +
    secretos `{ssh_user, ssh_password}` o `{ssh_user, ssh_key}` (PEM). Ayuda en el form de Recursos.
  - VERIFICADO EN VIVO (2026-06-17): activado en SW-CORE-01 (id 23, Dell EMC OS 9.14) — volcó 33,827 bytes /
    1485 líneas de `show running-config` (de "Current Configuration" a "end"), guardado en `config_respaldos`.
    Fix durante la verificación: Dell OS9 9.14 acepta `show running-config` pero NO la forma larga
    `show running-configuration` ("Invalid input"); login cae directo en modo enable (prompt `#`).

- ✅ TOPOLOGÍA L2 AUTOMÁTICA POR LLDP (2026-06-17) [migr. 0021, tabla `lldp_vecinos`] — DESPLEGADO.
  **4ª mejora, parte B** (cierra la secuencia de 4). El worker camina la LLDP-MIB por SNMP de cada switch
  y registra sus VECINOS (qué equipo/puerto cuelga de cada puerto local); agregado entre switches = mapa
  de conexiones físicas, sin dibujarlo a mano. Usa la community SNMP ya configurada (no pide credenciales nuevas).
  - **Worker**: `probes/lldp.py` (parseo PURO de lldpRemTable —chassis/portId/portDesc/sysName/sysDesc—
    y lldpLocPortTable; `fmt_chassis` formatea MAC; el índice OID da el puerto local). Job
    `recolectar_topologia` (sweep cada `TOPOLOGIA_CHECK_SEG`, def 600s) hace los walks con `snmp_client`,
    parsea y persiste; resuelve el vecino a un recurso conocido por sysName (`lldp_vecinos.recurso_remoto_id`).
    8 tests nuevos (156 worker en verde).
  - **API**: `GET /recursos/{id}/vecinos` (tabla del detalle) y `GET /topologia` (grafo: nodos + enlaces,
    dedup de enlaces no dirigidos, nodos externos para vecinos no gestionados).
  - **UI**: sección "Vecinos LLDP" en el detalle del switch (puerto local→vecino/puerto, link al recurso
    remoto) + pantalla "Topología" (grafo SVG con layout circular: recursos en anillo interior coloreados
    por estado, externos fuera; clic en nodo→recurso). Nav + ruta.
  - NOTA: requiere LLDP activo en los equipos. Los vecinos no gestionados aparecen como nodos "externos".
  - RESOLUCIÓN POR IP DE GESTIÓN [migr. 0023] (2026-06-17): como el sysName LLDP rara vez coincide con el
    nombre del recurso en SIMON, ahora se camina también `lldpRemManAddrTable` (la IP va en el ÍNDICE del OID;
    `parse_direcciones_gestion` la extrae para IPv4) y se guarda `lldp_vecinos.remote_mgmt`. El resolver enlaza
    el vecino a un recurso por `hostname`=IP_de_gestión (COALESCE) y, si no, por sysName. UI: columna "Gestión".
  - ENLACE POR MAC DE CHASSIS (2026-06-17): como estos switches NO publican lldpRemManAddr y el sysName no
    coincide, el resolver añade un 3er método: lee el chassis-id propio de cada switch (`lldpLocChassisId`),
    arma un mapa MAC→recurso y enlaza el vecino cuyo `remote_chassis` coincida. Resultado real: 19 enlaces
    gestionados (los anillos/stacks de FortiSwitch por piso). Orden de resolución: MAC → IP gestión → sysName.

Con esto quedan las **4 mejoras** de la secuencia (auto-descubrimiento, hardware, sintéticos, backup SSH +
topología LLDP), todas en producción y **todas verificadas EN VIVO**: auto-descubrimiento (escaneo real),
hardware Redfish (Dell R640 en id 24), sintéticos (transacción 2 pasos), backup SSH (SW-CORE-01 Dell OS9,
33 KB) y topología LLDP (286 vecinos). Secuencia de 4 mejoras COMPLETA.

- ✅ OLA DE VISIBILIDAD DE RED (2026-06-17) — EN PRODUCCIÓN, VERIFICADA EN VIVO:
  - **NetFlow/IPFIX (#1)** [migr. 0024, tabla `flujos`]: servicio systemd `simon-netflow`
    (`monitor/netflow_listener.py`, UDP/2055) con parser PURO v5/v9/IPFIX (templates) en
    `monitor/netflow.py`; agrega el TOP-N de conversaciones por ventana (def 60s, top 50) y mapea el
    exportador→recurso. API `FlujoController` (top hablantes/destinos/apps/conversaciones por rango);
    pantalla **Flujos**. ufw 2055/udp. VERIFICADO: FortiGate exporta (config `system netflow` +
    `config collectors` en FortiOS 7.x; sampler por interfaz `set netflow-sampler both` en la WAN);
    100+ conversaciones reales, top app = syslog. El `recurso_id_por_host` ahora empareja **ignorando
    el puerto** del hostname (`split_part(hostname,':',1)`) para vincular el exportador `192.168.50.1`
    al recurso FortiGate cuyo hostname es `192.168.50.1:25443` (también arregla el enlace de traps).
  - **Calidad WAN activa (#4)** [migr. 0024, tabla `wan_calidad`]: job `medir_calidad_wan` (opt-in
    `parametros.wan_calidad`), mide latencia/jitter/pérdida (ICMP) + throughput (iperf3 si hay
    `iperf_host`) y estima **MOS** por E-model (Ie-eff logarítmico, `monitor/wan_calidad.py`). Opción
    `target` para sondear un destino concreto (p.ej. 1.1.1.1 = enlace de Internet del sitio) en vez del
    hostname. Emite métricas `wan_*` + tabla; API `WanCalidadController`; panel "Calidad de enlace WAN"
    en el detalle. VERIFICADO: FortiGate→1.1.1.1 MOS 4.40 "buena"; Starlink Old Providence (caído)
    detectado "mala" (100% pérdida). iperf3 instalado.

- ✅ OLAS 2–5 + GLPI (2026-06-17) [migr. 0025–0032] — EN PRODUCCIÓN, VERIFICADAS (190 tests worker
  en verde + `ng build` OK; endpoints probados 200 con JWT acuñado del AUTH_JWT_SECRET):
  - **Auto-remediación / runbooks (#5)** [0025, `runbooks`/`runbook_ejecuciones`]: al abrir una
    incidencia, ejecuta acciones que coincidan con sus disparadores (tipo/severidad/match): **webhook**
    a un orquestador o **comando SSH** al equipo. Lógica pura `monitor/remediacion.py` (coincidencia +
    interpolación `{hostname}`…), hook en `_gestionar_incidencia`, cooldown por (runbook,recurso).
    `RunbookController` (CRUD + secretos pgcrypto), pantalla **Runbooks**.
  - **Cumplimiento de configuración (#7)** [0026, `cumplimiento_politicas`/`_resultados`]: valida la
    última config respaldada (`config_respaldos`) contra políticas golden-config (contiene/no_contiene/
    regex; `monitor/cumplimiento.py`); job `evaluar_cumplimiento` avisa al incumplir. `CumplimientoController`
    (CRUD + GET resultados), pantalla **Cumplimiento**.
  - **Agente ligero (#8)** [0027, `agentes`]: `agent/simon_agent.py` (psutil; Win/Linux) recolecta
    CPU/mem/disco-por-volumen/top-procesos/servicios y hace `POST /api/ingest/agente` autenticado por
    **token** (cabecera X-Agent-Token, sha256 en BD). `IngestController.agente` mete métricas en
    `metricas` y el inventario en `agentes`; `AgenteController` (admin, token visible 1 vez). Pantalla
    **Agentes**.
  - **Virtualización (#9)** [0028, `vm_inventario`]: probe vCenter REST (`monitor/probes/vmware.py`,
    parsers puros) inventaría VMs (power/cpu/mem/guest) de hosts opt-in (`parametros.virtualizacion`);
    job `procesar_virtualizacion`. `VmController` GET `/recursos/{id}/vms`; panel "Máquinas virtuales"
    en el detalle. (Hyper-V se cubre con el agente.)
  - **PWA Web Push (#11)** [0029, `push_suscripciones`]: `public/sw.js` + `manifest.webmanifest`;
    `PushService` (registra SW, suscribe con VAPID), botón 🔔 en la topbar; el motor de notificaciones
    envía push por `pywebpush` al abrir/cerrar incidencias. VAPID generado en el despliegue (clave
    privada en `monitor/vapid_private.pem` ref. por `VAPID_PRIVATE_KEY`; pública en api `.env` →
    `config/push.php` → `/api/push/vapid`).
  - **Status page pública (#12)** [sin migr.]: `GET /api/status` (sin JWT) agrega disponibilidad por
    sede; ruta pública `/status` fuera del Shell (`StatusController` + componente `Status`).
  - **APM RUM/OTel (#13)** [0030, `rum_eventos`/`spans`]: beacon JS en `index.html` reporta el tiempo
    REAL de carga (`/api/ingest/rum`, público) + ingesta de trazas (`/api/ingest/span`, estilo OTel);
    `RumController` (KPIs avg/p95, páginas lentas, errores, spans por servicio), pantalla **Experiencia
    (RUM)**. Es el "Camino B" de observabilidad que estaba pendiente.
  - **AIOps · correlación de alertas (#14)** [0031, `correlaciones` + `incidencias.correlacion_id`]:
    job `correlacionar_incidencias` agrupa incidencias abiertas de la misma sede dentro de una ventana
    (`monitor/correlacion.py`, puro) y marca la **causa raíz** probable (ancestro por dependencia, o la
    más antigua). `CorrelacionController`, pantalla **Correlaciones**. Reduce el ruido del operador.
  - **GLPI (mesa de ayuda, #3 — listo)** [0032, `incidencias.ticket_externo`]: canal de notificación
    tipo `glpi` (`senders._glpi`: initSession→createTicket→killSession por REST) que crea ticket al
    abrir incidencia y guarda su nº. Env-gated: funciona en cuanto se crea un canal `glpi` con
    `url`+`app_token`+`user_token` (sin configurar aún).
  Despliegue: `infra/deploy/40_flujos_wan.sh` (ola 1) y `41_olas2_5.sh` (olas 2–5; migraciones,
  pywebpush, VAPID, servicio `simon-netflow`). NOTA: agente/vCenter/GLPI quedan "listos" pero sin
  credenciales reales; su E/S de red no se validó contra esos servicios.

- ✅ ALERTAS DE ANCHO DE BANDA / SATURACIÓN DE INTERFAZ (2026-11-03) [migr. 0040] — worker verificado
  (235 tests) + `ng build` OK. Cierra el gap competitivo vs PRTG/SolarWinds: SIMON ya recolectaba
  util%/Mbps/errores por interfaz (IF-MIB HC64) pero solo ALERTABA por link up/down. Ahora, sobre las
  interfaces monitoreadas (`monitorear=true`), evalúa **utilización** (% de ifHighSpeed, el peor de
  entrada/salida) y **errores**/intervalo contra umbral y abre/escala/cierra una incidencia de
  **saturación**.
  - **Worker**: lógica pura `monitor/interfaces_umbral.py` (`evaluar_banda`, trivaluada: métrica
    ausente no dispara; umbral 0 = off). `runner._gestionar_incidencias_banda` con anti-flapping
    (`IF_SAT_ATTEMPTS` ciclos seguidos, def 3) y caché `_banda_intentos`. La incidencia reutiliza el
    modelo por interfaz (`if_index`) distinguiéndose de link-down por `componente='saturacion'`
    (índice único ya ampliado por la ola de hardware; `incidencia_interfaz_abierta`/`abrir_incidencia_interfaz`
    ahora reciben `componente`). Notifica apertura/escalada/cierre por el motor de incidencias.
  - **Config**: `IF_UTIL_WARNING` (def 80), `IF_UTIL_CRITICAL` (def 95), `IF_ERR_WARNING`/`IF_ERR_CRITICAL`
    (def 0=off), `IF_SAT_ATTEMPTS` (def 3). Override por interfaz: `interfaces.umbral_util_warning/critical`
    (NULL = usa el global).
  - **API**: `PUT /recursos/{id}/interfaces/{ifIndex}` ahora acepta (opcional) `umbral_util_warning/critical`
    además de `monitorear` (valida 0-100 y crítico≥warning). Auditado por el alcance.
  - **UI**: en la sección "Interfaces de red" del detalle, la columna Util. se colorea warn/crít según
    el umbral efectivo del puerto, y hay una columna "Umbral util. %" editable (warn/crít por interfaz,
    gated por rol). VERIFICADO EN VIVO (2026-11-03): migración + pull + restart worker + rebuild frontend;
    endpoint probado 200/422 con JWT acuñado; 10 interfaces ya ejercen la lógica sin errores.

- ✅ PERCENTIL 95 DE BANDA + TRACEROUTE POR SALTO (2026-11-03) [migr. 0041] — worker 240 tests +
  `ng build` OK. Los dos "opcionales" para rematar la paridad con SolarWinds/PRTG:
  - **Percentil 95 de ancho de banda** (métrica de facturación ISP, firma de SolarWinds): el 95% del
    tiempo el tráfico estuvo por debajo de este valor. `GET /recursos/{id}/interfaces/{ifIndex}/percentil?rango=24h|7d|30d`
    (`percentile_cont(0.95)` sobre `interfaces_historico` in/out + máx). Para el periodo mensual, la
    retención del histórico pasó a ser configurable (`INTERFACES_HIST_RETENCION_DIAS`, def **35**;
    `purgar_datos` la recibe). UI: línea "Percentil 95 (30 d)" en la interfaz expandida.
  - **Traceroute por salto** (hop-by-hop de SolarWinds / herramienta de ruta de PRTG): localiza en qué
    tramo del camino se mete latencia/pérdida (Starlink→ISP→destino). Opt-in `parametros.traceroute =
    true | {target?, max_hops?}`. Worker: `monitor/traceroute.py` (parsers PUROS `parse_traceroute` /
    `parse_tracepath` + I/O `trazar` con `traceroute -n`, fallback `tracepath`); job `recolectar_rutas`
    (cada `TRACEROUTE_CHECK_SEG`, def 600s) guarda la última ruta en tabla `rutas` (reemplazo por recurso).
    API `GET /recursos/{id}/ruta`. UI: sección "Ruta de red" en el detalle (saltos con IP/RTT, marca '*').
    NOTA: requiere `traceroute` o `tracepath` instalado en el servidor (`apt install traceroute`).

- ✅ CANALES DE ALERTA 24×7: correo + Telegram + WhatsApp (2026-11-03) [migr. 0042] — worker 245 tests +
  `ng build` OK. Deja los tres medios cableados de punta a punta para operación 24×7; solo falta
  ingresar credenciales y activar.
  - **Correo (email)**: ya estaba activo en producción (canal "Correo NOC", Gmail/Workspace). Sin cambios.
  - **Telegram**: sender ya existía (`senders._telegram`), solo faltaba el canal. config `{chat_id}` +
    secretos `{bot_token}` (crear bot con @BotFather; chat_id del grupo con @getidsbot).
  - **WhatsApp (NUEVO)**: `senders._whatsapp` con DOS proveedores — **Meta WhatsApp Cloud API** (por
    defecto) y **Twilio**. Payload Meta en función pura testeable `payload_whatsapp_meta` (plantilla si
    hay `template_name`, si no texto plano). Meta: config `{proveedor:'meta', phone_number_id,
    destinatarios[], template_name?, template_lang?='es', api_version?='v22.0'}` + secretos
    `{access_token}`. Twilio: config `{proveedor:'twilio', account_sid, from:'whatsapp:+…',
    destinatarios[]}` + secretos `{auth_token}`. OJO: fuera de la ventana de 24 h Meta exige plantilla
    aprobada.
  - **BD** migr. 0042: el CHECK de `canales_notificacion.tipo` (solo email/sms/webhook/slack/telegram)
    se amplió a incluir teams/whatsapp/glpi (los senders de teams/glpi ya existían pero NO se podían dar
    de alta por el CHECK).
  - **API**: `CanalNotificacionController` ahora valida `whatsapp` en los tipos permitidos.
  - **UI** (Configuración → Canales): `whatsapp` en el selector de tipo + ayuda con la forma exacta de
    config/secretos por medio (email/telegram/whatsapp). El enrutamiento por canal (min_severidad / tipos
    / sitios / horario de guardia) ya existía y aplica a los tres.
  - Se crearon canales placeholder INACTIVOS "Telegram NOC" y "WhatsApp NOC" listos para pegar tokens y
    activar. El motor solo usa canales `activo=true`, así que no envían hasta configurarse.

- ✅ INFORMES REFORZADOS — 4 tipos periódicos (2026-11-03) [migr. 0043] — worker 251 tests + `ng build` OK.
  El motor de reportes programados (`reportes_programados`, job `enviar_reportes_programados`) pasó de
  generar solo disponibilidad/SLA a **4 tipos** seleccionables por informe (columna `tipo`):
  1. **Disponibilidad** (tabla por recurso, % y conteos) — ya existía, ahora es un tipo.
  2. **Cumplimiento de SLA** — misma data filtrada a los recursos con `sla_objetivo`, resalta incumplen.
  3. **Consumo de ancho de banda** — por interfaz: promedio/p95/máx de Mbps in/out sobre
     `interfaces_historico` (repo.datos_banda / ReporteController::banda).
  4. **Alertas enviadas** — detalle de `notificaciones`: fecha/hora, medio (canal), destino, recurso,
     severidad, evento, alerta (payload→asunto), estado y error (repo.datos_alertas / ::alertas).
  - **Worker**: `reportes.py` gana generadores PUROS por tipo (kpis/CSV/PDF de banda y alertas);
    `_construir_reporte` ramifica por `tipo` en el job (PDF fpdf2, cae a CSV). Respeta periodicidad
    (diario/semanal/mensual) y filtros tipo_recurso/sitio; se envía por el canal email.
  - **API**: `GET /reportes/banda` y `/reportes/alertas` (lectura, con alcance por usuario);
    `ReporteProgramadoController` valida `tipo`.
  - **UI** (Reportes → Programación): selector "Tipo de informe" en el alta/edición + columna Tipo.
  - El export on-screen manual (ejecutivo/sitio/recurso/servicios) sigue igual; banda/alertas se
    consultan por sus endpoints.

Nota de numeración: el usuario llamó "FASE 3" a los workers (en el plan original eran FASE 4).
Orden real ejecutado: estructura → datos → API → workers → frontend → notificaciones → despliegue → mejoras.

## Entorno de desarrollo (esta máquina)
- Windows + PowerShell. **NO** hay instalados: `docker`, `psql`, `php`, `composer`, `laravel`.
  → No se pueden ejecutar migraciones, `docker compose`, `php artisan` ni tests aquí;
  el código se escribe a mano y se verifica en la máquina del usuario. No reintentar
  estos comandos en local salvo que el usuario confirme que ya los instaló.