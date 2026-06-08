# Qora · Design System

> Manual de marca y sistema de diseño canónico de **Qora**.
> Este documento es la fuente de verdad para cualquier entorno de desarrollo (IDE, Claude Code, Cursor, v0, Figma) que vaya a producir interfaces, piezas o copy para la marca.
> Si está acá: es la regla. Si no está acá: **no es Qora**.

**Versión:** 2026.05 · Buenos Aires
**Idioma de la marca:** Español (es-AR)
**Estado:** Documento vivo · sujeto a iteración controlada

---

## 0 · Quién es Qora

| Campo | Valor |
|---|---|
| Nombre | **Qora** |
| Categoría | Plataforma B2B de agentes de voz IA |
| Promesa | "Memoria que opera sobre cada conversación." |
| Tagline | Agentes de voz que llaman, conversan y no olvidan. |
| Tono de voz | Editorial, calmo, técnico sin ser frío. Bonito sin gritar. |
| Idioma producto | Español rioplatense, vos (no tú). |
| Dominio | qora.ai |
| Email contacto | brand@qora.ai · hola@qora.ai |

### Principios fundacionales (no negociables)

1. **Calma sobre estridencia.** Una idea por bloque. Aire. Silencio. Pieza editorial antes que demo de feria.
2. **El teal es la firma.** Un único color saturado carga toda la personalidad. Cuando hay segunda voz, es coral, y aparece con cuentagotas.
3. **La tipografía hace el peso.** Fredoka no necesita ornamento. Bien usada, alcanza.

---

## 1 · Color — Sistema canónico

La paleta se construye sobre **tres planos**:
- Una **familia clara y fría** (la página).
- Un **teal signature** (la firma).
- Un **coral complementario** que aparece con cuentagotas.

### 1.1 — Tokens primarios

| Token | Hex | RGB | Rol |
|---|---|---|---|
| `--teal` | `#1A8B7A` | `26 · 139 · 122` | **Signature.** CTA, focus, estados activos, marca visible sobre claro. |
| `--teal-bright` | `#2EC9B0` | `46 · 201 · 176` | Teal sobre fondo **oscuro** (producto/dark mode). |
| `--teal-deep` | `#0E4E45` | `14 · 78 · 69` | Profundidad, sombras de marca, hover de teal sobre claro. |
| `--teal-navy` | `#031A17` | `3 · 26 · 23` | Sombra extrema, fondos premium muy oscuros. |
| `--pearl` | `#F2F4F3` | `242 · 244 · 243` | **Base página** (off-white frío). |
| `--paper` | `#FFFFFF` | `255 · 255 · 255` | **Papel.** Superficies elevadas, cards en claro. |
| `--carbon` | `#0E1217` | `14 · 18 · 23` | **Tinta.** Texto sobre claro · base página en dark. |
| `--onyx` | `#0A0B0E` | `10 · 11 · 14` | Página dark mode (producto). |
| `--coral` | `#E0764F` | `224 · 118 · 79` | **Acento complementario.** Cuentagotas. Máx 1 por pieza. |
| `--coral-soft` | `#FBE2D6` | `251 · 226 · 214` | Coral suave (salmón) — backgrounds de cita, alertas tenues. |

### 1.2 — Neutras (superficies)

| Token | Hex | Rol |
|---|---|---|
| `--mist` | `#E8ECEB` | Superficie reposada: cards, secciones reposadas. |
| `--smoke` | `#D6DAD9` | Superficie deprimida: inputs, footers, fondos hundidos. |
| `--surface-dark` | `#14171D` | Card en dark mode. |
| `--surface-dark-2` | `#1A1E26` | Card elevado en dark mode. |

### 1.3 — Líneas y opacidades

```css
/* Light */
--line:   rgba(14,18,23,0.08);
--line-2: rgba(14,18,23,0.14);
--line-3: rgba(14,18,23,0.24);

/* Dark */
--line-dark:   rgba(255,255,255,0.06);
--line-dark-2: rgba(255,255,255,0.10);
--line-dark-3: rgba(255,255,255,0.16);

/* Teal con opacidad — para faints, glows, badges */
--teal-faint: rgba(26,139,122,0.08);
--teal-line:  rgba(26,139,122,0.28);

/* Coral con opacidad */
--coral-faint: rgba(224,118,79,0.09);
--coral-line:  rgba(224,118,79,0.30);
```

