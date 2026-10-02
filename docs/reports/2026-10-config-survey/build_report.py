"""Build the configuration survey report (HTML → PDF via headless Chrome).

Usage: python build_report.py  (writes report.html next to this file)
"""

from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONTS = (HERE.parents[2] / "frontend" / "public" / "fonts").as_uri()

# ---------------------------------------------------------------------------
# Inventory: one row per configurable setting.
# (setting, where it lives today, who edits it today, reaches ElevenLabs?,
#  proposed level, status flag)
# status: ok | warn | bad | dead | missing
# ---------------------------------------------------------------------------

DB, FILE, EL, ENV, CODE, WORKOS, NONE = (
    "Base de datos",
    "Archivo del repo",
    "Dashboard ElevenLabs",
    "Variable de entorno",
    "Código fijo",
    "WorkOS",
    "No existe",
)

INVENTORY: dict[str, list[tuple[str, str, str, str, str, str]]] = {
    "Identidad y objetivo": [
        ("Nombre del cliente", DB, "Superadmin (UI)", "—", "Cliente", "ok"),
        ("Cliente activo / inactivo", DB, "Superadmin (UI)", "—", "Cliente", "ok"),
        ("Slug del agente", DB, "Superadmin, solo al crear", "—", "Agente", "ok"),
        ("Nombre del agente", DB, "Superadmin (UI)", "—", "Agente", "ok"),
        ("Agente por defecto / activo", DB, "Superadmin (UI)", "—", "Agente", "warn"),
        ("Copia vieja de config del agente en el cliente", DB, "Superadmin (UI)", "—", "Eliminar", "dead"),
        ("Objetivo del agente", NONE, "—", "—", "Agente (obligatorio)", "missing"),
    ],
    "Conversación y prompt": [
        ("System prompt (archivo)", FILE, "Git (deploy)", "Indirecto: texto del LLM", "Agente, versionado", "warn"),
        ("System prompt (base de datos)", DB, "Superadmin (UI), ignorado", "—", "Unificar con el anterior", "bad"),
        ("Prompt de cliente y plantilla Jaumpablo", CODE, "Git (deploy)", "—", "Plantillas de Qora", "warn"),
        ("Knowledge base (DB y knowledge.md)", DB, "Superadmin (UI), sin efecto", "—", "Skill «info de la empresa»", "dead"),
        ("Primer mensaje", EL, "Manual (vacío hoy)", "Sí, a mano", "Agente", "warn"),
        ("Idioma de la conversación", EL, "Manual", "Sí, a mano", "Agente", "warn"),
        ("Variables dinámicas por llamada", CODE, "3 implementaciones", "Sí, por llamada", "Contrato único de Qora", "warn"),
    ],
    "Modelo de lenguaje": [
        ("Modelo del agente", DB, "Superadmin, la UI solo al crear", "—", "Estándar Qora + override", "warn"),
        ("Temperatura y largo de respuesta", DB, "Superadmin (UI)", "—", "Estándar Qora + override", "ok"),
        ("Modelo del análisis post-llamada", ENV, "Railway", "—", "Estándar Qora", "warn"),
        ("Frases de espera de las tools", CODE, "—", "—", "Estándar Qora + idioma", "warn"),
    ],
    "Voz": [
        ("Voz elegida", EL, "Dashboard a mano; DB decorativa", "Solo a mano", "Agente (obligatoria)", "bad"),
        ("Modelo de voz (TTS)", DB, "API, sin UI", "No se sincroniza", "Agente", "bad"),
        ("Velocidad, estabilidad, similitud", DB, "Superadmin (UI)", "Solo en la demo web", "Agente", "bad"),
        ("Sonido de fondo", EL, "Manual", "Sí, a mano", "Agente", "warn"),
        ("Voz y agente por defecto de plataforma", ENV, "Railway", "—", "Eliminar", "dead"),
    ],
    "Turnos y control de la llamada": [
        ("Agresividad de turnos y timeout de turno", EL, "Manual («eager» hoy)", "Sí, a mano", "Estándar Qora + override", "bad"),
        ("Muletilla de espera (soft timeout)", DB, "API, sin UI", "Sí, por API", "Agente", "warn"),
        ("Duración máxima de la llamada", DB, "API, sin UI", "Sí, por API", "Agente", "ok"),
        ("Detección de buzón de voz", DB, "API, sin UI", "Sí, por API", "Agente", "warn"),
        ("Colgar al terminar (end_call)", EL, "Manual (apagado)", "Sí, a mano", "Agente", "bad"),
        ("Palabras clave de reconocimiento", EL, "Manual", "Sí, a mano", "Agente", "warn"),
    ],
    "Tools y skills": [
        ("Tools habilitadas", DB, "UI desactualizada", "—", "Agente", "bad"),
        ("Campos de captura de datos", FILE, "Superadmin (UI) → crm.yaml", "—", "Cliente / agente", "bad"),
        ("Índice de skills (registry.yaml)", FILE, "Git (deploy)", "—", "Paquetes de skills", "warn"),
        ("Contenido de cada skill", FILE, "Git (deploy)", "—", "Paquetes, versionado", "warn"),
    ],
    "Memoria y análisis": [
        ("Llamadas previas en memoria (3)", CODE, "—", "—", "Estándar Qora + override", "ok"),
        ("Hechos del lead extraídos", DB, "Se guardan, nunca se usan", "—", "Agente (activar)", "bad"),
        ("Zona horaria de la memoria", CODE, "Fija: Buenos Aires", "—", "Cliente", "warn"),
        ("Catálogo de productos y necesidades", CODE, "Fijo: productos de Quintana", "—", "Perfil de análisis", "bad"),
        ("Reglas de próxima acción", DB, "Nadie (sin API)", "—", "Cliente", "bad"),
        ("Idioma del análisis", DB, "Nadie (sin API)", "—", "Cliente", "bad"),
        ("Configuración de extracción", DB, "Nadie (sin uso)", "—", "Eliminar", "dead"),
        ("Tipo de memoria del agente", NONE, "—", "—", "Agente (futuro)", "missing"),
    ],
    "Agenda y reintentos (cliente)": [
        ("Agenda habilitada", DB, "API, sin UI", "—", "Cliente", "warn"),
        ("Intentos, espera y backoff", DB, "API, sin UI", "—", "Cliente", "warn"),
        ("Horario permitido", DB, "API, sin UI", "—", "Cliente", "warn"),
        ("Resultados que reintentan", DB, "API, sin validar", "—", "Cliente", "warn"),
        ("Zona horaria del cliente", DB, "API, sin UI", "—", "Cliente", "warn"),
        ("Reintento técnico y timeouts", CODE, "—", "—", "Estándar Qora", "ok"),
        ("Llamadas simultáneas del discador", ENV, "Railway (1 global)", "—", "Plan del cliente", "warn"),
    ],
    "Plan y acceso": [
        ("Plan", DB, "Superadmin (UI)", "—", "Cliente", "ok"),
        ("Features y límites del plan", DB, "Superadmin (UI)", "—", "Cliente", "ok"),
        ("Catálogo de planes", CODE, "Git (deploy)", "—", "Estándar Qora", "ok"),
        ("Organización de login", WORKOS, "Superadmin (UI)", "—", "Cliente", "ok"),
        ("Invitaciones de usuarios", WORKOS, "Superadmin (UI)", "—", "Cliente", "ok"),
        ("Superadmins", ENV, "Railway", "—", "Qora", "ok"),
        ("Límites de costo y minutos por agente", NONE, "—", "—", "Agente", "missing"),
    ],
    "Integraciones y conexión": [
        ("CRM: base, tabla, mapeos, estados", FILE, "Superadmin (UI), se pierde al deployar", "—", "Cliente (DB)", "bad"),
        ("API key del CRM", ENV, "Railway, una por cliente", "—", "Cliente (DB cifrada)", "bad"),
        ("Número de teléfono saliente", DB, "API (ignorado al crear)", "Sí, por llamada", "Agente", "warn"),
        ("Agente de ElevenLabs vinculado", DB, "Superadmin (UI)", "—", "Automático", "warn"),
        ("URL del LLM, secreto y webhooks", EL, "Copiar y pegar a mano", "Sí, a mano", "Automático", "bad"),
        ("Trunk SIP y números", EL, "Manual", "Sí, a mano", "Plataforma", "ok"),
    ],
}

