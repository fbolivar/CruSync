// Modelos compartidos (espejo de las respuestas JSON de la API PHP).

export type Estado = 'up' | 'degraded' | 'down' | 'unknown' | 'maintenance';
export type Severidad = 'info' | 'warning' | 'critical';
export type EstadoIncidencia = 'abierta' | 'reconocida' | 'resuelta';
export type Rol = 'admin' | 'operador' | 'viewer';

export interface TipoRecurso {
  id: number;
  codigo: string;
  nombre: string;
}

export interface Sitio {
  id: number;
  codigo: string;
  nombre: string;
  direccion?: string | null;
  ciudad?: string | null;
  latitud?: number | null;
  longitud?: number | null;
  descripcion?: string | null;
  activo?: boolean;
}

export interface Recurso {
  id: number;
  nombre: string;
  hostname?: string | null;
  estado_actual: Estado;
  tipo_id: number;
  sitio_id?: number | null;
  intervalo_segundos: number;
  activo: boolean;
  ultimo_chequeo_at?: string | null;
  parametros?: Record<string, unknown>;
  depende_de_id?: number | null;
  max_check_attempts?: number | null;
  sla_objetivo?: number | null;
  tipo?: TipoRecurso;
  sitio?: Sitio;
  depende_de?: { id: number; nombre: string } | null;
  tiene_secretos?: boolean;
}

export interface Chequeo {
  id: number;
  recurso_id: number;
  ts: string;
  estado: Estado;
  latencia_ms?: number | null;
  detalle?: Record<string, unknown>;
}

// Resultado de un paso de un chequeo sintético (vive en chequeos.detalle.pasos).
export interface PasoSintetico {
  nombre: string;
  url: string;
  status: number | null;
  ok: boolean;
  motivo: string | null;
  ms: number;
  lento?: boolean;
}

export interface Metrica {
  recurso_id: number;
  metrica: string;
  valor: number;
  unidad?: string | null;
  ts: string;
}

export interface Incidencia {
  id: number;
  recurso_id: number;
  estado: EstadoIncidencia;
  severidad: Severidad;
  titulo: string;
  descripcion?: string | null;
  abierta_at: string;
  reconocida_at?: string | null;
  resuelta_at?: string | null;
  recurso?: { id: number; nombre: string };
}

export interface Interfaz {
  recurso_id: number;
  if_index: number;
  if_name: string;
  admin_estado: string;       // up | down
  oper_estado: string;        // up | down
  speed_mbps?: number | null;
  in_mbps?: number | null;
  out_mbps?: number | null;
  util_in?: number | null;
  util_out?: number | null;
  in_err?: number | null;
  out_err?: number | null;
  monitorear?: boolean;
  umbral_util_warning?: number | null;   // override de util % (warning); null = global
  umbral_util_critical?: number | null;  // override de util % (crítico); null = global
  ts: string;
}

export interface MuestraInterfaz {
  ts: string;
  in_mbps: number | null;
  out_mbps: number | null;
}

export interface Baseline {
  metrica: string;
  hora: number;          // 0-23 (UTC)
  media: number;
  desviacion: number;
  muestras: number;
  actualizado_at: string;
}

export interface Respaldo {
  id: number;
  ts: string;
  bytes: number | null;
  cambio: boolean;
}

export interface RespaldoDetalle extends Respaldo {
  diff: string | null;
  contenido: string;
}

export interface FilaDisponibilidad {
  id: number;
  nombre: string;
  tipo_id: number;
  sitio_id: number | null;
  tipo_nombre: string;
  sitio_nombre: string | null;
  estado_actual: Estado;
  evaluables_total: number;
  up: number;
  degraded: number;
  down: number;
  unknown: number;
  mantenimiento: number;
  incidencias: number;
  disponibilidad: number | null;
  /** Objetivo de SLA efectivo (recurso o, si no, el del tipo). null = sin objetivo. */
  sla_objetivo: number | null;
  /** true/false; null = sin objetivo o sin datos (nunca se marca incumplimiento sin medir). */
  cumple_sla: boolean | null;
}

export interface ReporteDisponibilidad {
  rango: string;
  desde: string;
  /** 'historico' cuando el rango supera los 30 días (viene de disponibilidad_diaria). */
  fuente?: string;
  recursos: FilaDisponibilidad[];
}

