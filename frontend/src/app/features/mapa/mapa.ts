import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EnlaceMapa, Estado, Sitio } from '../../core/models';
import { RecursosService } from '../../core/recursos.service';
import { COLOMBIA_DEPARTAMENTOS } from './colombia-geo';

interface Sede {
  sitio: Sitio;
  estado: Estado;          // peor estado de sus recursos
  total: number;
  up: number;
  degraded: number;
  down: number;
  otros: number;           // unknown + maintenance
  x: number | null;        // proyección (null si la sede no tiene coordenadas)
  y: number | null;
}

interface MarcadorEnlace {
  enlace: EnlaceMapa;
  estado: Estado;
  x: number;
  y: number;
  propia: boolean;         // true = coords propias del enlace; false = heredó las de la sede
}

interface Cluster {
  x: number;
  y: number;
  n: number;                 // nº de enlaces agrupados
  estado: Estado;            // peor estado del grupo (semáforo)
  down: number;
  degraded: number;
  items: MarcadorEnlace[];
}

const PESO: Record<Estado, number> = { down: 5, degraded: 4, unknown: 3, maintenance: 2, up: 1 };

@Component({
  selector: 'app-mapa',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './mapa.html',
  styleUrl: './mapa.scss',
})
export class Mapa implements OnInit {
  private svc = inject(RecursosService);

  readonly W = 437;
  readonly H = 600;
  private readonly LON_MIN = -79.1;
  private readonly LON_MAX = -66.8;
  private readonly LAT_MIN = -4.3;
  private readonly LAT_MAX = 12.6;

  sitios = signal<Sitio[]>([]);
  enlaces = signal<EnlaceMapa[]>([]);
  cargando = signal(true);
  hoverId = signal<number | null>(null);      // sede resaltada
  hoverEnlace = signal<number | null>(null);   // enlace resaltado
  vista = signal<'sedes' | 'enlaces'>('sedes');

  departamentos = COLOMBIA_DEPARTAMENTOS;

  // ── Zoom / paneo (viewBox del SVG) ──
  view = signal({ x: 0, y: 0, w: this.W, h: this.H });
  viewBox = computed(() => { const v = this.view(); return `${v.x} ${v.y} ${v.w} ${v.h}`; });
  private readonly MINW = 30;   // acercamiento máximo (ancho mínimo del viewBox)
  // Factor de escala actual (1 = vista completa; <1 = acercado). Se usa para que
  // los marcadores conserven tamaño visual al hacer zoom.
  k = computed(() => this.view().w / this.W);
  private drag: { px: number; py: number; vx: number; vy: number; w: number; h: number } | null = null;
  arrastrando = signal(false);

  private aplicarZoom(factor: number, cx: number, cy: number): void {
    const v = this.view();
    const w = Math.max(this.MINW, Math.min(v.w * factor, this.W));
    const h = w * (this.H / this.W);
    let x = cx - (cx - v.x) * (w / v.w);
    let y = cy - (cy - v.y) * (h / v.h);
    x = Math.max(0, Math.min(x, this.W - w));
    y = Math.max(0, Math.min(y, this.H - h));
    this.view.set({ x, y, w, h });
  }
  zoomBoton(factor: number): void {
    const v = this.view();
    this.aplicarZoom(factor, v.x + v.w / 2, v.y + v.h / 2);
  }
  resetZoom(): void { this.view.set({ x: 0, y: 0, w: this.W, h: this.H }); }

  onWheel(ev: WheelEvent): void {
    ev.preventDefault();
    const r = (ev.currentTarget as Element).getBoundingClientRect();
    const v = this.view();
    const cx = v.x + ((ev.clientX - r.left) / r.width) * v.w;
    const cy = v.y + ((ev.clientY - r.top) / r.height) * v.h;
    this.aplicarZoom(ev.deltaY < 0 ? 0.8 : 1.25, cx, cy);
  }
  onPointerDown(ev: PointerEvent): void {
    const r = (ev.currentTarget as Element).getBoundingClientRect();
    const v = this.view();
    this.drag = { px: ev.clientX, py: ev.clientY, vx: v.x, vy: v.y, w: r.width, h: r.height };
    this.arrastrando.set(true);
    (ev.currentTarget as Element).setPointerCapture?.(ev.pointerId);
  }
  onPointerMove(ev: PointerEvent): void {
    if (!this.drag) return;
    const v = this.view();
    const dx = ((ev.clientX - this.drag.px) / this.drag.w) * v.w;
    const dy = ((ev.clientY - this.drag.py) / this.drag.h) * v.h;
    const x = Math.max(0, Math.min(this.drag.vx - dx, this.W - v.w));
    const y = Math.max(0, Math.min(this.drag.vy - dy, this.H - v.h));
    this.view.set({ ...v, x, y });
  }
  onPointerUp(): void { this.drag = null; this.arrastrando.set(false); }

  private sitiosMap = computed(() => {
    const m = new Map<number, Sitio>();
    for (const s of this.sitios()) m.set(s.id, s);
    return m;
  });

