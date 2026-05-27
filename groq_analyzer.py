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
  "contenido_central": {"presente": true,  "observacion": "comentario breve"},
  "resumen": "Una oración sobre el estado general del plano"
}

Criterios:
- vineta_keywords: ¿La viñeta/carátula tiene todos estos campos RELLENOS con contenido real (no vacíos, no en blanco): título del proyecto, número de lámina, escala, fecha y firma o nombre del profesional? Marca false si alguno de estos campos está vacío, en blanco o sin contenido visible.
- vineta_ubicacion: ¿La viñeta está en la esquina inferior derecha o borde derecho?
- numero_lamina: ¿Se ve un código de lámina (L-01, A-101, PL-02, Sheet 3, etc.)?
- escala_numerica: ¿Se indica la escala como 1:X (ej: 1:50, 1:100)? Si ves "As Indicated", "As indicated" o "Según se indica" → marca presente=false con observacion que empiece exactamente con "As Indicated —" seguido de una breve nota (indica que la escala está en inglés o no es un valor numérico).
- orientacion_norte: PRIMERO: si la lámina es corte, elevación, alzado, fachada, detalle, perspectiva, cuadro o tabla → marca presente=true con "No aplica — lámina tipo [X]". Para plantas de cualquier especialidad (arquitectura, instalaciones, estructura, MEP): busca CUALQUIERA de estas indicaciones — (a) símbolo de norte, flecha N, flecha con la letra N o la palabra NORTE, aunque sea una flecha simple sin círculo; (b) plano de ubicación o plano de emplazamiento que muestre la orientación del proyecto; (c) plano llave o key plan — diagrama pequeño que muestra qué zona o sector del edificio cubre esta lámina, generalmente un rectángulo o polígono con un área resaltada o sombreada — puede estar en la viñeta, en una esquina del dibujo o en cualquier parte de la lámina. Marca false SOLO si no encuentras absolutamente ninguno de los tres en toda la lámina.
- nombres_ambientes: Si la lámina es corte, elevación, alzado, fachada, detalle, perspectiva, cuadro o tabla → marca presente=true con "No aplica — lámina tipo [X]". Para plantas, evalúa según el tipo: (A) Plantas de ARQ, MEP, instalaciones o estructura → busca etiquetas de recintos en el área de dibujo: CÓDIGOS X.X.X, nombres completos (DORMITORIO, BAÑO, COCINA, SALA, LIVING, SALA DE MÁQUINAS, CUARTO DE BOMBAS, LABORATORIO, etc.), abreviaciones (DORM., HAB., BÑO., SS.HH, WC) y regionalismos (PIEZA, CUARTO, QUINCHO) — los planos MEP y estructura suelen mostrar las etiquetas arquitectónicas de base, búscalas. (B) Plantas de coordinación (varios sistemas superpuestos o láminas con código ALL, COORD o similar) → evalúa si se identifica claramente el edificio, bloque, torre o sector al que corresponde el dibujo (ej: "Edificio A", "Block B", "Torre 1", "Sector Norte", nombre del recinto principal) — esto es necesario para evitar ambigüedad sobre qué edificio se está viendo. Marca false si en el tipo A no hay ninguna etiqueta de recinto, o en el tipo B no se identifica el edificio/sector.
- cotas_dimensiones: ¿Hay cotas numéricas de medidas en muros o espacios?
- densidad_grafica: ¿El dibujo tiene líneas claras de elementos propios de la especialidad? Para arquitectura: muros, puertas, ventanas. Para instalaciones (eléctrica, sanitaria, climatización, gases, incendio): tuberías, ductos, conexiones, símbolos técnicos. Para estructura: vigas, columnas, fundaciones, armaduras. Evalúa según lo que corresponde a la especialidad visible, no solo muros arquitectónicos.
- densidad_texto: ¿Hay texto distribuido en la ZONA DE DIBUJO del plano (fuera de la viñeta)? El texto debe aparecer en el área de dibujo como etiquetas de ambientes, cotas, referencias o anotaciones. NO cuentes el texto que está únicamente dentro de la viñeta/carátula (borde derecho o inferior). Si la lámina parece en blanco o el único texto visible es la viñeta, marca false.
- contenido_central: ¿La zona de dibujo de la lámina tiene contenido gráfico distribuido? NO evalúes solo el centro geométrico — revisa toda el área excluyendo la viñeta (borde derecho/inferior). El contenido puede estar sesgado a la izquierda, derecha, arriba o en varias zonas. Marca presente=true si hay líneas, muros, elementos arquitectónicos o dibujo técnico en AL MENOS 2 zonas distintas de la hoja. Solo marca false si la lámina parece completamente en blanco o casi vacía en toda su extensión.

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