STATUS_LABEL = {
    "ok": ("Bien", "s-ok"),
    "warn": ("Ordenar", "s-warn"),
    "bad": ("Problema", "s-bad"),
    "dead": ("Sin uso", "s-dead"),
    "missing": ("Falta", "s-missing"),
}

ALL_ROWS = [row for rows in INVENTORY.values() for row in rows]
TOTAL = len(ALL_ROWS)
BY_PLACE = Counter(row[1] for row in ALL_ROWS)
BY_STATUS = Counter(row[5] for row in ALL_ROWS)


def place_bars() -> str:
    order = [DB, EL, FILE, CODE, ENV, WORKOS, NONE]
    colors = {
        DB: "#4edea3",
        EL: "#d0bcff",
        FILE: "#f59e0b",
        CODE: "#EE9170",
        ENV: "#7dd3fc",
        WORKOS: "#bbcabf",
        NONE: "#5b6478",
    }
    peak = max(BY_PLACE.values())
    out = []
    for i, place in enumerate(order):
        n = BY_PLACE.get(place, 0)
        width = 300 * n / peak
        y = 14 + i * 40
        out.append(
            f'<text x="0" y="{y + 15}" class="svg-label">{escape(place)}</text>'
            f'<rect x="180" y="{y}" width="{width:.0f}" height="22" rx="3" fill="{colors[place]}"/>'
            f'<text x="{188 + width:.0f}" y="{y + 16}" class="svg-num">{n}</text>'
        )
    return (
        '<svg viewBox="0 0 540 300" class="chart">' + "".join(out) + "</svg>"
    )


def status_donut() -> str:
    import math

    order = ["bad", "warn", "dead", "missing", "ok"]
    colors = {"bad": "#EE9170", "warn": "#f59e0b", "dead": "#5b6478", "missing": "#d0bcff", "ok": "#4edea3"}
    cx, cy, r = 110, 110, 80
    angle = -math.pi / 2
    paths = []
    for key in order:
        n = BY_STATUS.get(key, 0)
        if not n:
            continue
        sweep = 2 * math.pi * n / TOTAL
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        angle += sweep
        x2, y2 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        large = 1 if sweep > math.pi else 0
        paths.append(
            f'<path d="M {x1:.1f} {y1:.1f} A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f}" '
            f'stroke="{colors[key]}" stroke-width="30" fill="none"/>'
        )
    legend = []
    for i, key in enumerate(order):
        label = STATUS_LABEL[key][0]
        legend.append(
            f'<rect x="240" y="{40 + i * 30}" width="14" height="14" rx="3" fill="{colors[key]}"/>'
            f'<text x="262" y="{52 + i * 30}" class="svg-label">{label}: {BY_STATUS.get(key, 0)}</text>'
        )
    return (
        '<svg viewBox="0 0 420 220" class="chart">'
        + "".join(paths)
        + f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" class="svg-big">{TOTAL}</text>'
        + f'<text x="{cx}" y="{cy + 24}" text-anchor="middle" class="svg-small">configuraciones</text>'
        + "".join(legend)
        + "</svg>"
    )


def inventory_pages() -> list[str]:
    """Chunk inventory groups into pages of at most ~19 rows."""
    pages: list[list[tuple[str, list]]] = [[]]
    budget = 0
    for group, rows in INVENTORY.items():
        cost = len(rows) + 2
        if budget + cost > 25 and pages[-1]:
            pages.append([])
            budget = 0
        pages[-1].append((group, rows))
        budget += cost
    html_pages = []
    for idx, groups in enumerate(pages, start=1):
        body = []
        for group, rows in groups:
            trs = []
            for setting, place, editor, el, level, status in rows:
                label, css = STATUS_LABEL[status]
                trs.append(
                    "<tr>"
                    f"<td class='c-set'>{escape(setting)}</td>"
                    f"<td>{escape(place)}</td>"
                    f"<td>{escape(editor)}</td>"
                    f"<td>{escape(el)}</td>"
                    f"<td class='c-level'>{escape(level)}</td>"
                    f"<td><span class='pill {css}'>{label}</span></td>"
                    "</tr>"
                )
            body.append(
                f"<h3 class='group'>{escape(group)}</h3>"
                "<table class='inv'><thead><tr><th>Configuración</th><th>Dónde vive hoy</th>"
                "<th>Quién la cambia hoy</th><th>¿Llega a ElevenLabs?</th><th>Nivel propuesto</th>"
                "<th>Estado</th></tr></thead><tbody>" + "".join(trs) + "</tbody></table>"
            )
        html_pages.append(
            page(
                f"Inventario completo · {idx}/{len(pages)}",
                "Inventario completo",
                "".join(body),
            )
        )
    return html_pages


