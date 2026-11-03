<?php

namespace App\Http\Controllers;

use App\Support\ReporteData;
use App\Support\ReporteExport;
use Dompdf\Dompdf;
use Dompdf\Options;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

/**
 * Exporta los 4 reportes (ejecutivo / sitio / recurso / servicios) en CSV, XLSX
 * y PDF (con imagen corporativa). Lectura: disponible a cualquier rol autenticado.
 */
class ReporteExportController extends Controller
{
    public function export(string $tipo, Request $request)
    {
        $request->merge(['tipo' => $tipo]);
        $v = $request->validate([
            'tipo'    => [Rule::in(['ejecutivo', 'sitio', 'recurso', 'servicios', 'banda', 'alertas'])],
            'formato' => [Rule::in(['csv', 'xlsx', 'pdf'])],
            'rango'   => ['nullable', Rule::in(['24h', '7d', '30d'])],
            'id'      => ['nullable', 'integer'],
        ]);
        $rango = $v['rango'] ?? '7d';
        $id = isset($v['id']) ? (int) $v['id'] : null;

        $data = ReporteData::construir($tipo, $rango, $id);
        $base = 'reporte_'.$tipo.'_'.$rango.'_'.now()->format('Ymd_Hi');

        return match ($v['formato']) {
            'csv'  => $this->descarga(ReporteExport::csv($data), "$base.csv", 'text/csv; charset=utf-8'),
            'xlsx' => $this->descarga(ReporteExport::xlsx($data), "$base.xlsx",
                          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            'pdf'  => $this->descarga($this->pdf($data), "$base.pdf", 'application/pdf'),
        };
    }

    private function descarga(string $contenido, string $nombre, string $mime)
    {
        return response($contenido, 200, [
            'Content-Type'        => $mime,
            'Content-Disposition' => 'attachment; filename="'.$nombre.'"',
            'Content-Length'      => (string) strlen($contenido),
        ]);
    }

    private function pdf(array $data): string
    {
        // Dompdf carga el DOM completo + glifos de fuente en memoria; un informe
        // tabular grande (p.ej. cientos de alertas) supera el límite por defecto de
        // PHP (128M). Se eleva solo para esta generación (el servidor tiene RAM de sobra).
        ini_set('memory_limit', '512M');

        $html = view('reportes.pdf', [
            'data'     => $data,
            'logo'     => $this->logoDataUri(),
            'generado' => now()->format('Y-m-d H:i'),
        ])->render();

        $options = new Options();
        $options->set('isRemoteEnabled', false);
        $options->set('defaultFont', 'DejaVu Sans');
        $options->set('isHtml5ParserEnabled', true);

        $dompdf = new Dompdf($options);
        $dompdf->loadHtml($html);
        $dompdf->setPaper('A4', 'landscape');
        $dompdf->render();

        // Pie institucional + numeración en cada página (vía canvas).
        $canvas = $dompdf->getCanvas();
        $font = $dompdf->getFontMetrics()->getFont('DejaVu Sans');
        $gris = [0.54, 0.58, 0.55];
        $y = $canvas->get_height() - 30;
        $canvas->line(36, $y - 6, $canvas->get_width() - 36, $y - 6, [0.84, 0.88, 0.85], 0.5);
        $canvas->page_text(36, $y, 'Parques Nacionales Naturales de Colombia — SIMON', $font, 8, $gris);
        $canvas->page_text($canvas->get_width() - 130, $y, 'Página {PAGE_NUM} de {PAGE_COUNT}', $font, 8, $gris);

        return (string) $dompdf->output();
    }

    private function logoDataUri(): ?string
    {
        $ruta = resource_path('branding/logo-simon.png');
        if (! is_file($ruta)) {
            return null;
        }

        return 'data:image/png;base64,'.base64_encode((string) file_get_contents($ruta));
    }
}
