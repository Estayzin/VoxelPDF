import streamlit as st
import fitz
from PIL import Image
import io
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from dotenv import load_dotenv

from analyzer import CHECKS
import analyzer as gemini_analyzer
import groq_analyzer
from rules import analizar_con_reglas, calcular_puntaje_reglas, RuleResult
from slack_notifier import send_bulk_report, send_report

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)


def analizar_pagina(page, img, modo, groq_key, gemini_key, modelo_gemini):
    if modo == "Reglas (sin IA)":
        rule_results = analizar_con_reglas(page)
        aprobados, total = calcular_puntaje_reglas(rule_results)
        checks_bool = {r.nombre: 1 if r.presente else 0 for r in rule_results}
        resultado = {r.id: {"presente": r.presente, "observacion": r.observacion} for r in rule_results}
        resultado["resumen"] = f"{aprobados}/{total} checks por análisis de reglas"
        return resultado, aprobados, total, checks_bool, rule_results
    else:
        if "Groq" in modo:
            resultado = groq_analyzer.analyze_page(img, groq_key)
        else:
            resultado = gemini_analyzer.analyze_page(img, gemini_key, modelo_gemini)
        aprobados, total = gemini_analyzer.calcular_puntaje(resultado)
        checks_bool = {c["nombre"]: 1 if resultado.get(c["id"], {}).get("presente") else 0 for c in CHECKS}
        return resultado, aprobados, total, checks_bool, None


def generar_grafico_resumen(resultados, checks_names, titulo):
    labels = [f"Pág {r['pagina']}" for r in resultados]
    puntajes = [int(r["aprobados"] / r["total"] * 100) for r in resultados]

    fig, axes = plt.subplots(1, 2, figsize=(14, max(4, len(checks_names) * 0.5 + 2)))
    fig.suptitle(titulo, fontsize=13, fontweight="bold")

    colors = ["#2eb886" if p >= 80 else "#e8a838" if p >= 50 else "#e01e5a" for p in puntajes]
    axes[0].bar(labels, puntajes, color=colors)
    axes[0].axhline(y=80, color="#2eb886", linestyle="--", alpha=0.7, label="Aprobado (80%)")
    axes[0].axhline(y=50, color="#e8a838", linestyle="--", alpha=0.7, label="Revisar (50%)")
    axes[0].set_ylim(0, 115)
    axes[0].set_ylabel("Puntaje (%)")
    axes[0].set_title("Puntaje por página")
    axes[0].legend(fontsize=8)
    axes[0].tick_params(axis="x", rotation=45)
    for i, val in enumerate(puntajes):
        axes[0].text(i, val + 2, f"{val}%", ha="center", fontsize=8)

    checks_data = {name: [r["checks_bool"].get(name, 0) for r in resultados] for name in checks_names}
    matrix = np.array([checks_data[n] for n in checks_names])
    axes[1].imshow(matrix, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)
    axes[1].set_xticks(range(len(labels)))
    axes[1].set_xticklabels(labels, rotation=45, fontsize=8)
    axes[1].set_yticks(range(len(checks_names)))
    axes[1].set_yticklabels(checks_names, fontsize=8)
    axes[1].set_title("Detalle de checks")
    axes[1].legend(
        handles=[
            mpatches.Patch(facecolor="#91cf60", label="Presente"),
            mpatches.Patch(facecolor="#d73027", label="Ausente"),
        ],
        loc="upper right", fontsize=8,
    )
    plt.tight_layout()
    return fig


# ── Config ───────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Revisor de Planimetria", page_icon="📐", layout="wide")

# Inicializar session_state
if "resultados" not in st.session_state:
    st.session_state.resultados = []
if "analizado" not in st.session_state:
    st.session_state.analizado = False
if "nombres_pdf" not in st.session_state:
    st.session_state.nombres_pdf = []

