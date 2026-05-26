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


def get_secret(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, "")


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
st.set_page_config(page_title="Revisor de Planimetría", page_icon="📐", layout="wide")

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;600;700;800&display=swap');
/* ── Paleta VoxelBIM ── */
:root {
  --navy:   #060d18;
  --blue:   #0a1628;
  --accent: #00d4ff;
  --green:  #00c853;
  --bg:     #0a0f1e;
  --card:   #0d1526;
  --text:   #c8d8f0;
  --muted:  #4a6080;
  --border: #1a2a40;
  --warn:   #ff6b35;
  --red:    #ff3d57;
  --mono:   'JetBrains Mono', monospace;
  --sans:   'Syne', sans-serif;
}

/* ── Ocultar chrome nativo de Streamlit ── */
[data-testid="stHeader"]    { display: none !important; }
[data-testid="stMainMenu"]  { display: none !important; }
[data-testid="stDecoration"]{ display: none !important; }
footer                      { display: none !important; }
#MainMenu                   { display: none !important; }

/* ── Base ── */
html, body, .stApp {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: var(--sans) !important;
}

/* ── Hero header ── */
@keyframes scan-line {
  0%   { top: 0%;   opacity: .7; }
  80%  { top: 100%; opacity: .2; }
  100% { top: 100%; opacity: 0;  }
}
@keyframes corner-blink { 0%,100%{opacity:.6} 50%{opacity:.15} }

.vbim-hero {
  position: relative;
  overflow: hidden;
  background: var(--navy);
  min-height: 220px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  margin: -1rem -1rem 2rem -1rem;
  border-bottom: 1px solid var(--border);
}
/* blueprint minor grid */
.vbim-hero-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,212,255,.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,212,255,.055) 1px, transparent 1px),
    linear-gradient(rgba(0,212,255,.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,212,255,.018) 1px, transparent 1px);
  background-size: 48px 48px, 48px 48px, 8px 8px, 8px 8px;
  pointer-events: none;
}
/* animated scan line */
.vbim-scan {
  position: absolute;
  left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: scan-line 3.6s ease-in-out infinite;
  pointer-events: none;
  z-index: 2;
}
/* corner registration marks */
.vbim-corner {
  position: absolute;
  width: 18px; height: 18px;
  animation: corner-blink 3.6s ease-in-out infinite;
  pointer-events: none;
  z-index: 2;
}
.vbim-corner::before,
.vbim-corner::after {
  content: '';
  position: absolute;
  background: var(--accent);
}
.vbim-corner::before { width: 100%; height: 1.5px; top: 0; left: 0; }
.vbim-corner::after  { width: 1.5px; height: 100%; top: 0; left: 0; }
.vbim-corner--tl { top: 14px; left: 14px; }
.vbim-corner--tr { top: 14px; right: 14px; transform: scaleX(-1); }
.vbim-corner--bl { bottom: 36px; left: 14px; transform: scaleY(-1); }
.vbim-corner--br { bottom: 36px; right: 14px; transform: scale(-1); }
/* decorative floor plan SVG (right side) */
.vbim-hero-floorplan {
  position: absolute;
  right: -20px; top: 50%; transform: translateY(-50%);
  opacity: .11;
  pointer-events: none;
}
/* content row */
.vbim-hero-content {
  position: relative;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 28px 32px 16px;
}
.vbim-hero-title {
  font-family: var(--mono);
  font-size: clamp(15px, 2.2vw, 24px);
  font-weight: 700;
  color: #e8f4ff;
  letter-spacing: .12em;
  text-transform: uppercase;
  line-height: 1.15;
}
.vbim-hero-title span { color: var(--accent); }
.vbim-hero-sub {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  margin-top: 6px;
  letter-spacing: .06em;
}
.vbim-hero-tags {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.vbim-tag {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: .12em;
  text-transform: uppercase;
  padding: 3px 8px;
  border: 1px solid rgba(0,212,255,.25);
  border-radius: 3px;
  color: rgba(0,212,255,.6);
}
/* bottom status bar */
.vbim-hero-bar {
  position: relative;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 32px;
  border-top: 1px solid var(--border);
  background: rgba(0,0,0,.18);
  font-family: var(--mono);
  font-size: 9px;
  color: var(--muted);
  letter-spacing: .1em;
}
.vbim-hero-bar-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 6px var(--green);
  flex-shrink: 0;
}
.vbim-hero-bar-live { color: var(--green); font-weight: 700; }
.vbim-hero-bar-sep  { color: var(--border); }
/* ── BIT animations ── */
@keyframes bit-pulse  { 0%,100%{opacity:.95} 50%{opacity:.15} }
@keyframes bit-edge-a { 0%,100%{opacity:1;stroke-width:2.4} 45%{opacity:.1;stroke-width:.4} 65%{opacity:.9;stroke-width:2.0} }
@keyframes bit-edge-b { 0%,100%{opacity:1;stroke-width:1.6} 45%{opacity:.1;stroke-width:.4} 65%{opacity:.8;stroke-width:1.4} }
@keyframes bit-glow   { 0%,100%{opacity:.22} 50%{opacity:.55} }
@keyframes bit-vtx    { 0%,100%{opacity:.5}  50%{opacity:.08} }
@keyframes bit-vtx2   { 0%,100%{opacity:.65} 50%{opacity:.15} }
.bit-wrap    { transform-origin:45px 52px; }
.bit-top     { animation:bit-pulse  2s ease-in-out infinite; }
.bit-edge1   { animation:bit-edge-a 2s ease-in-out infinite; }
.bit-edge2   { animation:bit-edge-b 2s ease-in-out infinite .15s; }
.bit-face    { animation:bit-glow   2s ease-in-out infinite; }
.bit-vtx-mid { animation:bit-vtx   2s ease-in-out infinite; }
.bit-vtx-bot { animation:bit-vtx2  2s ease-in-out infinite .3s; }