PAGE_NO = [0]


def page(kicker: str, title: str, body: str, extra_class: str = "") -> str:
    PAGE_NO[0] += 1
    return f"""
<section class="page {extra_class}">
  <header class="ph"><span class="brand">QORA</span><span class="kicker">{escape(kicker)}</span></header>
  <h2>{escape(title)}</h2>
  {body}
  <footer class="pf"><span>Relevamiento de configuración · Octubre 2026</span><span>{PAGE_NO[0]}</span></footer>
</section>"""


# ---------------------------------------------------------------------------
# Diagrams (inline SVG)
# ---------------------------------------------------------------------------

TODAY_DIAGRAM = """
<svg viewBox="0 0 680 330" class="diagram">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#86948a"/></marker></defs>
  <g class="node db"><rect x="20" y="20" width="190" height="78" rx="8"/><text x="115" y="50" class="nt">Base de datos</text><text x="115" y="72" class="ns">cliente, agente, plan, agenda</text></g>
  <g class="node file"><rect x="245" y="20" width="190" height="78" rx="8"/><text x="340" y="50" class="nt">Archivos del repo</text><text x="340" y="72" class="ns">prompts, skills, CRM</text></g>
  <g class="node el"><rect x="470" y="20" width="190" height="78" rx="8"/><text x="565" y="50" class="nt">Dashboard ElevenLabs</text><text x="565" y="72" class="ns">voz, turnos, webhooks</text></g>
  <g class="node env"><rect x="20" y="232" width="190" height="78" rx="8"/><text x="115" y="262" class="nt">Variables de Railway</text><text x="115" y="284" class="ns">secretos por cliente</text></g>
  <g class="node code"><rect x="245" y="232" width="190" height="78" rx="8"/><text x="340" y="262" class="nt">Código fijo</text><text x="340" y="284" class="ns">catálogo, memoria, reintentos</text></g>
  <g class="node workos"><rect x="470" y="232" width="190" height="78" rx="8"/><text x="565" y="262" class="nt">WorkOS</text><text x="565" y="284" class="ns">login y usuarios</text></g>
  <g class="call"><circle cx="340" cy="165" r="44"/><text x="340" y="161" class="nt dark">Una</text><text x="340" y="180" class="nt dark">llamada</text></g>
  <path d="M115 98 L305 140" class="edge" marker-end="url(#arr)"/>
  <path d="M340 98 L340 120" class="edge" marker-end="url(#arr)"/>
  <path d="M565 98 L375 140" class="edge" marker-end="url(#arr)"/>
  <path d="M115 232 L305 190" class="edge" marker-end="url(#arr)"/>
  <path d="M340 232 L340 210" class="edge" marker-end="url(#arr)"/>
  <path d="M565 232 L375 190" class="edge dashed" marker-end="url(#arr)"/>
</svg>"""

INHERIT_DIAGRAM = """
<svg viewBox="0 0 680 300" class="diagram">
  <defs><marker id="arr2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#4edea3"/></marker></defs>
  <g class="tier t1"><rect x="20" y="20" width="400" height="66" rx="8"/><text x="40" y="48" class="nt left">Estándar Qora</text><text x="40" y="70" class="ns left">modelo recomendado, turnos, reintentos, plantillas</text></g>
  <g class="tier t2"><rect x="60" y="116" width="400" height="66" rx="8"/><text x="80" y="144" class="nt left">Cliente</text><text x="80" y="166" class="ns left">pisa lo que necesite: horarios, idioma, CRM, análisis</text></g>
  <g class="tier t3"><rect x="100" y="212" width="400" height="66" rx="8"/><text x="120" y="240" class="nt left">Agente</text><text x="120" y="262" class="ns left">objetivo, prompt y voz obligatorios; pisa el resto</text></g>
  <path d="M440 53 Q520 53 520 140" class="edge green" marker-end="url(#arr2)"/>
  <path d="M480 149 Q560 149 560 236" class="edge green" marker-end="url(#arr2)"/>
  <g class="result"><rect x="530" y="212" width="135" height="66" rx="8"/><text x="597" y="240" class="nt dark">Config</text><text x="597" y="260" class="nt dark">resuelta</text></g>
  <path d="M500 245 L528 245" class="edge green" marker-end="url(#arr2)"/>
</svg>"""

RECONCILE_DIAGRAM = """
<svg viewBox="0 0 680 230" class="diagram">
  <defs><marker id="arr3" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#d0bcff"/></marker></defs>
  <g class="node db"><rect x="20" y="70" width="170" height="90" rx="8"/><text x="105" y="104" class="nt">Qora</text><text x="105" y="126" class="ns">fuente de verdad</text><text x="105" y="144" class="ns">config versionada</text></g>
  <g class="node code"><rect x="255" y="70" width="170" height="90" rx="8"/><text x="340" y="104" class="nt">Sincronizador</text><text x="340" y="126" class="ns">calcula diferencias</text><text x="340" y="144" class="ns">y las aplica por API</text></g>
  <g class="node el"><rect x="490" y="70" width="170" height="90" rx="8"/><text x="575" y="104" class="nt">ElevenLabs</text><text x="575" y="126" class="ns">reflejo del agente</text><text x="575" y="144" class="ns">nunca se edita a mano</text></g>
  <path d="M190 115 L253 115" class="edge violet" marker-end="url(#arr3)"/>
  <path d="M425 115 L488 115" class="edge violet" marker-end="url(#arr3)"/>
  <path d="M575 160 Q575 190 340 190 Q160 190 105 162" class="edge dashed violet" marker-end="url(#arr3)"/>
  <text x="340" y="222" class="ns" text-anchor="middle">control de desvío: si alguien tocó el dashboard, Qora lo detecta</text>
</svg>"""

