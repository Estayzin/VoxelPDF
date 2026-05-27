/**
 * VoxelPDF — Cloudflare Worker
 * Proxy para Groq. Recibe imagen base64 del browser,
 * llama a la API de IA y devuelve el resultado de análisis.
 *
 * Variables de entorno (Cloudflare Dashboard > Workers > Settings):
 *   GROQ_API_KEY — clave de Groq (fallback si el cliente no envía la suya)
 */

// ── Checks (mismo orden que el frontend) ──────────────────────────────────────
const CHECKS = [
  { id: 'vineta_keywords' },
  { id: 'vineta_ubicacion' },
  { id: 'numero_lamina' },
  { id: 'escala_numerica' },
  { id: 'orientacion_norte' },
  { id: 'nombres_ambientes' },
  { id: 'cotas_dimensiones' },
  { id: 'densidad_grafica' },
  { id: 'densidad_texto' },
  { id: 'concordancia_nombre' },
  { id: 'legibilidad_ejes' },
  { id: 'paleta_colores' },
];

// ── Modelos Groq con visión ───────────────────────────────────────────────────
const GROQ_MODELS = [
  'meta-llama/llama-4-scout-17b-16e-instruct',
];

// ── Prompt (igual al groq_analyzer.py) ───────────────────────────────────────
const PROMPT = `Eres un revisor experto en planimetría arquitectónica latinoamericana (Chile, Colombia, Perú, México, Argentina). Analiza esta imagen y evalúa exactamente estos 10 elementos. En la observación incluye el texto exacto que encontraste. Responde SOLO con este JSON:

{
  "vineta_keywords":   {"presente": true,  "observacion": "comentario breve"},
  "vineta_ubicacion":  {"presente": true,  "observacion": "comentario breve"},
  "numero_lamina":     {"presente": false, "observacion": "comentario breve"},
  "escala_numerica":   {"presente": true,  "observacion": "comentario breve"},
  "orientacion_norte": {"presente": false, "observacion": "comentario breve"},
  "nombres_ambientes": {"presente": true,  "observacion": "comentario breve"},
  "cotas_dimensiones": {"presente": true,  "observacion": "comentario breve"},
  "densidad_grafica":    {"presente": true,  "observacion": "comentario breve"},
  "densidad_texto":      {"presente": true,  "observacion": "comentario breve"},
  "concordancia_nombre": {"presente": true,  "observacion": "comentario breve"},
  "legibilidad_ejes":    {"presente": true,  "observacion": "comentario breve"},
  "paleta_colores":      {"presente": true,  "observacion": "comentario breve"},
  "resumen": "Una oración sobre el estado general del plano"
}

Criterios:
- vineta_keywords: ¿La viñeta/carátula tiene todos estos campos RELLENOS con contenido real (no vacíos, no en blanco): título del proyecto, número de lámina, escala, fecha y firma o nombre del profesional? Marca false si alguno de estos campos está vacío, en blanco o sin contenido visible.
- vineta_ubicacion: ¿La viñeta está en la esquina inferior derecha o borde derecho?
- numero_lamina: ¿Se ve un código de lámina (L-01, A-101, PL-02, Sheet 3, etc.)?
- escala_numerica: ¿Se indica la escala como 1:X (ej: 1:50, 1:100)? Si ves "As Indicated", "As indicated" o "Según se indica" → marca presente=false con observacion que empiece exactamente con "As Indicated —" seguido de una breve nota (indica que la escala está en inglés o no es un valor numérico).
- orientacion_norte: PRIMERO: si la lámina es corte, elevación, alzado, fachada, detalle, perspectiva, cuadro o tabla → marca presente=true con "No aplica — lámina tipo [X]". Para plantas de cualquier especialidad (arquitectura, instalaciones, estructura, MEP): busca CUALQUIERA de estas indicaciones — (a) símbolo de norte, flecha N, flecha con la letra N o la palabra NORTE, aunque sea una flecha simple sin círculo; (b) plano de ubicación o plano de emplazamiento que muestre la orientación del proyecto; (c) plano llave o key plan — diagrama pequeño que muestra qué zona o sector del edificio cubre esta lámina, generalmente un rectángulo o polígono con un área resaltada o sombreada — puede estar en la viñeta, en una esquina del dibujo o en cualquier parte de la lámina. Marca false SOLO si no encuentras absolutamente ninguno de los tres en toda la lámina.
- nombres_ambientes: Si la lámina es corte, elevación, alzado, fachada, detalle, perspectiva, cuadro o tabla → marca presente=true con "No aplica — lámina tipo [X]". Para plantas, evalúa según el tipo: (A) Plantas de ARQ, MEP, instalaciones o estructura → busca etiquetas de recintos en el área de dibujo: CÓDIGOS X.X.X, nombres completos (DORMITORIO, BAÑO, COCINA, SALA, LIVING, SALA DE MÁQUINAS, LABORATORIO, etc.), abreviaciones (DORM., HAB., BÑO., SS.HH, WC) y regionalismos (PIEZA, CUARTO, QUINCHO) — los planos MEP y estructura suelen mostrar las etiquetas arquitectónicas de base, búscalas. (B) Plantas de coordinación (varios sistemas superpuestos o láminas con código ALL, COORD o similar) → evalúa si se identifica claramente el edificio, bloque, torre o sector al que corresponde el dibujo (ej: "Edificio A", "Block B", "Torre 1", "Sector Norte", nombre del recinto principal) — esto es necesario para evitar ambigüedad sobre qué edificio se está viendo. Marca false si en el tipo A no hay ninguna etiqueta de recinto, o en el tipo B no se identifica el edificio/sector.
- cotas_dimensiones: Si la lámina es de instalaciones o MEP (climatización, sanitario, eléctrico, gases, incendio, pavimentos, u otra especialidad de redes) → marca presente=true con "No aplica — lámina MEP/instalaciones". Para láminas de ARQ o EST: busca líneas de cota con valor numérico de medida (ej: "3.50", "120", "2500") asociadas a muros, vanos o elementos estructurales. NO confundas etiquetas de recintos, números de ejes o códigos de lámina con cotas. Marca false si no hay ninguna línea de cota con valor numérico en la zona de dibujo.
- densidad_grafica: Evalúa dos cosas juntas — (1) ¿La zona de dibujo tiene contenido gráfico distribuido en al menos 2 zonas distintas de la hoja (no está en blanco)? (2) ¿Las líneas y elementos corresponden a la especialidad de la lámina? Para arquitectura: muros, puertas, ventanas. Para instalaciones (CLI, APO, ELE, PCI, etc.): tuberías, ductos, conexiones, símbolos técnicos. Para estructura: vigas, columnas, fundaciones. Marca false si la lámina parece en blanco o si el contenido no corresponde a ninguna especialidad técnica reconocible.
- densidad_texto: Evalúa si hay etiquetas o anotaciones técnicas en la ZONA DE DIBUJO propias de la especialidad (fuera de la viñeta). Para ARQ: nombres de recintos, cotas, notas de materiales. Para MEP e instalaciones: etiquetas de ductos, cañerías, diámetros, caudales, circuitos, símbolos con texto. Para EST: referencias de elementos estructurales, armaduras, perfiles. NO cuentes el texto que está únicamente dentro de la viñeta/carátula. Marca false si no hay ninguna anotación técnica en la zona de dibujo.
- concordancia_nombre: Usando el nombre del archivo PDF indicado al final del mensaje, ¿el código o número de lámina visible en el plano (en viñeta u otro lugar) corresponde o guarda relación con ese nombre de archivo? Si el nombre no contiene un código reconocible (ej: "scan_001", "documento", solo números), marca presente=true con "Nombre genérico, sin código comparable". Si el nombre contiene un código (A-101, PL-02, E-03, ARQ-001, etc.), verifica si ese código aparece en el plano. Marca false solo si hay un código claro en el nombre pero no aparece en el plano.
- legibilidad_ejes: Solo marca "No aplica" si la lámina es plano topográfico, plano de ubicación/emplazamiento, cuadro, tabla o perspectiva sin grilla de ejes. Para TODAS las demás láminas (ARQ, MEP, instalaciones, EST, coordinación) que tengan grilla de ejes estructurales: evalúa si los ejes son legibles. Los planos de instalaciones y MEP comparten la misma grilla de ejes que el ARQ — búscalos aunque estén en segundo plano. Marca false si: (a) los círculos o burbujas de eje se solapan entre sí o con texto/cotas cercanas, (b) el texto dentro de la burbuja es ilegible o está tapado, (c) los ejes están tan juntos que sus burbujas se tocan o cruzan. Marca true si todos los ejes visibles son claramente legibles y no se solapan.
- paleta_colores: Si el dibujo es monocromo (solo líneas negras/grises, sin colores) → marca presente=true con "No aplica — lámina monocroma". Si el dibujo usa colores para diferenciar sistemas, elementos o categorías → verifica que haya una leyenda o simbología de colores en la viñeta o en algún recuadro de la lámina que explique qué representa cada color. Marca false si hay colores en el dibujo pero no hay ninguna leyenda que los explique.

Responde SOLO con el JSON, sin texto adicional.`;

