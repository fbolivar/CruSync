import { HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { Paginated, Pronostico, ReporteAlertas, ReporteBanda, ReporteDisponibilidad, ReporteProgramado } from './models';

@Injectable({ providedIn: 'root' })
export class ReportesService {
  private api = inject(ApiService);

  disponibilidad(rango: string): Observable<ReporteDisponibilidad> {
    return this.api.get<ReporteDisponibilidad>('/reportes/disponibilidad', { rango });
  }

  pronosticos(): Observable<Pronostico[]> {
    return this.api.get<Pronostico[]>('/pronosticos');
  }

  /** Consumo de ancho de banda por interfaz (vista previa en pantalla). */
  banda(rango: string): Observable<ReporteBanda> {
    return this.api.get<ReporteBanda>('/reportes/banda', { rango });
  }
  /** Alertas enviadas con detalle (vista previa en pantalla). */
  alertas(rango: string): Observable<ReporteAlertas> {
    return this.api.get<ReporteAlertas>('/reportes/alertas', { rango });
  }

  /** Exporta un reporte (ejecutivo/sitio/recurso/servicios) en csv/xlsx/pdf. */
  exportar(tipo: string, formato: 'csv' | 'xlsx' | 'pdf',
           query?: Record<string, unknown>): Observable<HttpResponse<Blob>> {
    return this.api.descargar(`/reportes/export/${tipo}`, { formato, ...query });
  }

  // ── Reportes programados (CRUD) ──
  programados(): Observable<Paginated<ReporteProgramado>> {
    return this.api.get<Paginated<ReporteProgramado>>('/reportes-programados', { per_page: 200 });
  }
  crearProgramado(b: Partial<ReporteProgramado>): Observable<ReporteProgramado> {
    return this.api.post<ReporteProgramado>('/reportes-programados', b);
  }
  actualizarProgramado(id: number, b: Partial<ReporteProgramado>): Observable<ReporteProgramado> {
    return this.api.put<ReporteProgramado>(`/reportes-programados/${id}`, b);
  }
  eliminarProgramado(id: number): Observable<void> {
    return this.api.delete<void>(`/reportes-programados/${id}`);
  }
}