### 1.4 — Texto (jerarquía de ink)

| Token | Light hex | Dark hex | Uso |
|---|---|---|---|
| `--ink` | `#0E1217` | `#E8ECEB` | Texto principal, títulos. |
| `--ink-2` | `#44474D` | `#A4A39C` | Texto secundario, párrafos. |
| `--ink-3` | `#767880` | `#65645E` | Texto terciario, meta. |
| `--ink-4` | `#B5B7BC` | `#3A3A36` | Disabled, ghost. |

### 1.5 — Reglas de uso (críticas)

✅ **Permitido**
- Página por defecto: **Pearl `#F2F4F3`** o **Papel `#FFFFFF`**.
- Producto (dashboard, panel): **Onyx `#0A0B0E`** o **Carbón `#0E1217`**.
- Teal es siempre la única voz saturada del sistema.
- Coral aparece como interrupción intencional — máx **1 vez por pieza**.

🚫 **Prohibido**
- **Cualquier color "tibio"** en fondos: cremas, beige, off-whites cálidos (`#F6F5F0`, `#F1EADC`, `#E8ECEB` con undertone cálido, `#d9d7cf`, etc.). Si tiene tonalidad cálida, **no es Qora**.
- **Verde "startup"** (`#3FDBA0`, `#1F9D6F`, lima, neón). Qora superó esa paleta.
- **Combinar coral con cualquier otro cálido** (ámbar, mostaza, oro, rojos). Si aparece coral, no aparece ningún otro cálido.
- **Gradientes en el wordmark o la Q.** Nunca.
- **Sombras coloreadas saturadas.** Las sombras son siempre carbón con opacidad baja.
- **Más de un color saturado por pieza.** Teal o coral, no los dos protagonistas.

### 1.6 — Reglas del coral (regla del cuentagotas)

El coral es el opuesto cromático del teal. Por eso tiene fuerza. Por eso se usa muy poco.

**Casos válidos** (máx 1 por pieza):
- Cita o testimonio humano dentro de pieza editorial.
- Dato clímax de un caso de uso ("interés subió 30 → 72").
- Señal de urgencia o alerta dentro del producto.

**Test rápido:** si en una sola pieza el coral aparece dos veces, está mal usado.

---

## 2 · Logo y marca visual

### 2.1 — La marca **es** la palabra

El logo de Qora es su **wordmark** compuesto en Fredoka — Q mayúscula, "ora" minúscula, tracking justo.

**No hay isotipo separado. No hay símbolo. No hay marca dentro de un círculo.**

```
Tipografía: Fredoka
Peso: 500 (Medium)
Caja: Q mayúscula + "ora" minúscula — siempre así
Tracking: -0.04em en uso general
         -0.055em en escalas grandes (> 80px)
Color por defecto: --carbon (#0E1217)
```

### 2.2 — La Q sola (ícono de bolsillo)

Solo cuando el wordmark no entra con dignidad.

| Tamaño contenedor | Uso |
|---|---|
| ≤ 16 px | Favicon, app icon |
| 24–32 px | Avatar de cuenta, badge |
| 40 px + | Sellos, marcas de agua, recurso gráfico |
| ≥ 200 px de ancho | **Usar wordmark completo, no la Q** |

### 2.3 — Variantes cromáticas autorizadas

Solo estas cuatro. **No hay más.**

| Variante | Color glyph | Sobre fondo | Uso |
|---|---|---|---|
| **Carbón / Papel** | `#0E1217` | `#FFFFFF` o `#F2F4F3` | **Principal.** Por defecto siempre. |
| **Teal Qora** | `#1A8B7A` | `#F2F4F3` o `#FFFFFF` | Firma — cabezales, sellos, watermark. |
| **Teal brillante** | `#2EC9B0` | `#0A0B0E` o `#0E1217` | Dark mode — producto, panel. |
| **Coral** | `#E0764F` | `#F2F4F3` | Cuentagotas — máx 1 por pieza. |