// ── Calcular puntaje ──────────────────────────────────────────────────────────
function calcularPuntaje(resultado) {
  const aplicables = CHECKS.filter(c => {
    const obs = resultado[c.id]?.observacion || '';
    return !obs.startsWith('No aplica');
  });
  const aprobados = aplicables.filter(c => resultado[c.id]?.presente === true).length;
  return { aprobados, total: aplicables.length };
}

// ── Llamada a Groq ────────────────────────────────────────────────────────────
async function callGroq(imageB64, pdfName, apiKey) {
  const promptFinal = pdfName
    ? PROMPT + `\n\nNombre del archivo PDF: «${pdfName}». Úsalo como referencia adicional para numero_lamina.`
    : PROMPT;

  for (const model of GROQ_MODELS) {
    const resp = await fetch('https://api.groq.com/openai/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model,
        messages: [{
          role: 'user',
          content: [
            { type: 'image_url', image_url: { url: `data:image/jpeg;base64,${imageB64}` } },
            { type: 'text', text: promptFinal },
          ],
        }],
        temperature: 0.1,
        max_tokens: 800,
      }),
    });

    if (resp.status === 429) continue; // rate limit → intentar siguiente modelo

    if (!resp.ok) {
      const body = await resp.text().catch(() => '');
      throw new Error(`Groq ${resp.status}: ${body.slice(0, 200)}`);
    }

    const data = await resp.json();
    const text = data.choices[0].message.content.trim();
    const match = text.match(/\{[\s\S]*\}/);
    if (match) return JSON.parse(match[0]);
    throw new Error('Respuesta inesperada de Groq (no es JSON)');
  }

  throw new Error('Todos los modelos Groq agotaron su límite de tokens. Intenta en unos minutos.');
}

// ── Headers CORS ──────────────────────────────────────────────────────────────
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

// ── Handler principal ─────────────────────────────────────────────────────────
export default {
  async fetch(request, env) {

    // Preflight CORS
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405, headers: CORS });
    }

    const json = (body, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });

    try {
      const { image_b64, api_key, page_num = 1, pdf_name = '' } =
        await request.json();

      if (!image_b64) return json({ error: 'image_b64 es requerido' }, 400);

      const key = api_key || env.GROQ_API_KEY;
      if (!key) return json({ error: 'GROQ_API_KEY no configurada' }, 400);

      const resultado = await callGroq(image_b64, pdf_name, key);

      const { aprobados, total } = calcularPuntaje(resultado);
      const pct = total > 0 ? Math.round((aprobados / total) * 100) : 0;

      return json({ pagina: page_num, pdf_name, resultado, aprobados, total, pct });

    } catch (e) {
      return json({ error: e.message }, 500);
    }
  },
};