/* ── Sidebar section header VoxelBIM ── */
.vbim-sb-title {
  font-family: var(--mono) !important;
  font-size: 9px !important;
  font-weight: 700 !important;
  color: var(--muted) !important;
  text-transform: uppercase;
  letter-spacing: .2em;
  padding: 12px 0 8px 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 10px;
}
.vbim-status {
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  padding: 4px 0;
}
.vbim-dot-ok  { width:7px; height:7px; border-radius:50%; background:var(--green); flex-shrink:0; }
.vbim-dot-err { width:7px; height:7px; border-radius:50%; background:var(--red);   flex-shrink:0; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
  background: var(--blue) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
  font-family: var(--mono) !important;
  font-size: 11px !important;
  text-transform: uppercase;
  letter-spacing: .15em;
  color: var(--muted) !important;
}
[data-testid="stSidebar"] .stMarkdown p {
  font-family: var(--mono) !important;
  font-size: 11px !important;
}
[data-testid="stSidebarNav"] { display: none; }

/* ── Encabezados ── */
h1 {
  font-family: var(--sans) !important;
  font-weight: 800 !important;
  font-size: 22px !important;
  color: var(--text) !important;
  letter-spacing: .02em;
}
h2, h3 {
  font-family: var(--mono) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  text-transform: uppercase;
  letter-spacing: .2em;
  color: var(--muted) !important;
}

/* ── Caption ── */
[data-testid="stCaptionContainer"] p {
  font-family: var(--mono) !important;
  font-size: 10px !important;
  color: var(--muted) !important;
  letter-spacing: .05em;
}

/* ── Botón primario ── */
.stButton > button[kind="primary"] {
  background: var(--accent) !important;
  color: #000 !important;
  border: none !important;
  border-radius: 6px !important;
  font-family: var(--mono) !important;
  font-size: 11px !important;
  font-weight: 700 !important;
  text-transform: uppercase;
  letter-spacing: .1em;
  padding: 10px 20px !important;
  transition: box-shadow .15s, transform .15s !important;
}
.stButton > button[kind="primary"]:hover {
  background: #00bcd4 !important;
  box-shadow: 0 0 20px rgba(0,212,255,.35) !important;
  transform: translateY(-1px);
}

/* ── Botón secundario ── */
.stButton > button[kind="secondary"],
.stButton > button:not([kind]) {
  background: transparent !important;
  color: var(--muted) !important;
  border: 1px solid var(--border) !important;
  border-radius: 6px !important;
  font-family: var(--mono) !important;
  font-size: 10px !important;
  font-weight: 600 !important;
  text-transform: uppercase;
  letter-spacing: .1em;
  transition: border-color .15s, color .15s !important;
}
.stButton > button[kind="secondary"]:hover,
.stButton > button:not([kind]):hover {
  border-color: var(--accent) !important;
  color: var(--accent) !important;
}