export type TipoComponente = 'web' | 'api' | 'gateway' | 'cache' | 'db' | 'externo' | 'servicio';

export interface ServicioComponente {
  id?: number;
  orden?: number;
  nombre: string;
  tipo: TipoComponente;
  recurso_id?: number | null;
  umbral_ms?: number | null;
}

export interface Servicio {
  id: number;
  nombre: string;
  descripcion?: string | null;
  objetivo_ms: number;
  impacto_negocio?: string | null;
  activo: boolean;
  componentes?: ServicioComponente[];
}

export interface ComponenteAnalisis {
  orden: number;
  nombre: string;
  tipo: TipoComponente;
  recurso_id: number | null;
  recurso_nombre: string | null;
  estado: Estado;
  latencia_ms: number | null;
  infra: boolean;            // equipo SNMP: aporta salud, no latencia de servicio
  umbral_ms: number | null;
  supera_umbral: boolean;
}

export interface ServicioAnalisis {
  id: number;
  nombre: string;
  descripcion?: string | null;
  objetivo_ms: number;
  impacto_negocio?: string | null;
  activo: boolean;
  estado: Estado;
  experiencia_ms: number | null;
  total_ms: number;
  alto_impacto: boolean;
  cuello: { nombre: string; latencia_ms: number | null; recurso_id: number | null; estado: Estado } | null;
  causa: string | null;
  componentes?: ComponenteAnalisis[];
}

export const TIPOS_COMPONENTE: TipoComponente[] = ['web', 'api', 'gateway', 'cache', 'db', 'externo', 'servicio'];

export interface ReporteProgramado {
  id: number;
  nombre: string;
  periodo: 'diario' | 'semanal' | 'mensual';
  rango: '24h' | '7d' | '30d';
  destinatarios: string;
  formato: 'pdf' | 'csv';
  activo: boolean;
  ultimo_envio_at?: string | null;
  /** Filtro opcional del informe (null = todos los recursos). */
  tipo_id?: number | null;
  sitio_id?: number | null;
}

export interface Pronostico {
  recurso_id: number;
  recurso_nombre: string;
  metrica: string;
  ts: string;
  valor_actual: number;
  pendiente_dia: number;
  dias_restantes: number | null;
  techo: number;
  r2: number | null;
  muestras: number;
}

export interface AuditoriaEntrada {
  id: number;
  ts: string;
  perfil_id: string | null;
  actor_email: string | null;
  actor_rol: string | null;
  accion: string;       // crear | actualizar | eliminar | login | login_fallido
  entidad: string;
  entidad_id: string | null;
  descripcion: string | null;
  cambios: Record<string, [unknown, unknown]> | null;
  ip: string | null;
}

export interface Trap {
  id: number;
  ts: string;
  source_ip: string | null;
  recurso_id: number | null;
  recurso_nombre: string | null;
  trap_oid: string | null;
  nombre: string | null;
  severidad: Severidad;
  descripcion: string | null;
  varbinds: Record<string, string> | null;
}

export interface Perfil {
  id: string;
  email: string;
  nombre?: string | null;
  rol: Rol;
  activo: boolean;
  origen?: string;
  totp_activo?: boolean;
  /** El usuario está acotado a unas territoriales (la API filtra lo que ve). */
  acotado?: boolean;
  sitios?: number[] | null;
  /** Territoriales asignadas (solo en el listado de admin). Vacío = ve toda la entidad. */
  alcance_sitios?: { id: number; nombre: string }[];
}

export interface Umbral {
  id: number;
  recurso_id?: number | null;
  tipo_id?: number | null;
  metrica: string;
  operador: string;
  valor_warning?: number | null;
  valor_critical?: number | null;
  duracion_segundos: number;
  activo: boolean;
}

export interface Regla {
  id: number;
  recurso_id?: number | null;
  tipo_id?: number | null;
  nombre: string;
  descripcion?: string | null;
  expresion: Record<string, unknown>;
  severidad: Severidad;
  duracion_segundos: number;
  activo: boolean;
}

export interface Mantenimiento {
  id: number;
  recurso_id?: number | null;
  sitio_id?: number | null;
  inicio: string;
  fin: string;
  motivo: string;
  recurso?: { id: number; nombre: string };
  sitio?: { id: number; nombre: string };
}

export interface Canal {
  id: number;
  tipo: string;
  nombre: string;
  config?: Record<string, unknown>;
  activo: boolean;
  tiene_secretos?: boolean;
}

