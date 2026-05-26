import base64
import json
import re
import io
from groq import Groq
from PIL import Image

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
- vineta_keywords: ¿Hay viñeta/carátula con título, número de lámina, escala, fecha y firma?
- vineta_ubicacion: ¿La viñeta está en la esquina inferior derecha o borde derecho?
- numero_lamina: ¿Se ve un código de lámina (L-01, A-101, PL-02, Sheet 3, etc.)?
- escala_numerica: ¿Se indica la escala como 1:X (ej: 1:50, 1:100)?
- orientacion_norte: ¿Hay símbolo de norte u orientación?
- nombres_ambientes: ¿Hay AL MENOS UNA etiqueta que identifique un espacio o ambiente en el cuerpo del plano? Considera válido: nombres completos (DORMITORIO, BAÑO, COCINA, SALA, LIVING, COMEDOR, PASILLO, BODEGA, TERRAZA, PATIO, HALL, OFICINA, ESTUDIO, GARAGE, LOGIA, RECEPCIÓN, LOBBY, VESTÍBULO, LAVANDERÍA); abreviaciones frecuentes en planimetría (DORM., DORM 1, HAB., BÑO., BNO., BOD., EST., VEST., COMED., GAR., LAV., SS.HH, SSHH, WC); regionalismos latinoamericanos (PIEZA, CUARTO, QUINCHO, BALCÓN, ESTAR, ESCRITORIO, JARDIN). Marca presente=true si encuentras CUALQUIERA de estas etiquetas, incluso si es una sola y abreviada.
- cotas_dimensiones: ¿Hay cotas numéricas de medidas en muros o espacios?
- densidad_grafica: ¿El dibujo tiene líneas claras de muros y elementos arquitectónicos?
- densidad_texto: ¿Hay texto distribuido en el plano (referencias, números, anotaciones)?
- contenido_central: ¿La zona central de la lámina tiene dibujo y no está vacía?

Responde SOLO con el JSON, sin texto adicional."""


MAX_PIXELS = 33_000_000


def _resize_if_needed(image: Image.Image) -> Image.Image:
    w, h = image.size
    if w * h > MAX_PIXELS:
        scale = (MAX_PIXELS / (w * h)) ** 0.5
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return image


def analyze_page(image: Image.Image, api_key: str) -> dict:
    client = Groq(api_key=api_key)
    image = _resize_if_needed(image)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": PROMPT},
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

    raise ValueError(f"Respuesta inesperada de Groq: {text}")


def calcular_puntaje(resultado: dict) -> tuple[int, int]:
    from analyzer import CHECKS
    total = len(CHECKS)
    aprobados = sum(1 for c in CHECKS if resultado.get(c["id"], {}).get("presente", False))
    return aprobados, total
