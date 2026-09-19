# Guion de reuniones — Thinkuy (SciImago y ReHuSo)

> Documento de preparación. Todos los números fueron medidos en vivo con Thinkuy el 08-09-2026 y son reproducibles en el demo. No citar ninguno sin volver a medirlo si pasa más de una semana.

---

## PARTE 0 — Las 4 frases que ordenan todo (memorizar)

1. **"Las citas miden quién te referencia; la web mide quién te encuentra y quién de ti habla. Nosotros medimos lo segundo."**
2. **"No es SEO: un percentil del grafo no se puede comprar. Se puede *ganar* con práctica real (que te enlacen) o *fingir* con práctica penalizable (enlaces recíprocos). Nuestro trabajo es ayudarte a ganar, y el grafo te prueba que no fingiste."**
3. **"Antes de decirte algo bonito, te decimos dónde NO podemos saber: el grafo mide dominios, no artículos; la proyección 2D exhibe, no mide; y si un dato no existe, aparece 'no disponible', nunca un número inventado."**
4. **"La herramienta diagnostica gratis; el servicio (Unidad de Cultura Científica) trata lo que el diagnóstico encuentra; y la misma herramienta prueba el antes/después."**

---

## PARTE 1 — Conceptos definidos (qué / analogía / ejemplo / frase de 15 segundos)

### 1.1 Grafo web de Common Crawl
- **Qué:** mapa público de hipervínculos entre dominios, construido con los rastreos de Common Crawl (la misma fuente abierta que alimenta índices y entrenamientos de IA). Release actual: junio-agosto 2026, ~58.9 millones de dominios.
- **Analogía:** la "calle real" de la web: quién tiene la dirección puesta hacia quién.
- **Ejemplo:** 378 dominios distintos tienen un enlace hacia el portal de SciImago EPI (`scimagoepi.com`).
- **Frase:** "Es el censo público de los enlaces de la web. No es Google, pero Google lo usa entre sus señales; y a diferencia de Google, aquí puedes auditar cada dato."

### 1.2 PageRank y Centralidad Armónica (los dos "puestos en la lista")
- **Qué:** PageRank = cuánto poder de enlace acumulas (los enlaces que recibes, ponderados por quién te enlaza). Centralidad armónica = qué tan lejos estás del resto de la web (proximidad estructural a hubs).
- **Analogía:** PageRank es tu patrimonio; la armónica es qué tan céntrica está tu casa en la ciudad.
- **Ejemplo:** `scimagoepi.com`: PageRank #557,476 y armónica #2,084,160 sobre 58.9M.
- **Frase:** "Te damos dos posiciones y, sobre todo, el *porqué*: quién te enlaza (entrada) y a quién enlazas (salida) explican tu puesto."

### 1.3 Atribución honesta: portal vs revista (escalamiento)
- **Qué:** el grafo es por dominio registrable. Si la revista vive en `revistas.utm.edu.ec`, las métricas de grafo son de `utm.edu.ec` (toda la universidad). Thinkuy lo declara con etiqueta *escalada* y, en portales multi-revista, marca `shared_host`.
- **Analogía:** decir el ingreso del edificio, no del apartamento — y decir en voz alta que es del edificio.
- **Ejemplo:** ReHuSo: tier "top 0.9%" es de UTM (universidad); su retrato como revista se mide en out-links, menciones y gemelos.
- **Frase:** "El mismo dato, con la etiqueta de hasta dónde llega. Eso es lo que ninguna caja negra te muestra."

### 1.4 In-links (quién te enlaza)
- **Qué:** lista de dominios reales que apuntan a tu dominio, contada sobre el grafo CC (no estimación comercial).
- **Ejemplo demo:** a Comunicar la enlazan universidades argentinas (austral, uca, unlp…); al portal SciImago EPI lo enlazan redes de bibliotecas biomédicas de Brasil (ibict.br, febab.org.br).
- **Matiz a decir tú antes que pregunten:** el grafo colapsa A→B en un borde; el número que importa es *cuántos dominios distintos te enlazan* (378, 512, 856), no el contador por par.

### 1.5 Out-links e higiene de enlaces (ciencia abierta enlazada)
- **Qué:** Thinkuy escanea la portada Y hasta 5 páginas informativas del menú de la revista (fix del 08-09: los bloques de indexación/redes suelen estar en `/indexacion`, no en la portada) y clasifica a qué enlaza: identificadores (ORCID/DOI), instituciones/índices (DOAJ, Latindex, Dialnet), medios/redes, datos abiertos.
- **Ejemplo:** Infonomy: 62 enlaces externos, 59 clasificados (42 PID, 12 académicos, 5 redes). Ratio Decidendi: 15, solo 4 clasificados — flanco débil real.
- **Frase:** "Un artículo invisible es malo; una revista que no enlaza su propia infraestructura de visibilidad es una revista que no la está usando."

