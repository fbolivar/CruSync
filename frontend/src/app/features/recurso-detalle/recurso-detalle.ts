import { DecimalPipe, JsonPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Baseline, Chequeo, HardwareComponente, HardwareInventario, Incidencia, Interfaz, Metrica, MuestraInterfaz, PasoSintetico, Recurso, Respaldo, RespaldoDetalle, VecinoLldp, VmResp, WanCalidadResp } from '../../core/models';
import { AuthService } from '../../core/auth.service';
import { OperacionService } from '../../core/operacion.service';
import { RecursosService } from '../../core/recursos.service';
import { TelemetriaService } from '../../core/telemetria.service';
import { EstadoBadge } from '../../shared/estado-badge';
import { LineChart, Punto } from '../../shared/line-chart';
import { duracion, fecha, hace } from '../../shared/tiempo';

interface SerieMetrica { metrica: string; unidad: string; puntos: Punto[]; }

@Component({
  selector: 'app-recurso-detalle',
  standalone: true,
  imports: [RouterLink, JsonPipe, DecimalPipe, EstadoBadge, LineChart],
  templateUrl: './recurso-detalle.html',
  styleUrl: './recurso-detalle.scss',
})
export class RecursoDetalle {
  private route = inject(ActivatedRoute);
  private recursosSvc = inject(RecursosService);
  private opSvc = inject(OperacionService);
  private tele = inject(TelemetriaService);
  auth = inject(AuthService);

  id = 0;
  recurso = signal<Recurso | null>(null);
  ultimoChequeo = signal<Chequeo | null>(null);
  metricas = signal<Metrica[]>([]);
  incidencias = signal<Incidencia[]>([]);
  interfaces = signal<Interfaz[]>([]);
  respaldos = signal<Respaldo[]>([]);
  baselines = signal<Baseline[]>([]);
  hwInventario = signal<HardwareInventario | null>(null);
  hwComponentes = signal<HardwareComponente[]>([]);
  vecinos = signal<VecinoLldp[]>([]);
  wan = signal<WanCalidadResp | null>(null);
  vms = signal<VmResp | null>(null);
  respaldoSel = signal<RespaldoDetalle | null>(null);
  respaldoVista = signal<'diff' | 'completo'>('diff');
  rango = signal<'1h' | '24h' | '7d'>('24h');
  cargando = signal(true);

  // Histórico por interfaz (gráfica expandible)
  ifExpandida = signal<number | null>(null);
  ifRango = signal<'1h' | '24h' | '7d'>('24h');
  ifHist = signal<MuestraInterfaz[]>([]);
  ifCargandoHist = signal(false);

  serieIn = computed<Punto[]>(() => this.ifHist().map((m) => ({ ts: m.ts, valor: m.in_mbps ?? 0 })));
  serieOut = computed<Punto[]>(() => this.ifHist().map((m) => ({ ts: m.ts, valor: m.out_mbps ?? 0 })));

  fecha = fecha;
  hace = hace;
  duracion = duracion;
  max = (a?: number | null, b?: number | null) => Math.max(a ?? 0, b ?? 0);

  // ── Línea base / anomalías ──
  horaUtc = new Date().getUTCHours();
  // Métricas con detección de anomalías activada (opt-in en parametros).
  baselineMetricas = computed<string[]>(() => {
    const p = this.recurso()?.parametros as Record<string, unknown> | undefined;
    const v = p?.['baseline_metricas'];
    return Array.isArray(v) ? (v as string[]) : [];
  });
  // Líneas base de la hora actual (UTC), ordenadas por métrica.
  baselineHoraActual = computed<Baseline[]>(() =>
    this.baselines().filter((b) => b.hora === this.horaUtc).sort((a, b) => a.metrica.localeCompare(b.metrica)),
  );
  // Límite de anomalía ≈ media + max(3σ, 5) (defaults del worker).
  limiteAnomalia(b: Baseline): number {
    return b.media + Math.max(3 * b.desviacion, 5);
  }

  series = computed<SerieMetrica[]>(() => {
    const porMetrica = new Map<string, Metrica[]>();
    for (const m of this.metricas()) {
      (porMetrica.get(m.metrica) ?? porMetrica.set(m.metrica, []).get(m.metrica)!).push(m);
    }
    return [...porMetrica.entries()]
      .map(([metrica, ms]) => ({
        metrica,
        unidad: ms[0]?.unidad ?? '',
        puntos: ms.map((m) => ({ ts: m.ts, valor: m.valor })),
      }))
      .sort((a, b) => a.metrica.localeCompare(b.metrica));
  });

