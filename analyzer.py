import json
import re
import io
from google import genai
from google.genai import types
from PIL import Image

# 10 checks unificados — mismos IDs y nombres que rules.py
CHECKS = [
    {"id": "vineta_keywords",  "nombre": "Viñeta / Carátula",              "descripcion": "Campos mínimos: título, número de lámina, escala, fecha, firma/responsable"},
    {"id": "vineta_ubicacion", "nombre": "Viñeta en zona correcta",        "descripcion": "La viñeta está en la esquina inferior derecha o borde derecho de la hoja"},
    {"id": "numero_lamina",    "nombre": "Número de lámina",               "descripcion": "Código de lámina visible: L-01, A-101, PL-02, Sheet 3, etc."},
    {"id": "escala_numerica",  "nombre": "Escala numérica",                "descripcion": "Escala indicada como 1:50, 1:100, 1:200, etc."},
    {"id": "orientacion_norte","nombre": "Orientación / Norte",            "descripcion": "Símbolo de norte o indicador de orientación presente en el plano"},
    {"id": "nombres_ambientes","nombre": "Nomenclatura de ambientes",      "descripcion": "Etiquetas de espacios: dormitorio, baño, cocina, sala, oficina, etc."},
    {"id": "cotas_dimensiones","nombre": "Cotas / dimensiones",            "descripcion": "Cotas numéricas de medidas (ej: 2.50, 3,00 m, 120 cm) en muros o espacios"},
    {"id": "densidad_grafica", "nombre": "Grafismo / contenido gráfico",   "descripcion": "El dibujo tiene líneas claras de muros, espacios y elementos arquitectónicos"},
    {"id": "densidad_texto",   "nombre": "Etiquetas y texto distribuido",  "descripcion": "Texto distribuido en el plano: referencias, números, anotaciones"},
    {"id": "contenido_central","nombre": "Contenido en zona de dibujo",    "descripcion": "La zona central de la lámina tiene dibujo, no está vacía ni cortada"},
]

PROMPT_TEMPLATE = """Eres un revisor experto en planimetría arquitectónica. Analiza esta imagen y evalúa exactamente estos 10 elementos. Responde SOLO con este JSON:

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
- nombres_ambientes: ¿Hay etiquetas de ambientes (dormitorio, baño, cocina, sala, etc.)?
- cotas_dimensiones: ¿Hay cotas numéricas de medidas en muros o espacios?
- densidad_grafica: ¿El dibujo tiene líneas claras de muros y elementos arquitectónicos?
- densidad_texto: ¿Hay texto distribuido en el plano (referencias, números, anotaciones)?
- contenido_central: ¿La zona central de la lámina tiene dibujo y no está vacía?

Responde SOLO con el JSON, sin texto adicional."""


def analyze_page(image: Image.Image, api_key: str, model: str = "gemini-2.0-flash-lite") -> dict:
    client = genai.Client(api_key=api_key)

    img_bytes = io.BytesIO()
    image.save(img_bytes, format="PNG")
    img_data = img_bytes.getvalue()

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=img_data, mime_type="image/png"),
            types.Part.from_text(text=PROMPT_TEMPLATE),
        ],
        config=types.GenerateContentConfig(temperature=0.1),
    )

    text = response.text.strip()
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())

    raise ValueError(f"Respuesta inesperada de Gemini: {text}")


def calcular_puntaje(resultado: dict) -> tuple[int, int]:
    aplicables = [
        c for c in CHECKS
        if not resultado.get(c["id"], {}).get("observacion", "").startswith("No aplica")
    ]
    aprobados = sum(1 for c in aplicables if resultado.get(c["id"], {}).get("presente", False))
    return aprobados, len(aplicables)
