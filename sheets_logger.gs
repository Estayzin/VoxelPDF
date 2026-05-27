/**
 * VoxelBIM — Google Apps Script Logger
 * ─────────────────────────────────────
 * Instrucciones:
 *   1. Crea una hoja en sheets.google.com y copia su ID desde la URL:
 *      https://docs.google.com/spreadsheets/d/[ESTE_ES_EL_ID]/edit
 *   2. Pega el ID en SPREADSHEET_ID (abajo)
 *   3. Implementar → Nueva implementación → Tipo: App web
 *      · Ejecutar como: Yo
 *      · Quién tiene acceso: Cualquier persona
 *   4. Copia la URL generada y pégala en VoxelBIM → ⚙ API Keys → Google Sheets URL
 */

// ▼ PEGA AQUÍ EL ID DE TU GOOGLE SHEET ▼
const SPREADSHEET_ID = 'PEGA_TU_ID_AQUI';
// ▲────────────────────────────────────▲

const SHEET_NAME = 'Historial VoxelBIM';

const HEADERS = [
  'Fecha', 'PDF', 'Páginas OK', 'Páginas Error', '% Promedio',
  'Aprobadas', 'Total', 'Estado',
  'Viñeta/Carátula', 'Viñeta zona correcta', 'Nº Lámina', 'Escala numérica',
  'Orientación/Norte', 'Nomenclatura ambientes', 'Cotas/dimensiones',
  'Grafismo zona dibujo', 'Etiquetas y texto', 'Código vs nombre archivo',
  'Ejes legibles', 'Formato hoja', 'Tamaño texto mín', 'Simbología colores'
];

const CHECK_IDS = [
  'vineta_keywords', 'vineta_ubicacion', 'numero_lamina', 'escala_numerica',
  'orientacion_norte', 'nombres_ambientes', 'cotas_dimensiones',
  'densidad_grafica', 'densidad_texto', 'concordancia_nombre',
  'legibilidad_ejes', 'formato_hoja', 'tamanio_texto_min', 'paleta_colores'
];

function doPost(e) {
  try {
    const data  = JSON.parse(e.postData.contents);
    const ss    = SpreadsheetApp.openById(SPREADSHEET_ID);
    let   sheet = ss.getSheetByName(SHEET_NAME);

    if (!sheet) {
      sheet = ss.insertSheet(SHEET_NAME);
      sheet.appendRow(HEADERS);
      sheet.setFrozenRows(1);
      sheet.getRange(1, 1, 1, HEADERS.length)
           .setBackground('#0a1628').setFontColor('#00d4ff')
           .setFontWeight('bold');
    }

    // Agregar una fila por PDF
    data.pdfs.forEach(pdf => {
      const estado = pdf.pct >= 80 ? 'APROBADO' : pdf.pct >= 50 ? 'REVISAR' : 'RECHAZADO';

      const checkCols = CHECK_IDS.map(id => {
        const v = pdf.checks[id];
        if (v === null || v === undefined) return '';
        if (typeof v === 'string') return v;          // "No aplica"
        return v ? 'OK' : 'FALLA';
      });

      sheet.appendRow([
        data.fecha,
        pdf.pdf_name,
        pdf.paginas_ok,
        pdf.paginas_error,
        pdf.pct + '%',
        pdf.aprobadas,
        pdf.total,
        estado,
        ...checkCols
      ]);
    });

    return ContentService
      .createTextOutput(JSON.stringify({ ok: true }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// Necesario para que el navegador no falle con preflight CORS
function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, service: 'VoxelBIM Sheets Logger' }))
    .setMimeType(ContentService.MimeType.JSON);
}