/* ── Métricas ── */
[data-testid="stMetric"] {
  background: var(--card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 8px !important;
  padding: 16px !important;
}
[data-testid="stMetricLabel"] {
  font-family: var(--mono) !important;
  font-size: 9px !important;
  text-transform: uppercase;
  letter-spacing: .2em;
  color: var(--muted) !important;
}
[data-testid="stMetricValue"] {
  font-family: var(--mono) !important;
  font-size: 26px !important;
  font-weight: 600 !important;
  color: var(--accent) !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
  background: var(--card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 8px !important;
  overflow: hidden;
}
[data-testid="stExpander"] summary {
  font-family: var(--mono) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  color: var(--text) !important;
  letter-spacing: .04em;
  padding: 12px 16px !important;
  background: var(--blue) !important;
}
[data-testid="stExpander"] summary:hover {
  color: var(--accent) !important;
}

/* ── Progress bar ── */
[data-testid="stProgressBar"] > div > div {
  background: linear-gradient(90deg, var(--accent), #00bcd4) !important;
}
[data-testid="stProgressBar"] > div {
  background: rgba(255,255,255,.06) !important;
  border-radius: 4px !important;
  height: 3px !important;
}

/* ── File uploader ── */
[data-testid="stFileUploader"] {
  background: var(--card) !important;
  border: 1px dashed var(--border) !important;
  border-radius: 8px !important;
  padding: 12px !important;
}
[data-testid="stFileUploader"]:hover {
  border-color: var(--accent) !important;
}
[data-testid="stFileUploader"] * {
  font-family: var(--mono) !important;
  font-size: 11px !important;
  color: var(--muted) !important;
}

/* ── Alerts ── */
[data-testid="stAlert"][data-baseweb="notification"] {
  border-radius: 6px !important;
  font-family: var(--mono) !important;
  font-size: 11px !important;
}
.stSuccess { background: rgba(0,200,83,.1) !important; border-left: 3px solid var(--green) !important; color: var(--green) !important; }
.stWarning { background: rgba(255,107,53,.1) !important; border-left: 3px solid var(--warn) !important; color: var(--warn) !important; }
.stError   { background: rgba(255,61,87,.1) !important;  border-left: 3px solid var(--red) !important;  color: var(--red) !important; }
.stInfo    { background: rgba(0,212,255,.08) !important; border-left: 3px solid var(--accent) !important; color: var(--accent) !important; }

/* ── Radio / Slider / Selectbox ── */
[data-testid="stRadio"] label,
[data-testid="stSlider"] label,
[data-testid="stSelectbox"] label {
  font-family: var(--mono) !important;
  font-size: 10px !important;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: var(--muted) !important;
}
[data-testid="stRadio"] p,
[data-testid="stSelectbox"] div {
  font-family: var(--mono) !important;
  font-size: 11px !important;
  color: var(--text) !important;
}

/* ── Divider ── */
hr { border-color: var(--border) !important; }

/* ── Imagen ── */
[data-testid="stImage"] img {
  border-radius: 6px !important;
  border: 1px solid var(--border) !important;
}

/* ── Markdown general ── */
.stMarkdown p, .stMarkdown li {
  font-family: var(--mono) !important;
  font-size: 11px !important;
  color: var(--text) !important;
  line-height: 1.9;
}
.stMarkdown strong { color: var(--accent) !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--navy); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# Inicializar session_state
if "resultados" not in st.session_state:
    st.session_state.resultados = []
if "analizado" not in st.session_state:
    st.session_state.analizado = False
if "nombres_pdf" not in st.session_state:
    st.session_state.nombres_pdf = []

groq_key = get_secret("GROQ_API_KEY")
slack_url = get_secret("SLACK_WEBHOOK_URL")
gemini_key = ""
modelo_gemini = "gemini-2.0-flash-lite"

with st.sidebar:
    st.markdown('<div class="vbim-sb-title">Configuración</div>', unsafe_allow_html=True)
    modo = st.radio(
        "Motor de análisis",
        ["Reglas (sin IA)", "Groq (IA gratuita)"],
        index=1,
        label_visibility="collapsed",
    )
    dpi = st.slider("Resolución (DPI)", 72, 300, 150, 24)

    st.markdown('<div class="vbim-sb-title" style="margin-top:16px">Conexiones</div>', unsafe_allow_html=True)
    dot_groq  = "vbim-dot-ok" if groq_key  else "vbim-dot-err"
    dot_slack = "vbim-dot-ok" if slack_url else "vbim-dot-err"
    st.markdown(f"""
        <div class="vbim-status"><span class="{dot_groq}"></span> Groq</div>
        <div class="vbim-status"><span class="{dot_slack}"></span> Slack</div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="vbim-sb-title" style="margin-top:16px">Acciones</div>', unsafe_allow_html=True)
    if st.button("Limpiar resultados", use_container_width=True):
        st.session_state.resultados = []
        st.session_state.analizado = False
        st.session_state.nombres_pdf = []
        st.rerun()

# ── Main ─────────────────────────────────────────────────────────────────────
_BIT_SVG = """
<svg width="72" height="72" viewBox="0 0 90 105" fill="none" xmlns="http://www.w3.org/2000/svg">
  <g class="bit-wrap">
    <polygon class="bit-face" points="45,4 75,28 15,28" fill="rgba(0,212,255,0.22)" stroke="#00d4ff" stroke-width="1.4" stroke-linejoin="round"/>
    <polygon points="75,28 45,4 82,52" fill="rgba(0,212,255,0.10)" stroke="#00d4ff" stroke-width="0.9" stroke-linejoin="round"/>
    <polygon points="15,28 45,4 8,52" fill="rgba(0,212,255,0.18)" stroke="#00d4ff" stroke-width="0.9" stroke-linejoin="round"/>
    <polygon points="15,28 75,28 82,52 45,68 8,52" fill="rgba(0,212,255,0.07)" stroke="#00d4ff" stroke-width="1.0" stroke-linejoin="round"/>
    <polygon points="75,28 82,52 62,78" fill="rgba(0,212,255,0.15)" stroke="#00d4ff" stroke-width="0.9" stroke-linejoin="round"/>
    <polygon points="15,28 8,52 28,78" fill="rgba(0,212,255,0.20)" stroke="#00d4ff" stroke-width="0.9" stroke-linejoin="round"/>
    <polygon points="8,52 28,78 45,100 45,68" fill="rgba(0,212,255,0.07)" stroke="rgba(0,212,255,0.35)" stroke-width="0.7" stroke-linejoin="round"/>
    <polygon points="82,52 62,78 45,100 45,68" fill="rgba(0,212,255,0.12)" stroke="rgba(0,212,255,0.35)" stroke-width="0.7" stroke-linejoin="round"/>
    <polygon points="28,78 62,78 45,100" fill="rgba(0,212,255,0.14)" stroke="#00d4ff" stroke-width="1.2" stroke-linejoin="round"/>
    <line class="bit-edge1" x1="15" y1="28" x2="45" y2="4" stroke="#00d4ff" stroke-width="2.4" stroke-linecap="round"/>
    <line class="bit-edge2" x1="45" y1="4" x2="75" y2="28" stroke="#00d4ff" stroke-width="1.6" stroke-linecap="round"/>
    <circle class="bit-top" cx="45" cy="4" r="3" fill="#00d4ff"/>
    <circle class="bit-vtx-mid" cx="15" cy="28" r="1.8" fill="#00d4ff" opacity="0.5"/>
    <circle class="bit-vtx-mid" cx="75" cy="28" r="1.8" fill="#00d4ff" opacity="0.5"/>
    <circle class="bit-vtx-mid" cx="8" cy="52" r="1.4" fill="#00d4ff" opacity="0.35"/>
    <circle class="bit-vtx-mid" cx="82" cy="52" r="1.4" fill="#00d4ff" opacity="0.35"/>
    <circle class="bit-vtx-bot" cx="45" cy="100" r="2.2" fill="#00d4ff" opacity="0.65"/>
  </g>
</svg>
"""

_FLOORPLAN_SVG = """
<svg class="vbim-hero-floorplan" width="420" height="300"
     viewBox="0 0 500 360" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- perimeter -->
  <rect x="30" y="30" width="440" height="300" stroke="#00d4ff" stroke-width="3.5"/>
  <!-- interior walls -->
  <line x1="30"  y1="180" x2="210" y2="180" stroke="#00d4ff" stroke-width="2.5"/>
  <line x1="210" y1="30"  x2="210" y2="330" stroke="#00d4ff" stroke-width="2.5"/>
  <line x1="210" y1="150" x2="470" y2="150" stroke="#00d4ff" stroke-width="2.5"/>
  <line x1="340" y1="150" x2="340" y2="330" stroke="#00d4ff" stroke-width="2.5"/>
  <!-- door openings (gaps + arcs) -->
  <path d="M 210 255 Q 240 255 240 285" stroke="#00d4ff" stroke-width="1.5" fill="none" stroke-dasharray="3 2"/>
  <path d="M 130 180 Q 130 210 160 210" stroke="#00d4ff" stroke-width="1.5" fill="none" stroke-dasharray="3 2"/>
  <!-- windows (dashed segments on perimeter) -->
  <line x1="80"  y1="30"  x2="140" y2="30"  stroke="#00d4ff" stroke-width="4" stroke-dasharray="6 4"/>
  <line x1="270" y1="30"  x2="360" y2="30"  stroke="#00d4ff" stroke-width="4" stroke-dasharray="6 4"/>
  <line x1="30"  y1="70"  x2="30"  y2="130" stroke="#00d4ff" stroke-width="4" stroke-dasharray="6 4"/>
  <!-- dimension lines -->
  <line x1="30"  y1="15" x2="470" y2="15"   stroke="#00d4ff" stroke-width="1"/>
  <line x1="30"  y1="10" x2="30"  y2="20"   stroke="#00d4ff" stroke-width="1"/>
  <line x1="470" y1="10" x2="470" y2="20"   stroke="#00d4ff" stroke-width="1"/>
  <line x1="485" y1="30" x2="485" y2="330"  stroke="#00d4ff" stroke-width="1"/>
  <line x1="480" y1="30" x2="490" y2="30"   stroke="#00d4ff" stroke-width="1"/>
  <line x1="480" y1="330" x2="490" y2="330" stroke="#00d4ff" stroke-width="1"/>
  <!-- room codes -->
  <text x="118" y="112" font-family="monospace" font-size="20" fill="#00d4ff" text-anchor="middle">1.1.1</text>
  <text x="118" y="260" font-family="monospace" font-size="20" fill="#00d4ff" text-anchor="middle">1.1.2</text>
  <text x="338" y="97"  font-family="monospace" font-size="20" fill="#00d4ff" text-anchor="middle">1.1.3</text>
  <text x="273" y="250" font-family="monospace" font-size="20" fill="#00d4ff" text-anchor="middle">1.1.4</text>
  <text x="405" y="250" font-family="monospace" font-size="20" fill="#00d4ff" text-anchor="middle">1.1.5</text>
  <!-- north indicator -->
  <circle cx="455" cy="58" r="16" stroke="#00d4ff" stroke-width="1.5"/>
  <line x1="455" y1="46" x2="455" y2="36" stroke="#00d4ff" stroke-width="2.5"/>
  <polygon points="455,44 451,56 455,52 459,56" fill="#00d4ff"/>
  <text x="455" y="34" font-family="monospace" font-size="12" fill="#00d4ff" text-anchor="middle">N</text>
  <!-- scale bar -->
  <line x1="60" y1="348" x2="160" y2="348" stroke="#00d4ff" stroke-width="1.5"/>
  <line x1="60" y1="344" x2="60"  y2="352" stroke="#00d4ff" stroke-width="1.5"/>
  <line x1="160" y1="344" x2="160" y2="352" stroke="#00d4ff" stroke-width="1.5"/>
  <text x="110" y="358" font-family="monospace" font-size="11" fill="#00d4ff" text-anchor="middle">ESC 1:50</text>
</svg>
"""

_motor_tag = "Groq · IA" if "Groq" in modo else "Reglas"

st.markdown(f"""
<div class="vbim-hero">
  <div class="vbim-hero-grid"></div>
  <div class="vbim-scan"></div>
  <div class="vbim-corner vbim-corner--tl"></div>
  <div class="vbim-corner vbim-corner--tr"></div>
  <div class="vbim-corner vbim-corner--bl"></div>
  <div class="vbim-corner vbim-corner--br"></div>
  {_FLOORPLAN_SVG}
  <div class="vbim-hero-content">
    <div style="flex-shrink:0">{_BIT_SVG}</div>
    <div>
      <div class="vbim-hero-title">Revisor de <span>Planimetría</span></div>
      <div class="vbim-hero-sub">Análisis automatizado de láminas PDF con inteligencia artificial</div>
      <div class="vbim-hero-tags">
        <span class="vbim-tag">VoxelBIM</span>
        <span class="vbim-tag">{_motor_tag}</span>
        <span class="vbim-tag">{dpi} DPI</span>
        <span class="vbim-tag">PDF · Planimetría</span>
      </div>
    </div>
  </div>
  <div class="vbim-hero-bar">
    <div class="vbim-hero-bar-dot"></div>
    <span class="vbim-hero-bar-live">SISTEMA ACTIVO</span>
    <span class="vbim-hero-bar-sep">│</span>
    <span>VoxelBIM</span>
    <span class="vbim-hero-bar-sep">·</span>
    <span>Arquitectura · Datos · BIM</span>
  </div>
</div>
""", unsafe_allow_html=True)

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
