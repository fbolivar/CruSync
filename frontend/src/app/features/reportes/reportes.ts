import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FilaAlertaReporte, FilaBandaReporte, FilaDisponibilidad, Pronostico, Recurso, ReporteProgramado, Sitio } from '../../core/models';
import { AuthService } from '../../core/auth.service';
import { RecursosService } from '../../core/recursos.service';
import { ReportesService } from '../../core/reportes.service';
import { EstadoBadge } from '../../shared/estado-badge';
import { fecha } from '../../shared/tiempo';

// 24h/7d/30d se calculan en vivo; 90d/6m/12m salen del histórico consolidado
// (chequeos solo guarda 30 días).
type Rango = '24h' | '7d' | '30d' | '90d' | '6m' | '12m';
type TipoReporte = 'ejecutivo' | 'sitio' | 'recurso' | 'servicios';

@Component({
  selector: 'app-reportes',
  standalone: true,
  imports: [EstadoBadge, DecimalPipe, FormsModule],
  templateUrl: './reportes.html',
  styleUrl: './reportes.scss',
})
export class Reportes implements OnInit {
  private svc = inject(ReportesService);
  private recSvc = inject(RecursosService);
  auth = inject(AuthService);
  fecha = fecha;

  // ── Generador/exportador de reportes ──
  tipoRep = signal<TipoReporte>('ejecutivo');
  repRango = signal<Rango>('7d');
  repSitio = signal<number | ''>('');
  repRecurso = signal<number | ''>('');
  sitiosLista = signal<Sitio[]>([]);
  recursosLista = signal<Recurso[]>([]);
  generando = signal<string | null>(null);   // formato en curso
  errorExp = signal<string | null>(null);

  readonly tiposRep: { id: TipoReporte; label: string }[] = [
    { id: 'ejecutivo', label: 'Ejecutivo general' },
    { id: 'sitio', label: 'Por sitio' },
    { id: 'recurso', label: 'Por recurso' },
    { id: 'servicios', label: 'Servicios' },
  ];

  exportar(formato: 'csv' | 'xlsx' | 'pdf'): void {
    const tipo = this.tipoRep();
    this.errorExp.set(null);
    this.generando.set(formato);
    const query: Record<string, unknown> = { rango: this.repRango() };
    if (tipo === 'sitio' && this.repSitio()) query['id'] = this.repSitio();
    if (tipo === 'recurso' && this.repRecurso()) query['id'] = this.repRecurso();

    this.svc.exportar(tipo, formato, query).subscribe({
      next: (resp) => { this.guardar(resp, `reporte_${tipo}.${formato}`); this.generando.set(null); },
      error: () => { this.errorExp.set('No se pudo generar el reporte.'); this.generando.set(null); },
    });
  }