### 2.4 — Área de seguridad

```
x = altura de la "o" (x-height del wordmark)
Margen libre en todas direcciones ≥ x
```

Nada (texto, imagen, otro logo) puede invadir esa zona.

### 2.5 — Tamaños mínimos

| Contexto | Mínimo |
|---|---|
| Web | **72 px** de ancho |
| Header | **120 px** de ancho |
| Impreso | **15 mm** de ancho |

Bajo el mínimo: usar la Q sola.

### 2.6 — Usos incorrectos (don'ts)

❌ Reemplazar la tipografía (Inter, system fonts, otra rounded).
❌ Estirar, deformar, condensar, expandir.
❌ Todo en mayúsculas (`QORA`).
❌ Todo en minúsculas (`qora`).
❌ Aplicar degradados al wordmark o a la Q.
❌ Rotar, inclinar, transformar perspectiva.
❌ Colocarlo sobre fondos que pierdan legibilidad (gradientes saturados, fotos cargadas sin scrim).
❌ Agregar contornos, sombras decorativas, glow al wordmark.
❌ Acompañarlo de orbes, círculos contenedores o cualquier "isotipo" inventado.

---

## 3 · Tipografía

### 3.1 — Familias autorizadas (solo estas tres)

| Rol | Familia | Fallback | Cuándo |
|---|---|---|---|
| **Display / Titulares / Marca** | **Fredoka** | `ui-rounded, system-ui, sans-serif` | Wordmark, H1–H3, números clímax. |
| **Cuerpo / Lectura / UI** | **Inter** | `system-ui, sans-serif` | Párrafos, descripciones, interfaz del producto. |
| **Mono / Etiquetas / Técnica** | **JetBrains Mono** | `ui-monospace, monospace` | Eyebrows, métricas, código, identificadores. |

**No se agregan tipografías adicionales.** Ni Roboto, ni Arial, ni Helvetica, ni Manrope, ni Geist, ni Space Grotesk, ni Fraunces, ni Plus Jakarta.

### 3.2 — Pesos disponibles

| Familia | Pesos |
|---|---|
| Fredoka | 300, 400, **500** (default), 600, 700 |
| Inter | 300, **400** (default), 500, 600, 700 |
| JetBrains Mono | 400, **500** (default), 600 |

### 3.3 — Escala tipográfica canónica

| Token | Familia · peso | Tamaño | Tracking | LH | Uso |
|---|---|---|---|---|---|
| `--t-h1` | Fredoka 500 | `clamp(48px, 7.2vw, 96px)` | `-0.04em` | `1.00` | Hero, una vez por pieza. |
| `--t-h2` | Fredoka 500 | `clamp(40px, 5.2vw, 72px)` | `-0.03em` | `1.05` | Apertura de sección. |
| `--t-h3` | Fredoka 500 | `clamp(24px, 2.4vw, 34px)` | `-0.025em` | `1.15` | Subtítulos. |
| `--t-h4` | Fredoka 500 | `18px` | `-0.015em` | `1.3` | Sub-subtítulos. |
| `--t-lead` | Inter 400 | `clamp(18px, 1.45vw, 22px)` | `0` | `1.5` | Bajada de sección. |
| `--t-body` | Inter 400 | `16px` | `0` | `1.6` | Cuerpo general. |
| `--t-small` | Inter 400 | `14px` | `0` | `1.55` | Captions, meta. |
| `--t-mono` | JetBrains Mono 500 | `11px` | `+0.20em uppercase` | `1.0` | Eyebrows, etiquetas. |
| `--t-mono-lg` | JetBrains Mono 500 | `14px` | `+0.18em uppercase` | `1.0` | Eyebrows grandes. |

### 3.4 — Patrón "eyebrow" (uso estricto)