SKILLS_DIAGRAM = """
<svg viewBox="0 0 680 270" class="diagram">
  <g class="pkg q"><rect x="20" y="20" width="230" height="230" rx="10"/><text x="135" y="48" class="nt">Paquete Qora</text><text x="135" y="68" class="ns">nuestras skills, reutilizables</text>
    <rect x="40" y="90" width="190" height="34" rx="6" class="chip"/><text x="135" y="112" class="ns">Manejo de objeciones</text>
    <rect x="40" y="134" width="190" height="34" rx="6" class="chip"/><text x="135" y="156" class="ns">Agendar seguimiento</text>
    <rect x="40" y="178" width="190" height="34" rx="6" class="chip"/><text x="135" y="200" class="ns">Cierre de llamada</text></g>
  <g class="pkg c"><rect x="290" y="20" width="370" height="230" rx="10"/><text x="475" y="48" class="nt">Paquete del cliente</text><text x="475" y="68" class="ns">Quintana Seguros</text>
    <rect x="310" y="88" width="330" height="40" rx="6" class="sect"/><text x="475" y="113" class="ns">General (todos sus agentes): info de la empresa</text>
    <rect x="310" y="142" width="155" height="90" rx="6" class="sect a"/><text x="387" y="166" class="ns">Agente de leads</text><text x="387" y="188" class="ns">cotizar auto</text><text x="387" y="208" class="ns">capturar datos</text>
    <rect x="485" y="142" width="155" height="90" rx="6" class="sect a"/><text x="562" y="166" class="ns">Agente de cobranza</text><text x="562" y="188" class="ns">recordar pago</text><text x="562" y="208" class="ns">medios de pago</text></g>
</svg>"""

ER_DIAGRAM = """
<svg viewBox="0 0 680 330" class="diagram er">
  <g class="ent"><rect x="20" y="20" width="190" height="86" rx="8"/><text x="115" y="44" class="nt">clients</text><text x="115" y="66" class="ns">identidad, plan, zona horaria</text><text x="115" y="86" class="ns">overrides del cliente</text></g>
  <g class="ent"><rect x="245" y="20" width="190" height="86" rx="8"/><text x="340" y="44" class="nt">agents</text><text x="340" y="66" class="ns">identidad, objetivo, estado</text><text x="340" y="86" class="ns">→ revisión activa</text></g>
  <g class="ent new"><rect x="470" y="20" width="190" height="86" rx="8"/><text x="565" y="44" class="nt">agent_config_revisions</text><text x="565" y="66" class="ns">prompt, voz, turnos, tools</text><text x="565" y="86" class="ns">inmutables, con autor</text></g>
  <g class="ent new"><rect x="20" y="130" width="190" height="86" rx="8"/><text x="115" y="154" class="nt">client_integrations</text><text x="115" y="176" class="ns">CRM, mapeos, estados</text><text x="115" y="196" class="ns">(reemplaza crm.yaml)</text></g>
  <g class="ent new"><rect x="245" y="130" width="190" height="86" rx="8"/><text x="340" y="154" class="nt">client_secrets</text><text x="340" y="176" class="ns">API keys cifradas</text><text x="340" y="196" class="ns">(reemplaza env por cliente)</text></g>
  <g class="ent new"><rect x="470" y="130" width="190" height="86" rx="8"/><text x="565" y="154" class="nt">elevenlabs_bindings</text><text x="565" y="176" class="ns">agente EL, teléfono</text><text x="565" y="196" class="ns">última revisión aplicada</text></g>
  <g class="ent new"><rect x="20" y="240" width="190" height="78" rx="8"/><text x="115" y="264" class="nt">skill_packages</text><text x="115" y="286" class="ns">Qora o cliente, secciones</text></g>
  <g class="ent new"><rect x="245" y="240" width="190" height="78" rx="8"/><text x="340" y="264" class="nt">skills + revisiones</text><text x="340" y="286" class="ns">contenido versionado</text></g>
  <g class="ent new"><rect x="470" y="240" width="190" height="78" rx="8"/><text x="565" y="264" class="nt">analysis_profiles</text><text x="565" y="286" class="ns">catálogo y reglas por vertical</text></g>
  <path d="M210 63 L245 63" class="edge"/><path d="M435 63 L470 63" class="edge"/>
  <path d="M115 106 L115 130" class="edge"/><path d="M180 106 L300 130" class="edge"/>
  <path d="M400 106 L520 130" class="edge"/><path d="M340 216 L340 240" class="edge"/>
  <path d="M210 279 L245 279" class="edge"/>
</svg>"""

ROADMAP = """
<div class="roadmap">
  <div class="phase p0"><div class="pn">0</div><div><h4>Arreglos rápidos</h4><p>Sin cambiar el modelo. Que lo que se configura en Qora llegue de verdad a las llamadas.</p></div></div>
  <div class="phase"><div class="pn">1</div><div><h4>Configuración del agente en la base</h4><p>Prompt, voz, turnos y tools en revisiones versionadas. Los archivos pasan a ser importación inicial.</p></div></div>
  <div class="phase"><div class="pn">2</div><div><h4>ElevenLabs como reflejo</h4><p>Sincronizador completo, control de desvío y ruteo por agente (no por cliente).</p></div></div>
  <div class="phase"><div class="pn">3</div><div><h4>Integraciones y secretos</h4><p>CRM y API keys por cliente en la base, cifradas. Un cliente mal configurado no tumba a los demás.</p></div></div>
  <div class="phase"><div class="pn">4</div><div><h4>Paquetes de skills</h4><p>Paquete Qora + paquete del cliente con secciones por agente.</p></div></div>
  <div class="phase"><div class="pn">5</div><div><h4>Perfiles de análisis</h4><p>Catálogo de productos y reglas por vertical o cliente.</p></div></div>
  <div class="phase p6"><div class="pn">6</div><div><h4>Arnés de onboarding y MCP</h4><p>Dar de alta un cliente es una operación guiada; el MCP opera sobre esta misma API.</p></div></div>
</div>"""


def card(title: str, text: str, css: str) -> str:
    return f"<div class='card {css}'><h4>{escape(title)}</h4><p>{text}</p></div>"


CRITICAL = [
    ("La voz configurada en Qora no llega a las llamadas",
     "Velocidad, estabilidad, similitud y modelo de voz solo se aplican en la demo web. En producción Qora dice 1.0 y 0.7; ElevenLabs usa 1.2 y 1.0, y Qora igual lo marca como «sincronizado»."),
    ("Las llamadas siempre usan el agente por defecto del cliente",
     "La URL del LLM es por cliente y resuelve el agente default (<code>webhook.py:902</code>, <code>initiation.py:110</code>). Con dos agentes por cliente, el segundo nunca habla con su propio prompt."),
    ("El CRM editado desde el panel se pierde en cada deploy",
     "<code>crm.yaml</code> vive en el repo y se reescribe en el servidor. El próximo deploy lo vuelve a la versión de git. Además, la API key puede quedar escrita en ese archivo."),
    ("La API key faltante de un cliente apaga toda la plataforma",
     "El chequeo de credenciales al arrancar corta el servidor completo si falta la key de un solo cliente. Sumar un cliente obliga a tocar Railway y reiniciar."),
    ("El análisis «universal» tiene los productos de Quintana",
     "El catálogo de interés son los 9 seguros de Quintana (<code>catalog.py:20</code>). Cualquier cliente de otro rubro recibe un análisis de interés equivocado."),
    ("Lo que el análisis aprende del lead no llega al agente",
     "Los hechos del perfil se guardan pero nadie los inyecta en la conversación (<code>memory.py:147</code>, <code>_format_accumulated_profile</code> sin uso). La memoria real es: últimos 3 resúmenes, notas y campos del lead."),
]