export interface LdapConfig {
  enabled: boolean;
  host: string | null;
  port: number;
  use_tls: boolean;
  bind_pattern: string;
  rol_default: string;
  group_dn?: string;
  auto_create?: boolean;
  usuarios_permitidos?: string;
}

export const OPERADORES = ['>', '>=', '<', '<=', '==', '!='];
export const TIPOS_CANAL = ['email', 'sms', 'webhook', 'slack', 'telegram', 'teams'];
export const ROLES: Rol[] = ['admin', 'operador', 'viewer'];
export const SEVERIDADES: Severidad[] = ['info', 'warning', 'critical'];

// Paginador de Laravel.
export interface Paginated<T> {
  data: T[];
  current_page: number;
  last_page: number;
  per_page: number;
  total: number;
}

// ── Topología L2 (LLDP) ────────────────────────────────────────────────
export interface VecinoLldp {
  local_port: string | null;
  local_port_num: number | null;
  remote_sysname: string | null;
  remote_port: string | null;
  remote_chassis: string | null;
  remote_sysdesc: string | null;
  remote_mgmt: string | null;
  recurso_remoto_id: number | null;
  remoto_nombre: string | null;
  ts: string;
}

export interface TopologiaNodo {
  id: string;
  nombre: string;
  estado: Estado | null;
  es_recurso: boolean;
  hostname?: string | null;
  sitio_id?: number | null;
  sitio?: string | null;
  tipo?: string | null;
  tipo_nombre?: string | null;
  grado?: number;
}

export interface TopologiaEnlace {
  origen: string;
  origen_port: string | null;
  destino: string;
  destino_port: string | null;
}

export interface TopologiaResp {
  nodos: TopologiaNodo[];
  enlaces: TopologiaEnlace[];
}

// ── Flujos de tráfico (NetFlow/IPFIX) ──────────────────────────────────
export interface FlujoAgregado {
  ip?: string;
  app?: string;
  src_ip?: string;
  dst_ip?: string;
  dst_port?: number | null;
  protocolo?: number | null;
  bytes: number;
  paquetes: number;
}

export interface FlujosResp {
  rango: string;
  total_bytes: number;
  talkers: FlujoAgregado[];
  destinos: FlujoAgregado[];
  apps: FlujoAgregado[];
  conversaciones: FlujoAgregado[];
}

export interface FlujoOverview {
  rango: string;
  kpis: {
    total_bytes: number; total_delta: number | null;
    avg_mbps: number; avg_delta: number | null;
    flows: number; flows_delta: number | null;
    hosts: number; hosts_delta: number | null;
  };
  spark: { traffic: number[]; flows: number[]; hosts: number[]; bandwidth: number[] };
  serie: { labels: string[]; apilada: { app: string; valores: number[] }[] };
  apps: { app: string; bytes: number }[];
  protocolos: { proto: string; bytes: number }[];
  talkers: { ip: string; bytes: number; pct: number }[];
  destinos: { ip: string; bytes: number; pct: number }[];
  flujo: { src: string; dst: string; app: string; bytes: number }[];
}

// ── Calidad activa de enlace WAN ───────────────────────────────────────
export interface WanCalidadMuestra {
  id: number;
  ts: string;
  latency_ms: number | null;
  jitter_ms: number | null;
  loss_pct: number | null;
  down_mbps: number | null;
  up_mbps: number | null;
  mos: number | null;
  calidad: 'buena' | 'aceptable' | 'mala' | null;
}

export interface WanCalidadResp {
  ultimo: WanCalidadMuestra | null;
  serie: WanCalidadMuestra[];
}

// ── Olas 2–5 ───────────────────────────────────────────────────────────
export interface Runbook {
  id: number;
  nombre: string;
  descripcion?: string | null;
  activo: boolean;
  trigger_tipo_id?: number | null;
  trigger_severidad?: 'info' | 'warning' | 'critical' | null;
  trigger_match?: string | null;
  accion: { tipo: 'webhook' | 'ssh'; [k: string]: unknown };
  cooldown_seg?: number;
  tiene_secretos?: boolean;
  ejecuciones?: RunbookEjecucion[];
}
export interface RunbookEjecucion {
  id: number; ts: string; exito: boolean; salida: string | null;
  incidencia_id?: number | null; recurso_id?: number | null;
}