  // Chequeo sintético: pasos y fases del último chequeo (si aplica).
  pasosSinteticos = computed<PasoSintetico[] | null>(() => {
    const d = this.ultimoChequeo()?.detalle as Record<string, unknown> | undefined;
    return Array.isArray(d?.['pasos']) ? (d!['pasos'] as PasoSintetico[]) : null;
  });
  fasesSinteticas = computed<{ nombre: string; ms: number }[]>(() => {
    const d = this.ultimoChequeo()?.detalle as Record<string, unknown> | undefined;
    const f = (d?.['fases'] ?? {}) as Record<string, number>;
    const orden: [string, string][] = [['dns_ms', 'DNS'], ['tcp_ms', 'TCP'], ['tls_ms', 'TLS']];
    return orden.filter(([k]) => k in f).map(([k, nombre]) => ({ nombre, ms: f[k] }));
  });

  // Hardware agrupado por categoría (orden lógico para la UI).
  hwCatLabel: Record<string, string | undefined> = {
    chassis: 'Chasis', power: 'Energía', thermal: 'Temperatura', fan: 'Ventiladores',
    storage: 'Almacenamiento', memory: 'Memoria', processor: 'Procesador',
  };
  hwCategorias = computed<{ categoria: string; comps: HardwareComponente[] }[]>(() => {
    const orden = ['chassis', 'power', 'thermal', 'fan', 'storage', 'memory', 'processor'];
    const map = new Map<string, HardwareComponente[]>();
    for (const c of this.hwComponentes()) {
      (map.get(c.categoria) ?? map.set(c.categoria, []).get(c.categoria)!).push(c);
    }
    return [...map.entries()]
      .sort((a, b) => orden.indexOf(a[0]) - orden.indexOf(b[0]))
      .map(([categoria, comps]) => ({ categoria, comps }));
  });

