import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { Baseline, FlujoOverview, FlujosResp, HardwareResp, ImportacionResultado, Interfaz, MapaResp, MuestraInterfaz, Paginated, PercentilBanda, Recurso, Respaldo, RespaldoDetalle, SaltoRuta, Sitio, TipoRecurso, TopologiaResp, VecinoLldp, WanCalidadResp } from './models';

@Injectable({ providedIn: 'root' })
export class RecursosService {
  private api = inject(ApiService);

  listar(query?: Record<string, unknown>): Observable<Paginated<Recurso>> {
    return this.api.get<Paginated<Recurso>>('/recursos', { per_page: 200, ...query });
  }
  obtener(id: number): Observable<Recurso> {
    return this.api.get<Recurso>(`/recursos/${id}`);
  }
  /** Datos del mapa geográfico (enlaces con coords/estado + sedes). */
  mapa(): Observable<MapaResp> {
    return this.api.get<MapaResp>('/mapa');
  }
  /** Alta masiva desde inventario (CSV parseado a filas). */
  importar(body: Record<string, unknown>): Observable<ImportacionResultado> {
    return this.api.post<ImportacionResultado>('/recursos/importar', body);
  }
  crear(body: Partial<Recurso>): Observable<Recurso> {
    return this.api.post<Recurso>('/recursos', body);
  }
  actualizar(id: number, body: Partial<Recurso>): Observable<Recurso> {
    return this.api.put<Recurso>(`/recursos/${id}`, body);
  }
  eliminar(id: number): Observable<void> {
    return this.api.delete<void>(`/recursos/${id}`);
  }

  interfaces(id: number): Observable<Interfaz[]> {
    return this.api.get<Interfaz[]>(`/recursos/${id}/interfaces`);
  }
  interfazMonitorear(id: number, ifIndex: number, monitorear: boolean): Observable<unknown> {
    return this.api.put(`/recursos/${id}/interfaces/${ifIndex}`, { monitorear });
  }
  /** Fija el umbral de utilización (%) propio de la interfaz; null = usa el global. */
  interfazUmbral(id: number, ifIndex: number, warning: number | null, critical: number | null): Observable<unknown> {
    return this.api.put(`/recursos/${id}/interfaces/${ifIndex}`, {
      umbral_util_warning: warning, umbral_util_critical: critical,
    });
  }
  interfazHistorico(id: number, ifIndex: number, rango: '1h' | '24h' | '7d'): Observable<MuestraInterfaz[]> {
    return this.api.get<MuestraInterfaz[]>(`/recursos/${id}/interfaces/${ifIndex}/historico`, { rango });
  }
  /** Percentil 95 de ancho de banda de una interfaz (facturación ISP). */
  interfazPercentil(id: number, ifIndex: number, rango: '24h' | '7d' | '30d'): Observable<PercentilBanda> {
    return this.api.get<PercentilBanda>(`/recursos/${id}/interfaces/${ifIndex}/percentil`, { rango });
  }
  /** Última ruta de red (traceroute por salto) del recurso. */
  ruta(id: number): Observable<SaltoRuta[]> {
    return this.api.get<SaltoRuta[]>(`/recursos/${id}/ruta`);
  }

  baselines(id: number): Observable<Baseline[]> {
    return this.api.get<Baseline[]>(`/recursos/${id}/baselines`);
  }

  hardware(id: number): Observable<HardwareResp> {
    return this.api.get<HardwareResp>(`/recursos/${id}/hardware`);
  }

  vecinos(id: number): Observable<VecinoLldp[]> {
    return this.api.get<VecinoLldp[]>(`/recursos/${id}/vecinos`);
  }

  topologia(): Observable<TopologiaResp> {
    return this.api.get<TopologiaResp>('/topologia');
  }

  flujos(query?: Record<string, unknown>): Observable<FlujosResp> {
    return this.api.get<FlujosResp>('/flujos', query);
  }

  flujosOverview(rango: '1h' | '6h' | '24h' | '7d' = '24h'): Observable<FlujoOverview> {
    return this.api.get<FlujoOverview>('/flujos/overview', { rango });
  }

  wanCalidad(id: number, rango: '1h' | '24h' | '7d' | '30d' = '24h'): Observable<WanCalidadResp> {
    return this.api.get<WanCalidadResp>(`/recursos/${id}/wan-calidad`, { rango });
  }

  respaldos(id: number): Observable<Respaldo[]> {
    return this.api.get<Respaldo[]>(`/recursos/${id}/respaldos`);
  }
  respaldoContenido(id: number, respaldoId: number): Observable<RespaldoDetalle> {
    return this.api.get<RespaldoDetalle>(`/recursos/${id}/respaldos/${respaldoId}`);
  }

  tipos(): Observable<Paginated<TipoRecurso>> {
    return this.api.get<Paginated<TipoRecurso>>('/tipos-recurso', { per_page: 100 });
  }
  sitios(): Observable<Paginated<Sitio>> {
    return this.api.get<Paginated<Sitio>>('/sitios', { per_page: 100 });
  }
}