export interface PoliticaCumplimiento {
  id: number;
  nombre: string;
  descripcion?: string | null;
  tipo: 'contiene' | 'no_contiene' | 'regex';
  patron: string;
  severidad: 'info' | 'warning' | 'critical';
  aplica_tipo_id?: number | null;
  activo: boolean;
}
export interface ResultadoCumplimiento {
  id: number; recurso_id: number; politica_id: number; cumple: boolean;
  detalle: string | null; ts: string; politica: string; severidad: string; recurso_nombre: string;
}

export interface Vm {
  id: number; vm_id: string; nombre: string | null; power_state: string | null;
  cpu_count: number | null; memoria_mb: number | null; guest_os: string | null; ts: string;
}
export interface VmResp { total: number; encendidas: number; vms: Vm[]; }

export interface Agente {
  id: number; recurso_id: number | null; nombre: string; hostname: string | null;
  so: string | null; version: string | null; last_seen: string | null;
  inventario?: Record<string, unknown> | null; activo: boolean;
}

export interface RumResp {
  rango: string;
  kpis: { muestras: number; avg_ms: number | null; p95_ms: number | null; max_ms: number | null };
  errores: number;
  por_url: { url: string; muestras: number; avg_ms: number; max_ms: number }[];
  spans: { servicio: string; n: number; avg_ms: number }[];
}

export interface Correlacion {
  id: number; creada_at: string; sitio_id: number | null; sitio_nombre: string | null;
  causa_incidencia_id: number | null; resumen: string; n_incidencias: number; abierta: boolean;
  incidencias: { id: number; titulo: string; severidad: string; estado: string;
    inicio: string; recurso_nombre: string }[];
}

// ── Hardware físico (Redfish / IPMI) ───────────────────────────────────
export interface HardwareInventario {
  recurso_id: number;
  fabricante: string | null;
  modelo: string | null;
  serial: string | null;
  sku: string | null;
  bios_version: string | null;
  bmc_firmware: string | null;
  cpu_modelo: string | null;
  cpu_cantidad: number | null;
  memoria_gb: number | null;
  power_state: string | null;
  salud_global: Estado | null;
  protocolo: string | null;
  actualizado_at: string;
}

export interface HardwareComponente {
  categoria: string;
  nombre: string;
  estado: Estado;
  lectura: number | null;
  unidad: string | null;
  detalle: Record<string, unknown> | null;
  actualizado_at: string;
}

export interface HardwareResp {
  inventario: HardwareInventario | null;
  componentes: HardwareComponente[];
}

// ── Auto-descubrimiento de red ─────────────────────────────────────────
export type DescubrimientoEstado = 'pendiente' | 'ejecutando' | 'completado' | 'error';
export type CandidatoEstado = 'nuevo' | 'agregado' | 'descartado' | 'existente';

export interface DescubrimientoEscaneo {
  id: number;
  subred: string;
  snmp_version: string;
  estado: DescubrimientoEstado;
  total_vivos: number | null;
  total_candidatos: number | null;
  mensaje: string | null;
  created_at: string;
  completado_at: string | null;
  candidatos_count?: number;
  candidatos_nuevos?: number;
  candidatos?: DescubrimientoCandidato[];
}

export interface DescubrimientoCandidato {
  id: number;
  escaneo_id: number;
  ip: string;
  sysname: string | null;
  sysdescr: string | null;
  sysobjectid: string | null;
  tipo_sugerido: string | null;
  responde_snmp: boolean;
  latencia_ms: number | null;
  estado: CandidatoEstado;
  recurso_id: number | null;
}

export const ESTADOS: Estado[] = ['up', 'degraded', 'down', 'unknown', 'maintenance'];

export const ESTADO_LABEL: Record<Estado, string> = {
  up: 'Operativo',
  degraded: 'Degradado',
  down: 'Caído',
  unknown: 'Desconocido',
  maintenance: 'Mantenimiento',
};

/** Respaldo .pnnc (módulo de backup, formato propio PNNC). */
export interface Backup {
  id: string;
  tam: number;
  creado_en: string | null;
  cifrado: string | null;
  sha256: string | null;
  base_datos: string | null;
  servidor: string | null;
  nota: string | null;
  app_version: string | null;
}

/** Nota de la bitácora del operador sobre una incidencia. */
export interface NotaIncidencia {
  id: number;
  autor_email: string | null;
  nota: string;
  created_at: string;
}
