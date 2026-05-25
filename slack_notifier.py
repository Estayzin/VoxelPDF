import requests
from PIL import Image


def send_report(
    webhook_url: str,
    filename: str,
    pagina: int,
    resultado: dict,
    aprobados: int,
    total: int,
    thumbnail: Image.Image,
):
    """Envía el reporte de una sola página a Slack."""
    pct = int(aprobados / total * 100)
    estado = "APROBADO ✅" if pct >= 80 else "REVISAR ⚠️" if pct >= 50 else "RECHAZADO ❌"
    color = "#2eb886" if pct >= 80 else "#e8a838" if pct >= 50 else "#e01e5a"

    checks_lines = []
    for key, val in resultado.items():
        if key == "resumen" or not isinstance(val, dict):
            continue
        icon = ":white_check_mark:" if val.get("presente") else ":x:"
        obs = val.get("observacion", "")
        nombre = key.replace("_", " ").title()
        checks_lines.append(f"{icon} *{nombre}*: {obs}")

    resumen = resultado.get("resumen", "")
    checks_text = "\n".join(checks_lines)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Revisión — Página {pagina} — {estado}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Archivo:*\n{filename}"},
                {"type": "mrkdwn", "text": f"*Puntaje:*\n{aprobados}/{total} ({pct}%)"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": checks_text or "_Sin detalle_"},
        },
    ]
    if resumen:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"💬 {resumen}"}],
        })

    payload = {"attachments": [{"color": color, "blocks": blocks}]}
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    return True


def send_bulk_report(webhook_url: str, filename: str, resultados: list):
    """Envía un único mensaje consolidado con el resumen de todas las páginas."""
    total_pags = len(resultados)
    aprobadas = sum(1 for r in resultados if int(r["aprobados"] / r["total"] * 100) >= 80)
    revisar = sum(1 for r in resultados if 50 <= int(r["aprobados"] / r["total"] * 100) < 80)
    rechazadas = total_pags - aprobadas - revisar

    pct_global = int(sum(r["aprobados"] / r["total"] for r in resultados) / total_pags * 100)
    color = "#2eb886" if pct_global >= 80 else "#e8a838" if pct_global >= 50 else "#e01e5a"
    estado_global = "APROBADO ✅" if pct_global >= 80 else "REVISAR ⚠️" if pct_global >= 50 else "RECHAZADO ❌"

    # Tabla de páginas
    filas = []
    for r in resultados:
        pct = int(r["aprobados"] / r["total"] * 100)
        icono = "✅" if pct >= 80 else "⚠️" if pct >= 50 else "❌"
        pdf_label = f" `{r['pdf_name']}`" if r.get("pdf_name") else ""
        filas.append(f"{icono} *Pág {r['pagina']}*{pdf_label}: {r['aprobados']}/{r['total']} checks ({pct}%)")
    tabla = "\n".join(filas)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📐 Revisión de Planimetría — {estado_global}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Archivo:*\n{filename}"},
                {"type": "mrkdwn", "text": f"*Páginas revisadas:*\n{total_pags}"},
                {"type": "mrkdwn", "text": f"*Puntaje global:*\n{pct_global}%"},
                {"type": "mrkdwn", "text": f"*Resultado:*\n✅ {aprobadas}  ⚠️ {revisar}  ❌ {rechazadas}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Detalle por página:*\n{tabla}"},
        },
    ]

    # Detalle de checks fallidos para cada página
    for r in resultados:
        pct = int(r["aprobados"] / r["total"] * 100)
        if pct < 100:
            fallidos = [
                f"  • {k.replace('_', ' ').title()}: {v.get('observacion', '')}"
                for k, v in r["resultado"].items()
                if isinstance(v, dict) and not v.get("presente")
            ]
            if fallidos:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"*Pág {r['pagina']} — checks fallidos:*\n" + "\n".join(fallidos)}],
                })

    payload = {"attachments": [{"color": color, "blocks": blocks}]}
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    return True
