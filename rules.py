import re
import fitz
from dataclasses import dataclass

@dataclass
class RuleResult:
    id: str
    nombre: str
    presente: bool
    observacion: str
    confianza: str  # "alta" | "media" | "baja"


def analizar_con_reglas(page: fitz.Page) -> list[RuleResult]:
    texto_raw = page.get_text("text")
    texto = texto_raw.upper()
    bloques = page.get_text("dict")["blocks"]
    dibujos = page.get_drawings()
    rect = page.rect  # dimensiones de la página

    resultados = []

    # ── REGLA 1: Escala numérica ────────────────────────────────────────────
    # Busca patrones como 1:50, 1:100, 1:200, ESC. 1:500
    patron_escala = re.search(r"1\s*[:]\s*\d{1,4}", texto_raw)
    resultados.append(RuleResult(
        id="escala_numerica",
        nombre="Escala numérica",
        presente=bool(patron_escala),
        observacion=f"Encontrada: {patron_escala.group().strip()}" if patron_escala else "No se detectó patrón 1:X",
        confianza="alta",
    ))

    # ── REGLA 2: Viñeta — keywords mínimos ─────────────────────────────────
    # Una viñeta válida debe tener al menos 3 de estos campos
    keywords_vineta = ["FECHA", "ESCALA", "LAMINA", "LÁMINA", "PROYECTO",
                       "NOMBRE", "REVISIÓN", "REVISION", "DIBUJÓ", "DIBUJO",
                       "APROBÓ", "APROBACION", "SHEET", "DATE", "SCALE"]
    encontrados = [k for k in keywords_vineta if k in texto]
    resultados.append(RuleResult(
        id="vineta_keywords",
        nombre="Viñeta / Carátula",
        presente=len(encontrados) >= 3,
        observacion=f"Campos detectados: {', '.join(encontrados)}" if encontrados else "Sin campos de viñeta",
        confianza="alta" if len(encontrados) >= 4 else "media",
    ))

    # ── REGLA 3: Número de lámina ───────────────────────────────────────────
    # Busca patrones como L-01, PL-01, A-101, Lámina 3, Sheet 2
    patron_lamina = re.search(
        r"\b(L|PL|A|E|S|M|C|LÁM|LAM|SHEET|HJ|PLANO)[\s\-_]?\d{1,3}\b",
        texto_raw, re.IGNORECASE
    )
    resultados.append(RuleResult(
        id="numero_lamina",
        nombre="Número de lámina",
        presente=bool(patron_lamina),
        observacion=f"Detectado: {patron_lamina.group().strip()}" if patron_lamina else "Sin número de lámina identificable",
        confianza="media",
    ))

    # ── REGLA 4: Norte u orientación ────────────────────────────────────────
    keywords_norte = ["NORTE", "NORTH", "↑N", "° N", "°N"]
    tiene_norte_texto = any(k in texto for k in keywords_norte)
    # También busca la letra N aislada cerca de bordes (heurística)
    n_aislada = bool(re.search(r"\bN\b", texto_raw))
    resultados.append(RuleResult(
        id="orientacion_norte",
        nombre="Orientación / Norte",
        presente=tiene_norte_texto or n_aislada,
        observacion="Indicador de norte encontrado" if tiene_norte_texto else
                    "Letra N aislada (posible norte)" if n_aislada else "Sin indicador de orientación",
        confianza="alta" if tiene_norte_texto else "baja",
    ))

    # ── REGLA 5: Nombres de ambientes ───────────────────────────────────────
    ambientes = [
        "DORMITORIO", "HABITACIÓN", "HABITACION", "BAÑO", "BANO", "COCINA",
        "SALA", "LIVING", "COMEDOR", "PASILLO", "BODEGA", "ESTUDIO",
        "GARAGE", "PATIO", "TERRAZA", "LOGIA", "HALL", "RECEPCIÓN",
        "OFICINA", "ESTAR", "SERVICIO", "LAVANDERÍA", "LAVANDERIA",
        "BEDROOM", "KITCHEN", "BATHROOM", "CORRIDOR",
    ]
    ambientes_encontrados = [a for a in ambientes if a in texto]
    resultados.append(RuleResult(
        id="nombres_ambientes",
        nombre="Nomenclatura de ambientes",
        presente=len(ambientes_encontrados) >= 1,
        observacion=f"Ambientes: {', '.join(ambientes_encontrados[:5])}" if ambientes_encontrados
                    else "Sin nombres de ambientes reconocibles",
        confianza="alta" if len(ambientes_encontrados) >= 2 else "media",
    ))

    # ── REGLA 6: Cotas / dimensiones ────────────────────────────────────────
    # Busca números con unidades típicas de planos: 2.50, 3,00 m, 120cm, etc.
    cotas = re.findall(r"\b\d{1,2}[.,]\d{2}\b", texto_raw)
    cotas_unidades = re.findall(r"\b\d+\s*(m|cm|mm|ml)\b", texto_raw, re.IGNORECASE)
    total_cotas = len(cotas) + len(cotas_unidades)
    resultados.append(RuleResult(
        id="cotas_dimensiones",
        nombre="Cotas / dimensiones",
        presente=total_cotas >= 3,
        observacion=f"{total_cotas} cotas detectadas" if total_cotas >= 3
                    else f"Solo {total_cotas} cota(s) — puede ser insuficiente",
        confianza="alta" if total_cotas >= 5 else "media",
    ))

    # ── REGLA 7: Densidad de contenido gráfico ──────────────────────────────
    # Mide qué proporción del área tiene dibujos vectoriales
    area_pagina = rect.width * rect.height
    area_dibujos = sum(
        (d["rect"].width * d["rect"].height)
        for d in dibujos
        if d.get("rect") and d["rect"].width > 5 and d["rect"].height > 5
    )
    densidad = area_dibujos / area_pagina if area_pagina > 0 else 0
    resultados.append(RuleResult(
        id="densidad_grafica",
        nombre="Densidad gráfica del plano",
        presente=densidad > 0.05,
        observacion=f"Cobertura gráfica: {densidad:.1%}" ,
        confianza="alta" if densidad > 0.1 else "media",
    ))

    # ── REGLA 8: Viñeta en zona de borde ───────────────────────────────────
    # La viñeta suele estar en la esquina inferior derecha o derecha de la hoja
    zona_vineta = fitz.Rect(rect.width * 0.6, rect.height * 0.7, rect.width, rect.height)
    texto_zona = page.get_textbox(zona_vineta)
    tiene_vineta_zona = len(texto_zona.strip()) > 20
    resultados.append(RuleResult(
        id="vineta_ubicacion",
        nombre="Viñeta en zona correcta",
        presente=tiene_vineta_zona,
        observacion="Texto en esquina inferior derecha (posición estándar de viñeta)"
                    if tiene_vineta_zona else "Sin contenido en zona de viñeta (inf. derecha)",
        confianza="media",
    ))

    # ── REGLA 9: Densidad de texto (etiquetas) ──────────────────────────────
    # Un plano bien etiquetado tiene muchos bloques de texto cortos distribuidos
    bloques_texto = [b for b in bloques if b.get("type") == 0]
    n_bloques = len(bloques_texto)
    resultados.append(RuleResult(
        id="densidad_texto",
        nombre="Etiquetas y texto distribuido",
        presente=n_bloques >= 5,
        observacion=f"{n_bloques} bloques de texto detectados en la lámina",
        confianza="alta" if n_bloques >= 10 else "media",
    ))

    # ── REGLA 10: Contenido en zona central ─────────────────────────────────
    # El área central del plano debe tener dibujos (no estar vacía)
    zona_central = fitz.Rect(
        rect.width * 0.1, rect.height * 0.1,
        rect.width * 0.85, rect.height * 0.75
    )
    dibujos_centrales = [
        d for d in dibujos
        if d.get("rect") and zona_central.intersects(d["rect"])
    ]
    resultados.append(RuleResult(
        id="contenido_central",
        nombre="Contenido en zona de dibujo",
        presente=len(dibujos_centrales) >= 5,
        observacion=f"{len(dibujos_centrales)} elementos gráficos en zona central",
        confianza="alta" if len(dibujos_centrales) >= 20 else "media",
    ))

    return resultados


def calcular_puntaje_reglas(resultados: list[RuleResult]) -> tuple[int, int]:
    aprobados = sum(1 for r in resultados if r.presente)
    return aprobados, len(resultados)
