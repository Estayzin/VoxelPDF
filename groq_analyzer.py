import base64
import json
import re
import io
from groq import Groq
from PIL import Image


class GroqRateLimitError(Exception):
    """Se lanza cuando todos los modelos de Groq han agotado su límite de tokens."""
    def __init__(self, msg, retry_after: str = ""):
        super().__init__(msg)
        self.retry_after = retry_after


# Modelos con soporte de visión — se prueban en orden hasta encontrar uno disponible
_VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
]

PROMPT = """Eres un revisor experto en planimetría arquitectónica latinoamericana (Chile, Colombia, Perú, México, Argentina). Analiza esta imagen y evalúa exactamente estos 10 elementos. En la observación incluye el texto exacto que encontraste. Responde SOLO con este JSON:

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
  "legibilidad_ejes":  {"presente": true,  "observacion": "comentario breve"},
  "paleta_colores":    {"presente": true,  "observacion": "comentario breve"},
  "resumen": "Una oración sobre el estado general del plano"
}

Criterios:
- vineta_keywords: ¿La viñeta/carátula tiene todos estos campos RELLENOS con contenido real (no vacíos, no en blanco): título del proyecto, número de lámina, escala, fecha y firma o nombre del profesional? Marca false si alguno de estos campos está vacío, en blanco o sin contenido visible.
- vineta_ubicacion: ¿La viñeta está en la esquina inferior derecha o borde derecho?
- numero_lamina: ¿Se ve un código de lámina (L-01, A-101, PL-02, Sheet 3, etc.)?
- escala_numerica: ¿Se indica la escala como 1:X (ej: 1:50, 1:100)? Si ves "As Indicated", "As indicated" o "Según se indica" → marca presente=false con observacion que empiece exactamente con "As Indicated —" seguido de una breve nota (indica que la escala está en inglés o no es un valor numérico).
- orientacion_norte: PRIMERO: si la lámina es corte, elevación, alzado, fachada, detalle, perspectiva, cuadro o tabla → marca presente=true con "No aplica — lámina tipo [X]". Para plantas de cualquier especialidad (arquitectura, instalaciones, estructura, MEP): busca CUALQUIERA de estas indicaciones — (a) símbolo de norte, flecha N, flecha con la letra N o la palabra NORTE, aunque sea una flecha simple sin círculo; (b) plano de ubicación o plano de emplazamiento que muestre la orientación del proyecto; (c) plano llave o key plan — diagrama pequeño que muestra qué zona o sector del edificio cubre esta lámina, generalmente un rectángulo o polígono con un área resaltada o sombreada — puede estar en la viñeta, en una esquina del dibujo o en cualquier parte de la lámina. Marca false SOLO si no encuentras absolutamente ninguno de los tres en toda la lámina.
- nombres_ambientes: Si la lámina es corte, elevación, alzado, fachada, detalle, perspectiva, cuadro o tabla → marca presente=true con "No aplica — lámina tipo [X]". Para plantas, evalúa según el tipo: (A) Plantas de ARQ, MEP, instalaciones o estructura → busca etiquetas de recintos en el área de dibujo: CÓDIGOS X.X.X, nombres completos (DORMITORIO, BAÑO, COCINA, SALA, LIVING, SALA DE MÁQUINAS, CUARTO DE BOMBAS, LABORATORIO, etc.), abreviaciones (DORM., HAB., BÑO., SS.HH, WC) y regionalismos (PIEZA, CUARTO, QUINCHO) — los planos MEP y estructura suelen mostrar las etiquetas arquitectónicas de base, búscalas. (B) Plantas de coordinación (varios sistemas superpuestos o láminas con código ALL, COORD o similar) → evalúa si se identifica claramente el edificio, bloque, torre o sector al que corresponde el dibujo (ej: "Edificio A", "Block B", "Torre 1", "Sector Norte", nombre del recinto principal) — esto es necesario para evitar ambigüedad sobre qué edificio se está viendo. Marca false si en el tipo A no hay ninguna etiqueta de recinto, o en el tipo B no se identifica el edificio/sector.
- cotas_dimensiones: Si la lámina es de instalaciones o MEP (climatización, sanitario, eléctrico, gases, incendio, pavimentos, u otra especialidad de redes) → marca presente=true con "No aplica — lámina MEP/instalaciones". Para láminas de ARQ o EST: busca líneas de cota con valor numérico de medida (ej: "3.50", "120", "2500") asociadas a muros, vanos o elementos estructurales. NO confundas etiquetas de recintos, números de ejes o códigos de lámina con cotas. Marca false si no hay ninguna línea de cota con valor numérico en la zona de dibujo.
- densidad_grafica: Evalúa dos cosas juntas — (1) ¿La zona de dibujo tiene contenido gráfico distribuido en al menos 2 zonas distintas de la hoja (no está en blanco)? (2) ¿Las líneas y elementos corresponden a la especialidad de la lámina? Para arquitectura: muros, puertas, ventanas. Para instalaciones (eléctrica, sanitaria, climatización, gases, incendio): tuberías, ductos, conexiones, símbolos técnicos. Para estructura: vigas, columnas, fundaciones, armaduras. Marca false si la lámina parece en blanco o si el contenido no corresponde a ninguna especialidad técnica reconocible.
- densidad_texto: Evalúa si hay etiquetas o anotaciones técnicas en la ZONA DE DIBUJO propias de la especialidad (fuera de la viñeta). Para ARQ: nombres de recintos, cotas, notas de materiales. Para MEP e instalaciones: etiquetas de ductos, cañerías, diámetros, caudales, circuitos, símbolos con texto. Para EST: referencias de elementos estructurales, armaduras, perfiles. NO cuentes el texto que está únicamente dentro de la viñeta/carátula (borde derecho o inferior). Marca false si no hay ninguna anotación técnica en la zona de dibujo.
- legibilidad_ejes: Solo marca "No aplica" si la lámina es plano topográfico, plano de ubicación/emplazamiento, cuadro, tabla o perspectiva sin grilla de ejes. Para TODAS las demás láminas (ARQ, MEP, instalaciones, EST, coordinación) que tengan grilla de ejes estructurales: evalúa si los ejes son legibles. Los planos de instalaciones y MEP comparten la misma grilla de ejes que el ARQ — búscalos aunque estén en segundo plano. Marca false si: (a) los círculos o burbujas de eje se solapan entre sí o con texto/cotas cercanas, (b) el texto dentro de la burbuja es ilegible o está tapado, (c) los ejes están tan juntos que sus burbujas se tocan o cruzan. Marca true si todos los ejes visibles son claramente legibles y no se solapan.
- paleta_colores: Si el dibujo es monocromo (solo líneas negras/grises, sin colores) → marca presente=true con "No aplica — lámina monocroma". Si el dibujo usa colores para diferenciar sistemas, elementos o categorías → verifica que haya una leyenda o simbología de colores en la viñeta o en algún recuadro de la lámina que explique qué representa cada color. Marca false si hay colores en el dibujo pero no hay ninguna leyenda que los explique.

Responde SOLO con el JSON, sin texto adicional."""