```
Familia: JetBrains Mono · 500 · 11px
Transform: uppercase
Letter-spacing: +0.20em
Color: --teal (en contextos donde marca firma) | --ink-3 (neutral)
Precedido por: línea horizontal 18px × 1px de currentColor
```

Ejemplo HTML:
```html
<span class="eyebrow">─ Lo que lo hace distinto</span>
```

### 3.5 — Reglas de uso tipográfico

✅ **Permitido**
- `text-wrap: balance` en titulares y `text-wrap: pretty` en párrafos.
- Tracking apretado en titulares grandes (-0.025em a -0.055em).
- `em` con `font-style: normal` para énfasis cromático en H2: `<h2>El teal manda. <em>El resto acompaña.</em></h2>`.

🚫 **Prohibido**
- Combinar más de **3 familias** en una pieza (Fredoka + Inter + JetBrains Mono y nada más).
- Usar Fredoka para body copy (es de display).
- Usar Inter en titulares hero (rompe la voz de marca).
- Itálicas reales (`font-style: italic`). Para énfasis: color, peso, o caja, nunca itálicas.
- Subrayados como énfasis. Solo en links.
- Texto **sub-24px** en slides de presentación.
- Texto **sub-12pt** en print.

---

## 4 · Espaciado, forma y elevación

### 4.1 — Radius (border-radius)

| Token | Valor | Uso |
|---|---|---|
| `--r-sm` | `6px` | Chips, tags pequeños. |
| `--r-md` | `12px` | Botones, inputs, tarjetas internas. |
| `--r-lg` | `20px` | Cards, paneles. |
| `--r-xl` | `32px` | Hero containers, frames grandes. |
| `--r-full` | `999px` | Pills, badges, avatars. |

### 4.2 — Container & padding

```css
--maxw: 1240px;
--pad:  clamp(24px, 5vw, 72px);   /* horizontal page padding */

/* Section vertical padding */
section            { padding: 140px var(--pad); }
section.tight      { padding: 96px var(--pad); }
```

### 4.3 — Sombras

**Una sola escala. Cero sombras coloreadas.**

```css
--shadow-sm: 0 1px 0 var(--line);
--shadow-md: 0 12px 28px rgba(14,18,23,0.06);
--shadow-lg: 0 24px 60px -45px rgba(14,18,23,0.30);
--shadow-xl: 0 30px 70px -40px rgba(14,18,23,0.35);
```

### 4.4 — Grid

- **Flex/grid con `gap`** siempre. Nunca márgenes encadenados entre hermanos.
- Densidad cómoda: gap `16–24px` para cards en grid, `12px` para chips.
- Hit-targets mínimos: **44 × 44 px** en mobile.

---

## 5 · Componentes (especificaciones canónicas)

### 5.1 — Botón sólido (CTA primario)

```css
background: var(--teal);          /* o --teal-bright en dark mode */
color: #ECFAF3;
font: 500 14px/1 'Inter', sans-serif;
padding: 12px 22px;
border-radius: var(--r-full);
border: none;
transition: all .25s cubic-bezier(.4,0,.2,1);

/* hover */
background: var(--teal-deep);
transform: translateY(-1px);
```

### 5.2 — Botón ghost (CTA secundario)

```css
background: transparent;
color: var(--ink-2);
border: 1px solid var(--line-2);
border-radius: var(--r-full);
padding: 12px 22px;
font: 500 14px/1 'Inter', sans-serif;

/* hover */
color: var(--ink);
border-color: var(--line-3);
background: var(--surface-2);
```

### 5.3 — Card (estándar)

```css
background: var(--paper);                /* #FFFFFF en claro */
border: 1px solid var(--line);
border-radius: var(--r-lg);
padding: 28px;
box-shadow: var(--shadow-md);
```

### 5.4 — Badge / Pill teal

```css
background: var(--teal-faint);
color: var(--teal);
border: 1px solid var(--teal-line);
border-radius: var(--r-full);
padding: 5px 11px;
font: 500 11px/1 'JetBrains Mono', monospace;
letter-spacing: 0.20em;
text-transform: uppercase;
```

### 5.5 — Input

