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
  { id: 'contenido_central' },
  { id: 'concordancia_nombre' },
  { id: 'legibilidad_ejes' },
];

// ── Modelos Groq con visión (se prueban en orden) ─────────────────────────────
const GROQ_MODELS = [
  'meta-llama/llama-4-scout-17b-16e-instruct',
  'meta-llama/llama-4-maverick-17b-128e-instruct',
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
  "densidad_grafica":  {"presente": true,  "observacion": "comentario breve"},
  "densidad_texto":    {"presente": true,  "observacion": "comentario breve"},
  "contenido_central":   {"presente": true,  "observacion": "comentario breve"},
  "concordancia_nombre": {"presente": true,  "observacion": "comentario breve"},
  "legibilidad_ejes":    {"presente": true,  "observacion": "comentario breve"},
  "resumen": "Una oración sobre el estado general del plano"
}

Criterios:
- vineta_keywords: ¿Hay viñeta/carátula con título, número de lámina, escala, fecha y firma?
- vineta_ubicacion: ¿La viñeta está en la esquina inferior derecha o borde derecho?
- numero_lamina: ¿Se ve un código de lámina (L-01, A-101, PL-02, Sheet 3, etc.)?
- escala_numerica: ¿Se indica la escala como 1:X (ej: 1:50, 1:100)?
- orientacion_norte: PRIMERO: si la lámina es corte, elevación, alzado, fachada, detalle, perspectiva, cuadro o tabla → marca presente=true con "No aplica — lámina tipo [X]". Para plantas de cualquier especialidad (arquitectura, instalaciones, estructura, MEP): busca (a) símbolo de norte o flecha N, (b) plano de ubicación o emplazamiento en la viñeta que muestre la orientación del proyecto — cualquiera de los dos es válido. Marca false solo si no hay ninguno de los dos.
- nombres_ambientes: Si la lámina es corte, elevación, alzado, fachada, detalle, perspectiva, cuadro o tabla → marca presente=true con "No aplica — lámina tipo [X]". Para plantas de CUALQUIER especialidad evalúa si hay etiquetas de recintos o espacios: CÓDIGOS X.X.X, nombres completos (DORMITORIO, BAÑO, COCINA, SALA, LIVING, SALA DE MÁQUINAS, etc.), abreviaciones (DORM., HAB., BÑO., SS.HH, WC) y regionalismos (PIEZA, CUARTO, QUINCHO).
- cotas_dimensiones: ¿Hay cotas numéricas de medidas en muros o espacios?
- densidad_grafica: ¿El dibujo tiene líneas claras de elementos propios de la especialidad? Para arquitectura: muros, puertas, ventanas. Para instalaciones: tuberías, ductos, conexiones, símbolos técnicos. Para estructura: vigas, columnas, fundaciones.
- densidad_texto: ¿Hay texto distribuido en la ZONA DE DIBUJO del plano (fuera de la viñeta)? NO cuentes el texto que está únicamente dentro de la viñeta/carátula. Si la lámina parece en blanco o el único texto visible es la viñeta, marca false.
- contenido_central: ¿La zona de dibujo de la lámina tiene contenido gráfico distribuido? Marca presente=true si hay líneas o dibujo técnico en AL MENOS 2 zonas distintas de la hoja. Solo marca false si la lámina parece completamente en blanco.
- concordancia_nombre: Usando el nombre del archivo PDF indicado al final del mensaje, ¿el código o número de lámina visible en el plano (en viñeta u otro lugar) corresponde o guarda relación con ese nombre de archivo? Si el nombre no contiene un código reconocible (ej: "scan_001", "documento", solo números), marca presente=true con "Nombre genérico, sin código comparable". Si el nombre contiene un código (A-101, PL-02, E-03, ARQ-001, etc.), verifica si ese código aparece en el plano. Marca false solo si hay un código claro en el nombre pero no aparece en el plano.
- legibilidad_ejes: Si la lámina es un plano topográfico, plano de ubicación/emplazamiento, cuadro, tabla o perspectiva sin grilla estructural → marca presente=true con "No aplica — lámina tipo [X]". Para plantas y cortes/elevaciones con grilla de ejes: evalúa si los ejes (círculos o burbuja con número o letra en los extremos de la grilla) son legibles. Marca false si: (a) los círculos de eje se solapan entre sí o con cotas/texto cercano, (b) el texto dentro de la burbuja es ilegible o está tapado, (c) los ejes están tan juntos que sus burbujas se tocan o cruzan. Marca true si todos los ejes visibles son claramente legibles y no se solapan.

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