MAX_PIXELS = 33_000_000


def _resize_if_needed(image: Image.Image) -> Image.Image:
    w, h = image.size
    if w * h > MAX_PIXELS:
        scale = (MAX_PIXELS / (w * h)) ** 0.5
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return image


def analyze_page(image: Image.Image, api_key: str, nombre_archivo: str = "") -> dict:
    client = Groq(api_key=api_key)
    image = _resize_if_needed(image)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    prompt = PROMPT
    if nombre_archivo:
        prompt += f"\n\nNombre del archivo PDF: «{nombre_archivo}». Úsalo como referencia adicional para numero_lamina (solo informativo, el check pasa/falla según lo visible en el plano)."

    last_rate_limit = None  # type: GroqRateLimitError

    for model in _VISION_MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                temperature=0.1,
                max_tokens=600,
            )
            text = response.choices[0].message.content.strip()
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError(f"Respuesta inesperada de Groq ({model}): {text}")

        except Exception as e:
            err_str = str(e)
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                m = re.search(r"try again in ([\d\w\.\s]+?)(?:\.|$)", err_str)
                retry = m.group(1).strip() if m else "unos minutos"
                last_rate_limit = GroqRateLimitError(
                    f"Límite de tokens Groq agotado en {model} — intenta en {retry}.",
                    retry_after=retry,
                )
                continue  # probar siguiente modelo
            raise  # cualquier otro error se propaga inmediatamente

    raise last_rate_limit  # todos los modelos agotados


def calcular_puntaje(resultado: dict) -> tuple[int, int]:
    from analyzer import CHECKS
    total = len(CHECKS)
    aprobados = sum(1 for c in CHECKS if resultado.get(c["id"], {}).get("presente", False))
    return aprobados, total
