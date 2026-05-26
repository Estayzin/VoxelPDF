"""
Planimetry Reviewer — FastAPI backend
Expone endpoints REST para que planimetria.html pueda analizar PDFs desde el navegador.

Uso directo:
    cd Prototipos/planimetry-reviewer
    python -m uvicorn api:app --reload --port 8000

Uso como .exe (via main.py):
    python main.py  →  build.bat  →  dist/Revisor Planimetria.exe
"""
import asyncio
import base64
import io
import json
import os
import sys

import fitz
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from PIL import Image
from typing import List


# ── Helpers de ruta ───────────────────────────────────────────────────────────
def _exe_dir() -> str:
    """Directorio del .exe en producción, o del script en desarrollo."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _resource(relative: str) -> str:
    """Ruta a un archivo bundleado (sys._MEIPASS) o relativo al script."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


# Asegura que los módulos locales sean encontrados al ejecutar desde otro directorio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# .env: busca primero junto al .exe (para usuarios), luego junto al script (desarrollo)
load_dotenv(os.path.join(_exe_dir(), ".env"), override=True)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)

# Ruta del HTML — puede ser sobreescrita por main.py via variable de entorno
# Fallback para uso directo con uvicorn: sube dos niveles hasta GitHub/ y entra a VoxelBIM/
_HTML_PATH = os.environ.get(
    'PLANIMETRIA_HTML',
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  '..', '..', 'VoxelBIM', 'app', 'planimetria.html'))
)

from analyzer import CHECKS
import analyzer as gemini_analyzer
import groq_analyzer
from rules import analizar_con_reglas, calcular_puntaje_reglas
from slack_notifier import send_bulk_report

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Planimetry Reviewer API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
SLACK_URL  = os.getenv("SLACK_WEBHOOK_URL", "")

_IMG_MAX_W = 900   # px — ancho máximo de preview
_IMG_QUALITY = 78  # JPEG quality para los previews