### 1.6 Gemelos web (embedding de hosts)
- **Qué:** 52.9M hosts proyectados en 128 dimensiones por Common Crawl según su **patrón de enlaces**. Dos revistas son gemelas si se enlazan igual y las enlazan igual (nicho estructural, no contenido).
- **Analogía:** huella ecológica web: ocupas el mismo nicho que otros cuando compartes ecosistema de enlaces.
- **Ejemplo:** vecinos de Comunicar: OJS de Uruguay, Cuba, Ecuador, Costa Rica, Latindex UNAM — su tribu web.
- **Límite que debes decir:** empareja por dominio registrable; journals que compiten host con path no se distinguen entre sí.

### 1.7 Brecha de enlaces (la pregunta estratégica)
- **Qué:** hubs que enlazan a varios de tus gemelos y NO te enlazan a ti. Adquisición legítima por gestión editorial (solicitar inclusión, aportar contenido, colaborar).
- **Ejemplo ReHuSo:** `unizg.hr`, `una.ac.cr`, `ufmg.br`, `usal.es` enlazan a 4-5 de sus gemelos y no a UTM.
- **Límite que debes decir:** NO es intercambio recíproco coordinado (link scheme: penalizado y autodestruye tu medición). Y se filtran los "hubs sombra" (google, wikipedia, redes, hostings gratuitos): enlazan a todos, no son objetivo.

### 1.8 La otra orilla: visibilidad conversacional (tu servicio)
- **Qué:** menciones del trabajo científico fuera del circuito académico: Wikipedia, blogs, Substack, podcasts, prensa. Thinkuy ya mide pedazos: menciones Wikipedia (filtradas por segmento OJS para no confundir revistas del mismo portal) y detección de canales transmedia con **estado de actividad** (posts recientes encontrados o canal vacío).
- **Ejemplo demo (contundente):** KMEL: 8,291 citas en OpenAlex, **0** menciones Wikipedia, **0** canales. Comunicar: 16 menciones Wikipedia. Ratio Decidendi: Substack abierto con 3 posts y LinkedIn con 0 — *fachada*.
- **Frase:** "Citar es la orilla de cerca. Que hablen de ti es la orilla de lejos. Nadie le vende a la revista diamante iberoamericana un instrumento para la orilla de lejos."

### 1.9 JARI — agent readiness (el puente con SciImago)
- **Qué:** índice propio (paper en preparación) que mide si la infraestructura de una revista permite que **agentes IA** la lean: robots.txt, semántica HTML, metadatos, extractibilidad, identificadores, y discriminación por User-Agent.
- **Hallazgos del estudio de 50 revistas LIS (incluida Scientometrics):** 54% de las revistas discrimina por User-Agent; Springer aplica "406 Gate" (Chrome pasa, GPTBot/Claude/Perplexity reciben 406); Elsevier bloquea uniforme. Paradoja: Scientometrics puntúa JARI 0.751 (infraestructura excelente) y aun así es invisible para 3 de 5 asistentes IA. **Sur supera al Norte en JARI: 0.409 vs 0.357.**
- **Frase para SciImago:** "Ustedes miden citas desde 2011. La pregunta nueva es: ¿te miden las IA? Sus tres revistas están en Springer/Elsevier, los dos regímenes que bloquean agentes. Ese es un problema de su casa, y lo medimos."

### 1.10 Serie temporal scivis_store (el contrato de confianza)
- **Qué:** cada auditoría queda persistida con fecha y release → la trayectoria de una revista se puede medir release a release de CC. El ROI del servicio UCC se demuestra con antes/después verificable, no con promesas.
- **Frase:** "No te vendo un número: te firmo una serie temporal."

---

## PARTE 2 — REUNIÓN CON EL DIRECTOR ASOCIADO DE SCIMAGO

### Contexto que tienes (y que es oro)
- SciImago **es proveedor técnico de la revista donde tú trabajas**: el pie de RPC dice "Hosting & Support: SCImago" (EPI) y el Dr. Rafael Repiso figura como responsable de edición del número actual. No empieces vendiendo: empiezas siendo usuario y colega del ecosistema.
- Ellos construyeron la orilla de cerca (SJR). Tú llegas con la orilla de lejos + la capa agéntica (JARI) — **complemento, no competencia**.
- EPI vende alojamiento OJS a revistas: un diagnóstico de visibilidad/agente-readiness es un **módulo vendible para SUS clientes**.

### Gancho (30 segundos, de pie)
"Trabajo en la Revista Panamericana de Comunicación, alojada en su plataforma EPI — así que esto también me toca de cerca. Construí Thinkuy: una herramienta que audita, con datos verificables de Common Crawl, la otra capa de visibilidad de una revista: quién la enlaza en la web, qué enlaza ella, dónde está su nicho estructural entre 52.9 millones de hosts… y si sus agentes IA pueden leerla. Para ilustrarlo, voy a auditar su propia revista insignia."