groq_key = os.getenv("GROQ_API_KEY", "")
slack_url = os.getenv("SLACK_WEBHOOK_URL", "")
gemini_key = ""
modelo_gemini = "gemini-2.0-flash-lite"

with st.sidebar:
    st.title("⚙️ Configuración")
    modo = st.radio(
        "Motor de análisis",
        ["Reglas (sin IA)", "Groq (IA gratuita)"],
        index=1,
    )
    dpi = st.slider("Resolución (DPI)", 72, 300, 150, 24)

    st.markdown("---")
    # Estado de conexiones
    st.markdown("**Estado:**")
    st.markdown("🟢 Groq" if groq_key else "🔴 Groq (sin key)")
    st.markdown("🟢 Slack" if slack_url else "🔴 Slack (sin webhook)")

    st.markdown("---")
    if st.button("🗑️ Limpiar resultados"):
        st.session_state.resultados = []
        st.session_state.analizado = False
        st.session_state.nombres_pdf = []
        st.rerun()

# ── Main ─────────────────────────────────────────────────────────────────────
st.title("📐 Revisor de Planimetría")
st.caption(f"Motor activo: **{modo}**")

uploads = st.file_uploader(
    "Sube uno o varios PDFs de planimetría",
    type=["pdf"],
    accept_multiple_files=True,
)

if not uploads:
    st.markdown("""
    **Cómo usar:**
    1. Selecciona el motor en la barra lateral
    2. Sube uno o **varios PDFs** a la vez
    3. Haz clic en **Analizar todo**
    4. Envía el reporte consolidado a Slack
    """)
    if st.session_state.analizado:
        st.info("Resultados anteriores disponibles abajo ↓")
    st.stop()

if st.button("🔍 Analizar todo", type="primary"):
    st.session_state.resultados = []
    st.session_state.analizado = False
    st.session_state.nombres_pdf = [u.name for u in uploads]

    checks_names = (
        [r.nombre for r in analizar_con_reglas(fitz.open(stream=uploads[0].read(), filetype="pdf")[0])]
        if modo == "Reglas (sin IA)"
        else [c["nombre"] for c in CHECKS]
    )
    for u in uploads:
        u.seek(0)

    st.session_state.checks_names = checks_names

    for upload in uploads:
        pdf_bytes = upload.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)

        st.markdown(f"### 📄 {upload.name}")
        progress = st.progress(0, text="Iniciando...")

        for i, num_pag in enumerate(range(1, total_pages + 1)):
            progress.progress(i / total_pages, text=f"Página {num_pag}/{total_pages}...")

            page = doc[num_pag - 1]
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))

            try:
                resultado, aprobados, total, checks_bool, rule_results = analizar_pagina(
                    page, img, modo, groq_key, gemini_key, modelo_gemini
                )

                # Guardar imagen como bytes para no perderla en rerun
                img_buf = io.BytesIO()
                img.save(img_buf, format="PNG")

                st.session_state.resultados.append({
                    "pagina": num_pag,
                    "pdf_name": upload.name,
                    "resultado": resultado,
                    "aprobados": aprobados,
                    "total": total,
                    "checks_bool": checks_bool,
                    "img_bytes": img_buf.getvalue(),
                    "rule_results": [
                        {"id": r.id, "nombre": r.nombre, "presente": r.presente,
                         "observacion": r.observacion, "confianza": r.confianza}
                        for r in rule_results
                    ] if rule_results else None,
                })
            except Exception as e:
                st.error(f"Error página {num_pag}: {e}")

            progress.progress((i + 1) / total_pages, text=f"Página {num_pag}/{total_pages} lista")

        progress.empty()

    st.session_state.analizado = True
    st.rerun()