HIGH = [
    ("Panel de tools desactualizado", "3 de 4 casillas son tools que ya no existen y 5 tools reales no aparecen."),
    ("Prompt de la base ignorado sin aviso", "Si existe <code>system-prompt.md</code>, editar el prompt en el panel no cambia nada. La knowledge base tampoco se usa."),
    ("Configuración sin acceso", "Idioma del análisis y reglas de próxima acción no se pueden cambiar ni por API. La agenda y la zona horaria no tienen pantalla."),
    ("Agente de ElevenLabs compartido", "En producción, el demo de Qora y el agente de Quintana apuntan al mismo agente de ElevenLabs."),
    ("Controles solo en el dashboard", "Turnos en «eager» (interrumpe), colgar apagado, primer mensaje vacío: nada de eso se ve ni se cambia desde Qora."),
    ("Detalles de creación", "El teléfono se ignora al crear un agente y el default de tools tiene nombres viejos."),
]

MEDIUM = [
    ("Valores por defecto repetidos", "Los mismos números de voz están en 3 lugares; variables de plataforma guardan nombres de Quintana."),
    ("Variables por llamada en 3 lugares", "Inicio, salida y demo arman los datos del lead por separado."),
    ("Documentación desactualizada", "La skill y la guía de ElevenLabs describen una sincronización vieja."),
    ("Código y settings sin uso", "Pantallas duplicadas, <code>filler_timeout_ms</code>, <code>extraction_config</code>, la métrica <code>has_facts</code> (siempre falsa)."),
    ("Integraciones", "Un usuario cliente puede disparar el test de Airtable; las escrituras del archivo no son atómicas."),
    ("Constantes fijas", "Zona horaria de la memoria, reintentos técnicos y frases de espera en español."),
]

QUICK_WINS = [
    "Enviar voz y parámetros de voz a ElevenLabs en la sincronización, y que «sincronizado» compare valores reales.",
    "Pasar turnos a una agresividad normal y habilitar «colgar» en el agente de producción.",
    "Corregir la lista de tools del panel y el default de la columna.",
    "Aceptar el teléfono al crear un agente.",
    "Separar el agente de ElevenLabs del demo y el de Quintana.",
    "Activar los hechos del perfil del lead en la memoria del agente.",
    "Exponer por API idioma del análisis y reglas de próxima acción.",
]

DECISIONS = [
    ("¿Qué puede tocar el cliente?",
     "Propuesta: el cliente ve todo, pero edita solo lo de negocio (horarios, primer mensaje, datos de su empresa, voz desde un catálogo curado). Modelo, turnos y análisis quedan en manos de Qora."),
    ("¿Un agente de ElevenLabs por cada agente de Qora?",
     "Propuesta: sí, creado y mantenido por la API, nunca a mano. Un agente de ElevenLabs es solo configuración, no cuesta capacidad. Si algún día conviene compartir, ElevenLabs permite pisar voz, prompt y primer mensaje por llamada."),
    ("¿Perfiles de análisis por rubro o por cliente?",
     "Propuesta: por rubro (seguros, cobranzas, inmobiliaria) con override por cliente. Arranca con «seguros» = lo de hoy."),
    ("¿Por dónde empezamos?",
     "Propuesta: fase 0 primero (arreglos rápidos, 1 o 2 días) y después fase 1. Las fases 2 a 6 se diseñan con OpenSpec antes de tocar código."),
]