```css
background: var(--paper);
border: 1px solid var(--line-2);
border-radius: var(--r-md);
padding: 12px 16px;
font: 400 16px/1.5 'Inter', sans-serif;
color: var(--ink);

/* focus */
border-color: var(--teal);
box-shadow: 0 0 0 3px var(--teal-faint);
outline: none;
```

### 5.6 — Status dots (en panel de leads)

| Estado | Color fondo | Color texto | Borde |
|---|---|---|---|
| Cotizado / OK | `rgba(46,201,176,0.10)` | `#2EC9B0` | `rgba(46,201,176,0.28)` |
| Interesado | `rgba(255,184,119,0.10)` | `#FFB877` | `rgba(255,184,119,0.28)` |
| Nuevo / Muted | `rgba(255,255,255,0.04)` | `rgba(232,236,235,0.5)` | `rgba(255,255,255,0.10)` |
| Urgente / Crítico | `rgba(224,118,79,0.10)` | `#E0764F` | `rgba(224,118,79,0.30)` |

---

## 6 · Patrones de superficie

### 6.1 — Marca en CLARO (default)

Papelería, slides, landing, brand pieces.
```
Background: #F2F4F3 (Pearl) o #FFFFFF (Paper)
Text: #0E1217 (Carbón)
Brand: #1A8B7A (Teal Qora)
Accent: #E0764F (Coral, cuentagotas)
```

### 6.2 — Producto en OSCURO

Panel, dashboard, dev tools.
```
Background: #0A0B0E (Onyx)
Surface:    #14171D
Surface 2:  #1A1E26
Text:       #E8ECEB
Brand:      #2EC9B0 (Teal brillante)
Lines:      rgba(255,255,255,0.06–0.16)
```

### 6.3 — Letterbox / chrome de presentaciones

```
Body / fuera del canvas: #0E1217 (Carbón)
Canvas slide: #FFFFFF (Papel) o #F2F4F3 (Pearl)
```

Nunca **tibio** afuera del canvas. Nunca crema. Nunca beige.

---

## 7 · Motion

| Pattern | Duración / curva | Uso |
|---|---|---|
| Reveal enter | `opacity 0→1, translateY(18px→0)`, `0.8s cubic-bezier(.2,.8,.2,1)` | Scroll reveal de bloques. |
| Reveal delays | `0s / 0.08s / 0.16s / 0.24s` | Cascada de elementos. |
| Interactive transition | `all .25s cubic-bezier(.4,0,.2,1)` | Hover, focus de botones/inputs. |
| Theme toggle | `.35s ease` en `background-color` y `color`. | Cambio claro/oscuro. |
| Waveform (transcript) | `1.1s ease-in-out infinite`, alternancia de altura. | Indicador de voz activa. |

**Reducir movimiento:** respetar `prefers-reduced-motion`. Reveals se vuelven instantáneos; animaciones decorativas se pausan.

---

## 8 · Voz y copy

### 8.1 — Reglas de escritura

- **Vos**, no tú. (Producto en es-AR.)
- Oraciones cortas. Una idea por oración.
- Verbos concretos. Nada de "potenciar", "revolucionar", "sinergizar".
- No usar adjetivos que prometan sin sustentar. ("Increíble", "mágico", "el mejor".)
- Números reales cuando hay datos reales. Si no hay dato, no inventar.
- Sin emojis en interfaz, marca o copy comercial. Cero. (Emojis solo en chats internos.)

### 8.2 — Tonos por contexto

| Contexto | Tono |
|---|---|
| Marketing / landing | Editorial, contemplativo. "Memoria que opera sobre cada conversación." |
| Producto (UI) | Directo, breve, funcional. "Iniciar campaña", "Volver a llamar a Marina". |
| Estados de éxito | Neutros. No "¡Genial!". Solo confirmación. |
| Estados de error | Honestos. "No se pudo guardar el contacto." Nunca "Oops" o "Ups". |
| Pitch / deck | Narrativo, escena por escena. Una idea por slide. |

### 8.3 — Palabras de la marca (vocabulario interno)

