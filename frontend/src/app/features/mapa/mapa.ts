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
    if (s.down > 0 || s.degraded > 0) return 10;
    return Math.max(5, Math.min(11, 4 + Math.sqrt(s.total) * 2));
  }
  radioEnlace(m: MarcadorEnlace): number {
    return m.estado === 'down' || m.estado === 'degraded' ? 4.2 : 3;
  }
  hayProblema(s: Sede): boolean { return s.down > 0 || s.degraded > 0; }
}