  constructor() {
    // Reacciona a cambios de :id (Angular reutiliza el componente entre recursos).
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      const id = Number(pm.get('id'));
      if (!Number.isFinite(id) || id <= 0) return;
      this.id = id;
      this.cargarTodo();
    });
  }

  private cargarTodo(): void {
    this.recurso.set(null);
    this.ultimoChequeo.set(null);
    this.incidencias.set([]);
    this.interfaces.set([]);
    this.recursosSvc.obtener(this.id).subscribe({
      next: (r) => this.recurso.set(r),
      error: () => {},
    });
    this.recursosSvc.interfaces(this.id).subscribe({
      next: (xs) => this.interfaces.set(xs),
      error: () => this.interfaces.set([]),
    });
    this.respaldoSel.set(null);
    this.recursosSvc.respaldos(this.id).subscribe({
      next: (rs) => this.respaldos.set(rs),
      error: () => this.respaldos.set([]),
    });
    this.baselines.set([]);
    this.recursosSvc.baselines(this.id).subscribe({
      next: (bs) => this.baselines.set(bs),
      error: () => this.baselines.set([]),
    });
    this.hwInventario.set(null);
    this.hwComponentes.set([]);
    this.recursosSvc.hardware(this.id).subscribe({
      next: (h) => { this.hwInventario.set(h.inventario); this.hwComponentes.set(h.componentes); },
      error: () => { this.hwInventario.set(null); this.hwComponentes.set([]); },
    });
    this.vecinos.set([]);
    this.recursosSvc.vecinos(this.id).subscribe({
      next: (vs) => this.vecinos.set(vs),
      error: () => this.vecinos.set([]),
    });
    this.wan.set(null);
    this.recursosSvc.wanCalidad(this.id, '24h').subscribe({
      next: (w) => this.wan.set(w?.ultimo ? w : null),
      error: () => this.wan.set(null),
    });
    this.vms.set(null);
    this.opSvc.vms(this.id).subscribe({
      next: (v) => this.vms.set(v?.total ? v : null),
      error: () => this.vms.set(null),
    });
    this.tele.chequeos({ recurso_id: this.id, per_page: 1 }).subscribe({
      next: (p) => this.ultimoChequeo.set(p.data[0] ?? null),
    });
    this.tele.incidencias({ recurso_id: this.id, per_page: 50 }).subscribe({
      next: (p) => this.incidencias.set(p.data),
    });
    this.cargarMetricas();
  }

  cambiarRango(r: '1h' | '24h' | '7d'): void {
    this.rango.set(r);
    this.cargarMetricas();
  }

  toggleInterfaz(idx: number): void {
    if (this.ifExpandida() === idx) { this.ifExpandida.set(null); return; }
    this.ifExpandida.set(idx);
    this.cargarHistIf();
  }

  cambiarRangoIf(r: '1h' | '24h' | '7d'): void {
    this.ifRango.set(r);
    this.cargarHistIf();
  }

  private cargarHistIf(): void {
    const idx = this.ifExpandida();
    if (idx == null) return;
    this.ifCargandoHist.set(true);
    this.ifHist.set([]);
    this.recursosSvc.interfazHistorico(this.id, idx, this.ifRango()).subscribe({
      next: (h) => { this.ifHist.set(h); this.ifCargandoHist.set(false); },
      error: () => this.ifCargandoHist.set(false),
    });
  }

  verRespaldo(r: Respaldo): void {
    if (this.respaldoSel()?.id === r.id) { this.respaldoSel.set(null); return; }
    this.respaldoVista.set(r.cambio ? 'diff' : 'completo');
    this.recursosSvc.respaldoContenido(this.id, r.id).subscribe({
      next: (d) => this.respaldoSel.set(d),
      error: () => this.respaldoSel.set(null),
    });
  }

  toggleMonitorear(x: Interfaz): void {
    const nuevo = !x.monitorear;
    this.recursosSvc.interfazMonitorear(this.id, x.if_index, nuevo).subscribe({
      next: () => this.interfaces.update((xs) =>
        xs.map((i) => (i.if_index === x.if_index ? { ...i, monitorear: nuevo } : i))),
      // Si falla, avisa y fuerza re-render para revertir el checkbox al estado real.
      error: () => { alert('No se pudo cambiar el monitoreo del puerto.'); this.interfaces.update((xs) => [...xs]); },
    });
  }

  // Umbral de utilización por interfaz (sensor de ancho de banda). Vacío = usa el
  // umbral global del worker; estos valores por defecto son solo para pintar el
  // estado en la tabla (la alerta real la decide el worker).
  readonly UTIL_WARN_DEF = 80;
  readonly UTIL_CRIT_DEF = 95;

  /** '' sana · 'warn' · 'crit', según la util vs el umbral efectivo del puerto. */
  utilNivel(x: Interfaz): '' | 'warn' | 'crit' {
    const u = Math.max(x.util_in ?? 0, x.util_out ?? 0);
    const crit = x.umbral_util_critical ?? this.UTIL_CRIT_DEF;
    const warn = x.umbral_util_warning ?? this.UTIL_WARN_DEF;
    if (crit > 0 && u >= crit) return 'crit';
    if (warn > 0 && u >= warn) return 'warn';
    return '';
  }

  guardarUmbralInterfaz(x: Interfaz, w: string, c: string): void {
    const warning = w.trim() === '' ? null : Number(w);
    const critical = c.trim() === '' ? null : Number(c);
    if ((warning !== null && (warning < 0 || warning > 100)) ||
        (critical !== null && (critical < 0 || critical > 100))) {
      alert('El umbral debe estar entre 0 y 100.'); return;
    }
    if (warning !== null && critical !== null && critical < warning) {
      alert('El umbral crítico no puede ser menor que el de warning.'); return;
    }
    this.recursosSvc.interfazUmbral(this.id, x.if_index, warning, critical).subscribe({
      next: () => this.interfaces.update((xs) => xs.map((i) =>
        i.if_index === x.if_index
          ? { ...i, umbral_util_warning: warning, umbral_util_critical: critical } : i)),
      error: () => alert('No se pudo guardar el umbral del puerto.'),
    });
  }

  private cargarMetricas(): void {
    this.cargando.set(true);
    const ms = { '1h': 3600, '24h': 86400, '7d': 604800 }[this.rango()];
    const desde = new Date(Date.now() - ms * 1000).toISOString();
    this.tele.metricas({ recurso_id: this.id, desde, per_page: 1000 }).subscribe({
      next: (p) => { this.metricas.set(p.data); this.cargando.set(false); },
      error: () => this.cargando.set(false),
    });
  }
}