| Decir | Evitar |
|---|---|
| Agente de voz | Bot, chatbot, IA |
| Memoria | Knowledge base, contexto |
| Capa operativa | Layer, stack |
| Conversación | Interacción, intercambio |
| Recuerda · Entiende · Actúa | Smart, inteligente, AI-powered |

---

## 9 · Iconografía

- **Iconos:** trazo lineal `1.5px`, esquinas redondeadas `2px`, sin relleno.
- Tamaño base **20 × 20 px** sobre grid de `24 × 24`.
- **Nunca SVGs ilustrados a mano** (humanos, edificios, productos). Si la pieza pide imagen, usar **fotografía real** o **placeholder rayado** con leyenda monospace.

### 9.1 — Placeholder de imagen (cuando no hay foto)

```html
<image-slot id="..." shape="rounded" radius="18" placeholder="Arrastrá una foto — descripción específica">
</image-slot>
```

Stroke en `var(--line-2)`, fondo `var(--surface-2)`, label en JetBrains Mono 11px uppercase.

---

## 10 · Tokens completos (CSS variables — copy-paste ready)

```css
:root {
  /* ─── canvas (light) */
  --bg:        #F2F4F3;   /* Pearl */
  --bg-2:      #FFFFFF;   /* Paper */
  --surface:   #FFFFFF;
  --surface-2: #EAECEB;   /* Mist */
  --surface-3: #D6DAD9;   /* Smoke */
  --line:      rgba(14,18,23,0.08);
  --line-2:    rgba(14,18,23,0.14);
  --line-3:    rgba(14,18,23,0.24);

  /* ─── ink */
  --ink:       #0E1217;   /* Carbón */
  --ink-2:     #44474D;
  --ink-3:     #767880;
  --ink-4:     #B5B7BC;

  /* ─── brand */
  --teal:        #1A8B7A;
  --teal-deep:   #0E4E45;
  --teal-bright: #2EC9B0;
  --teal-navy:   #031A17;
  --teal-faint:  rgba(26,139,122,0.08);
  --teal-line:   rgba(26,139,122,0.28);

  /* ─── accent (cuentagotas) */
  --coral:       #E0764F;
  --coral-soft:  #FBE2D6;
  --coral-faint: rgba(224,118,79,0.09);
  --coral-line:  rgba(224,118,79,0.30);

  /* ─── shape */
  --r-sm:   6px;
  --r-md:  12px;
  --r-lg:  20px;
  --r-xl:  32px;
  --r-full: 999px;

  /* ─── layout */
  --maxw: 1240px;
  --pad:  clamp(24px, 5vw, 72px);

  /* ─── motion */
  --ease-out:    cubic-bezier(.2,.8,.2,1);
  --ease-inout:  cubic-bezier(.4,0,.2,1);

  /* ─── shadows */
  --shadow-sm: 0 1px 0 var(--line);
  --shadow-md: 0 12px 28px rgba(14,18,23,0.06);
  --shadow-lg: 0 24px 60px -45px rgba(14,18,23,0.30);
  --shadow-xl: 0 30px 70px -40px rgba(14,18,23,0.35);
}

/* ─── dark mode (producto) */
[data-theme='dark'] {
  --bg:        #0A0B0E;   /* Onyx */
  --bg-2:      #0E1217;   /* Carbón */
  --surface:   #14171D;
  --surface-2: #1A1E26;
  --surface-3: #232830;
  --line:      rgba(255,255,255,0.06);
  --line-2:    rgba(255,255,255,0.10);
  --line-3:    rgba(255,255,255,0.16);

  --ink:       #E8ECEB;
  --ink-2:     #A4A39C;
  --ink-3:     #65645E;
  --ink-4:     #3A3A36;

  --teal:        #2EC9B0;  /* en dark mode el teal vivo es el brillante */
  --teal-deep:   #1A8B7A;
  --teal-faint:  rgba(46,201,176,0.08);
  --teal-line:   rgba(46,201,176,0.28);
}
```

---