  private guardar(resp: HttpResponse<Blob>, fallback: string): void {
    const blob = resp.body;
    if (!blob) return;
    const cd = resp.headers.get('Content-Disposition') ?? '';
    const m = /filename="?([^"]+)"?/.exec(cd);
    const nombre = m ? m[1] : fallback;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = nombre;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Vista previa: CONSUMO DE ANCHO DE BANDA ──
  bandaRango = signal<'24h' | '7d' | '30d'>('7d');
  bandaFilas = signal<FilaBandaReporte[]>([]);
  bandaCargando = signal(false);
  cargarBanda(): void {
    this.bandaCargando.set(true);
    this.svc.banda(this.bandaRango()).subscribe({
      next: (r) => { this.bandaFilas.set(r.interfaces); this.bandaCargando.set(false); },
      error: () => { this.bandaFilas.set([]); this.bandaCargando.set(false); },
    });
  }
  cambiarRangoBanda(r: '24h' | '7d' | '30d'): void { this.bandaRango.set(r); this.cargarBanda(); }
  exportarBandaPdf(): void {
    this.svc.exportar('banda', 'pdf', { rango: this.bandaRango() })
      .subscribe({ next: (resp) => this.guardar(resp, `reporte_banda_${this.bandaRango()}.pdf`) });
  }
  csvBanda(): void {
    const cab = ['Recurso', 'Interfaz', 'Sitio', 'Prom. entrada (Mbps)', 'Prom. salida (Mbps)',
      'P95 entrada (Mbps)', 'P95 salida (Mbps)', 'Max entrada (Mbps)', 'Max salida (Mbps)', 'Muestras'];
    const filas = this.bandaFilas().map((f) => [f.nombre, f.if_name, f.sitio_nombre ?? '',
      f.avg_in ?? '', f.avg_out ?? '', f.p95_in ?? '', f.p95_out ?? '', f.max_in ?? '', f.max_out ?? '', f.muestras]);
    this.descargarCsv([cab, ...filas], `reporte_banda_${this.bandaRango()}.csv`);
  }

  // ── Vista previa: ALERTAS ENVIADAS ──
  alertasRango = signal<'24h' | '7d' | '30d'>('7d');
  alertasFilas = signal<FilaAlertaReporte[]>([]);
  alertasCargando = signal(false);
  cargarAlertas(): void {
    this.alertasCargando.set(true);
    this.svc.alertas(this.alertasRango()).subscribe({
      next: (r) => { this.alertasFilas.set(r.alertas); this.alertasCargando.set(false); },
      error: () => { this.alertasFilas.set([]); this.alertasCargando.set(false); },
    });
  }
  cambiarRangoAlertas(r: '24h' | '7d' | '30d'): void { this.alertasRango.set(r); this.cargarAlertas(); }
  exportarAlertasPdf(): void {
    this.svc.exportar('alertas', 'pdf', { rango: this.alertasRango() })
      .subscribe({ next: (resp) => this.guardar(resp, `reporte_alertas_${this.alertasRango()}.pdf`) });
  }
  csvAlertas(): void {
    const cab = ['Fecha y hora', 'Medio', 'Canal', 'Destino', 'Recurso', 'Severidad',
      'Evento', 'Alerta', 'Estado', 'Error'];
    const filas = this.alertasFilas().map((a) => [a.ts, a.medio, a.canal_nombre, a.destino ?? '',
      a.recurso, a.severidad ?? '', a.evento ?? '', a.asunto ?? '', a.estado, a.error ?? '']);
    this.descargarCsv([cab, ...filas], `reporte_alertas_${this.alertasRango()}.csv`);
  }

  /** CSV client-side (UTF-8 con BOM) a partir de una matriz; descarga directa. */
  private descargarCsv(matriz: (string | number)[][], nombre: string): void {
    const cuerpo = matriz.map((fila) =>
      fila.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const blob = new Blob(['﻿' + cuerpo], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = nombre; a.click();
    URL.revokeObjectURL(url);
  }

  rango = signal<Rango>('7d');
  filas = signal<FilaDisponibilidad[]>([]);
  desde = signal<string | null>(null);
  cargando = signal(true);

  // Filtros de la vista y del ver/guardar (tipo de recurso + sitio). El periodo es `rango`.
  filtroTipo = signal<number | ''>('');
  filtroSitio = signal<number | ''>('');

  // Opciones de filtro derivadas de los datos cargados (solo lo que existe).
  tiposEnDatos = computed(() => {
    const m = new Map<number, string>();
    for (const f of this.filas()) m.set(f.tipo_id, f.tipo_nombre);
    return [...m.entries()].map(([id, nombre]) => ({ id, nombre }))
      .sort((a, b) => a.nombre.localeCompare(b.nombre));
  });
  sitiosEnDatos = computed(() => {
    const m = new Map<number, string>();
    for (const f of this.filas()) { if (f.sitio_id != null) m.set(f.sitio_id, f.sitio_nombre ?? '—'); }
    return [...m.entries()].map(([id, nombre]) => ({ id, nombre }))
      .sort((a, b) => a.nombre.localeCompare(b.nombre));
  });

  // Filas tras aplicar los filtros: es lo que se ve, se cuenta y se exporta.
  filtradas = computed(() => {
    const t = this.filtroTipo();
    const s = this.filtroSitio();
    return this.filas().filter((f) =>
      (t === '' || f.tipo_id === t) && (s === '' || f.sitio_id === s));
  });

  limpiarFiltros(): void { this.filtroTipo.set(''); this.filtroSitio.set(''); }

  /** Texto legible del filtro activo (para encabezado del PDF/CSV). */
  filtroTexto(): string {
    const t = this.filtroTipo();
    const s = this.filtroSitio();
    const partes: string[] = [];
    if (t !== '') { partes.push('Tipo: ' + (this.tiposEnDatos().find((x) => x.id === t)?.nombre ?? '')); }
    if (s !== '') { partes.push('Sitio: ' + (this.sitiosEnDatos().find((x) => x.id === s)?.nombre ?? '')); }
    return partes.length ? partes.join(' · ') : 'Todos los recursos';
  }

  /** Sufijo de nombre de archivo según rango + filtros. */
  private sufijoArchivo(): string {
    const slug = (v: string) => v.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    let suf = this.rango();
    const t = this.filtroTipo();
    const s = this.filtroSitio();
    if (t !== '') { suf += '_' + slug(this.tiposEnDatos().find((x) => x.id === t)?.nombre ?? ''); }
    if (s !== '') { suf += '_' + slug(this.sitiosEnDatos().find((x) => x.id === s)?.nombre ?? ''); }
    return suf;
  }

  // Pronósticos de capacidad (calculados por el worker). Urgentes primero.
  pronosticos = signal<Pronostico[]>([]);
  pronosticosAlerta = computed(() => this.pronosticos().filter((p) => p.dias_restantes != null));

  rangos: Rango[] = ['24h', '7d', '30d', '90d', '6m', '12m'];
  fuente = signal<string | null>(null);

  // Peor disponibilidad primero (los recursos con problemas arriba). Sobre lo filtrado.
  ordenadas = computed(() =>
    [...this.filtradas()].sort((a, b) => (a.disponibilidad ?? 101) - (b.disponibilidad ?? 101)),
  );

  promedio = computed(() => {
    const v = this.filtradas().map((f) => f.disponibilidad).filter((x): x is number => x != null);
    return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
  });

  totalIncidencias = computed(() => this.filtradas().reduce((s, f) => s + f.incidencias, 0));

  // Cumplimiento de SLA: solo cuenta lo MEDIDO y con objetivo. Lo no medible se
  // reporta aparte (`sinDatos`) para no disfrazarlo de incumplimiento.
  incumplen = computed(() => this.filtradas().filter((f) => f.cumple_sla === false).length);
  conObjetivo = computed(() => this.filtradas().filter((f) => f.sla_objetivo != null).length);
  sinDatos = computed(() => this.filtradas().filter((f) => f.disponibilidad == null).length);

  // Reportes programados (CRUD)
  programados = signal<ReporteProgramado[]>([]);
  editId = signal<number | null>(null);
  creando = signal(false);
  errorProg = signal<string | null>(null);
  fProg = this.progVacio();

  ngOnInit(): void {
    this.cargar();
    this.svc.pronosticos().subscribe((p) => this.pronosticos.set(p));
    this.cargarBanda();
    this.cargarAlertas();
    this.cargarProgramados();
    this.recSvc.sitios().subscribe((p) => this.sitiosLista.set(p.data));
    this.recSvc.listar({ per_page: 300 }).subscribe((p) => this.recursosLista.set(p.data));
  }

  readonly tiposInforme: { id: 'disponibilidad' | 'sla' | 'banda' | 'alertas'; label: string }[] = [
    { id: 'disponibilidad', label: 'Disponibilidad' },
    { id: 'sla', label: 'Cumplimiento de SLA' },
    { id: 'banda', label: 'Consumo de ancho de banda' },
    { id: 'alertas', label: 'Alertas enviadas' },
  ];

  private progVacio() {
    return {
      nombre: '', tipo: 'disponibilidad' as 'disponibilidad' | 'sla' | 'banda' | 'alertas',
      periodo: 'mensual' as 'diario' | 'semanal' | 'mensual',
      rango: '30d' as '24h' | '7d' | '30d', destinatarios: '',
      formato: 'pdf' as 'pdf' | 'csv', activo: true,
      // Filtro del informe ('' = todos). Permite acotarlo a una audiencia
      // (p. ej. enviar al proveedor solo sus enlaces, sin el resto de la red).
      tipo_id: '' as number | '', sitio_id: '' as number | '',
    };
  }

  etiquetaTipoInforme(t?: string): string {
    return this.tiposInforme.find((x) => x.id === (t ?? 'disponibilidad'))?.label ?? 'Disponibilidad';
  }

  /** Alcance legible de un reporte programado (para la tabla). */
  alcanceProg(r: ReporteProgramado): string {
    const partes: string[] = [];
    if (r.tipo_id) { partes.push(this.tiposEnDatos().find((t) => t.id === r.tipo_id)?.nombre ?? 'tipo'); }
    if (r.sitio_id) { partes.push(this.sitiosLista().find((s) => s.id === r.sitio_id)?.nombre ?? 'sitio'); }
    return partes.length ? partes.join(' · ') : 'Todos';
  }
  private cargarProgramados(): void {
    this.svc.programados().subscribe((p) => this.programados.set(p.data));
  }
  nuevoProg(): void { this.creando.set(true); this.editId.set(null); this.fProg = this.progVacio(); this.errorProg.set(null); }
  editarProg(r: ReporteProgramado): void {
    this.creando.set(false); this.editId.set(r.id); this.errorProg.set(null);
    this.fProg = {
      nombre: r.nombre, tipo: r.tipo ?? 'disponibilidad', periodo: r.periodo, rango: r.rango,
      destinatarios: r.destinatarios, formato: r.formato, activo: r.activo,
      tipo_id: r.tipo_id ?? '', sitio_id: r.sitio_id ?? '',
    };
  }
  cancelarProg(): void { this.creando.set(false); this.editId.set(null); this.errorProg.set(null); }
  guardarProg(): void {
    const f = this.fProg;
    this.errorProg.set(null);
    if (!f.nombre.trim()) { this.errorProg.set('Indica un nombre.'); return; }
    if (!f.destinatarios.trim()) { this.errorProg.set('Indica al menos un correo.'); return; }
    // '' (todos) viaja como null; la API espera int|null.
    const cuerpo: Partial<ReporteProgramado> = {
      ...f, tipo_id: f.tipo_id === '' ? null : f.tipo_id,
      sitio_id: f.sitio_id === '' ? null : f.sitio_id,
    };
    const id = this.editId();
    const obs = id ? this.svc.actualizarProgramado(id, cuerpo) : this.svc.crearProgramado(cuerpo);
    obs.subscribe({
      next: () => { this.cancelarProg(); this.cargarProgramados(); },
      error: (e) => this.errorProg.set((e as { error?: { message?: string } })?.error?.message ?? 'Error al guardar.'),
    });
  }
  eliminarProg(r: ReporteProgramado): void {
    if (!confirm(`¿Eliminar el reporte programado "${r.nombre}"?`)) return;
    this.svc.eliminarProgramado(r.id).subscribe({ next: () => this.cargarProgramados() });
  }

  // Clase de urgencia según días restantes para llegar al techo.
  claseDias(d: number | null): string {
    if (d == null) return 'sd';
    if (d <= 7) return 'mal';
    if (d <= 30) return 'warn';
    return 'bien';
  }

  cambiarRango(r: Rango): void {
    this.rango.set(r);
    this.cargar();
  }

  private cargar(): void {
    this.cargando.set(true);
    this.svc.disponibilidad(this.rango()).subscribe({
      next: (r) => { this.filas.set(r.recursos); this.desde.set(r.desde); this.fuente.set(r.fuente ?? null); this.cargando.set(false); },
      error: () => this.cargando.set(false),
    });
  }

  clase(d: number | null): string {
    if (d == null) return 'sd';
    if (d >= 99.9) return 'ok';
    if (d >= 99) return 'bien';
    if (d >= 95) return 'warn';
    return 'mal';
  }

  exportarCsv(): void {
    const cab = ['Recurso', 'Tipo', 'Sitio', 'Estado', 'Disponibilidad %',
      'Up', 'Degradado', 'Caido', 'Desconocido', 'Mantenimiento', 'Incidencias'];
    const filas = this.ordenadas().map((f) => [
      f.nombre, f.tipo_nombre, f.sitio_nombre ?? '', f.estado_actual,
      f.disponibilidad ?? 'sin datos',
      f.up, f.degraded, f.down, f.unknown, f.mantenimiento, f.incidencias,
    ]);
    const csv = [cab, ...filas]
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\r\n');

    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `disponibilidad_${this.sufijoArchivo()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  /** Abre una vista de impresión maquetada; el navegador la guarda como PDF. */
  descargarPdf(): void {
    const esc = (v: unknown): string =>
      String(v ?? '').replace(/[&<>"]/g, (c) =>
        (({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }) as Record<string, string>)[c]);
    const rangoTxt = ({ '24h': 'últimas 24 horas', '7d': 'últimos 7 días', '30d': 'últimos 30 días' } as Record<string, string>)[this.rango()];
    const prom = this.promedio();
    const generado = new Date().toLocaleString('es-CO');
    const col = (d: number | null) => (d == null ? '#777' : d >= 99 ? '#1b8a3a' : d >= 95 ? '#c88c00' : '#c81e1e');

    const filas = this.ordenadas().map((f) => `
      <tr><td>${esc(f.nombre)}</td><td>${esc(f.tipo_nombre)}</td><td>${esc(f.sitio_nombre ?? '—')}</td>
      <td>${esc(f.estado_actual)}</td>
      <td class="num" style="color:${col(f.disponibilidad)};font-weight:700">${f.disponibilidad != null ? f.disponibilidad.toFixed(3) + '%' : 'sin datos'}</td>
      <td class="num">${f.up}</td><td class="num">${f.degraded}</td><td class="num">${f.down}</td><td class="num">${f.incidencias}</td></tr>`).join('');

    const html = `<!doctype html><html lang="es"><head><meta charset="utf-8">
      <title>Reporte de disponibilidad ${esc(this.rango())}</title><style>
      *{font-family:Arial,Helvetica,sans-serif} body{margin:24px;color:#1a1a1a}
      h1{font-size:18px;margin:0 0 2px;color:#256a36} .meta{color:#666;font-size:12px;margin-bottom:12px}
      .kpis{display:flex;gap:28px;margin:10px 0 16px} .kpi b{font-size:20px;display:block} .kpi span{font-size:11px;color:#666;text-transform:uppercase}
      table{width:100%;border-collapse:collapse;font-size:11px} th,td{border:1px solid #cfd8d0;padding:4px 6px;text-align:left}
      th{background:#e8f0e9} .num{text-align:right} .pie{margin-top:16px;color:#888;font-size:10px}
      @media print{body{margin:10mm}}</style></head><body>
      <h1>SIMON · Reporte de disponibilidad</h1>
      <div class="meta">Periodo: ${rangoTxt} · ${esc(this.filtroTexto())} · Generado: ${esc(generado)}</div>
      <div class="kpis">
        <div class="kpi"><b>${this.filtradas().length}</b><span>Recursos</span></div>
        <div class="kpi"><b>${prom != null ? prom.toFixed(2) + '%' : '—'}</b><span>Disponibilidad promedio</span></div>
        <div class="kpi"><b>${this.totalIncidencias()}</b><span>Incidencias</span></div>
      </div>
      <table><thead><tr><th>Recurso</th><th>Tipo</th><th>Sitio</th><th>Estado</th>
        <th class="num">Disponibilidad</th><th class="num">Up</th><th class="num">Degr.</th><th class="num">Caído</th><th class="num">Incid.</th></tr></thead>
      <tbody>${filas}</tbody></table>
      <div class="pie">Parques Nacionales Naturales de Colombia — SIMON, Sistema Integral de Monitoreo</div>
      </body></html>`;

    const w = window.open('', '_blank');
    if (!w) { alert('Permite las ventanas emergentes para generar el PDF.'); return; }
    w.document.write(html);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 350);
  }
}