def build() -> str:
    pages = []

    # Cover
    PAGE_NO[0] += 1
    pages.append(f"""
<section class="page cover">
  <div class="cover-top"><span class="brand big">QORA</span><span class="dot"></span></div>
  <div class="cover-mid">
    <p class="eyebrow">RELEVAMIENTO · OCTUBRE 2026</p>
    <h1>Configuración de clientes y agentes</h1>
    <p class="lead">Qué se puede configurar hoy, dónde vive cada cosa, qué no funciona y cómo lo ordenamos para que Qora sea un producto de producción.</p>
  </div>
  <div class="cover-stats">
    <div><span class="num">{TOTAL}</span><span class="lbl">configuraciones relevadas</span></div>
    <div><span class="num">{len(BY_PLACE) - (1 if NONE in BY_PLACE else 0)}</span><span class="lbl">lugares distintos donde viven</span></div>
    <div><span class="num">{BY_STATUS['bad']}</span><span class="lbl">con un problema real</span></div>
  </div>
  <p class="cover-foot">Basado en el código de <code>main</code> (d518d30), el agente de ElevenLabs de producción y la API de producción en Railway.</p>
</section>""")

    # Executive summary
    pages.append(page("Resumen", "En una página", f"""
<div class="two">
  <div>
    <h3 class="sub">Lo que encontramos</h3>
    <ul class="clean">
      <li><b>La configuración está repartida en 6 lugares</b>: base de datos, archivos del repo, dashboard de ElevenLabs, variables de Railway, código fijo y WorkOS.</li>
      <li><b>Qora no es la fuente de verdad.</b> Varias cosas que se editan en el panel no llegan a la llamada real, y varias que sí importan solo se tocan a mano en ElevenLabs.</li>
      <li><b>El sistema asume un agente por cliente</b> aunque la base permite varios.</li>
      <li><b>Hay restos del prototipo de un solo cliente</b>: productos, nombres y valores de Quintana dentro de la plataforma.</li>
    </ul>
  </div>
  <div>
    <h3 class="sub">Lo que proponemos</h3>
    <ul class="clean">
      <li><b>Toda la configuración del cliente y del agente en la base</b>, versionada.</li>
      <li><b>Herencia con override</b>: estándar Qora → cliente → agente. Voz, prompt y objetivo son obligatorios por agente.</li>
      <li><b>ElevenLabs como reflejo</b>: Qora aplica la config por API y detecta si alguien la tocó a mano.</li>
      <li><b>Skills en paquetes</b> y <b>perfiles de análisis</b> por rubro.</li>
      <li><b>No es una reescritura</b>: son 7 fases chicas, empezando por arreglos de 1 o 2 días.</li>
    </ul>
  </div>
</div>
<div class="two charts">
  <div><h3 class="sub">Dónde vive cada configuración</h3>{place_bars()}</div>
  <div><h3 class="sub">En qué estado está</h3>{status_donut()}</div>
</div>"""))

    # Today
    pages.append(page("Cómo está hoy", "Seis fuentes para una sola llamada", f"""
<p class="intro">Para que un agente haga una llamada, Qora junta configuración de seis lugares que no se hablan entre sí. Nadie tiene la foto completa, y un cambio en uno no se refleja en los otros.</p>
{TODAY_DIAGRAM}
<div class="three">
  {card("Se pierde al deployar", "Lo que se edita en el panel y vive en archivos del repo (CRM) vuelve a la versión de git en cada deploy.", "bad")}
  {card("Solo a mano", "Primer mensaje, turnos, colgar, webhooks y voz real se cambian en el dashboard de ElevenLabs, sin rastro en Qora.", "warn")}
  {card("Sin pantalla", "Agenda, zona horaria, idioma del análisis y reglas de próxima acción no tienen UI; dos ni siquiera API.", "warn")}
</div>"""))

    # Story: one setting's journey
    pages.append(page("Un ejemplo concreto", "El viaje de la velocidad de la voz", """
<div class="journey">
  <div class="step"><span class="sn">1</span><h4>Panel de Qora</h4><p>El superadmin pone la velocidad en <b>1.0</b>. El panel dice «se aplica en la próxima llamada».</p></div>
  <div class="step"><span class="sn">2</span><h4>Base de datos</h4><p>Se guarda <code>tts_speed = 1.0</code> y el agente queda <b>«sincronizado»</b>.</p></div>
  <div class="step bad"><span class="sn">3</span><h4>Sincronización</h4><p>Solo envía muletilla, buzón y duración. <b>La voz no viaja.</b></p></div>
  <div class="step bad"><span class="sn">4</span><h4>Llamada real</h4><p>ElevenLabs usa su propio valor: <b>1.2</b>. Similitud 1.0 en vez de 0.7.</p></div>
</div>
<p class="intro">Lo mismo pasa con el modelo de voz y con la voz elegida. Solo la demo web pisa estos valores por conexión; las llamadas telefónicas nunca.</p>
<h3 class="sub">El mismo patrón, en otros lugares</h3>
<div class="two">
  <div class="card warn"><h4>Dos agentes por cliente</h4><p>La llamada entra por <code>/voice/quintana-seguros/custom-llm</code>: la URL identifica al cliente, no al agente. Qora carga siempre el agente <b>por defecto</b>. Un segundo agente (por ejemplo, de cobranzas) hablaría con el prompt del primero.</p></div>
  <div class="card warn"><h4>La memoria del lead</h4><p>El análisis extrae hechos del lead (vehículo, necesidades, señales de compra) y los guarda. <b>Ningún código los vuelve a poner en la conversación.</b> El agente recuerda resúmenes, no el perfil.</p></div>
</div>"""))

    pages.extend(inventory_pages())

    # Problems
    pages.append(page("Problemas", "Críticos: afectan llamadas reales hoy",
        "<div class='grid2'>" + "".join(card(t, x, "bad") for t, x in CRITICAL) + "</div>"))
    pages.append(page("Problemas", "Altos y medios",
        "<h3 class='sub'>Altos</h3><div class='grid3'>" + "".join(card(t, x, "warn") for t, x in HIGH) + "</div>"
        "<h3 class='sub'>Medios</h3><div class='grid3'>" + "".join(card(t, x, "dead") for t, x in MEDIUM) + "</div>"))

    # Proposal: inheritance
    pages.append(page("Modelo propuesto", "Una configuración, tres niveles", f"""
<p class="intro">El valor que usa un agente sale de él mismo; si no lo define, del cliente; si tampoco, del estándar de Qora. El estándar es una guía que se puede pisar en cualquier nivel.</p>
{INHERIT_DIAGRAM}
<div class="three">
  {card("Obligatorio, sin default", "Objetivo, prompt y voz se definen siempre para cada agente. Qora ofrece plantillas y lineamientos, no valores impuestos.", "ok")}
  {card("Versionado", "Cada cambio crea una revisión inmutable con autor y fecha. Cada llamada guarda qué revisión usó: se puede comparar y volver atrás.", "ok")}
  {card("Visible", "El panel muestra el valor efectivo y de qué nivel viene. Nada se edita sin ver qué pisa.", "ok")}
</div>"""))

    # Proposal: storage
    pages.append(page("Modelo propuesto", "Dónde se guarda cada cosa", f"""
<p class="intro">La regla: <b>el código guarda lo de Qora, la base guarda lo de cada cliente</b>. Dar de alta un cliente pasa a ser crear filas, no carpetas ni deploys. SQLite sigue siendo la base.</p>
{ER_DIAGRAM}
<div class="two">
  {card("Se queda en el código", "Estándares de Qora, plantillas de prompt, paquete de skills Qora, catálogo de planes, reglas técnicas de reintento. Versionado en git y revisado en PR.", "ok")}
  {card("Pasa a la base", "Todo lo del cliente y el agente: prompt, voz, turnos, tools, skills propias, CRM, secretos cifrados, perfil de análisis. Los archivos actuales se importan una vez.", "ok")}
</div>"""))

    # Proposal: ElevenLabs + skills
    pages.append(page("Modelo propuesto", "ElevenLabs como reflejo y skills en paquetes", f"""
{RECONCILE_DIAGRAM}
<p class="intro"><b>Un agente de ElevenLabs por cada agente de Qora</b>, creado y actualizado por la API. Es solo configuración: tener muchos no consume capacidad. La URL del LLM pasa a identificar al agente, así cada uno usa su propio prompt.</p>
{SKILLS_DIAGRAM}
<p class="intro">Cada agente ve el paquete Qora, la sección general de su cliente y su propia sección. Una skill puede vivir en una sección y estar habilitada en varios agentes.</p>"""))

    # Who edits what
    matrix_rows = [
        ("Objetivo, prompt y skills del agente", "Edita", "Ve y propone"),
        ("Voz y parámetros de voz", "Edita", "Elige de un catálogo"),
        ("Primer mensaje e idioma", "Edita", "Edita"),
        ("Modelo de lenguaje y temperatura", "Edita", "No ve"),
        ("Turnos, interrupciones y muletillas", "Edita", "No ve"),
        ("Horarios, reintentos y zona horaria", "Edita", "Edita"),
        ("Integración con su CRM", "Edita", "Conecta y mapea"),
        ("Perfil de análisis", "Edita", "Ve"),
        ("Plan, features y límites", "Edita", "Ve"),
        ("Usuarios de su empresa", "Edita", "Invita"),
    ]
    trs = "".join(
        f"<tr><td class='c-set'>{escape(a)}</td><td><span class='pill s-ok'>{escape(b)}</span></td>"
        f"<td><span class='pill {'s-dead' if c == 'No ve' else 's-missing'}'>{escape(c)}</span></td></tr>"
        for a, b, c in matrix_rows
    )
    pages.append(page("Modelo propuesto", "Quién toca qué", f"""
<p class="intro">Propuesta para validar. Hoy todo es superadmin y el cliente no tiene ninguna pantalla de configuración.</p>
<table class="inv matrix"><thead><tr><th>Configuración</th><th>Qora (superadmin)</th><th>Cliente</th></tr></thead><tbody>{trs}</tbody></table>
<div class="three">
  {card("Hoy", "Todas las pantallas de configuración son de superadmin. El usuario cliente solo ve dashboards y el monitor en vivo.", "warn")}
  {card("Por qué separar", "Lo que define la calidad de la llamada (modelo, turnos, análisis) es parte del producto Qora. Lo que define el negocio (horarios, mensajes, CRM) es del cliente.", "ok")}
  {card("Siempre con permiso", "Cada edición queda registrada como revisión con autor. Un cambio del cliente se puede auditar y revertir.", "violet")}
</div>"""))

    # Roadmap
    qw = "".join(f"<li>{escape(x)}</li>" for x in QUICK_WINS)
    pages.append(page("Plan", "De acá a un producto ordenado", f"""
{ROADMAP}
<h3 class="sub">Fase 0 en detalle</h3>
<ul class="clean small">{qw}</ul>"""))

    # Decisions
    dec = "".join(card(t, x, "violet") for t, x in DECISIONS)
    pages.append(page("Para decidir", "Lo que necesito de vos", f"""
<p class="intro">Con estas cuatro respuestas arranco la fase 0 y escribo la propuesta formal de la fase 1.</p>
<div class="grid2">{dec}</div>"""))

    return HTML_HEAD + "".join(pages) + "</body></html>"


