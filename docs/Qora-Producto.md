# Qora — Documento de Producto (Fuente de Verdad)

> **Qué es este documento.** Es la descripción completa y objetiva de Qora tal como existe hoy. No es un plan de negocio ni una pieza de venta. Es la "biblioteca" del producto: la base desde la cual el equipo web arma el sitio, marketing genera contenido, ventas prepara presentaciones, y cualquier desarrollador nuevo entiende Qora desde adentro.
>
> **Regla de oro.** Todo lo que está acá es factual y verificado contra el código. Cuando algo no está implementado, se dice explícitamente. No se exagera ninguna capacidad ni se la presenta como superior a la competencia. Si una sección no distingue entre "implementado" y "planificado", es un error y hay que corregirlo.
>
> **Fecha del relevamiento:** mayo 2026. Qora es un producto en evolución; este documento describe el estado actual, que puede cambiar.

---

## Índice

1. [Resumen en una página](#1-resumen-en-una-página)
2. [Qué problema resuelve Qora](#2-qué-problema-resuelve-qora) · [El foco: outbound, no inbound](#el-foco-salida-outbound-no-entrada)
3. [Qué es Qora exactamente](#3-qué-es-qora-exactamente) · [3.5 Ecosistema inter-agéntico](#35-qora-como-ecosistema-inter-agéntico)
4. [Cómo funciona una llamada, paso a paso](#4-cómo-funciona-una-llamada-paso-a-paso)
5. [El cerebro: análisis post-llamada](#5-el-cerebro-análisis-post-llamada)
6. [La memoria: por qué el agente "recuerda"](#6-la-memoria-por-qué-el-agente-recuerda)
7. [Conocimiento dinámico: el sistema de skills](#7-conocimiento-dinámico-el-sistema-de-skills)
8. [El agendador de llamadas](#8-el-agendador-de-llamadas)
9. [Integración con CRM](#9-integración-con-crm)
10. [El panel: qué ve el cliente y el administrador](#10-el-panel-qué-ve-el-cliente-y-el-administrador)
11. [Multi-cliente: cómo se aíslan los datos](#11-multi-cliente-cómo-se-aíslan-los-datos)
12. [Tecnología que usa Qora](#12-tecnología-que-usa-qora)
13. [Qué datos guarda Qora](#13-qué-datos-guarda-qora)
14. [Estado actual: qué funciona y qué todavía no](#14-estado-actual-qué-funciona-y-qué-todavía-no)
15. [El cliente piloto: Quintana Seguros](#15-el-cliente-piloto-quintana-seguros)
16. [Glosario](#16-glosario)

---

## 1. Resumen en una página

**Qora es una plataforma de software que permite reemplazar a los agentes de un call center por agentes de inteligencia artificial que hablan por voz.** En lugar de contratar personas para llamar a una lista de clientes potenciales, una empresa configura un "agente" de Qora que conversa por voz, suena natural, conoce el producto que vende y registra el resultado de cada conversación.

La idea central no es solo "una IA que habla". Es **la capa de operación de call center que se construye encima de la voz**: quién llamar, cuándo, cuántas veces, qué se dijo en cada conversación, qué objeciones aparecieron, qué nivel de interés mostró cada persona, y qué hay que hacer después con ese contacto.

**Dos definiciones que distinguen a Qora desde el primer minuto:**

- **Qora es un sistema inter-agéntico, no un agente suelto.** No se trata de "un bot". Qora es el **ecosistema donde varios agentes de IA trabajan** sobre los mismos leads: comparten un mismo cuerpo de conocimiento, una misma memoria de cada contacto y un mismo registro de lo que pasó. Un agente puede continuar el trabajo donde lo dejó otro, porque todos operan sobre el mismo sustrato de información. (El alcance exacto de esta colaboración hoy se detalla en la [sección 3.5](#35-qora-como-ecosistema-inter-agéntico).)

- **Qora está enfocado en HACER las llamadas, no en responderlas.** El foco del producto hoy es la **venta saliente (outbound)**: agentes que toman una lista de leads y los llaman para vender y dar seguimiento. No es un asistente reactivo que espera que alguien le escriba para responder un par de preguntas. La iniciativa es del agente: él conduce, pregunta, propone y cierra.

Hoy Qora está construido y funcionando como producto, con un cliente piloto real (una correduría de seguros argentina, **Quintana Seguros**). Tiene:

- Un agente de voz que conversa en español rioplatense.
- Un sistema que **recuerda conversaciones anteriores** con la misma persona.
- Un **análisis automático** de cada llamada que extrae interés, objeciones, problemas, compromisos y datos.
- Un **CRM** propio para ver leads, historial de llamadas, transcripciones y análisis.
- Un **panel de métricas y analítica**.
- Un **panel de administración** para crear clientes y agentes.
- Una **integración con CRM externo** (Airtable) en ambas direcciones.

**Lo más importante a entender desde el inicio:** hoy el canal de voz que funciona es **a través del navegador** (una persona habla con el agente desde una página web). **La llamada telefónica real a un número de teléfono todavía no está implementada.** El sistema agenda las llamadas que habría que hacer, pero todavía no las disca. Esto se detalla en la [sección 14](#14-estado-actual-qué-funciona-y-qué-todavía-no).

---

## 2. Qué problema resuelve Qora

### El problema de fondo

Un call center de salida (outbound) — el que llama a clientes potenciales para vender o hacer seguimiento — tiene problemas estructurales conocidos:

- **Las personas son caras y no escalan linealmente.** Duplicar la capacidad de llamadas implica duplicar el equipo, con todo lo que eso conlleva (contratación, capacitación, espacio, supervisión).
- **La calidad es inconsistente.** Un agente tiene días buenos y días malos, se cansa, improvisa, olvida lo que pasó en la llamada anterior con el mismo cliente.
- **La información se pierde.** Gran parte de lo que ocurre en una conversación (por qué el cliente dijo que no, qué le preocupaba, qué prometió el agente) no queda registrado de forma estructurada y aprovechable.
- **El seguimiento es manual y se cae.** Decidir a quién volver a llamar, cuándo y por qué depende de la disciplina de cada persona.

### Qué aborda Qora hoy

Qora trabaja sobre estos puntos de la siguiente manera concreta:

| Problema | Cómo lo aborda Qora hoy |
|----------|--------------------------|
| Costo y escala del equipo humano | Un agente de IA atiende la conversación; el costo es por minuto de conversación, no por empleado. |
| Inconsistencia de calidad | El agente sigue un guion configurado (prompt) que define cómo conduce la conversación y cómo maneja objeciones. |
| Pérdida de información | Cada llamada se transcribe y se analiza automáticamente en múltiples dimensiones estructuradas. |
| El agente "no recuerda" | Qora inyecta el historial de conversaciones previas con esa persona antes de cada llamada. |
| Seguimiento manual | Un motor de reglas decide la próxima acción para cada lead (volver a llamar, hacer seguimiento, cerrar) y agenda automáticamente. |

> **Aclaración honesta de alcance.** La frase "reemplaza al call center" describe la *intención* del producto y la dirección del roadmap. Hoy, en términos de lo que el software efectivamente hace, Qora **conduce y analiza conversaciones de voz y gestiona la operación de leads**, pero **la marcación telefónica saliente real aún no está conectada** (ver [sección 14](#14-estado-actual-qué-funciona-y-qué-todavía-no)).

### El foco: salida (outbound), no entrada

Es importante entender qué tipo de problema eligió resolver Qora, porque define todo el diseño del producto.

Existen dos grandes familias de agentes de voz:

- **Reactivos / de entrada (inbound):** esperan a que alguien los contacte (un cliente que llama o escribe) y responden preguntas. Son asistentes que reaccionan.
- **Proactivos / de salida (outbound):** son ellos los que inician el contacto. Toman una lista de leads y los llaman con un objetivo: vender, calificar, hacer seguimiento.

**Qora está enfocado, hoy y como decisión de producto, en el segundo caso: hacer las llamadas.** El agente no espera; conduce. Toda la maquinaria de Qora —la memoria entre llamadas, el agendamiento, el motor de próxima acción, el análisis de objeciones e interés— está construida alrededor de la idea de **una campaña de llamadas de venta que avanza en el tiempo**, no de un bot que contesta consultas puntuales. Esta distinción no es menor: es lo que justifica que Qora tenga agendador, memoria acumulada y decisión automática de seguimiento, cosas que un bot reactivo no necesita.

---

## 3. Qué es Qora exactamente

Qora es un **producto de software B2B** (lo usan empresas, no consumidores finales). Se compone de tres piezas que trabajan juntas:

### 3.1 El motor de conversación (backend)

Es el componente central. Funciona como un **"cerebro" que se conecta entre el proveedor de voz y el modelo de lenguaje**. Su trabajo es:

1. Recibir lo que dijo la persona (ya convertido de voz a texto).
2. Armar las instrucciones para la IA: quién es el agente, a quién está llamando, qué pasó en llamadas anteriores, qué conocimiento tiene disponible.
3. Pedirle la respuesta a un modelo de lenguaje (GPT-4o de OpenAI).
4. Devolver esa respuesta para que se convierta en voz.
5. Guardar todo lo que ocurrió y analizarlo cuando la llamada termina.

Técnicamente, Qora actúa como un **"LLM personalizado"** para la plataforma de voz: la plataforma de voz cree que está hablando directamente con OpenAI, pero en el medio está Qora enriqueciendo cada respuesta con contexto del cliente, memoria y conocimiento del producto.

### 3.2 El panel web (frontend)

Una aplicación web donde:
- El **cliente** ve sus leads, el historial de llamadas, las transcripciones, el análisis de cada conversación y las métricas.
- El **administrador interno de Qora** crea y configura clientes y agentes.

### 3.3 La base de datos

Donde vive toda la información: clientes, agentes, leads, llamadas, transcripciones, análisis y llamadas agendadas.

### 3.4 Lo que Qora NO es

Para evitar confusiones:

- **Qora no fabrica la voz ni el reconocimiento de habla.** Eso lo provee ElevenLabs (un proveedor externo de voz). Qora es la inteligencia y la operación que va encima.
- **Qora no es "configurar un agente de ElevenLabs".** Cualquiera puede hacer eso. El valor de Qora está en las capas que agrega: memoria entre llamadas, análisis estructurado, gestión de leads, agendamiento, CRM y panel.
- **Qora no es un chatbot de texto.** Está diseñado para conversación de voz.
- **Qora no es un agente reactivo de soporte.** No espera consultas; hace llamadas (ver [foco outbound](#el-foco-salida-outbound-no-entrada)).

### 3.5 Qora como ecosistema inter-agéntico

Esta es una de las ideas que definen a Qora a nivel conceptual, y conviene explicarla con precisión para no confundir lo que es una *capacidad real hoy* con lo que es una *dirección de diseño*.

**La idea.** Qora no piensa en "un agente". Piensa en **un ecosistema donde múltiples agentes de IA trabajan sobre la misma operación de llamadas**. Un cliente puede tener varios agentes (1 cliente → N agentes), cada uno con su propia voz, su propio guion (prompt), su propio conocimiento (skills) y sus propias herramientas. Por ejemplo: un agente que califica leads nuevos, otro que cierra ventas, otro que hace seguimiento de los indecisos.

**Qué hace posible que colaboren (lo que SÍ existe hoy).** Lo que convierte a esto en un ecosistema —y no en agentes aislados que casualmente comparten dueño— es que **todos operan sobre un mismo sustrato de información compartido por lead**:

- La **memoria** de cada contacto (resúmenes de llamadas anteriores, sin importar qué agente las hizo).
- El **perfil acumulado** del lead (rasgos estables, preferencias, puntos de dolor).
- La **evolución del interés** a lo largo del tiempo.
- El **análisis** de cada conversación.
- El **estado** del lead y su **próxima acción**.

Gracias a esto, cuando un agente toma una llamada con un lead, **arranca con todo lo que cualquier otro agente dejó registrado antes**. En la práctica, esto es una forma de "pasarse el lead" entre agentes: el agente que sigue no empieza de cero, hereda el contexto completo. Además, cuando se agenda una llamada de seguimiento, esa llamada **lleva asignado un agente** — heredado de la llamada que la originó o el agente predeterminado del cliente — de modo que el sistema sabe quién debería tomar ese próximo contacto.

**Qué todavía NO existe (la dirección de diseño).** Para ser exactos: hoy **no hay un mecanismo de "traspaso" (handoff) explícito de un agente a otro** —del estilo "el agente A le pasa formalmente la conversación al agente B con una nota"—. La colaboración entre agentes ocurre **a través del estado compartido del lead**, no por un canal directo agente-a-agente. La visión de un ecosistema inter-agéntico más rico (con traspasos explícitos y coordinación directa entre agentes) es parte de la dirección del producto, y la arquitectura actual —datos compartidos por lead, agente asignado a cada llamada— es la base sobre la que eso se construiría.

> **Resumen sin humo:** el "ecosistema inter-agéntico" hoy es real en su fundamento (varios agentes, memoria y conocimiento compartidos por lead, agente asignado por llamada), y es aspiracional en su forma más avanzada (traspaso explícito y coordinación directa entre agentes).

---

## 4. Cómo funciona una llamada, paso a paso

Esta es la mecánica real de una conversación de voz, contada sin tecnicismos pero con precisión.

### Los actores

- **La persona** que habla (hoy, desde el navegador).
- **ElevenLabs**: el proveedor de voz. Convierte la voz de la persona en texto (STT), convierte el texto del agente en voz (TTS), y detecta cuándo la persona terminó de hablar.
- **Qora (backend)**: el cerebro.
- **GPT-4o (OpenAI)**: el modelo de lenguaje que genera lo que el agente dice.

### El flujo de un turno de conversación

```
1. La persona habla.
2. ElevenLabs convierte esa voz en texto.
3. ElevenLabs le envía ese texto a Qora.
4. Qora arma las instrucciones completas:
   - Quién es el agente y qué empresa representa.
   - A quién está llamando (nombre, auto, seguro actual, etc.).
   - Qué pasó en las últimas 3 llamadas con esta persona.
   - Qué conocimiento del producto tiene disponible.
5. Qora le pide la respuesta a GPT-4o, que la va generando palabra por palabra.
6. Qora devuelve esa respuesta a ElevenLabs en tiempo real.
7. ElevenLabs convierte el texto en voz y la persona la escucha.
8. Qora guarda lo que dijo el agente en la base de datos.
```

Este ciclo se repite en cada turno de la conversación.

### Detalles que hacen la diferencia en la experiencia

**El agente nunca se queda mudo "pensando".** Cuando el agente necesita consultar información (por ejemplo, cargar conocimiento sobre un producto), eso toma un instante. Para que no haya un silencio incómodo, Qora hace que el agente diga una frase puente natural — un *filler* como *"Dejame buscar esa información..."* — mientras la consulta ocurre por detrás. Las frases puente son configurables y se eligen para que suenen como una pausa natural, no como un mensaje robótico de "procesando".

**El agente puede ejecutar acciones durante la conversación.** A través de "herramientas" (tools), el agente puede, por ejemplo, consultar más datos del lead, cargar conocimiento específico de un producto, o registrar información capturada en la charla. Esto se detalla más abajo.

**El modelo que conversa es GPT-4o.** Es configurable por agente, pero el valor por defecto es GPT-4o. Cada turno tiene un límite de tiempo de 60 segundos para responder.

### Las herramientas que el agente puede usar durante la llamada

| Herramienta | Qué hace |
|-------------|----------|
| `get_lead_details` | Consulta los datos del lead (solo lectura). |
| `get_lead_profile` | Consulta el perfil acumulado del lead (rasgos, preferencias, señales). |
| `get_lead_history` | Consulta la evolución del nivel de interés del lead a lo largo del tiempo. |
| `get_lead_pain_points` | Consulta los puntos de dolor y problemas de servicio detectados. |
| `load_skill` | Carga conocimiento especializado (ej: detalles de un producto) a demanda. |
| `capture_data` | Registra datos capturados durante la conversación (campos configurables por agente). |

> **Nota sobre herramientas removidas.** Antes existían herramientas que cambiaban directamente el estado del lead durante la llamada (`register_interest`, `mark_not_interested`, `schedule_followup`). Hoy esas decisiones **ya no las toma el agente en vivo**: se derivan del análisis posterior a la llamada (ver [sección 5](#5-el-cerebro-análisis-post-llamada)). Las herramientas viejas siguen existiendo en el código pero están deshabilitadas; si se las invoca, devuelven un aviso de "herramienta removida". *(Detalle interno para devs: el panel de administración todavía las muestra como casillas seleccionables; es una inconsistencia conocida entre la UI y el backend.)*

---

## 5. El cerebro: análisis post-llamada

Esta es una de las piezas más distintivas de Qora a nivel de funcionalidad. **Cuando una llamada termina, Qora analiza automáticamente la conversación completa y extrae información estructurada.**

El análisis corre **en segundo plano**: nunca demora ni bloquea la llamada. Si alguna parte del análisis falla, las demás siguen funcionando, y el sistema guarda un registro de la falla parcial sin romperse.

### Qué se analiza (las dimensiones)

Qora descompone cada conversación en **once dimensiones de análisis** que corren en paralelo, más una decisión final de "próxima acción". Cada dimensión usa su propia llamada al modelo de lenguaje (GPT-4o-mini, una versión más económica) con un formato de salida estructurado.

| Dimensión | Qué extrae de la conversación |
|-----------|-------------------------------|
| **Resumen** | Una frase de qué pasó en la llamada. |
| **Resultado (outcome)** | Clasificación de cómo fue la llamada (positiva, neutral, negativa, no contestó, número equivocado, hostil, problema técnico, etc.) y, si se cortó de golpe, por qué. |
| **Intereses** | Qué productos le interesaron a la persona y qué necesidad específica hay detrás de cada uno. |
| **Nivel de interés** | Un puntaje de 0 a 100 de cuán comprometida está la persona, con señales positivas y de duda. |
| **Compromisos** | Qué se prometió de ambos lados ("el agente manda cotización", "el cliente consulta con su pareja"). |
| **Objeciones** | Qué reparos o resistencias planteó la persona (precio, tiene otro proveedor, no es el momento, etc.) y cómo las manejó el agente. |
| **Problema** | El dolor de fondo que motiva el interés (costo, mala experiencia previa, cobertura, vencimiento, etc.). |
| **Problemas de servicio** | Quejas concretas sobre su proveedor actual o anterior. |
| **Rasgos de perfil** | Características estables de la persona (ej: "consulta con su pareja antes de decidir", "prefiere WhatsApp"). Persisten entre llamadas. |
| **Notas operativas** | Contexto temporal para la próxima llamada (ej: "espera a su esposa el martes"). Es una ventana que se va actualizando. |
| **Correcciones de datos** | Si la persona corrigió algún dato suyo durante la llamada (ej: "en realidad mi auto es 2019, no 2018"), Qora lo detecta, lo valida y actualiza el dato. |

### La decisión de "próxima acción"

Después de analizar todas las dimensiones, Qora ejecuta un **motor de decisión** que determina qué hacer con ese lead. Funciona en dos pasos:

1. **Reglas de prioridad.** Hay una serie de reglas ordenadas. Por ejemplo: si la persona pidió no ser contactada o fue hostil → cerrar el lead. Si pidió que la vuelvan a llamar → agendar llamada. Si quedó con interés alto y la llamada fue positiva → hacer seguimiento. Si ya se superó el máximo de intentos → cerrar.
2. **Validación de la IA.** Después de que las reglas deciden, el modelo de lenguaje revisa la decisión de forma independiente. Si está de acuerdo, se mantiene. Si no, se escala a **revisión humana**.

El resultado posible es una de estas acciones: `follow_up` (seguimiento), `retry_call` (reintentar), `schedule_call` (agendar), `close_lead` (cerrar) o `human_review` (revisión humana).

### Dónde queda guardado

Todo el análisis se guarda de forma **atómica** (o se guarda todo, o no se guarda nada — no quedan datos a medias). Se almacena en dos lugares: en columnas estructuradas para poder hacer consultas y analítica, y como datos crudos para acceso directo. El nivel de interés, además, se guarda como **serie histórica**, lo que permite ver cómo evolucionó el interés de una persona a lo largo de varias llamadas.

---

## 6. La memoria: por qué el agente "recuerda"

Los modelos de lenguaje no recuerdan nada entre conversaciones. Cada llamada arranca de cero. Qora resuelve esto inyectando, **al inicio de cada llamada**, un resumen de todo lo que sabe sobre esa persona.

### Qué recuerda el agente al empezar una llamada

| Qué | De dónde sale |
|-----|---------------|
| Los **últimos 3 resúmenes** de llamadas anteriores. | Del resumen generado por el análisis post-llamada. |
| **Datos confirmados** (nivel de interés, resultado, seguro actual, etc.). | De los hechos extraídos del lead. |
| **Notas operativas** para esta llamada (ej: "esperá al martes"). | De la dimensión de notas operativas. |
| **Perfil acumulado** (rasgos estables, puntos de dolor, señales de compra). | De la tabla de rasgos de perfil. |
| **Evolución del interés** (ej: 30 → 55 → 72). | De la serie histórica de interés. |

Gracias a esto, el agente puede arrancar una llamada de seguimiento diciendo algo como: *"Hola, te vuelvo a llamar por lo del seguro de tu auto que hablamos antes. ¿Pudiste pensarlo?"* — y retomar objeciones previas sin repetir preguntas ya respondidas.

### Detalles importantes

- La memoria es **estática dentro de una llamada**: refleja lo que se sabía al empezar y no cambia a mitad de conversación.
- Se arma **una vez por llamada** y se reutiliza en todos los turnos de esa conversación.
- Las fechas se muestran en horario de Argentina (Buenos Aires).
- Una sesión de conversación expira tras **5 minutos de inactividad**.

---

## 7. Conocimiento dinámico: el sistema de skills

Un agente puede necesitar saber mucho: detalles de varios productos, precios, preguntas frecuentes, manejo de casos especiales. Meter todo eso en las instrucciones de cada llamada sería pesado e ineficiente.

Qora resuelve esto con **skills cargables a demanda**. Una *skill* es un documento con conocimiento sobre un tema (por ejemplo, "seguro de auto: coberturas y detalles"). El agente no lleva ese conocimiento encima todo el tiempo: lo **carga solo cuando la conversación lo requiere**.

### Cómo funciona

1. Cada agente tiene un **registro de skills** (`registry.yaml`) que lista qué skills existen y cuándo cargarlas.
2. Durante la llamada, si la conversación toca un tema que coincide con una skill, el agente la carga con la herramienta `load_skill`.
3. Mientras carga, dice una frase puente (filler) para no quedar en silencio.
4. Una vez cargada, ese conocimiento queda disponible por el resto de la conversación (se cachea, no se vuelve a cargar en cada turno).

Esto permite que un agente maneje muchos temas distintos sin "inflar" cada llamada con conocimiento irrelevante. El conocimiento de cada agente está **aislado por cliente**: un agente nunca puede acceder al conocimiento de otro cliente.

---

## 8. El agendador de llamadas

El agendador es una pieza **core** del producto, porque es lo que convierte a Qora en una operación de llamadas que avanza sola en el tiempo, en lugar de llamadas sueltas. Decide **cuándo hay que volver a llamar a cada lead**, lo deja en cola con el momento exacto y el agente asignado, y se ocupa de respetar las reglas del negocio.

### Cómo se crean las llamadas agendadas

Una llamada agendada puede nacer de tres orígenes (trigger reasons):

- **`auto_retry`** — la origina automáticamente el análisis post-llamada. Cuando el motor de "próxima acción" decide que hay que reintentar o hacer seguimiento, crea la entrada.
- **`followup_tool`** — originada desde una herramienta del agente durante la conversación.
- **`manual`** — creada a mano desde la API.

Cada llamada agendada queda con un **agente asignado**: se hereda del agente que tomó la llamada de origen y, si no hay, se usa el agente predeterminado del cliente. Esto conecta con la idea inter-agéntica de la [sección 3.5](#35-qora-como-ecosistema-inter-agéntico): el sistema sabe quién debería tomar el próximo contacto.

### La doble lógica del "cuándo": empresa vs. lo que pide el lead

Este es el punto más importante de entender del agendador, y es lo que lo hace inteligente y no un simple temporizador.

El momento de la próxima llamada se decide combinando **dos fuentes**, con una prioridad clara:

**1. Lo que pide o dice el lead (tiene prioridad).** Si durante la conversación la persona expresa cuándo quiere ser contactada —por ejemplo *"llamame en una hora"*, *"mejor el martes a la tarde"*, *"estoy ocupado, probá mañana"*— el análisis post-llamada **detecta esa intención y fija el momento concreto** de la próxima llamada en base a eso. Esa preferencia del lead **sobreescribe** la lógica genérica de la empresa.

**2. La lógica configurada por la empresa (por defecto).** Si el lead no pidió un momento específico, el agendador calcula el momento siguiendo las reglas que la empresa cliente configuró: el tiempo de espera entre intentos (cooldown), el horario permitido para llamar y la zona horaria.

En otras palabras: **Qora respeta primero al lead, y si el lead no dijo nada, aplica la política de la empresa.** Y aún cuando respeta al lead, sigue protegiendo ciertos límites del negocio: por ejemplo, si alguien dice "llamame a las 3 de la mañana", el horario permitido del cliente reencauza ese momento a una franja válida.

### Qué se puede configurar por cliente

Cada cliente tiene su propia configuración del agendador, sin tocar código:

- Si el agendador está **activado o no**.
- **Máximo de intentos** por lead (por defecto 3 en el agendador; el motor de próxima acción contempla hasta 5).
- **Tiempo de espera** entre intentos (cooldown).
- **Horario permitido** para llamar (ej: de 9 a 20 hs). Si una llamada cae fuera de ese horario, se reprograma para el siguiente horario válido.
- **Zona horaria** del cliente (ej: Buenos Aires).
- **Qué resultados disparan un reintento** (ej: "no contestó", "ocupado", "seguimiento").

### Cómo se "dispara" la llamada (el trigger)

El agendador funciona como un **reloj que late cada minuto**. En cada latido:

1. Busca las llamadas en cola cuyo momento programado ya llegó ("vencidas").
2. Las marca como **listas para ejecutar** ("en progreso").

Ese paso de "marcar como lista para ejecutar" **es el punto donde, conceptualmente, se dispararía la llamada telefónica**. La cadena completa —el análisis decide la próxima acción → se agenda con su momento y agente → el reloj la detecta cuando vence → se dispara el trigger— **está construida y funcionando hasta el momento del disparo.**

### Lo que el agendador hace y lo que NO hace hoy

- **Sí hace (implementado y funcionando):** crea las llamadas agendadas; decide el momento combinando la preferencia del lead con la política de la empresa; respeta horario, cooldown y zona horaria; asigna el agente; evita duplicados; controla el máximo de intentos; y cada minuto detecta las llamadas vencidas y las marca como listas para ejecutar (dispara el trigger).
- **No hace (todavía):** **realizar la llamada telefónica en sí.** El trigger se dispara y la llamada queda marcada como "en progreso", pero **no existe hoy el código que conecte ese disparo con una marcación real a un teléfono** (no hay integración de telefonía). Es un hecho del roadmap, documentado en el propio código como fase posterior (Phase 8): toda la lógica previa está lista para enchufar la telefonía cuando se conecte. Ver [sección 14](#14-estado-actual-qué-funciona-y-qué-todavía-no).

> **En una frase:** el agendador ya sabe *a quién*, *cuándo*, *con qué agente* y *por qué* llamar —y entiende si el lead pidió un horario específico—; lo único que falta conectar es el acto físico de discar.

---

## 9. Integración con CRM

Qora se integra con CRMs externos para mantener sincronizados los leads. **Hoy el único CRM integrado es Airtable.**

La integración funciona en **dos direcciones**:

### 9.1 Empuje (Qora → CRM)

Después de cada llamada y su análisis, Qora **envía** la información actualizada del lead al CRM externo (estado, datos, resultado). Esto ocurre en segundo plano y **nunca afecta el resultado del análisis**: si la sincronización con el CRM falla, se registra el error pero la llamada y su análisis quedan intactos.

### 9.2 Importación (CRM → Qora)

Qora puede **traer leads desde el CRM externo**. Se dispara manualmente (a través de un endpoint). El proceso:

- Trae todos los registros del CRM.
- Los mapea a la estructura de Qora.
- **Evita duplicados** por número de teléfono.
- Actualiza los existentes o crea los nuevos.
- Nunca "retrocede" el estado de un lead: solo lo avanza si el estado del CRM está más adelante.

### 9.3 Cómo se configura

Cada cliente tiene un archivo de configuración (`crm.yaml`) donde se define **todo** el mapeo, sin tocar código:

- Qué proveedor (hoy, Airtable).
- Las credenciales (se guarda solo el **nombre** de la variable de entorno, nunca el secreto en sí).
- El mapeo de cada campo (cómo se llama "teléfono" en Qora vs. cómo se llama en el CRM).
- El mapeo de estados (ej: el estado interno `quoted` de Qora se traduce a "Cotizado" en el CRM, y viceversa).

Esto significa que **adaptar Qora al CRM de un nuevo cliente es un trabajo de configuración, no de programación** — siempre que el CRM sea Airtable.

### 9.4 Lo que NO está integrado hoy

- **Solo Airtable.** No hay integración con HubSpot, Salesforce ni otros CRMs. El sistema está diseñado con un patrón que permite agregar otros proveedores, pero hoy ninguno está implementado.
- La importación es **manual/por lotes**, no en tiempo real (no hay sincronización automática cuando algo cambia en el CRM).

---

## 10. El panel: qué ve el cliente y el administrador

El panel web es una aplicación moderna construida en React. Tiene varias secciones reales y funcionando.

### 10.1 Dashboard de métricas

La pantalla principal del cliente. Muestra, con un selector de período (hoy / 7 días / 30 días / todo):

- **Total de llamadas**
- **Llamadas completadas**
- **Llamadas abandonadas**
- **Duración promedio**
- **Duración total**
- **Minutos facturables**
- Una barra de **distribución** entre completadas y abandonadas.

### 10.2 CRM / Leads

La lista de leads, con columnas:

- Nombre, Teléfono, Estado, Cantidad de llamadas, Última llamada, y **Próxima acción**.

Al entrar a un lead, se ve su **ficha detallada**:

- Datos de contacto y estado.
- **Nivel de interés**.
- **Próxima acción**.
- Indicador de "No llamar" si corresponde.
- **Resumen de la última llamada**.
- Panel de análisis (intereses detectados y problema identificado).
- **Historial completo de llamadas**, donde cada llamada se puede expandir para ver su transcripción turno por turno.

### 10.3 Detalle de llamada y análisis completo

Por cada llamada se puede ver el **análisis completo** de las doce dimensiones: resumen, nivel de interés (con barra visual), clasificación, razón del resultado, urgencia, necesidad principal, próxima acción, objeciones, puntos de dolor, problemas de servicio, intereses detectados, señales de compromiso, rasgos de perfil, notas y correcciones de datos. Incluye una sección de auditoría (estado del análisis, errores si los hubo, fecha de análisis).

### 10.4 Analítica

Una sección de analítica agregada, con selector de período y filtro por agente:

- **Overview**: total de llamadas, tasa de conversión, distribución de resultados.
- **Problemas de servicio** agregados.
- **Intereses** agregados.
- **Estadísticas por agente**.

### 10.5 Panel de administración (interno de Qora)

Para el equipo de Qora, no para el cliente. Tiene dos pestañas:

- **Clientes**: crear y gestionar clientes.
- **Agentes y configuración de voz**: por cada cliente, crear/editar/desactivar agentes, marcar uno como predeterminado, configurar el prompt del sistema, la base de conocimiento, el modelo, la temperatura, y el **ajuste fino de voz** (velocidad, estabilidad, similitud). Incluye una **lista de verificación de preparación** (¿tiene prompt?, ¿tiene ID de agente de ElevenLabs?, ¿tiene URL configurada?) que indica si el agente está listo para conversar, y un botón para copiar la URL que hay que pegar en ElevenLabs.

### 10.6 Lo que en el panel todavía NO está

- **Importación de leads por CSV**: la página existe pero dice "próximamente". No está implementada en la UI. *(La importación desde Airtable sí funciona, pero por endpoint, no desde esta pantalla.)*
- **Autenticación / login**: el panel **no tiene sistema de usuarios ni login** hoy. Ver [sección 14](#14-estado-actual-qué-funciona-y-qué-todavía-no).

---

## 11. Multi-cliente: cómo se aíslan los datos

Qora está diseñado para servir a **múltiples clientes (empresas) desde la misma plataforma**, manteniendo sus datos separados.

- Cada cliente tiene un identificador (ej: `quintana-seguros`).
- **Todos los datos importantes** (leads, llamadas, análisis, llamadas agendadas, agentes) están asociados a un cliente.
- El acceso entre clientes está **bloqueado explícitamente**: un lead de un cliente no puede ser tocado en el contexto de otro, y el conocimiento de un agente no puede filtrarse a otro cliente.
- Un cliente puede tener **varios agentes** (1 cliente → N agentes), cada uno con su propia configuración, voz y conocimiento. Dentro de un mismo cliente, esos agentes **comparten el sustrato de información por lead** (memoria, perfil, análisis), que es lo que habilita el funcionamiento inter-agéntico descrito en la [sección 3.5](#35-qora-como-ecosistema-inter-agéntico). El aislamiento es **entre clientes**, no entre los agentes de un mismo cliente.

### Configuración por cliente

La configuración de cada cliente vive en dos lugares:

1. **Base de datos**: configuración del agendador, idioma del análisis, parámetros del motor de próxima acción.
2. **Archivos**: el prompt del sistema de cada agente, sus skills (conocimiento) y la configuración de CRM. Tener esto en archivos permite que sea **versionable y revisable** (queda en el control de versiones, no escondido en una base de datos).

### Borrado seguro

Desactivar un cliente o un agente es siempre un **borrado lógico** (soft delete): se marca como inactivo, pero **no se borra físicamente ningún dato**. Los leads y llamadas asociados se conservan. Un cliente inactivo es rechazado en las llamadas entrantes.

---

## 12. Tecnología que usa Qora

Resumen del stack, en lenguaje claro:

| Capa | Tecnología | Para qué |
|------|-----------|----------|
| **Voz** | ElevenLabs (Conversational AI) | Convertir voz↔texto, detectar turnos de habla, generar la voz del agente. Proveedor externo. |
| **Cerebro de conversación** | GPT-4o (OpenAI) | Generar lo que el agente dice en cada turno. |
| **Análisis post-llamada** | GPT-4o-mini (OpenAI) | Extraer las dimensiones de análisis de cada conversación (versión más económica). |
| **Backend** | Python 3.11 + FastAPI | El motor central de Qora. |
| **Frontend** | React + TypeScript + Vite + TanStack Query | El panel web. |
| **Base de datos** | SQLite | Almacenamiento de todos los datos. |
| **CRM externo** | Airtable (vía librería pyairtable) | Sincronización de leads en ambas direcciones. |

### Notas técnicas relevantes para el negocio

- **La base de datos hoy es SQLite**, un motor liviano basado en un solo archivo. Es adecuado para el estado actual (piloto), pero está previsto migrar a PostgreSQL para escalar a producción multi-cliente con volumen.
- **OpenAI y ElevenLabs son proveedores externos.** Qora depende de ellos para el modelo de lenguaje y para la voz. La arquitectura está pensada para poder cambiar de proveedor de voz con relativa facilidad si fuese necesario.
- **El producto tiene una cobertura de pruebas amplia**: cientos de pruebas automatizadas tanto en el backend como en el frontend, lo que da una base sólida de confiabilidad para seguir construyendo.

---

## 13. Qué datos guarda Qora

Qora organiza la información en estas entidades principales:

| Entidad | Qué guarda |
|---------|-----------|
| **Clientes** | La empresa que usa Qora: nombre, configuración del agendador, idioma de análisis. |
| **Agentes** | Los agentes de IA de cada cliente: voz, modelo, prompt, ajuste de voz, conocimiento. |
| **Leads** | Los contactos: nombre, teléfono, email, edad, zona, datos del auto, seguro actual, estado, nivel de interés, cantidad de llamadas, próxima acción, objeciones escuchadas, hechos extraídos, ID en el CRM externo. |
| **Llamadas (sesiones)** | Cada llamada: cuándo empezó y terminó, duración, minutos facturables, resultado, resumen. |
| **Transcripciones** | El contenido turno por turno de cada conversación. |
| **Análisis de llamada** | El análisis estructurado de cada llamada (las doce dimensiones, en columnas consultables). |
| **Llamadas agendadas** | La cola de llamadas a futuro: cuándo, por qué, número de intento. |
| **Rasgos de perfil** | Hechos estables sobre cada lead, que persisten entre llamadas. |
| **Historial de interés** | La evolución del nivel de interés de cada lead a lo largo del tiempo. |

### El "estado" de un lead

Cada lead tiene un estado que sigue un ciclo controlado:

```
nuevo → llamado → (cotizado | interesado | no interesado | seguimiento)
seguimiento → llamado (puede volver a ser llamado)
```

Los estados "cotizado", "interesado" y "no interesado" son finales en el ciclo. Las transiciones inválidas están bloqueadas por el sistema.

---

## 14. Estado actual: qué funciona y qué todavía no

Esta sección es deliberadamente cruda y honesta. Es la más importante para que ningún equipo parta de una premisa falsa.

### ✅ Lo que funciona hoy

- **Conversación de voz por navegador**, de punta a punta, con voz natural en español rioplatense.
- **El cerebro de conversación** (Qora como LLM personalizado para ElevenLabs, con GPT-4o).
- **Memoria entre llamadas**: el agente recuerda conversaciones anteriores.
- **Análisis post-llamada** automático en once dimensiones + decisión de próxima acción.
- **Transcripción** turno por turno de cada conversación.
- **Carga dinámica de conocimiento** (skills) durante la llamada.
- **Agendador de llamadas**: crea y gestiona la cola, decide el momento combinando la preferencia del lead ("llamame en una hora") con la política de la empresa, respeta horarios/zona horaria/reintentos, asigna agente, evita duplicados y **dispara el trigger** de la llamada cuando vence.
- **Modelo inter-agéntico**: varios agentes por cliente compartiendo memoria, perfil y análisis por lead; agente asignado a cada llamada agendada.
- **CRM**: lista de leads, ficha de lead, historial, transcripciones, análisis, próxima acción.
- **Dashboard de métricas** y **analítica** agregada.
- **Panel de administración**: CRUD de clientes y agentes, ajuste de voz.
- **Integración con Airtable** en ambas direcciones (empuje automático + importación manual).
- **Multi-cliente** con aislamiento de datos entre clientes.
- **Seguimiento de minutos facturables** (la métrica, no el cobro).

### 🔲 Lo que NO está implementado hoy

| Funcionalidad | Estado real |
|---------------|-------------|
| **Llamada telefónica real (a un número de teléfono)** | **No implementada.** No hay integración con Twilio ni ningún sistema de telefonía. No hay marcación saliente. El único canal de voz que funciona es el navegador. |
| **La marcación que conecta el agendador con el teléfono** | **No implementada.** El agendador decide todo (a quién, cuándo, con qué agente, por qué) y **dispara el trigger** cuando la llamada vence, pero ese disparo todavía no está conectado a una marcación real. Falta enchufar la telefonía al final de una cadena que ya está construida. |
| **Traspaso (handoff) explícito entre agentes** | **No implementado.** Los agentes colaboran a través del estado compartido del lead, pero no hay un mecanismo de traspaso directo agente-a-agente. Es dirección de diseño (ver [sección 3.5](#35-qora-como-ecosistema-inter-agéntico)). |
| **Autenticación / login / usuarios** | **No implementada.** La API y el panel no tienen control de acceso. Es adecuado para un entorno de desarrollo/demo, no para producción abierta. |
| **Facturación / cobro por minuto** | **No implementada.** Se trackea la cantidad de minutos facturables, pero no hay precios, ni facturación, ni integración de pagos. |
| **Importación de leads por CSV (en el panel)** | **No implementada.** La página dice "próximamente". |
| **Otros CRMs (HubSpot, Salesforce, etc.)** | **No implementados.** Solo Airtable. |
| **Base de datos de producción (PostgreSQL)** | **No migrada.** Hoy usa SQLite. |

### Cómo leer esto

El estado actual de Qora es el de un **producto funcional con un piloto real**, donde **toda la inteligencia y la operación están construidas y probadas** (conversación, memoria, análisis, modelo inter-agéntico, gestión de leads, agendamiento con su trigger, CRM, panel), y donde **lo que falta para "salir a la calle" a escala es principalmente infraestructura de salida**: telefonía real, autenticación, facturación y base de datos de producción.

En otras palabras: el cerebro y la operación están hechos —incluido el agendador que decide y dispara *cuándo* llamar—; falta conectar ese disparo al teléfono y ponerle las cerraduras (autenticación) y la caja registradora (facturación).

---

## 15. El cliente piloto: Quintana Seguros

Qora hoy tiene un cliente piloto real: **Quintana Seguros**, una correduría de seguros argentina.

- **El agente se llama Jaumpablo.** Es un asesor de seguros que vende cobertura de autos.
- Habla en **español rioplatense con voseo**, de forma cálida y directa.
- **Conoce al lead antes de la llamada**: su nombre y los datos de su auto.
- **Recuerda conversaciones anteriores**.
- **Conduce la conversación activamente** siguiendo un guion definido: apertura, calificación, indagación sobre el seguro actual, propuesta de valor (sin inventar precios) y cierre.
- **Maneja objeciones** con respuestas concretas ("es caro", "ya tengo seguro", "no me interesa", "lo tengo que pensar").
- Tiene reglas estrictas: nunca inventa precios ni coberturas, nunca presiona después de un "no" claro, siempre cierra con amabilidad.
- Conecta con el **CRM de Airtable** de Quintana, traduciendo los estados internos de Qora a la nomenclatura del CRM del cliente (ej: `interesado` → "COMPRÓ", `seguimiento` → "Recontactar").

También existe un **agente de demostración de la propia Qora** (un agente "explicador" llamado Mariano) que sirve para mostrar la plataforma: responde preguntas sobre qué es Qora y cómo funciona.

---

## 16. Glosario

| Término | Significado |
|---------|-------------|
| **Lead** | Un contacto / cliente potencial al que se llama. |
| **Agente** | El "empleado" de IA configurado para conversar. Un cliente puede tener varios. |
| **Cliente / tenant** | La empresa que usa Qora. |
| **Prompt / prompt del sistema** | Las instrucciones que definen cómo se comporta el agente (su "personalidad" y su guion). |
| **STT (Speech to Text)** | Conversión de voz a texto. La hace ElevenLabs. |
| **TTS (Text to Speech)** | Conversión de texto a voz. La hace ElevenLabs. |
| **LLM** | Modelo de lenguaje (ej: GPT-4o). El "cerebro" que genera lo que el agente dice. |
| **Custom LLM (LLM personalizado)** | El mecanismo por el cual Qora se inserta como cerebro entre ElevenLabs y OpenAI. |
| **Tool / herramienta** | Una acción que el agente puede ejecutar durante la llamada (consultar datos, cargar conocimiento, registrar info). |
| **Skill** | Un documento de conocimiento que el agente carga a demanda durante la conversación. |
| **Filler** | Frase puente que el agente dice para no quedar en silencio mientras consulta algo. |
| **Outcome** | La clasificación del resultado de una llamada. |
| **Next action / próxima acción** | La decisión automática de qué hacer con un lead después de una llamada. |
| **Soft delete / borrado lógico** | Marcar algo como inactivo sin borrarlo físicamente. |
| **Multi-tenant** | Que sirve a múltiples clientes desde la misma plataforma, con datos aislados. |

---

*Documento de producto de Qora — fuente de verdad interna. Describe el estado del producto a mayo de 2026. Mantener actualizado a medida que el producto evoluciona.*
