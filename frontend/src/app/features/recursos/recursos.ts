import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { ImportacionResultado, Recurso, Sitio, TipoRecurso } from '../../core/models';
import { RecursosService } from '../../core/recursos.service';
import { EstadoBadge } from '../../shared/estado-badge';

interface FormRecurso {
  nombre: string;
  tipo_id: number | null;
  sitio_id: number | null;
  hostname: string;
  intervalo_segundos: number;
  activo: boolean;
  depende_de_id: number | null;
  max_check_attempts: number | null;
  sla_objetivo: number | null;
  parametrosTexto: string;
  secretosTexto: string;
}

@Component({
  selector: 'app-recursos',
  standalone: true,
  imports: [FormsModule, RouterLink, EstadoBadge],
  templateUrl: './recursos.html',
  styleUrl: './recursos.scss',
})
export class Recursos implements OnInit {
  private svc = inject(RecursosService);
  private route = inject(ActivatedRoute);
  auth = inject(AuthService);

  recursos = signal<Recurso[]>([]);
  tipos = signal<TipoRecurso[]>([]);
  sitios = signal<Sitio[]>([]);
  cargando = signal(true);
  error = signal<string | null>(null);

  fTipo = signal<number | ''>('');
  fSitio = signal<number | ''>('');
  busqueda = signal('');

  editandoId = signal<number | null>(null); // null = ninguno
  creando = signal(false);
  guardando = signal(false);
  form: FormRecurso = this.vacio();

  filtrados = computed(() => {
    const t = this.fTipo();
    const s = this.fSitio();
    const q = this.busqueda().trim().toLowerCase();
    return this.recursos().filter((r) => {
      if (t && r.tipo_id !== t) return false;
      if (s && r.sitio_id !== s) return false;
      if (q && !`${r.nombre} ${r.hostname ?? ''}`.toLowerCase().includes(q)) return false;
      return true;
    });
  });

  ngOnInit(): void {
    this.cargar();
    this.svc.tipos().subscribe((p) => this.tipos.set(p.data));
    this.svc.sitios().subscribe((p) => this.sitios.set(p.data));
    // Filtro inicial por sede (drill-down desde el Mapa: /recursos?sitio=ID).
    const sitio = this.route.snapshot.queryParamMap.get('sitio');
    if (sitio) this.fSitio.set(Number(sitio));
  }

  private cargar(): void {
    this.cargando.set(true);
    this.svc.listar().subscribe({
      next: (p) => { this.recursos.set(p.data); this.cargando.set(false); },
      error: () => { this.error.set('No se pudieron cargar los recursos.'); this.cargando.set(false); },
    });
  }

  // ── Importación masiva ──────────────────────────────────────────────
  importando = signal(false);
  impFilas = signal<Record<string, string>[]>([]);
  impArchivo = signal<string>('');
  impResultado = signal<ImportacionResultado | null>(null);
  impError = signal<string | null>(null);
  impEnviando = signal(false);
  impDef = {
    tipo: 'fibra_wan', community: '', snmp_version: '2c' as '2c' | 'v3',
    intervalo_segundos: 120, interfaces: true, activo: true, sitio: '',
  };

  abrirImport(): void {
    this.importando.set(true);
    this.impFilas.set([]); this.impArchivo.set(''); this.impResultado.set(null); this.impError.set(null);
  }
  cerrarImport(): void { this.importando.set(false); }

  /** Lee el CSV elegido y lo convierte en filas (cabecera → claves normalizadas). */
  onArchivoImport(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.impArchivo.set(file.name);
    this.impResultado.set(null); this.impError.set(null);
    const lector = new FileReader();
    lector.onload = () => {
      try { this.impFilas.set(this.parseCsv(String(lector.result ?? ''))); }
      catch { this.impError.set('No se pudo leer el CSV.'); this.impFilas.set([]); }
    };
    lector.readAsText(file, 'utf-8');
  }