# ── Mostrar resultados guardados ──────────────────────────────────────────────
if st.session_state.analizado and st.session_state.resultados:
    resultados = st.session_state.resultados
    checks_names = st.session_state.get("checks_names", [c["nombre"] for c in CHECKS])

    # Agrupar por PDF
    pdfs = {}
    for r in resultados:
        pdfs.setdefault(r["pdf_name"], []).append(r)

    for pdf_name, res_pdf in pdfs.items():
        with st.expander(f"📄 {pdf_name} — {len(res_pdf)} página(s)", expanded=True):
            for r in res_pdf:
                col_img, col_res = st.columns([1, 1])
                img = Image.open(io.BytesIO(r["img_bytes"]))

                with col_img:
                    st.image(img, caption=f"Página {r['pagina']}", use_container_width=True)

                with col_res:
                    pct = int(r["aprobados"] / r["total"] * 100)
                    if pct >= 80:
                        st.success(f"✅ APROBADO — {r['aprobados']}/{r['total']} ({pct}%)")
                    elif pct >= 50:
                        st.warning(f"⚠️ REVISAR — {r['aprobados']}/{r['total']} ({pct}%)")
                    else:
                        st.error(f"❌ RECHAZADO — {r['aprobados']}/{r['total']} ({pct}%)")

                    if r["rule_results"]:
                        for rr in r["rule_results"]:
                            icon = "✅" if rr["presente"] else "❌"
                            conf = {"alta": "🔵", "media": "🟡", "baja": "🟠"}.get(rr["confianza"], "")
                            st.markdown(f"{icon}{conf} **{rr['nombre']}**: {rr['observacion']}")
                    else:
                        for c in CHECKS:
                            rv = r["resultado"].get(c["id"], {})
                            icon = "✅" if rv.get("presente") else "❌"
                            st.markdown(f"{icon} **{c['nombre']}**: {rv.get('observacion', '')}")
                        resumen = r["resultado"].get("resumen", "")
                        if resumen:
                            st.caption(f"💬 {resumen}")

            st.markdown("---")
            fig = generar_grafico_resumen(res_pdf, checks_names, f"Resumen — {pdf_name}")
            st.pyplot(fig)
            plt.close(fig)

    # ── Métricas globales ─────────────────────────────────────────────────────
    st.markdown("---\n## 📊 Resumen global")
    total_pags = len(resultados)
    aprobadas = sum(1 for r in resultados if int(r["aprobados"] / r["total"] * 100) >= 80)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("PDFs analizados", len(pdfs))
    col2.metric("Páginas totales", total_pags)
    col3.metric("Aprobadas ✅", aprobadas)
    col4.metric("Con observaciones", total_pags - aprobadas)

    if total_pags > 1:
        fig = generar_grafico_resumen(resultados, checks_names, f"Global — {len(pdfs)} PDF(s)")
        st.pyplot(fig)
        plt.close(fig)

    # ── Slack ─────────────────────────────────────────────────────────────────
    if slack_url:
        st.markdown("---")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("📨 Enviar resumen masivo a Slack", type="primary"):
                try:
                    nombres = list(pdfs.keys())
                    send_bulk_report(
                        webhook_url=slack_url,
                        filename=", ".join(nombres),
                        resultados=resultados,
                    )
                    st.success(f"✅ Reporte de {total_pags} página(s) en {len(pdfs)} PDF(s) enviado.")
                except Exception as e:
                    st.error(f"Error: {e}")
        with col_s2:
            if st.button("📄 Enviar página por página"):
                prog = st.progress(0)
                for i, r in enumerate(resultados):
                    try:
                        img = Image.open(io.BytesIO(r["img_bytes"]))
                        send_report(
                            webhook_url=slack_url,
                            filename=r["pdf_name"],
                            pagina=r["pagina"],
                            resultado=r["resultado"],
                            aprobados=r["aprobados"],
                            total=r["total"],
                            thumbnail=img,
                        )
                    except Exception as e:
                        st.warning(f"Error pág {r['pagina']}: {e}")
                    prog.progress((i + 1) / len(resultados))
                st.success(f"✅ {len(resultados)} mensajes enviados a Slack.")
    else:
        st.info("Agrega un Slack Webhook en la barra lateral para enviar reportes.")