### Demo guiado (orden exacto, ~8 min)
1. `localhost:8000/app/` → modo Revista → pegar `https://infonomy.scimagoepi.com/index.php/infonomy/es/index`.
   - **Señalar:** identidad (ISSN 2990-2290, dominio directo, `shared_host: false` — "su plataforma es host propio, la herramienta lo distingue").
2. Tarjeta del grafo: **decir la escalada antes ellos**: "sus métricas de portal están atribuidas a `scimagoepi.com` (5 hosts), lo declaramos así siempre".
3. "Quién enlaza": 378 dominios; nombrar ibict.br / febab.org.br → "su ecosistema de enlace actual es la comunidad de bibliotecas biomédicas brasileñas: coherente con su historia, pero eso es lo que el grafo dice — ni inflado ni maquillado".
4. Out-links: 62 clasificados — "Infonomy tiene una de las portadas con mejor higiene de las que auditamos; 12 índices académicos enlazados".
5. Gemelos + explorador kNN embebido: escribe en vivo `infonomy.scimagoepi.com` (o cualquier revista que nombre el editor) en el panel kNN y muestra sus vecinos reales (cobertura: los 52.9M hosts). El enlace "mapa 2D de contexto" solo busca los 20.000 sitios más enlazados de la web → úsalo para la foto global ("el distrito del español, 1.2M hosts"), nunca para localizar revistas; dilo tú primero.
6. Brecha de enlaces: `ubc.ca`, `unipi.it`, `mdpi.com` enlazan a 3 de sus gemelos y no a ustedes → "así se ve una estrategia de adquisición legítima, sin granjas de enlaces".
7. Golpe de cierre (JARI, sin demo, solo número): "En nuestra auditoría de 50 revistas de ciencia e información, Scientometrics —publicada en Springer— dejó pasar a GPTBot, Claude y Perplexity con un 406. JARI le dio 0.751: infraestructura de primer mundo, invisibilidad de primer mundo. Sus revistas están en los dos regímenes de bloqueo (Springer, Elsevier). La pregunta '¿te citan?' ya tienen quién la responda; la pregunta '¿te leen las IA?' se la podemos responder nosotros".

### Los 3 números de memoria
- 58.9M dominios · release jun-ago 2026 (medible hasta en el disclaimer)
- Infonomy/scimagoepi: PageRank #557K; 378 enlazantes
- JARI: 54% de revistas discrimina por User-Agent; Sur 0.409 > Norte 0.357

### Objeciones probables
| Te dicen | Respondes |
|---|---|
| "Esto es SEO" | "No: SEO promete posiciones en Google. Esto describe el grafo público verificable; la estrategia se construye encima, con prácticas ganables. Y el grafo también detecta al que finge con esquemas recíprocos." |
| "Ya medimos citas" | "Exacto, esa es la orilla de cerca. La nuestra es estructural-conversacional: quién te enlaza, quién de ti habla, quién (IA) te puede leer. SJR es ciego a las tres." |
| "¿Common Crawl no tendrá sesgo?" | "Lo tiene: ~19% de hosts (grado ≥8) y presupuesto de rastreo desigual. Por eso publicamos el límite, usamos percentiles y CDX como verificación cruzada, y lo citamos como sesgo medido en el paper JARI — no como tabú." |
| "¿Precio/qué quieres?" | "Dos cosas posibles: que el diagnóstico entre como módulo de valor para clientes EPI, y que auditemos junto a ustedes las revistas del portafolio para decidir. La primera reunión no tiene precio." |

### CTA
"Les dejo una auditoría PDF de Infonomy y la serie temporal de sus 3 revistas. Si a los 30 días no les interesa el módulo, me quedo con que Thinkuy midió bien su casa — que es como uno quiere que lo recuerden."

---

## PARTE 3 — REUNIÓN CON EL EDITOR DE REHUSO (UTM, Ecuador)

### Gancho (30 segundos)
"Ustedes están mejor de lo que creen y más expuestos de lo que parece. Con una herramienta que construí, medí su revista contra el grafo completo de la web — 58.9 millones de dominios. Le muestro cuatro datos y una lista de universidades que enlazan a sus gemelos y no a ustedes. Eso último es literal dinero sobre la mesa en términos de visibilidad."

