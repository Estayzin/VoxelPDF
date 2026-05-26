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
    no_aplica: bool = False


def analizar_con_reglas(page: fitz.Page, nombre_archivo: str = "") -> list[RuleResult]:
    texto_raw = page.get_text("text")
    texto = texto_raw.upper()
    bloques = page.get_text("dict")["blocks"]
    dibujos = page.get_drawings()
    rect = page.rect  # dimensiones de la página

    resultados = []

    # ── Clasificación de tipo de lámina ─────────────────────────────────────
    # Detecta si la lámina es una planta o un tipo que no requiere norte.
    _kw_no_planta = [
        "CORTE", "SECCIÓN", "SECCION", "ELEVACIÓN", "ELEVACION",
        "ALZADO", "FACHADA", "DETALLE", "AMPLIACIÓN", "AMPLIACION",
        "PERSPECTIVA", "ISOMÉTRICO", "ISOMETRICO", "SECCIÓN TRANSVERSAL",
        "SECCIÓN LONGITUDINAL", "PERFIL", "CUADRO DE SUPERFICIE",
        "CUADRO DE RECINTOS", "TABLA DE", "SCHEDULE", "ESPECIFICACIONES",
    ]
    _kw_planta = [
        "PLANTA", "FLOOR PLAN", "FLOOR", "LAYOUT",
        "NIVEL", "PISO N", "PISO °", "NIVEL °",
    ]
    _match_no_planta = next((k for k in _kw_no_planta if k in texto), None)
    _match_planta    = next((k for k in _kw_planta    if k in texto), None)
    # Si hay indicador explícito de no-planta y ninguno de planta → no aplica norte
    _es_no_planta = bool(_match_no_planta) and not bool(_match_planta)

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
    _patron_lamina_re = r"\b(L|PL|A|E|S|M|C|LÁM|LAM|SHEET|HJ|PLANO)[\s\-_]?\d{1,3}\b"
    patron_lamina        = re.search(_patron_lamina_re, texto_raw, re.IGNORECASE)
    patron_lamina_nombre = re.search(_patron_lamina_re, nombre_archivo, re.IGNORECASE) if nombre_archivo else None

    _lamina_en_plano  = patron_lamina.group().strip()        if patron_lamina        else None
    _lamina_en_nombre = patron_lamina_nombre.group().strip() if patron_lamina_nombre else None

    if _lamina_en_plano:
        if _lamina_en_nombre:
            _coincide = _lamina_en_plano.upper() == _lamina_en_nombre.upper()
            _sufijo   = f" (archivo: {_lamina_en_nombre} {'✓' if _coincide else '≠ no coincide'})"
        else:
            _sufijo = ""
        _obs_lamina  = f"Detectado: {_lamina_en_plano}{_sufijo}"
        _conf_lamina = "alta" if (_lamina_en_nombre and _lamina_en_plano.upper() == _lamina_en_nombre.upper()) else "media"
    else:
        _sufijo      = f" — en nombre de archivo: {_lamina_en_nombre}" if _lamina_en_nombre else ""
        _obs_lamina  = f"Sin número de lámina en el plano{_sufijo}"
        _conf_lamina = "media"

    resultados.append(RuleResult(
        id="numero_lamina",
        nombre="Número de lámina",
        presente=bool(_lamina_en_plano),   # pasa/falla solo por lo que hay en el plano
        observacion=_obs_lamina,
        confianza=_conf_lamina,
    ))

    # ── REGLA 4: Norte u orientación ────────────────────────────────────────
    if _es_no_planta:
        resultados.append(RuleResult(
            id="orientacion_norte",
            nombre="Orientación / Norte",
            presente=True,
            observacion=f"No aplica — lámina tipo {_match_no_planta.title()}",
            confianza="alta",
            no_aplica=True,
        ))
    else:
        keywords_norte = ["NORTE", "NORTH", "↑N", "° N", "°N"]
        tiene_norte_texto = any(k in texto for k in keywords_norte)
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
    # Nombres completos (con y sin tilde, con y sin 'N' de baño)
    _ambientes_exactos = [
        "DORMITORIO", "HABITACIÓN", "HABITACION", "BAÑO", "BANO", "BÑO",
        "COCINA", "SALA", "LIVING", "COMEDOR", "PASILLO", "BODEGA",
        "ESTUDIO", "ESCRITORIO", "GARAGE", "GARAJE", "PATIO", "TERRAZA",
        "LOGIA", "HALL", "RECEPCIÓN", "RECEPCION", "LOBBY", "FOYER",
        "OFICINA", "ESTAR", "SERVICIO", "LAVANDERÍA", "LAVANDERIA",
        "PIEZA", "CUARTO", "QUINCHO", "BALCÓN", "BALCON", "JARDÍN",
        "JARDIN", "VESTÍBULO", "VESTIBULO", "CIRCULACIÓN", "CIRCULACION",
        "SSHH", "BAÑOS", "BANOS", "DUCHA",
        "BEDROOM", "KITCHEN", "BATHROOM", "CORRIDOR", "OFFICE", "DINING",
    ]
    # Abreviaturas comunes en planos: DORM., DORM 1, HAB., BÑO., BOD., etc.
    _patrones_abrev = [
        r"\bDORM[\.\s]",       # DORM. / DORM 1 / DORM.2
        r"\bHAB[\.\s]",        # HAB. / HAB 1
        r"\bB[ÑN]O[\.\s]?",    # BÑO. / BNO / BÑO
        r"\bBOD[\.\s]",        # BOD.
        r"\bEST[\.\s]",        # EST. (estudio/estar)
        r"\bVEST[\.\s]",       # VEST. (vestíbulo)
        r"\bCOMED[\.\s]",      # COMED.
        r"\bGAR[\.\s]",        # GAR. (garage)
        r"\bLAV[\.\s]",        # LAV. (lavandería)
        r"\bPAS[\.\s]",        # PAS. (pasillo)
        r"\bTERR[\.\s]",       # TERR. (terraza)
        r"\bSS\.?HH\b",        # SS.HH / SSHH (servicios higiénicos)
        r"\bWC\b",             # WC
    ]
    if _es_no_planta:
        resultados.append(RuleResult(
            id="nombres_ambientes",
            nombre="Nomenclatura de ambientes",
            presente=True,
            observacion=f"No aplica — lámina tipo {_match_no_planta.title()}",
            confianza="alta",
            no_aplica=True,
        ))
    else:
        ambientes_encontrados = [a for a in _ambientes_exactos if a in texto]
        for pat in _patrones_abrev:
            if re.search(pat, texto):
                ambientes_encontrados.append(re.search(pat, texto).group().strip())

        _codigos_recinto = re.findall(r"\b\d{1,2}\.\d{1,2}\.\d{1,2}\b", texto_raw)
        if len(_codigos_recinto) >= 2:
            ambientes_encontrados.append(f"códigos {_codigos_recinto[0]}…")

        resultados.append(RuleResult(
            id="nombres_ambientes",
            nombre="Nomenclatura de ambientes",
            presente=len(ambientes_encontrados) >= 1,
            observacion=f"Ambientes: {', '.join(dict.fromkeys(ambientes_encontrados[:6]))}" if ambientes_encontrados
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
    # Cuenta bloques de texto FUERA de la franja de viñeta (der./inf.).
    # La viñeta sola puede sumar 5+ bloques en una lámina vacía, así que
    # solo cuenta texto en la zona de dibujo (~82% ancho, ~88% alto).
    _zona_texto = fitz.Rect(
        rect.width * 0.02, rect.height * 0.02,
        rect.width * 0.82, rect.height * 0.88,
    )
    bloques_texto = [
        b for b in bloques
        if b.get("type") == 0
        and fitz.Rect(b["bbox"]).intersects(_zona_texto)
        and fitz.Rect(b["bbox"]).get_area() > 0
    ]
    n_bloques = len(bloques_texto)
    resultados.append(RuleResult(
        id="densidad_texto",
        nombre="Etiquetas y texto distribuido",
        presente=n_bloques >= 4,
        observacion=f"{n_bloques} bloques de texto en zona de dibujo (excl. viñeta)",
        confianza="alta" if n_bloques >= 8 else "media",
    ))

    # ── REGLA 10: Contenido en zona de dibujo ───────────────────────────────
    # Divide el área útil (excluyendo franja de viñeta derecha/inferior) en una
    # cuadrícula 3×3 y cuenta cuántas celdas tienen elementos gráficos.
    # Esto detecta contenido aunque esté sesgado a la izquierda, derecha o arriba.
    _zona_dibujo = fitz.Rect(
        rect.width * 0.02,  rect.height * 0.02,
        rect.width * 0.82,  rect.height * 0.88,  # excluye franja de viñeta
    )
    _gcols, _grows = 3, 3
    _cw = _zona_dibujo.width  / _gcols
    _ch = _zona_dibujo.height / _grows
    _celdas_con_contenido = 0
    for _row in range(_grows):
        for _col in range(_gcols):
            _celda = fitz.Rect(
                _zona_dibujo.x0 + _col * _cw,
                _zona_dibujo.y0 + _row * _ch,
                _zona_dibujo.x0 + (_col + 1) * _cw,
                _zona_dibujo.y0 + (_row + 1) * _ch,
            )
            if any(d.get("rect") and _celda.intersects(d["rect"]) for d in dibujos):
                _celdas_con_contenido += 1
    resultados.append(RuleResult(
        id="contenido_central",
        nombre="Contenido en zona de dibujo",
        presente=_celdas_con_contenido >= 2,
        observacion=f"{_celdas_con_contenido}/9 celdas de la cuadrícula con contenido gráfico",
        confianza="alta" if _celdas_con_contenido >= 5 else "media",
    ))

    return resultados


def analizar_contraste(page: fitz.Page, img, min_ratio: float = 3.0) -> RuleResult:
    """Mide el contraste de cada span de texto contra su fondo local en la imagen rasterizada."""
    import numpy as _np

    if img is None:
        return RuleResult(id="contraste_lectura", nombre="Contraste y legibilidad",
                          presente=True, observacion="Imagen no disponible", confianza="baja")

    rect = page.rect
    iw, ih = img.size
    if iw == 0 or ih == 0 or rect.width == 0 or rect.height == 0:
        return RuleResult(id="contraste_lectura", nombre="Contraste y legibilidad",
                          presente=True, observacion="Imagen vacía", confianza="baja")

    sx = iw / rect.width
    sy = ih / rect.height
    gray = _np.array(img.convert("L"), dtype=_np.float32)

    spans_bajo  = []
    spans_total = 0

    for block in page.get_text("rawdict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt  = span.get("text", "").strip()
                bbox = span.get("bbox")
                if not txt or not bbox or len(txt) < 2:
                    continue
                x0 = max(0,      int(bbox[0] * sx))
                y0 = max(0,      int(bbox[1] * sy))
                x1 = min(iw - 1, int(bbox[2] * sx) + 1)
                y1 = min(ih - 1, int(bbox[3] * sy) + 1)
                if x1 <= x0 or y1 <= y0:
                    continue
                region = gray[y0:y1, x0:x1].flatten()
                if region.size < 4:
                    continue
                spans_total += 1
                # p5 = trazo (oscuro), p95 = fondo (claro)
                delta = float(_np.percentile(region, 95) - _np.percentile(region, 5))
                ratio = 1.0 + (delta / 255.0) * 20.0  # 0→1:1, 255→21:1
                if ratio < min_ratio:
                    spans_bajo.append((txt[:20], round(ratio, 1)))

    if spans_total == 0:
        return RuleResult(id="contraste_lectura", nombre="Contraste y legibilidad",
                          presente=True, observacion="Sin texto analizable en la lámina",
                          confianza="baja")

    pct = len(spans_bajo) / spans_total
    presente = pct < 0.15   # falla si >15% de spans están bajo el umbral

    if spans_bajo:
        ej  = "; ".join(f'"{t}"({r:.0f}:1)' for t, r in spans_bajo[:3])
        obs = f"{len(spans_bajo)}/{spans_total} textos bajo umbral {min_ratio:.1f}:1 — {ej}"
    else:
        obs = f"Legibilidad OK — {spans_total} textos sobre umbral {min_ratio:.1f}:1"

    return RuleResult(id="contraste_lectura", nombre="Contraste y legibilidad",
                      presente=presente, observacion=obs,
                      confianza="alta" if spans_total >= 5 else "media")


def calcular_puntaje_reglas(resultados: list[RuleResult]) -> tuple[int, int]:
    aplicables = [r for r in resultados if not r.no_aplica]
    aprobados  = sum(1 for r in aplicables if r.presente)
    return aprobados, len(aplicables)