HTML_HEAD = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Qora · Relevamiento de configuración</title>
<style>
@font-face {{ font-family: Manrope; font-weight: 400; src: url('{FONTS}/manrope-400.woff2'); }}
@font-face {{ font-family: Manrope; font-weight: 600; src: url('{FONTS}/manrope-600.woff2'); }}
@font-face {{ font-family: Manrope; font-weight: 700; src: url('{FONTS}/manrope-700.woff2'); }}
@font-face {{ font-family: Inter; font-weight: 400; src: url('{FONTS}/inter-400.woff2'); }}
@font-face {{ font-family: Inter; font-weight: 500; src: url('{FONTS}/inter-500.woff2'); }}
@font-face {{ font-family: Inter; font-weight: 600; src: url('{FONTS}/inter-600.woff2'); }}
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
html, body {{ margin: 0; background: #0c1324; color: #dce1fb; font-family: Inter, sans-serif; font-size: 10.5pt; }}
.page {{ width: 210mm; height: 297mm; padding: 16mm 15mm 18mm; position: relative; overflow: hidden; page-break-after: always; background: #0c1324; }}
.ph {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 7mm; }}
.brand {{ font-family: Manrope; font-weight: 700; letter-spacing: .18em; color: #4edea3; font-size: 11pt; }}
.kicker {{ font-size: 7.5pt; letter-spacing: .12em; text-transform: uppercase; color: #bbcabf; }}
h1, h2, h3, h4 {{ font-family: Manrope; margin: 0; letter-spacing: -.02em; }}
h2 {{ font-size: 22pt; font-weight: 700; margin-bottom: 6mm; color: #eef1ff; }}
h3.sub {{ font-size: 12pt; color: #d0bcff; margin: 5mm 0 3mm; }}
h3.group {{ font-size: 11pt; color: #4edea3; margin: 4mm 0 2mm; }}
h4 {{ font-size: 11pt; margin-bottom: 2mm; color: #eef1ff; }}
p {{ margin: 0 0 2mm; line-height: 1.5; color: #c9cfe6; }}
.intro {{ font-size: 11pt; margin: 2mm 0 5mm; }}
code {{ font-family: ui-monospace, Menlo, monospace; font-size: 8.5pt; color: #4edea3; background: #151b2d; padding: 0 3px; border-radius: 3px; }}
.pf {{ position: absolute; bottom: 9mm; left: 15mm; right: 15mm; display: flex; justify-content: space-between; font-size: 7.5pt; color: #6f7894; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6mm; }}
.three {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4mm; margin-top: 5mm; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; }}
.grid3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 3.5mm; }}
.card {{ background: #151b2d; border-radius: 8px; padding: 4.5mm; border-left: 3px solid #3c4a42; }}
.card p {{ font-size: 9.5pt; margin: 0; }}
.grid3 .card p {{ font-size: 8.8pt; }}
.card.bad {{ border-left-color: #EE9170; }} .card.bad h4 {{ color: #EE9170; }}
.card.warn {{ border-left-color: #f59e0b; }} .card.warn h4 {{ color: #f5b54a; }}
.card.ok {{ border-left-color: #4edea3; }} .card.ok h4 {{ color: #4edea3; }}
.card.dead {{ border-left-color: #5b6478; }}
.card.violet {{ border-left-color: #d0bcff; }} .card.violet h4 {{ color: #d0bcff; }}
ul.clean {{ padding-left: 4mm; margin: 0; }} ul.clean li {{ margin-bottom: 2.6mm; line-height: 1.5; color: #c9cfe6; }}
ul.clean li b {{ color: #eef1ff; }} ul.small li {{ font-size: 9.5pt; margin-bottom: 1.8mm; }}
.charts {{ margin-top: 6mm; }} .chart {{ width: 100%; }}
.svg-label {{ font: 500 15px Inter; fill: #c9cfe6; }} .svg-num {{ font: 700 16px Manrope; fill: #eef1ff; }}
.svg-big {{ font: 700 34px Manrope; fill: #eef1ff; }} .svg-small {{ font: 400 11px Inter; fill: #bbcabf; }}
table.inv {{ width: 100%; border-collapse: collapse; font-size: 8.1pt; }}
table.inv th {{ text-align: left; font-weight: 600; color: #bbcabf; font-size: 7pt; text-transform: uppercase; letter-spacing: .06em; padding: 1.6mm 1.5mm; background: #151b2d; }}
table.inv td {{ padding: 1.6mm 1.5mm; border-bottom: 1px solid rgba(60,74,66,.35); color: #c9cfe6; vertical-align: top; }}
td.c-set {{ color: #eef1ff; font-weight: 500; width: 27%; }} td.c-level {{ color: #4edea3; }}
.matrix {{ font-size: 10pt; }} .matrix td {{ padding: 3mm 2mm; }}
.pill {{ display: inline-block; padding: .5mm 2mm; border-radius: 10px; font-size: 7pt; font-weight: 600; white-space: nowrap; }}
.matrix .pill {{ font-size: 8.5pt; }}
.s-ok {{ background: rgba(78,222,163,.15); color: #4edea3; }} .s-warn {{ background: rgba(245,158,11,.15); color: #f5b54a; }}
.s-bad {{ background: rgba(238,145,112,.18); color: #EE9170; }} .s-dead {{ background: rgba(91,100,120,.3); color: #aab2c8; }}
.s-missing {{ background: rgba(208,188,255,.15); color: #d0bcff; }}
.diagram {{ width: 100%; margin: 2mm 0 3mm; }}
.diagram .node rect, .diagram .ent rect {{ fill: #191f31; stroke-width: 2; }}
.node.db rect {{ stroke: #4edea3; }} .node.file rect {{ stroke: #f59e0b; }} .node.el rect {{ stroke: #d0bcff; }}
.node.env rect {{ stroke: #7dd3fc; }} .node.code rect {{ stroke: #EE9170; }} .node.workos rect {{ stroke: #bbcabf; }}
.ent rect {{ stroke: #3c4a42; }} .ent.new rect {{ stroke: #4edea3; stroke-dasharray: 5 3; }}
.nt {{ font: 700 14px Manrope; fill: #eef1ff; text-anchor: middle; }} .ns {{ font: 400 11px Inter; fill: #bbcabf; text-anchor: middle; }}
.nt.left, .ns.left {{ text-anchor: start; }} .nt.dark {{ fill: #003824; }}
.call circle {{ fill: #4edea3; }} .result rect {{ fill: #4edea3; }}
.tier rect {{ fill: #151b2d; stroke-width: 2; }} .t1 rect {{ stroke: #4edea3; }} .t2 rect {{ stroke: #7dd3fc; }} .t3 rect {{ stroke: #d0bcff; }}
.edge {{ stroke: #86948a; stroke-width: 1.6; fill: none; }} .edge.dashed {{ stroke-dasharray: 5 4; }}
.edge.green {{ stroke: #4edea3; stroke-width: 2; }} .edge.violet {{ stroke: #d0bcff; stroke-width: 2; }}
.pkg rect {{ fill: #151b2d; stroke-width: 2; }} .pkg.q > rect {{ stroke: #4edea3; }} .pkg.c > rect {{ stroke: #d0bcff; }}
.pkg .chip {{ fill: #191f31; stroke: #3c4a42; stroke-width: 1; }} .pkg .sect {{ fill: #191f31; stroke: #3c4a42; stroke-width: 1; }}
.pkg .sect.a {{ stroke: #d0bcff; stroke-dasharray: 4 3; }}
.journey {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin-bottom: 5mm; }}
.step {{ background: #151b2d; border-radius: 8px; padding: 4mm; border-top: 3px solid #4edea3; }}
.step.bad {{ border-top-color: #EE9170; }} .step p {{ font-size: 9pt; }}
.sn {{ display: inline-block; width: 7mm; height: 7mm; border-radius: 50%; background: #4edea3; color: #003824; font: 700 10pt Manrope; text-align: center; line-height: 7mm; margin-bottom: 2mm; }}
.step.bad .sn {{ background: #EE9170; }}
.roadmap {{ display: grid; gap: 2.6mm; }}
.phase {{ display: grid; grid-template-columns: 11mm 1fr; gap: 3mm; background: #151b2d; border-radius: 8px; padding: 3.2mm; align-items: center; }}
.phase h4 {{ margin-bottom: .8mm; }} .phase p {{ margin: 0; font-size: 9.3pt; }}
.pn {{ width: 10mm; height: 10mm; border-radius: 8px; background: #191f31; border: 2px solid #d0bcff; color: #d0bcff; font: 700 13pt Manrope; text-align: center; line-height: 9mm; }}
.p0 .pn {{ background: #4edea3; border-color: #4edea3; color: #003824; }} .p6 .pn {{ border-color: #4edea3; color: #4edea3; }}
.cover {{ background: radial-gradient(circle at 85% 15%, rgba(78,222,163,.16), transparent 45%), radial-gradient(circle at 10% 90%, rgba(208,188,255,.12), transparent 45%), #0c1324; display: flex; flex-direction: column; justify-content: space-between; padding: 22mm 18mm; }}
.cover-top {{ display: flex; align-items: center; gap: 4mm; }} .brand.big {{ font-size: 26pt; }}
.dot {{ width: 4mm; height: 4mm; border-radius: 50%; background: #4edea3; box-shadow: 0 0 18px #4edea3; }}
.eyebrow {{ font-size: 9pt; letter-spacing: .2em; color: #bbcabf; margin-bottom: 5mm; }}
.cover h1 {{ font-size: 40pt; line-height: 1.05; color: #eef1ff; margin-bottom: 7mm; }}
.cover .lead {{ font-size: 13pt; max-width: 150mm; color: #c9cfe6; }}
.cover-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 5mm; }}
.cover-stats div {{ background: rgba(21,27,45,.85); border-radius: 10px; padding: 6mm; }}
.cover-stats .num {{ display: block; font: 700 32pt Manrope; color: #4edea3; }} .cover-stats .lbl {{ font-size: 9.5pt; color: #bbcabf; }}
.cover-foot {{ font-size: 8.5pt; color: #6f7894; }}
</style></head><body>"""


if __name__ == "__main__":
    out = HERE / "report.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out} ({TOTAL} settings; by place {dict(BY_PLACE)}; by status {dict(BY_STATUS)})")