### Demo guiado (~7 min)
1. Pegar `https://revistas.utm.edu.ec/index.php/Rehuso` (URL completa).
2. **La lección de honestidad, como gancho de credibilidad:** "El 'top 0.9%' que ve aquí es del dominio de la UTM completa, no de ReHuSo — la herramienta lo dice con una etiqueta para que nadie venda humo. Su retrato como revista viene de acá…" → scrollear a out-links (58, 22 clasificados, crawl de 6 páginas del menú: about, revisión por pares, políticas).
3. "Quién enlaza" al portal: 512 dominios → "ese es el techo del edificio; vamos a ver el apartamento".
4. **La otra orilla (aquí está tu venta):** ReHuSo: 1 mención Wikipedia; LinkedIn detectado con **0 posts**. Contra-benchmark: Comunicar con 16 menciones; KMEL con 8,291 citas y 0 presencia pública → "citar y conversar son dos mercados distintos; ustedes solo están comprando entradas a uno".
5. Brecha de enlaces: `unizg.hr`, `una.ac.cr`, `ufmg.br`, `usal.es` (enlazan a 4-5 gemelos, no a UTM) → "no les voy a recomendar enlaces recíprocos —eso los penaliza y destruye su medición—; les voy a recomendar gestión real ante estos hubs: contenidos invitados, colaboración, presencia en sus listas".
6. Cerrar con serie temporal: "si trabajamos juntos, en 6 meses usted mismo ve esta página y mide el antes/después".

### Objeciones probables
| Te dicen | Respondes |
|---|---|
| "¿Esto sube mi posición en Google?" | "No lo prometo — quien lo promete, miente. Sube su descubribilidad demostrable: índices, repositorios, menciones, lectura por IA. Google suele seguirla, pero su negocio no es Google, es que lo lean y lo citeren." |
| "¿Y eso quién lo hace?" | "Yo. La auditoría es gratuita y es el diagnóstico; el servicio —transmediación de artículos, gestión ante hubs, Wikipedia, podcasts— es la Unidad de Cultura Científica. Con esto solo le muestro dónde está." |
| "No tengo presupuesto" | "No lo necesito hoy. Le dejo el informe y una de dos líneas de acción gratuitas: los 4 hubs de la brecha, y el LinkedIn vacío que ya tienen." |
| "Su lista me manda a enlazarme a un portal de Tailandia, si yo no hago nada con Tailandia" | "Tiene toda la razón — y por eso la herramienta ya no se lo muestra. En revistas académicas, la similitud de enlaces mide sobre todo *plomería compartida* (los mismos indexadores, el mismo OJS), no audiencia. Thinkuy clasifica la brecha: le recomienda solo hubs de su región iberoamericana o infraestructura de indexación reconocida (DOAJ, SciELO…), y le dice cuántos nodos 'globales' ocultó y por qué. Es un límite del dato, no de su revista: y declararlo es lo que distingue un instrumento de un generador de humo." |

---

## PARTE 4 — Protocolo técnico del día de la demo (checklist)

**Víspera:**
- [ ] Correr servidor desde terminal propia (no dejar procesos huérfanos): `backend\.venv\Scripts\python.exe run_server.py` (o `inicio.bat`).
- [ ] Abrir las 6 revistas del demo **con el botón "Forzar nueva medición"** (quedan cacheadas 24 h — la demo ya no depende de red para el núcleo). OBLIGATORIO para RPC/RPP/Ratio Decidendi: sin refresco no tendrán la tarjeta de gemelos ni el mapa (se auditaron antes de existir).
- [ ] `Ctrl+Shift+R` (dos veces) en el navegador → confirmar `v5.10` en Ver fuentes de developer tools.
- [ ] Probar el iframe kNN (buscador embebido) CON internet — buscar una revista de prueba; el buscador del mapa 2D solo sirve para contexto global (link aparte).
- [ ] **Respaldo offline:** capturas PNG de las 6 auditorías + este documento descargado.

**Régimen de red:** núcleo de la demo funciona offline (copia cacheada); probes live + mapa + OpenAlex necesitan internet. Si no hay wifi: mostrar solo cache (declarar: "medición de esta mañana, guardada para ustedes").

**Si algo falla en vivo:** respirar y decir: "el sistema solo muestra datos que pudo verificar; si una fuente no responde, aparece 'no disponible' — eso que usted ve es precisamente el diseño". (Nunca tapar un error con un número.)

---

## PARTE 5 — Líneas rojas (no decir, jamás)

1. No decir que el tier/percentil es de la revista cuando es del portal (decirlo tú primero).
2. No prometer posiciones en Google ni "subir en el ranking".
3. No recomendar enlazado recíproco coordinado (link scheme) — la herramienta lo detecta y lo denuncia, recuerda esa coherencia.
4. No usar distancias del mapa 2D como evidencia numérica.
5. No presentar el "1 enlace" como magnitud (la magnitud es el nº de dominios enlazantes).
6. No inventar precios ni prometer entregables que no existen (informe PDF ejecutivo = aún no construido; ofrecer "informe en markdown" sí existe).