  private parseCsv(texto: string): Record<string, string>[] {
    const lineas = texto.replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim() !== '');
    if (lineas.length < 2) return [];
    const alias: Record<string, string> = {
      nombre: 'nombre', hostname: 'hostname', ip: 'hostname', direccion: 'hostname',
      tipo: 'tipo', sitio: 'sitio', sede: 'sitio', community: 'community', comunidad: 'community',
      snmp_version: 'snmp_version', version: 'snmp_version', intervalo: 'intervalo_segundos',
      intervalo_segundos: 'intervalo_segundos', interfaces: 'interfaces', descripcion: 'descripcion',
    };
    const norm = (s: string) => s.trim().toLowerCase()
      .normalize('NFD').replace(/[̀-ͯ]/g, '');
    const cab = this.csvLinea(lineas[0]).map((c) => alias[norm(c)] ?? norm(c));
    const filas: Record<string, string>[] = [];
    for (let i = 1; i < lineas.length; i++) {
      const celdas = this.csvLinea(lineas[i]);
      const fila: Record<string, string> = {};
      cab.forEach((k, j) => { if (k) fila[k] = (celdas[j] ?? '').trim(); });
      if ((fila['nombre'] || fila['hostname'])) filas.push(fila);
    }
    return filas;
  }

  /** Parser de una línea CSV con soporte de comillas dobles. */
  private csvLinea(linea: string): string[] {
    const out: string[] = []; let cur = ''; let dentro = false;
    for (let i = 0; i < linea.length; i++) {
      const ch = linea[i];
      if (ch === '"') {
        if (dentro && linea[i + 1] === '"') { cur += '"'; i++; } else { dentro = !dentro; }
      } else if (ch === ',' && !dentro) { out.push(cur); cur = ''; } else { cur += ch; }
    }
    out.push(cur);
    return out;
  }

  plantillaCsv(): void {
    const contenido = 'nombre,hostname,tipo,sitio,community,snmp_version,intervalo_segundos,interfaces,descripcion\r\n'
      + 'ENLACE EJEMPLO - SEDE X,10.0.0.1,fibra_wan,Nivel Central,public,2c,120,true,Enlace WAN de ejemplo\r\n';
    const blob = new Blob(['﻿' + contenido], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'plantilla_enlaces.csv'; a.click();
    URL.revokeObjectURL(url);
  }

  enviarImport(): void {
    if (this.impFilas().length === 0) { this.impError.set('Carga un CSV con al menos una fila.'); return; }
    this.impError.set(null); this.impEnviando.set(true); this.impResultado.set(null);
    const d = this.impDef;
    this.svc.importar({
      tipo: d.tipo, community: d.community || null, snmp_version: d.snmp_version,
      intervalo_segundos: d.intervalo_segundos, interfaces: d.interfaces, activo: d.activo,
      sitio: d.sitio || null, filas: this.impFilas(),
    }).subscribe({
      next: (r) => { this.impResultado.set(r); this.impEnviando.set(false); this.cargar(); },
      error: (e) => {
        this.impError.set((e as { error?: { message?: string } })?.error?.message ?? 'Error al importar.');
        this.impEnviando.set(false);
      },
    });
  }

  private vacio(): FormRecurso {
    return {
      nombre: '', tipo_id: null, sitio_id: null, hostname: '',
      intervalo_segundos: 60, activo: true, depende_de_id: null, max_check_attempts: null,
      sla_objetivo: null,
      parametrosTexto: '{}', secretosTexto: '',
    };
  }

  nuevo(): void {
    this.creando.set(true);
    this.editandoId.set(null);
    this.form = this.vacio();
  }

  editar(r: Recurso): void {
    this.creando.set(false);
    this.editandoId.set(r.id);
    this.form = {
      nombre: r.nombre,
      tipo_id: r.tipo_id,
      sitio_id: r.sitio_id ?? null,
      hostname: r.hostname ?? '',
      intervalo_segundos: r.intervalo_segundos,
      activo: r.activo,
      depende_de_id: r.depende_de_id ?? null,
      max_check_attempts: r.max_check_attempts ?? null,
      sla_objetivo: r.sla_objetivo ?? null,
      parametrosTexto: JSON.stringify(r.parametros ?? {}, null, 2),
      secretosTexto: '',
    };
  }

  cancelar(): void {
    this.creando.set(false);
    this.editandoId.set(null);
    this.error.set(null);
  }

  guardar(): void {
    const f = this.form;
    this.error.set(null);

    let parametros: Record<string, unknown> = {};
    try { parametros = f.parametrosTexto.trim() ? JSON.parse(f.parametrosTexto) : {}; }
    catch { this.error.set('Parámetros: JSON inválido.'); return; }

    const body: Record<string, unknown> = {
      nombre: f.nombre,
      tipo_id: f.tipo_id,
      sitio_id: f.sitio_id,
      hostname: f.hostname || null,
      intervalo_segundos: f.intervalo_segundos,
      activo: f.activo,
      depende_de_id: f.depende_de_id,
      max_check_attempts: f.max_check_attempts || null,
      sla_objetivo: f.sla_objetivo ?? null,
      parametros,
    };

    if (f.secretosTexto.trim()) {
      try { body['secretos'] = JSON.parse(f.secretosTexto); }
      catch { this.error.set('Secretos: JSON inválido.'); return; }
    }

    this.guardando.set(true);
    const id = this.editandoId();
    const obs = id ? this.svc.actualizar(id, body) : this.svc.crear(body);
    obs.subscribe({
      next: () => { this.guardando.set(false); this.cancelar(); this.cargar(); },
      error: (e) => { this.guardando.set(false); this.error.set(this.msg(e)); },
    });
  }

  eliminar(r: Recurso): void {
    if (!confirm(`¿Eliminar el recurso "${r.nombre}"? Esta acción no se puede deshacer.`)) return;
    this.svc.eliminar(r.id).subscribe({
      next: () => this.cargar(),
      error: (e) => this.error.set(this.msg(e)),
    });
  }

  private msg(e: unknown): string {
    const err = e as { error?: { message?: string } };
    return err?.error?.message ?? 'Error al guardar.';
  }
}