## 11 · Fonts loader (HTML head)

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fredoka:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap">
```

---

## 12 · Favicon

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="#0E1217"/>
  <text x="16" y="22" text-anchor="middle"
        font-family="Fredoka, system-ui, sans-serif"
        font-weight="500" font-size="20"
        fill="#2EC9B0"
        letter-spacing="-0.04em">Q</text>
</svg>
```

Versiones alternativas autorizadas:
- Carbón sobre papel: `fill="#FFFFFF"` rect + `fill="#0E1217"` text.
- Teal sobre pearl: `fill="#F2F4F3"` rect + `fill="#1A8B7A"` text.

---

## 13 · Anti-patterns (lista explícita — no hacer)

Esta lista es la **frontera dura** del sistema. Si una pieza tiene cualquiera de esto, **no es Qora**.

### Color
1. ❌ Backgrounds tibios o crema (`#F6F5F0`, `#F1EADC`, `#D9D7CF`, `#FAF7F0`, cualquier off-white cálido).
2. ❌ Verdes "startup" (`#3FDBA0`, `#1F9D6F`, lima, neón, esmeralda eléctrica).
3. ❌ Más de un color saturado protagonista por pieza.
4. ❌ Coral acompañado de cualquier otro cálido (ámbar, oro, mostaza, rojos).
5. ❌ Gradientes saturados (excepto sombras sutiles de carbón con opacidad).
6. ❌ Sombras coloreadas (sombra teal, sombra coral). Sombras siempre carbón.

### Tipografía
7. ❌ Cualquier tipografía que no sea Fredoka / Inter / JetBrains Mono.
8. ❌ Fredoka como body copy.
9. ❌ Inter como hero titular.
10. ❌ Itálicas reales.
11. ❌ Subrayados como énfasis.

### Logo
12. ❌ Cualquier isotipo, símbolo, marca dentro de círculo o contenedor decorativo.
13. ❌ Wordmark en mayúsculas o todo minúsculas.
14. ❌ Gradiente en wordmark o en la Q.
15. ❌ Glow / blur / sombra coloreada en el wordmark.

### Layout
16. ❌ Texto sub-24px en slides 1920×1080.
17. ❌ Texto sub-12pt en print.
18. ❌ Botones / hit-targets sub-44px en mobile.
19. ❌ Inline flow con whitespace para layout de elementos UI (siempre flex/grid + gap).

### Tropos prohibidos
20. ❌ Emojis en marca, UI o copy comercial.
21. ❌ Tarjetas con borde-izquierdo de color como accent.
22. ❌ "Bots", "chatbots", "IA mágica", "revolucionario", "potenciar".
23. ❌ SVG ilustrativos hechos a mano (personas, productos, edificios).
24. ❌ Patrones de gradient mesh / aurora / orbes flotantes.
25. ❌ "Glassmorphism" agresivo (blur > 14px + transparencia > 40%).

---

## 14 · Checklist pre-publicación

Antes de aprobar cualquier pieza (slide, landing, mail, post, screen):

- [ ] Fondo es Pearl, Papel u Onyx. Cero tibios.
- [ ] Un solo color saturado protagonista (teal). Si hay coral, aparece una vez.
- [ ] Wordmark en una de las 4 variantes autorizadas.
- [ ] Tipografía: solo Fredoka / Inter / JetBrains Mono.
- [ ] Texto cumple mínimos de tamaño (24px slide, 12pt print, 44px hit-target).
- [ ] Sin emojis, sin gradientes saturados, sin sombras coloreadas.
- [ ] Copy: vos no tú, sin "bot", sin "increíble".
- [ ] Si hay imagen: foto real o placeholder rayado. Sin SVG ilustrativo a mano.
- [ ] Eyebrow (si aparece) sigue patrón canónico: JBM 500 11px +0.20em uppercase, precedido por línea.

---

## 15 · Versionado de este documento

| Versión | Fecha | Cambio |
|---|---|---|
| 2026.05 | 2026-06-02 | Sistema Teal & Carbón canónico. Eliminadas paletas verde-startup y tibios. Q con 4 variantes cromáticas autorizadas. |

**Mantenido por:** Equipo de marca · Qora · `brand@qora.ai`