  // ── Vista por SEDE (agregado) ──
  sedes = computed<Sede[]>(() => {
    const porSitio = new Map<number, EnlaceMapa[]>();
    for (const r of this.enlaces()) {
      if (r.sitio_id == null) continue;
      (porSitio.get(r.sitio_id) ?? porSitio.set(r.sitio_id, []).get(r.sitio_id)!).push(r);
    }
    return this.sitios().map((s) => {
      const rs = porSitio.get(s.id) ?? [];
      const peor = rs.reduce<Estado>(
        (acc, r) => (PESO[r.estado_actual] > PESO[acc] ? r.estado_actual : acc), 'up');
      const cuenta = (e: Estado) => rs.filter((r) => r.estado_actual === e).length;
      const p = s.latitud != null && s.longitud != null ? this.proj(+s.longitud, +s.latitud) : null;
      return {
        sitio: s, estado: rs.length ? peor : 'unknown', total: rs.length,
        up: cuenta('up'), degraded: cuenta('degraded'), down: cuenta('down'),
        otros: cuenta('unknown') + cuenta('maintenance'),
        x: p ? p.x : null, y: p ? p.y : null,
      };
    });
  });
  marcadores = computed<Sede[]>(() => this.sedes().filter((s) => s.x != null));
  sedesOrdenadas = computed<Sede[]>(() =>
    [...this.sedes()].sort((a, b) =>
      PESO[b.estado] - PESO[a.estado] || b.total - a.total || a.sitio.nombre.localeCompare(b.sitio.nombre)));

  // ── Vista por ENLACE (cada recurso con coordenadas, coloreado por semáforo) ──
  // Coord = propias del enlace o, si no tiene, las de su sede.
  marcadoresEnlaces = computed<MarcadorEnlace[]>(() => {
    const out: MarcadorEnlace[] = [];
    const sm = this.sitiosMap();
    for (const e of this.enlaces()) {
      let lat = e.latitud != null ? +e.latitud : null;
      let lon = e.longitud != null ? +e.longitud : null;
      let propia = lat != null && lon != null;
      if (!propia && e.sitio_id != null) {
        const s = sm.get(e.sitio_id);
        if (s?.latitud != null && s?.longitud != null) { lat = +s.latitud; lon = +s.longitud; }
      }
      if (lat == null || lon == null) continue;
      const p = this.proj(lon, lat);
      out.push({ enlace: e, estado: e.estado_actual, x: p.x, y: p.y, propia });
    }
    // Los problemáticos al final → se dibujan ENCIMA (más visibles).
    return out.sort((a, b) => PESO[a.estado] - PESO[b.estado]);
  });
  // Enlaces con alerta (caído/degradado) primero, para el panel lateral.
  enlacesProblema = computed<EnlaceMapa[]>(() =>
    this.enlaces()
      .filter((e) => e.estado_actual === 'down' || e.estado_actual === 'degraded')
      .sort((a, b) => PESO[b.estado_actual] - PESO[a.estado_actual]
        || a.nombre.localeCompare(b.nombre)));
  // Agrupamiento por cercanía: rejilla cuyo tamaño de celda depende del zoom
  // (al acercar, las celdas se achican y los grupos se separan). Estable al panear
  // porque la rejilla es absoluta. Un grupo de 1 se dibuja como marcador simple.
  clusters = computed<Cluster[]>(() => {
    const cell = Math.max(5, this.view().w / 16);
    const grid = new Map<string, Cluster>();
    for (const m of this.marcadoresEnlaces()) {
      const key = Math.floor(m.x / cell) + '_' + Math.floor(m.y / cell);
      let g = grid.get(key);
      if (!g) { g = { x: 0, y: 0, n: 0, estado: 'up', down: 0, degraded: 0, items: [] }; grid.set(key, g); }
      g.x += m.x; g.y += m.y; g.n++;
      if (PESO[m.estado] > PESO[g.estado]) g.estado = m.estado;
      if (m.estado === 'down') g.down++;
      if (m.estado === 'degraded') g.degraded++;
      g.items.push(m);
    }
    const out = [...grid.values()];
    for (const g of out) { g.x /= g.n; g.y /= g.n; }
    return out.sort((a, b) => PESO[a.estado] - PESO[b.estado]); // problemáticos encima
  });

  /** Clic en un clúster: acercar centrado en él para que se separe. */
  acercarCluster(c: Cluster): void {
    this.aplicarZoom(0.45, c.x, c.y);
  }
  radioCluster(c: Cluster): number {
    const base = c.n === 1 ? (c.estado === 'down' || c.estado === 'degraded' ? 4.2 : 3)
                           : 7 + Math.min(10, Math.sqrt(c.n) * 2.2);
    return base * this.k();  // conserva tamaño visual al hacer zoom
  }

  enlacesConCoord = computed(() => this.marcadoresEnlaces().length);
  enlacesCaidos = computed(() => this.enlaces().filter((e) => e.estado_actual === 'down').length);
  enlacesDegradados = computed(() => this.enlaces().filter((e) => e.estado_actual === 'degraded').length);

  // KPIs de cabecera (sede).
  totalSedes = computed(() => this.sedes().length);
  sedesConProblemas = computed(() => this.sedes().filter((s) => s.down > 0 || s.degraded > 0).length);
  recursosCaidos = computed(() => this.sedes().reduce((n, s) => n + s.down, 0));

  ngOnInit(): void {
    this.svc.mapa().subscribe({
      next: (r) => { this.sitios.set(r.sitios); this.enlaces.set(r.enlaces); this.cargando.set(false); },
      error: () => this.cargando.set(false),
    });
  }

  private proj(lon: number, lat: number): { x: number; y: number } {
    return {
      x: (lon - this.LON_MIN) / (this.LON_MAX - this.LON_MIN) * this.W,
      y: (this.LAT_MAX - lat) / (this.LAT_MAX - this.LAT_MIN) * this.H,
    };
  }

  color(estado: Estado): string {
    return { up: '#1b8a3a', degraded: '#e0a400', down: '#d11d1d',
             unknown: '#9aa0a6', maintenance: '#3b82f6' }[estado];
  }

  radio(s: Sede): number {
    const base = (s.down > 0 || s.degraded > 0) ? 10 : Math.max(5, Math.min(11, 4 + Math.sqrt(s.total) * 2));
    return base * this.k();  // conserva tamaño visual al hacer zoom
  }
  hayProblema(s: Sede): boolean { return s.down > 0 || s.degraded > 0; }
}