# ── Helpers ───────────────────────────────────────────────────────────────────
def _img_to_b64(img: Image.Image) -> str:
    w, h = img.size
    if w > _IMG_MAX_W:
        img = img.resize((_IMG_MAX_W, int(h * _IMG_MAX_W / w)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_IMG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode()


def _analizar_pagina(page: fitz.Page, img: Image.Image, mode: str) -> dict:
    if mode == "rules":
        rule_results = analizar_con_reglas(page)
        aprobados, total = calcular_puntaje_reglas(rule_results)
        resultado = {r.id: {"presente": r.presente, "observacion": r.observacion} for r in rule_results}
        resultado["resumen"] = f"{aprobados}/{total} checks por análisis de reglas"
        checks_bool = {r.nombre: (1 if r.presente else 0) for r in rule_results}
        rule_data = [
            {"id": r.id, "nombre": r.nombre, "presente": r.presente,
             "observacion": r.observacion, "confianza": r.confianza}
            for r in rule_results
        ]
        return resultado, aprobados, total, checks_bool, rule_data

    if mode == "groq":
        resultado = groq_analyzer.analyze_page(img, GROQ_KEY)
        aprobados, total = groq_analyzer.calcular_puntaje(resultado)
    elif mode == "gemini":
        resultado = gemini_analyzer.analyze_page(img, GEMINI_KEY)
        aprobados, total = gemini_analyzer.calcular_puntaje(resultado)
    else:
        raise ValueError(f"Modo desconocido: {mode}")

    checks_bool = {
        c["nombre"]: (1 if resultado.get(c["id"], {}).get("presente") else 0)
        for c in CHECKS
    }
    return resultado, aprobados, total, checks_bool, None


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/")
def serve_app():
    """Sirve planimetria.html — usado cuando main.py lanza pywebview."""
    return FileResponse(_HTML_PATH, media_type="text/html")


@app.get("/api/status")
def get_status():
    return {
        "groq":   bool(GROQ_KEY),
        "gemini": bool(GEMINI_KEY),
        "slack":  bool(SLACK_URL),
    }


@app.get("/api/checks")
def get_checks():
    return {"checks": CHECKS}


@app.post("/api/analyze")
async def analyze(
    files: List[UploadFile] = File(...),
    mode: str = Form("groq"),
    dpi: int = Form(150),
):
    if mode == "groq" and not GROQ_KEY:
        return JSONResponse({"error": "GROQ_API_KEY no configurada en .env"}, status_code=400)
    if mode == "gemini" and not GEMINI_KEY:
        return JSONResponse({"error": "GEMINI_API_KEY no configurada en .env"}, status_code=400)

    results = []
    dpi = max(72, min(dpi, 300))

    for upload in files:
        pdf_bytes = await upload.read()
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            return JSONResponse({"error": f"PDF inválido ({upload.filename}): {e}"}, status_code=400)

        total_pages = len(doc)
        for page_num in range(total_pages):
            page = doc[page_num]
            mat  = fitz.Matrix(dpi / 72, dpi / 72)
            pix  = page.get_pixmap(matrix=mat)
            img  = Image.open(io.BytesIO(pix.tobytes("png")))

            try:
                resultado, aprobados, total, checks_bool, rule_data = _analizar_pagina(
                    page, img, mode
                )
                results.append({
                    "pdf_name":    upload.filename,
                    "pagina":      page_num + 1,
                    "total_pages": total_pages,
                    "aprobados":   aprobados,
                    "total":       total,
                    "pct":         int(aprobados / total * 100),
                    "resultado":   resultado,
                    "checks_bool": checks_bool,
                    "img_b64":     _img_to_b64(img),
                    "rule_results": rule_data,
                })
            except Exception as e:
                results.append({
                    "pdf_name":    upload.filename,
                    "pagina":      page_num + 1,
                    "total_pages": total_pages,
                    "error":       str(e),
                    "aprobados":   0,
                    "total":       len(CHECKS),
                    "pct":         0,
                })

    checks_names = [c["nombre"] for c in CHECKS]
    return {"results": results, "checks_names": checks_names, "checks": CHECKS}


def _process_page(pdf_name: str, pdf_bytes: bytes, page_num: int, dpi: int, mode: str) -> dict:
    """Procesa una sola página — función síncrona para correr en thread pool."""
    doc         = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    page        = doc[page_num]
    mat         = fitz.Matrix(dpi / 72, dpi / 72)
    pix         = page.get_pixmap(matrix=mat)
    img         = Image.open(io.BytesIO(pix.tobytes("png")))

    try:
        resultado, aprobados, total, checks_bool, rule_data = _analizar_pagina(page, img, mode)
        return {
            "pdf_name":    pdf_name,
            "pagina":      page_num + 1,
            "total_pages": total_pages,
            "aprobados":   aprobados,
            "total":       total,
            "pct":         int(aprobados / total * 100),
            "resultado":   resultado,
            "checks_bool": checks_bool,
            "img_b64":     _img_to_b64(img),
            "rule_results": rule_data,
        }
    except Exception as e:
        return {
            "pdf_name":    pdf_name,
            "pagina":      page_num + 1,
            "total_pages": total_pages,
            "error":       str(e),
            "aprobados":   0,
            "total":       len(CHECKS),
            "pct":         0,
        }


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/analyze/stream")
async def analyze_stream(
    files: List[UploadFile] = File(...),
    mode: str = Form("groq"),
    dpi: int = Form(150),
):
    """Endpoint SSE — emite progreso página a página en tiempo real."""
    if mode == "groq" and not GROQ_KEY:
        return JSONResponse({"error": "GROQ_API_KEY no configurada en .env"}, status_code=400)
    if mode == "gemini" and not GEMINI_KEY:
        return JSONResponse({"error": "GEMINI_API_KEY no configurada en .env"}, status_code=400)

    dpi = max(72, min(dpi, 300))

    # Leer todos los archivos antes de iniciar el stream
    pdf_list: list[tuple[str, bytes]] = []
    for upload in files:
        content = await upload.read()
        pdf_list.append((upload.filename, content))

    async def generate():
        # Contar páginas totales
        total_pages = sum(
            len(fitz.open(stream=c, filetype="pdf"))
            for _, c in pdf_list
        )
        processed = 0

        for pdf_name, content in pdf_list:
            n_pages = len(fitz.open(stream=content, filetype="pdf"))
            for page_num in range(n_pages):
                # Evento de progreso antes de analizar
                yield _sse({
                    "type":    "progress",
                    "current": processed,
                    "total":   total_pages,
                    "pdf":     pdf_name,
                    "page":    page_num + 1,
                })

                # Análisis en thread pool para no bloquear el event loop
                result = await asyncio.to_thread(
                    _process_page, pdf_name, content, page_num, dpi, mode
                )
                processed += 1

                # Evento con el resultado de la página
                yield _sse({"type": "page", "result": result})

        # Evento final
        yield _sse({
            "type":         "done",
            "checks_names": [c["nombre"] for c in CHECKS],
            "checks":       CHECKS,
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )


@app.get("/api/config")
def get_config():
    """Devuelve si las keys están configuradas y versiones enmascaradas."""
    def mask(s: str) -> str:
        return s[:4] + "…" + s[-4:] if len(s) > 10 else ("●●●●●●" if s else "")
    return {
        "groq":         bool(GROQ_KEY),
        "gemini":       bool(GEMINI_KEY),
        "slack":        bool(SLACK_URL),
        "groq_masked":  mask(GROQ_KEY),
        "slack_masked": mask(SLACK_URL),
    }


@app.post("/api/config")
async def set_config(payload: dict):
    """Actualiza las API keys en memoria (persiste mientras corra el proceso)."""
    global GROQ_KEY, GEMINI_KEY, SLACK_URL
    if "groq_key" in payload:
        GROQ_KEY = payload["groq_key"].strip()
        os.environ["GROQ_API_KEY"] = GROQ_KEY
    if "gemini_key" in payload:
        GEMINI_KEY = payload["gemini_key"].strip()
        os.environ["GEMINI_API_KEY"] = GEMINI_KEY
    if "slack_url" in payload:
        SLACK_URL = payload["slack_url"].strip()
        os.environ["SLACK_WEBHOOK_URL"] = SLACK_URL
    return {"ok": True, "groq": bool(GROQ_KEY), "gemini": bool(GEMINI_KEY), "slack": bool(SLACK_URL)}


@app.post("/api/slack/bulk")
async def slack_bulk(payload: dict):
    if not SLACK_URL:
        return JSONResponse({"error": "SLACK_WEBHOOK_URL no configurada en .env"}, status_code=400)
    try:
        resultados = payload.get("results", [])
        filenames  = list(dict.fromkeys(r["pdf_name"] for r in resultados if "pdf_name" in r))
        send_bulk_report(
            webhook_url=SLACK_URL,
            filename=", ".join(filenames),
            resultados=resultados,
        )
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
