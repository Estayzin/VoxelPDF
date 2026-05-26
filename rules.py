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
    # Planos MEP: tienen vista de planta pero no requieren nomenclatura de ambientes
    _kw_mep = [
        "CLIMATIZACIÓN", "CLIMATIZACION", "DUCTO", "HVAC",
        "MECÁNICA", "MECANICA", "VENTILACIÓN", "VENTILACION",
        "ELÉCTRICA", "ELECTRICA", "ELÉCTRICO", "ELECTRICO",
        "ILUMINACIÓN", "ILUMINACION", "FUERZA", "TABLERO ELÉCTRICO",
        "SANITARIA", "SANITARIO", "AGUA POTABLE", "ALCANTARILLADO",
        "INCENDIO", "DETECCIÓN", "DETECCION", "SPRINKLER",
        "TELECOMUNICACIONES", "GAS NATURAL", "RED DE GAS",
        "INSTALACIÓN ELÉCTRICA", "INSTALACION ELECTRICA",
        "PLOMERÍA", "PLOMERIA",
    ]
    _match_no_planta = next((k for k in _kw_no_planta if k in texto), None)
    _match_planta    = next((k for k in _kw_planta    if k in texto), None)
    _match_mep       = next((k for k in _kw_mep       if k in texto), None)

    # No-planta: corte/elevación/detalle sin keyword de planta ni MEP
    _es_no_planta = bool(_match_no_planta) and not bool(_match_planta) and not bool(_match_mep)
    # MEP: instalaciones con vista de planta — norte aplica, ambientes no aplica
    _es_mep = bool(_match_mep)

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
        # Plano de ubicación en viñeta también es válido como referencia de orientación
        kw_ubicacion = ["PLANO DE UBICACIÓN", "PLANO DE UBICACION",
                        "UBICACIÓN", "UBICACION", "LOCATION MAP",
                        "LOCALIZACIÓN", "LOCALIZACION", "PLANO UBICACIÓN"]
        tiene_ubicacion = any(k in texto for k in kw_ubicacion)
        presente_norte = tiene_norte_texto or n_aislada or tiene_ubicacion
        if tiene_norte_texto:
            obs_norte = "Indicador de norte encontrado"
        elif tiene_ubicacion:
            obs_norte = "Plano de ubicación en viñeta (referencia de orientación válida)"
        elif n_aislada:
            obs_norte = "Letra N aislada (posible norte)"
        else:
            obs_norte = "Sin indicador de orientación ni plano de ubicación"
        resultados.append(RuleResult(
            id="orientacion_norte",
            nombre="Orientación / Norte",
            presente=presente_norte,
            observacion=obs_norte,
            confianza="alta" if (tiene_norte_texto or tiene_ubicacion) else "baja",
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


def analizar_contraste(page: fitz.Page, min_ratio: float = 3.0) -> RuleResult:
    """
    Verifica contraste de líneas/formas de color contra fondo blanco usando
    valores de color reales del PDF (fórmula WCAG 2.1). No requiere imagen.
    """
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def _ratio_vs_blanco(r: float, g: float, b: float) -> float:
        L = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
        return 1.05 / (L + 0.05)   # blanco L=1 → (1.05)/(L+0.05)

    bajo    = []
    total   = 0
    vistos  = {}  # hex_color → min_ratio para deduplicar en el reporte

    # ── Líneas y formas vectoriales ──
    for d in page.get_drawings():
        for key in ("color", "fill"):
            c = d.get(key)
            if not c or len(c) < 3:
                continue
            r, g, b = float(c[0]), float(c[1]), float(c[2])
            # Ignorar negro/casi negro y blanco/casi blanco (siempre OK)
            suma = r + g + b
            if suma < 0.15 or suma > 2.85:
                continue
            total += 1
            ratio = _ratio_vs_blanco(r, g, b)
            if ratio < min_ratio:
                hx = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
                bajo.append((hx, round(ratio, 1)))
                if hx not in vistos or vistos[hx] > ratio:
                    vistos[hx] = round(ratio, 1)

    if total == 0:
        return RuleResult(id="contraste_lectura", nombre="Contraste y legibilidad",
                          presente=True,
                          observacion="Sin elementos de color — todo en negro (contraste máximo)",
                          confianza="media")

    pct     = len(bajo) / total
    presente = pct < 0.20   # falla si >20 % de elementos de color están bajo umbral

    if vistos:
        ej  = "  ".join(f"{h} ({r:.0f}:1)" for h, r in list(vistos.items())[:4])
        obs = f"{len(bajo)}/{total} elementos bajo {min_ratio:.1f}:1 — colores: {ej}"
    else:
        obs = f"Contraste OK — {total} elementos de color sobre {min_ratio:.1f}:1"

    return RuleResult(id="contraste_lectura", nombre="Contraste y legibilidad",
                      presente=presente, observacion=obs,
                      confianza="alta" if total >= 3 else "media")


def calcular_puntaje_reglas(resultados: list[RuleResult]) -> tuple[int, int]:
    aplicables = [r for r in resultados if not r.no_aplica]
    aprobados  = sum(1 for r in aplicables if r.presente)
    return aprobados, len(aplicables)
