# Decisiones Técnicas

Registro de cada decisión de arquitectura o tecnología con su justificación.
Formato: **decisión** → **por qué** → **alternativas descartadas**.

---

## DEC-001 — SQLite sobre MySQL

**Decisión:** Usar SQLite como almacenamiento del knowledge store.

**Por qué:** SQLite no requiere servidor, no requiere credenciales, y el archivo de base
de datos vive junto al knowledge store en `~/.mycontext/`. Para uso personal y de fase
inicial, la simplicidad operativa vale más que las capacidades extra de MySQL. El
desarrollador no tiene que mantener un servidor corriendo para usar la herramienta.

**Alternativas descartadas:**
- MySQL: considerado inicialmente por disponibilidad de servidor local, descartado porque
  agrega fricción operativa innecesaria en Fase 1 — credenciales en .env, servidor que
  debe estar corriendo, PyMySQL como dependencia extra
- PostgreSQL: más complejo aún que MySQL para este caso de uso
- MongoDB: schema-less innecesario; los datos son estructurados
- JSON plano: sin queries, índices ni transacciones

**Nota:** El código en `aicli/db/__init__.py` aún usa MySQL y debe ser actualizado.
La migración es trivial: cambiar `DATABASE_URL` a `sqlite:///{home}/.mycontext/ctx.db`
y eliminar las variables de entorno `DB_*` del `.env`.

**Deuda técnica conocida hacia Fase 2:** SQLite es un archivo local. En Fase 1 (uso
personal) esto es una ventaja — sin servidor, sin configuración. Pero en Fase 2 (equipos),
la API REST no puede leer un SQLite que vive en la máquina de cada desarrollador.
Cuando se construya el portal web para equipos, la BD deberá migrarse a PostgreSQL o
MySQL en un servidor compartido. SQLModel hace esta migración trivial: solo cambia
el `DATABASE_URL`, los modelos y queries no cambian.

---

## DEC-002 — Typer sobre Click o argparse

**Decisión:** Usar Typer para la estructura de comandos CLI.

**Por qué:** Typer usa type hints de Python para definir comandos y argumentos — menos
código boilerplate, `--help` automático bien formateado, y autocompletion en shells sin
configuración extra. Es el sucesor moderno de Click del mismo autor.

**Alternativas descartadas:**
- Click: más verboso, requiere decoradores más complejos, no aprovecha type hints modernos
- argparse: stdlib pero muy verboso; el help generado es inferior
- Fire: demasiado mágico; difícil de controlar el comportamiento exacto de la CLI

---

## DEC-003 — SQLModel sobre SQLAlchemy puro o Peewee

**Decisión:** Usar SQLModel como ORM.

**Por qué:** SQLModel combina SQLAlchemy (ORM maduro) con Pydantic (validación de datos).
Define el modelo una sola vez y sirve tanto como tabla de base de datos como como schema
de validación. Creado por el autor de FastAPI — la misma filosofía de type hints primero.

**Alternativas descartadas:**
- SQLAlchemy puro: más flexible pero más verboso; necesitaríamos Pydantic aparte para validación
- Peewee: más simple pero ecosistema más chico y menos integración con type hints
- TinyDB: document store, no relacional; perdemos la capacidad de hacer queries SQL útiles

---

## DEC-004 — Almacenamiento en ~/.mycontext/ fuera de repos

**Decisión:** Todo el knowledge store vive en `~/.mycontext/`, nunca dentro de repos de clientes.

**Por qué:** AICLI sirve a múltiples proyectos de clientes. Si el knowledge store viviera
dentro de cada repo, contaminaríamos repos externos con archivos personales, tendríamos
que agregar entradas al .gitignore de cada proyecto, y el conocimiento quedaría fragmentado.
Centralizado en home, el conocimiento de todos los proyectos es accesible desde cualquier
directorio.

**Alternativas descartadas:**
- Una carpeta `.aicli/` por proyecto: contamina repos, conocimiento fragmentado
- XDG_DATA_HOME: más correcto en Linux pero complica portabilidad en Windows/Mac

---

## DEC-005 — Contenido de módulos en archivos .md, no en la BD

**Decisión:** El contenido markdown de cada módulo se guarda como archivo `.md` en disco
(`~/.mycontext/projects/<id>/`). La BD solo guarda metadatos y la ruta al archivo.

**Por qué:** Guardar markdown grande como TEXT en SQLite engrosa la BD innecesariamente,
mezcla datos estructurados con no estructurados, y hace imposible inspeccionar el contenido
sin consultar la BD. Con archivos en disco el contenido es legible directamente, la BD queda
liviana, y si la BD se corrompe el conocimiento no se pierde.

**Alternativas descartadas:**
- Guardar `content` como TEXT en SQLite: BD pesada, no inspectable sin queries, mezcla
  de responsabilidades

---

## DEC-006 — ctx task en lugar de integración Jira en fase inicial

**Decisión:** El comando `ctx task` recibe texto libre del desarrollador en lugar de
integrarse con la API de Jira desde el inicio.

**Por qué:** La integración con Jira agrega una capa de complejidad (OAuth, API keys del
workspace, manejo de errores de red) que bloquearía el uso real del sistema. Con `ctx task`
el flujo core funciona desde el primer día: el desarrollador describe la tarea, AICLI
detecta módulos afectados y entrega contexto a Claude. La integración Jira es una mejora
incremental, no un prerrequisito.

**Alternativas descartadas:**
- Integrar Jira desde el inicio: bloquea el uso real por semanas mientras se configura OAuth
- Integrar Linear/Notion: multiplica la complejidad sin agregar valor en esta fase

---

*DEC-005 corregida en conversación: la decisión original de guardar `content` en SQLite
fue revertida por el desarrollador al identificar que sería innecesariamente pesado.*

---

## DEC-007 — Señal de frescura con timestamp Unix para evitar re-documentación innecesaria

**Decisión:** El modelo `Module` incluye un campo `last_updated_at: float` (Unix timestamp).
Antes de llamar a Claude para documentar un módulo, se compara ese valor contra
`os.path.getmtime(archivo_fuente)`. Si el archivo no cambió desde la última documentación,
se salta la llamada a Claude completamente.

**Por qué:** Llamar a Claude en módulos que no cambiaron desperdicia tokens y tiempo.
En un proyecto con 15 módulos donde solo cambiaron 2, el flujo ingenuo haría 15 llamadas
(~45 segundos). Con la señal de frescura hace 2 (~6 segundos). Esto permite que el usuario
corra `ctx init` libremente al inicio de cada sesión como hábito — sin miedo al costo.

**Regla de actualización:** `last_updated_at` se setea a `time.time()` en el momento exacto
en que Claude termina de generar la documentación. No cuando el usuario corre el comando,
sino cuando la doc queda escrita en disco.

**Casos especiales:**
- `last_updated_at is None` → módulo documentado antes de esta feature → re-documentar siempre
- Archivo fuente no existe → no hacer nada, no es un error
- Módulo no existe en BD → documentar siempre (es nuevo)

**Implementación:**
```python
# La comparación central
def modulo_necesita_actualizacion(file_path, proyecto_path, modulo_existente):
    if modulo_existente is None or modulo_existente.last_updated_at is None:
        return True
    ruta = proyecto_path / file_path
    if not ruta.exists():
        return False
    return os.path.getmtime(ruta) > modulo_existente.last_updated_at
```

**Dónde aplica:**
- `ctx init` sobre proyecto ya registrado: salta módulos sin cambios, re-documenta los modificados,
  detecta archivos nuevos como módulos adicionales
- `ctx module add` sobre módulo existente: en lugar de error "ya documentado", aplica la misma
  lógica — si cambió, actualiza; si no cambió, informa que está al día

**Alternativas descartadas:**
- Hash del contenido del archivo: más preciso pero más lento (leer y hashear cada archivo)
  y overkill para este caso de uso
- Guardar fecha como string: requiere conversión para comparar; float es directo
- Siempre re-documentar: desperdicia tokens en archivos que no cambiaron
- Nunca re-documentar automáticamente: la doc decae y se vuelve inútil

---

## DEC-008 — Frontend Next.js como portal de documentación organizacional

**Decisión:** En Fase 2, la documentación generada por la CLI se expone a través de un
portal web construido en Next.js. Este portal es la interfaz principal para todos los
stakeholders que no son desarrolladores: gerentes, QA, arquitectos, nuevos integrantes.

**Por qué:** La documentación generada por la CLI vive en carpetas locales de cada
desarrollador, inaccesible para el resto de la organización. Un frontend convierte AICLI
de herramienta de desarrollador a plataforma de conocimiento organizacional. Las empresas
no solo quieren documentación técnica — quieren darle uso a esa documentación desde
múltiples áreas, sin depender de que alguien abra una terminal.

**Componentes del frontend:**
- Portal de documentación estructurada por módulos y por proyecto
- Buscador sobre toda la base de conocimiento
- Chatbot IA con RAG: el usuario pregunta en lenguaje natural, el sistema busca módulos
  relevantes en la BD, lee sus `.md` y responde con Claude API como motor
- Diseño personalizable por empresa (colores, logo, dominios)
- Acceso por roles: no toda la documentación es para todos los usuarios

**Arquitectura que conecta CLI con frontend:**
```
CLI (Python)
  └── genera docs → MySQL + archivos .md en ~/.mycontext/
                          ↓
                    API REST (FastAPI)
                          ↓
                   Frontend Next.js
                     ├── Portal de módulos por proyecto
                     ├── Buscador full-text
                     └── Chatbot IA (RAG sobre los .md)
```

**El chatbot es RAG, no magia:** flujo concreto:
1. Usuario pregunta: "¿Cómo funciona el módulo de pagos?"
2. Sistema busca en MySQL los módulos más relevantes por nombre/descripción
3. Lee el contenido de esos `.md`
4. Llama a Claude API con ese contenido como contexto
5. Devuelve la respuesta al usuario en la interfaz

**Decisiones de schema que hay que tomar ahora (antes de que sea tarde):**
El modelo `Module` necesita dos campos adicionales para que el frontend los pueda usar:
- `category: str` — área del sistema (ej: "backend", "frontend", "infraestructura", "negocio")
- `domain: str | None` — dominio funcional (ej: "autenticación", "pagos", "reportes")
Agregarlos ahora evita una migración costosa cuando el frontend esté en desarrollo.

**Timing:** Este componente es Fase 2 — no se implementa hasta que la CLI esté terminada
y validada con usuarios reales. Una interfaz sobre documentación incompleta destruye la
confianza antes de construirla.

**Alternativas descartadas:**
- Docusaurus (mencionado en el PDF): solución estática, no permite chatbot IA ni personalización
  dinámica por empresa, no se conecta a una BD viva
- Notion/Confluence como destino: dependencia de terceros, sin chatbot propio, sin control
  sobre el modelo de datos
- Solo CLI sin frontend: válido para Fase 1 pero no escala a empresas que necesitan acceso
  para múltiples áreas sin conocimientos técnicos

---

## DEC-009 — Documentación espeja la estructura del proyecto

**Decisión:** Los archivos `.md` de documentación se almacenan replicando la estructura
de rutas del proyecto. `pagos/PagosController.php` genera `~/.mycontext/projects/<id>/pagos/PagosController.md`.

**Por qué:** Consistencia total entre la ruta del archivo fuente y la ruta del documento.
`ctx module add pagos/X.php` → `pagos/X.md`. `ctx task --archivo pagos/X.php` → lee `pagos/X.md`.
El desarrollador usa el mismo patrón `modulo/archivo.php` en todos los comandos.

**Alternativas descartadas:**
- Archivos planos `nombre_modulo.md`: no relaciona visualmente la doc con el archivo fuente

---

## DEC-010 — analizar_y_documentar: una sola llamada en vez de N+1

**Decisión:** `ctx init` hace UNA sola llamada a Claude que identifica módulos Y genera
su documentación en la misma respuesta (campo `documentation` en el JSON).

**Por qué:** El flujo anterior (1 llamada para identificar + N llamadas para documentar)
tardaba 15 minutos en un proyecto Next.js con 15 módulos — 16 llamadas API secuenciales
con `time.sleep(4)` entre cada una. La nueva arquitectura tarda ~25 segundos.

**Alternativas descartadas:**
- Batching paralelo con ThreadPoolExecutor: innecesario si una sola llamada alcanza

---

## DEC-011 — Tres modos de ctx init para proyectos grandes

**Decisión:** `ctx init` tiene tres modos explícitos para proyectos con más de 500
archivos de código: `--zona`, `--reciente`, `--arquitectura`. Sin modo explícito,
muestra una guía interactiva con questionary.

**Por qué:** Documentar 11.000 archivos en una sola llamada es inviable. El desarrollador
necesita elegir conscientemente el alcance de la documentación según su tarea actual.

**Alternativas descartadas:**
- Auto-documentar todo siempre: 480.886 tokens en una llamada → rate limit garantizado
- Solo mostrar mensaje de error: no ayuda al usuario a saber qué hacer

---

## DEC-012 — ctx init --arquitectura lee código real de cada carpeta

**Decisión:** El modo `--arquitectura` escanea carpetas de nivel 1 que tienen archivos
de código directamente adentro (patrón `modulo/`), lee los archivos más representativos
de cada carpeta (priorizando los que tienen el nombre de la carpeta en el stem), y le
pasa ese código real a Claude. Lee máximo 500 chars por archivo para control de tokens.

**Por qué:** La versión anterior contaba archivos por carpeta y le pasaba a Claude solo
números y nombres. Claude generaba "áreas arquitectónicas" vagas sin ver el código.
Con código real, Claude discrimina módulos de negocio vs infraestructura y genera
documentación basada en lo que realmente hace cada módulo.

**Alternativas descartadas:**
- Leer 1.500 chars por archivo: ~22.500 tokens solo en muestras → cerca del rate limit
- Heurística "3 archivos más pequeños": el más pequeño puede ser `config.php`, no el controlador principal

---

## DEC-013 — Blocklist EXTENSIONES_NO_CODIGO en vez de allowlist

**Decisión:** En vez de una lista de extensiones de código conocidas (`.py`, `.php`, `.js`...),
se usa una blocklist de lo que definitivamente NO es código (imágenes, fuentes, binarios).
Todo lo que no esté en la blocklist se considera potencialmente código.

**Por qué:** La allowlist siempre queda corta — `.blade.php`, `.vue`, `.svelte`, `.dart`,
`.ex` no estaban. La blocklist es más robusta: cuando aparece un lenguaje nuevo, funciona
sin tocar AICLI.

---

## DEC-014 — .gitignore como fuente de verdad para archivos a ignorar

**Decisión:** `_cargar_ignorar()` lee el `.gitignore` del proyecto y extrae patrones
simples (sin wildcards) para combinarlos con un mínimo universal (`.git`, `node_modules`,
`.venv`, `__pycache__`).

**Por qué:** El proyecto ya sabe qué es ruido. Una lista estática en AICLI siempre
asume convenciones que no todos los proyectos siguen. Un proyecto PHP puede tener su
build en `public/` en vez de `dist/`. Con `.gitignore`, funciona automáticamente.

---

## DEC-015 — Extended thinking para detección de módulos en ctx task

**Decisión:** La llamada de detección de módulos relevantes usa
`thinking={"type": "enabled", "budget_tokens": 2000}`.

**Por qué:** Sin extended thinking, Claude hace asociación superficial de palabras entre
la tarea y los nombres de módulos. Con thinking, razona: "esta tarea dice X, eso implica
tocar Y, que conecta con Z...". La selección pasa de buena a quirúrgica.
Costo extra: ~$0.003 por invocación de `ctx task`.

---

## DEC-016 — Task brief generado antes de lanzar Claude Code

**Decisión:** Después de detectar módulos relevantes, `ctx task` hace una segunda llamada
rápida (max_tokens 512) para generar un plan técnico de 5-8 líneas. Este brief se
incluye en `session_context.md` entre el contexto de módulos y la descripción de la tarea.

**Por qué:** Claude Code actualmente recibe documentación + tarea y empieza a explorar.
Con el brief, recibe documentación + plan + tarea. La diferencia es entre arrancar desde
cero vs arrancar con el análisis ya hecho.

---

## DEC-017 — ctx task acepta --archivo con la ruta del problema

**Decisión:** `ctx task` acepta `--archivo modulo/archivo.php`. Ese archivo:
1. Se pasa al prompt de detección como "el problema ocurre específicamente aquí"
2. Si tiene un módulo documentado con ese `file_path`, se incluye siempre en el contexto
   sin importar si el filtrado de relevancia lo habría excluido
3. Se incluye explícitamente en el `session_context.md` como "Archivo de entrada"

**Por qué:** El desarrollador sabe exactamente en qué archivo está el bug. Pasarlo
elimina la ambigüedad en la detección y ancla el plan técnico al archivo correcto.

---

## DEC-018 — ctx module add acepta solo la ruta

**Decisión:** `ctx module add modulo/archivo.php` — sin argumento de nombre.
El nombre del módulo se deriva del stem del path (`PagosController` de `pagos/PagosController.php`).

**Por qué:** Consistencia con el patrón `modulo/archivo.php` que usa toda la CLI.
Pedir nombre y ruta por separado era redundante — el nombre siempre debería ser el
nombre del archivo sin extensión.

---

## DEC-020 — documentar_arquitectura: top 15 carpetas por densidad, max_tokens 8000

**Decisión:** `documentar_arquitectura()` ordena las carpetas de nivel 1 por cantidad de
archivos de código directos (descendente) y toma las 15 primeras. El límite de output
sube de 6000 a 8000 tokens. La documentación por módulo se limita a 3 secciones concisas.

**Por qué:** En el proyecto PHP de empresa (14.000 archivos), la llamada anterior llegó
exactamente a 6000 tokens y el JSON quedó truncado. Las carpetas con más archivos directos
son casi siempre los módulos de negocio principales — es el mejor heurístico disponible
sin leer el código. El límite de 15 módulos × ~250 tokens/módulo = ~3.750 tokens de output,
bien por debajo de 8000.

---

## DEC-021 — ctx file: documentación en profundidad de una zona

**Decisión:** `ctx file <carpeta>` reemplaza `ctx init --zona`. Lee 1000 chars de los
5 archivos más relevantes de la zona (priorizando los que tienen el nombre de la carpeta
en el stem, luego por tamaño descendente). El prompt incluye sección explícita de
"Queries SQL y tablas involucradas". Máximo 8 componentes por zona.

**Por qué:** `--zona` era un flag de `ctx init` — poco visible y conceptualmente acoplado
a la inicialización. `ctx file` es un comando dedicado que el usuario elige cuando quiere
profundizar en una zona antes de un ticket. Los 1000 chars (vs 500 del arquitectura)
permiten ver la estructura de clase y el primer método completo.

**Error handling:** Si `documentar_zona()` falla (JSON truncado u otro), muestra error
claro y vuelve al menú sin matar la CLI.

---

## DEC-022 — ctx archive: análisis profundo de archivo individual

**Decisión:** `ctx archive <ruta>` reemplaza `ctx module add`. Lee hasta 3000 chars del
archivo real. El prompt pide: funciones con parámetros, queries SQL con nombres exactos
de tablas, dependencias directas, patrones observados. No tiene límite artificial de tokens.

**Por qué:** `ctx module` con su flujo de `generar_contenido_modulo` leía el fuente
completo pero el prompt era genérico. `ctx archive` está orientado a archivos PHP: pide
explícitamente el `$querys[]`, los alias exactos del SELECT, y los métodos públicos con
sus parámetros — lo que realmente necesita Claude Code para trabajar sin asumir nada.

---

## DEC-023 — ctx sync: sincronización post-tarea con git

**Decisión:** `ctx sync` detecta archivos cambiados combinando tres fuentes git:
`diff HEAD --name-only`, `diff --cached --name-only`, `diff HEAD~1 --name-only`.
Para cada archivo: si existe módulo en BD → re-documenta. Si es nuevo → documenta
automáticamente con `analizar_archivo_profundo()`. Al final pregunta por decisiones técnicas
y hace append a `knowledge/decisions.md` con fecha.

**Por qué:** El flujo correcto de trabajo es: ticket → Claude Code trabaja → código cambia →
`ctx sync` actualiza la documentación. Sin este comando, la documentación decae después
de cada tarea. Documentar archivos nuevos automáticamente elimina el paso manual de
`ctx archive` para cada archivo creado durante la tarea.

---

## DEC-024 — ctx init corre arquitectura directamente

**Decisión:** `ctx init` sin flags ejecuta `documentar_arquitectura()` directo. Eliminados:
flags `--zona`, `--reciente`, `--arquitectura`; la guía interactiva de proyecto grande;
el UMBRAL_MODO_ARQUITECTURA. Si el proyecto ya existe en BD, corre actualización incremental.

**Por qué:** El modo arquitectura es el correcto para cualquier proyecto de más de unos
pocos archivos. Los otros modos tenían sentido cuando `ctx init` intentaba documentar
todo — con la nueva arquitectura de comandos (ctx file, ctx sync), cada uno tiene su
responsabilidad y `ctx init` solo necesita hacer una cosa bien.

---

## DEC-025 — ctx proyecto genera PROYECTO.md con IA

**Decisión:** `ctx proyecto` hace una sola llamada Claude usando árbol + módulos ya
documentados (nombres/descripciones) + muestra de `*_querys.php` + muestra de `conf/`.
Genera un PROYECTO.md estructurado en 10 secciones. Lo que puede inferir del código →
lo completa con precisión. Lo que requiere conocimiento humano → escribe
`> pendiente — enriquecé esta sección con tu conocimiento del proyecto`.

**Por qué:** El PROYECTO.md manual (generar prompt → ejecutar en otro Claude → importar)
es innecesariamente complejo. La CLI tiene acceso al código y a los módulos ya analizados —
puede inferir el 70% del conocimiento estructural sin intervención humana. El 30% restante
(reglas no obvias, decisiones acumuladas) se enriquece manualmente si el usuario quiere.

**Almacenamiento:** `~/.mycontext/projects/<id>/PROYECTO.md` — fuera del repo.
`builder.py` lo inyecta automáticamente en cada `session_context.md`.

---

## DEC-026 — rol.md global: comportamiento de Claude Code

**Decisión:** En el primer `ctx init`, se crea `~/.mycontext/rol.md` con instrucciones
de comportamiento para Claude Code. Contenido: idioma español, estilo de respuesta,
rol de senior developer PHP 10+ años, verificación SQL obligatoria (leer `*_querys.php`
antes de cualquier query), impacto multi-tenant, confirmación antes de acciones destructivas.
`builder.py` lo prepende a todo `session_context.md`.

**Por qué:** Sin rol, Claude Code decide su comportamiento solo. Con el rol, cada sesión
arranca con el mismo contrato: responde en español, verifica el esquema antes de escribir
SQL, sigue el patrón existente del archivo. El rol vive en `~/.mycontext/` — editable
por el usuario sin tocar el `.exe`.

---

## DEC-027 — _guardar_modulos: upsert por (project_id, file_path)

**Decisión:** `_guardar_modulos()` busca si ya existe un módulo con el mismo
`(project_id, file_path)` antes de insertar. Si existe → actualiza `content_path`,
`last_updated_at` y `description`. Si no → inserta nuevo.

**Por qué:** El bug conocido: correr `ctx file` dos veces sobre la misma zona creaba
módulos duplicados en la BD con el mismo `file_path`. El upsert elimina la duplicación
sin necesidad de limpiar la BD manualmente.

---

## DEC-028 — Encoding latin-1 para lectura de archivos PHP

**Decisión:** Todas las lecturas de archivos en `indexer.py` usan `encoding="latin-1"`
en lugar de `encoding="utf-8", errors="ignore"`.

**Por qué:** El proyecto PHP de la empresa usa codificación Windows-1252 / ISO-8859-1
(documentado en PROYECTO.md sección 10). Con `utf-8, errors="ignore"`, Python descartaba
silenciosamente todos los caracteres acentuados (tildes, ñ) del código PHP — generando
documentación con strings cortados y contexto incompleto. `latin-1` decodifica
correctamente el rango de bytes Windows-1252 sin pérdida.

---

## DEC-029 — PROYECTO.md en knowledge store, inyectado automáticamente

**Decisión:** El archivo `PROYECTO.md` con conocimiento estructural del proyecto se almacena
en `~/.mycontext/projects/<id>/PROYECTO.md` — dentro del knowledge store, fuera de cualquier
repo. `builder.py` lo lee automáticamente si existe y lo inyecta como segunda sección de
`session_context.md`, entre `rol.md` y la documentación de módulos.

**Por qué:** No puede vivir en la raíz del proyecto PHP — sería commiteado al repo de la
empresa. El knowledge store (`~/.mycontext/`) es exactamente el lugar correcto: privado,
centralizado, fuera de repos.

**Orden en session_context.md:**
1. `rol.md` — comportamiento de Claude
2. `PROYECTO.md` — conocimiento estructural del proyecto
3. Documentación de módulos relevantes
4. Plan de implementación (brief)
5. Archivo de entrada
6. Descripción de la tarea

---

## DEC-030 — Eliminación del orquestador y zone_detector.py

**Decisión:** Se eliminaron `zone_detector.py` (archivo completo) y 6 funciones de
`indexer.py`: `analizar_con_claude`, `analizar_y_documentar`, `_indexar_secuencial`,
`_leer_archivos_zona`, `_analizar_zona`, `indexar_proyecto_orquestado`, `indexar_arbol`,
`indexar_proyecto`. También las constantes `UMBRAL_PROYECTO_ORQUESTADO` y
`UMBRAL_MODO_ARQUITECTURA`.

**Por qué:** Tras la refactorización de comandos, ningún comando en `aicli/commands/`
llamaba a ninguna de estas funciones. El problema que resolvían (documentar proyectos
grandes con agentes paralelos por zona) está ahora resuelto de forma más simple:
`ctx init` → arquitectura top-down en una llamada, `ctx file` → zona específica cuando
el usuario la necesita. Código muerto es deuda — se elimina.

**El patrón sigue siendo válido:** Si en el futuro se necesita un `ctx full` que documente
profundamente todos los módulos en paralelo, el patrón orquestador/zona es el correcto.
Pero no se implementa hasta que haya un caso de uso real que lo justifique.

---

## DEC-031 — Detección de PHP puro sin composer.json

**Decisión:** `detectar_stack()` agrega una heurística final: si no coincidió ningún
indicador conocido, verifica si hay archivos `.php` en la raíz con `any(path.glob("*.php"))`.
Si existe al menos uno, retorna `"php"` en lugar de `"desconocido"`.

**Por qué:** El proyecto de la empresa es PHP puro sin framework — no tiene `composer.json`
(que habría indicado Laravel). Con stack `"desconocido"`, los prompts de Claude no tenían
contexto del lenguaje. Con `"php"`, los prompts incluyen el stack correcto y Claude puede
inferir el patrón `$querys[]`, PHPMailer, EasyUI, etc.

---

## DEC-032 — ctx task --imagen: visión con Claude API via base64

**Decisión:** `ctx task` acepta `--imagen <ruta>`. `describir_imagen()` en `indexer.py`
lee el archivo, lo codifica en base64 y envía un mensaje multipart a `claude-sonnet-4-6`
(bloque `image` + bloque `text`). La descripción técnica generada se inyecta en
`session_context.md` entre el brief y el archivo de entrada, como contexto visual previo
a la tarea.

**Por qué:** El desarrollador a veces tiene una captura de pantalla del bug o del diseño
esperado. Sin imagen, tiene que describir lo visual en texto — impreciso y lento. Con
`--imagen`, Claude Code arranca la sesión habiendo "visto" exactamente lo que hay que
resolver o implementar.

**Formatos soportados:** PNG, JPG, JPEG, WEBP, GIF.
**Alternativas descartadas:** URL externa — requiere que la imagen esté publicada, no funciona con capturas locales.

---

## DEC-033 — Formato del mensaje de Jira generado por ctx sync

**Decisión:** `generar_mensaje_jira()` produce un formato fijo de dos puntos:
`🌱 Causa Raiz` + `🛠️ Solucion Aplicada`, máximo 6 líneas en total. El cuerpo del
mensaje es ASCII puro — sin tildes ni acentos. Los dos emojis son la única excepción.

**Por qué:** Al pegar texto desde la terminal de Windows a Jira, los caracteres acentuados
(tildes, ñ) se corrompen o generan encoding issues. ASCII puro garantiza copia limpia.
Los emojis 🌱 y 🛠️ fueron verificados como renderizables en el Jira de la empresa.
El límite de 6 líneas fuerza síntesis: causa + solución debe caber en un mensaje de
transición de ticket, no en un ensayo.

**Alternativas descartadas:**
- UTF-8 completo con tildes: encoding corruption al pegar desde terminal Windows
- Formato libre sin estructura: los revisores de tickets necesitan distinguir causa vs solución de un vistazo

---

## DEC-034 — return vs raise typer.Exit para errores no fatales en comandos CLI

**Decisión:** Cuando un comando detecta un error de uso (ej: el usuario pasa un archivo
a `ctx file` en lugar de una carpeta), muestra un aviso con `console.print()` y hace
`return`. **No** usa `raise typer.Exit(code=1)`.

**Por qué:** `raise typer.Exit(code=1)` termina el proceso entero — el menú interactivo
muere y el usuario tiene que relanzar `ctx`. `return` devuelve el control al loop de menú:
el usuario ve el aviso y puede elegir la opción correcta sin salir. La diferencia es entre
"la CLI se cerró" y "cometí un error pero sigo aquí".

**Cuándo sí usar typer.Exit:** Solo en errores fatales de configuración (API key ausente,
proyecto no registrado en init) donde continuar en el menú no tiene sentido.

---

## DEC-035 — Sufijos de tipo en archivos de sistema de ~/.mycontext/

**Decisión:** BD renombrada de `ctx.db` a `ctx_bd.db`. Log renombrado de `aicli.log`
a `aicli_log.log`. El sufijo `_bd` y `_log` forma parte del nombre, no es la extensión.

**Por qué:** Al browsear `~/.mycontext/` desde el explorador de archivos o una terminal,
`.db` y `.log` son extensiones que no todos los sistemas asocian a un tipo visible. Con
`_bd` y `_log` en el nombre, el propósito del archivo es obvio incluso si el SO oculta
las extensiones.

**Impacto en usuarios existentes:** Quien tenga `ctx.db` de versiones anteriores necesita
renombrarlo manualmente: `Rename-Item "$env:USERPROFILE\.mycontext\ctx.db" "ctx_bd.db"`.

---

## DEC-036 — Hoja de ruta para soporte multi-stack dinámico

**Decisión pendiente:** La CLI está acoplada al stack PHP/MySQL del proyecto inicial de la empresa.
El desacoplamiento se hará en tres fases cuando haya un segundo proyecto real que lo justifique.
No se abstrae antes — las fases 1 y 2 son ~50 líneas de cambio y no valen el costo sin un caso concreto.

**Tres capas de acoplamiento identificadas:**
1. `_ROL_DEFAULT` en `init.py` — hardcodeado con PHP, MySQL, multi-tenant, `$querys[]`
2. Prompts en `indexer.py` — hints de PHP embebidos en `analizar_archivo_profundo()` y `documentar_arquitectura()`
3. `encoding="latin-1"` en lecturas de archivos — decisión específica del proyecto PHP (ver DEC-028)

**Fase 1 — rol dinámico por stack (bajo esfuerzo)**
`_crear_rol_si_no_existe()` → `_crear_rol_para_stack(stack)`.
Un dict `_ROL_POR_STACK` con keys por stack (`"php"`, `"python"`, `"nextjs"`, `"_base"`).
La sección base (idioma, estilo, confirmación antes de destructivos) es universal.
La sección de stack se agrega encima.

**Fase 2 — prompts stack-aware en indexer.py (esfuerzo medio, junto con Fase 1)**
Agregar un dict de hints por stack en `documentar_arquitectura()` y `analizar_archivo_profundo()`:
```python
hints = {
    "php":    "Buscá $querys[], métodos públicos con parámetros, includes.",
    "python": "Buscá clases, decoradores, funciones públicas.",
    "nextjs": "Buscá componentes, hooks, API routes.",
}.get(stack, "Documentá las funciones y clases principales.")
```

**Fase 3 — rol generado con IA por proyecto (esfuerzo alto, para 5+ proyectos)**
`ctx init` hace una llamada a Claude con stack + árbol + muestra de código y genera
un `rol.md` específico para ese proyecto — captura convenciones que ningún template asume.
Hacer solo cuando los templates estáticos queden cortos con proyectos reales.

**Timing:**
- Ahora → no tocar nada, el proyecto PHP es el validador real
- Próximo proyecto real (no PHP) → Fase 1 + 2 juntas
- Cuando haya 5+ proyectos distintos → Fase 3

---

## DEC-037 — Historial de tickets reabiertos en tickets.json

**Decisión:** Los tickets de Jira reabiertos por QA se persisten en `~/.mycontext/tickets.json`.
Cada entrada tiene una lista de rondas (fecha, archivos tocados, mensaje Jira, motivo de reapertura).
Purga automática de entradas con más de 7 días sin actividad al cargar el archivo.
Un archivo auxiliar `ticket_activo.json` actúa de puente entre `ctx retomar` y `ctx sync`
para pasar el motivo de reapertura sin que el usuario lo tenga que re-ingresar.

**Por qué:** El ciclo real de trabajo incluye tickets que se reabren 2-4 veces.
Sin historial, Claude Code arranca desde cero en cada reapertura — el desarrollador
tiene que re-explicar qué se hizo, por qué falló, y qué hay que cambiar.
Con el historial inyectado en `session_context.md`, Claude arranca con contexto completo
de todas las rondas anteriores.

**Estructura mínima:**
```json
{
  "PROJ-1234": {
    "descripcion": "Validar pagos con monto cero",
    "rondas": [
      {"fecha": "2026-06-18", "archivos_tocados": ["pagos/PagosController.php"],
       "mensaje_jira": "...", "motivo_reapertura": null},
      {"fecha": "2026-06-20", "archivos_tocados": [],
       "mensaje_jira": null, "motivo_reapertura": "QA: falla con descuento aplicado"}
    ],
    "ultima_actividad": 1750000000.0
  }
}
```

**Alternativas descartadas:**
- Un `.md` por ticket: archivos acumulados sin purga automática, más difícil de leer programáticamente
- Guardar en la BD SQLite: mezcla datos de sesión efímeros con conocimiento estructural persistente

---

## DEC-038 — ctx status como vista arquitectónica por carpeta

**Decisión:** `ctx status` muestra los módulos documentados agrupados por carpeta de nivel 1,
ordenados por fecha de última documentación descendente. Solo muestra el proyecto del
directorio actual (no todos los proyectos). Footer estático sugiere `ctx init` si falta una carpeta.

**Por qué:** La versión anterior listaba todos los módulos de todos los proyectos fila por fila.
Con 50+ módulos documentados la tabla se volvía inutilizable. La vista por carpeta es una
arquitectura legible en 5 segundos: el usuario ve qué zonas tiene documentadas y cuándo
fue la última vez que se actualizaron.

**Alternativas descartadas:**
- Detección automática de carpetas no documentadas comparando con disco: requiere escanear
  el proyecto, genera falsos positivos (vendor/, cache/, etc.), duplica lógica de init

---

## DEC-039 — QA adversarial integrado en ctx sync

**Decisión:** Antes de documentar archivos, `ctx sync` ofrece correr un QA de dos pasos:
1. `php -l` en cada archivo PHP cambiado (gratis, sin tokens, para en error de sintaxis)
2. Una llamada Claude API con prompt adversarial: busca fallas, no confirma éxito.
   Output estructurado JSON: `{"riesgos": [...], "veredicto": "ok|revisar|bloqueante"}`

Si el veredicto no es "ok", muestra el panel de riesgos y pregunta si continuar.
El QA es opcional — se puede saltar con N en la primera pregunta.

**Por qué:** El riesgo de Claude Code dándose razón a sí mismo es real. El framing
adversarial ("encontrá por qué puede fallar, no confirmes que funciona") cambia
genuinamente el comportamiento del modelo. El php -l gratis captura el caso más común
(error de sintaxis) antes de gastar tokens en el análisis.

**Costo:** ~3.000-5.000 tokens por sync ≈ $0.02. Salteable cuando el usuario ya probó manualmente.

**Alternativas descartadas:**
- Agente de Claude Code como sub-agente QA: no retorna output estructurado a AICLI,
  no controlable, más caro, diseñado para uso interactivo no batch

---

## DEC-040 — Fix encoding en builder.py y caller.py

**Decisión:** `builder.py` lee archivos `.md` con `errors="replace"` en lugar de
falla silenciosa. `caller.py` simplifica el mensaje del subprocess a una cadena
ASCII pura sin incluir la tarea del usuario.

**Por qué:** Los archivos `.md` generados por Claude pueden contener caracteres Unicode
especiales. En Windows, el encoding del argumento de subprocess falla con caracteres
no-ASCII cuando la tarea tiene tildes o caracteres especiales. La tarea ya está
dentro de `session_context.md` — no necesita repetirse en el argumento del proceso.
`errors="replace"` es más robusto que `errors="ignore"` porque el contenido sigue
siendo legible (reemplaza con `?`) en vez de desaparecer silenciosamente.

---

## DEC-019 — Diagnóstico automático de Claude Code no encontrado

**Decisión:** Cuando `lanzar_claude()` falla con FileNotFoundError, en vez de mostrar
un error genérico, busca `claude.cmd` en rutas conocidas de Windows (APPDATA/npm/,
LOCALAPPDATA/Programs/Claude/), muestra diagnóstico específico y ofrece reintentar.
Si encuentra `claude.cmd` aunque no esté en PATH, lo lanza directamente con ruta completa.

**Por qué:** El `.exe` de AICLI corre con un PATH diferente al de la terminal del usuario.
Claude puede estar instalado y funcionar en PowerShell pero ser invisible para el `.exe`.
El diagnóstico elimina la fricción de arranque para usuarios nuevos.

---

## DEC-041 — _archivos_cambiados: HEAD~1 como fallback, no siempre

**Decisión:** `_archivos_cambiados()` en `sync.py` primero acumula archivos de `git diff HEAD` y `git diff --cached`. Solo si ese conjunto está vacío ejecuta `git diff HEAD~1`. Los tres comandos ya no se corren siempre en unión.

**Por qué:** El flujo anterior hacía unión de los tres comandos siempre. Si el usuario ya había commiteado sus 3 archivos, `git diff HEAD` y `--cached` devolvían vacío, pero `git diff HEAD~1` devolvía los archivos del commit anterior — que podían ser 17 archivos de una sesión distinta. El resultado era que sync documentaba 20 archivos en vez de los 3 reales.

**Alternativas descartadas:**
- Eliminar HEAD~1 del todo: dejaría sin cobertura el caso en que el usuario hace commit antes de correr sync
- Preguntar al usuario cuántos commits atrás mirar: fricción innecesaria

---

## DEC-042 — analizar_archivo_profundo: 8000 chars + actualización incremental con diff

**Decisión:** `analizar_archivo_profundo()` sube de 3000 a 8000 chars de lectura. Acepta dos parámetros opcionales: `diff: str = ""` y `doc_existente: str = ""`. El prompt varía según lo que llega: si hay ambos → actualización incremental ("conservá lo válido, actualizá lo que cambió"); si solo hay diff → documenta sabiendo qué cambió; si ninguno → comportamiento original.

**Por qué:** Con 3000 chars, un archivo PHP real con métodos complejos quedaba cortado — Claude solo veía el `<?php` y las primeras funciones. Los métodos del medio y del final no existían para él. Además, `ctx sync` tenía el diff disponible pero no lo pasaba a la función, así que Claude documentaba el archivo entero desde cero como si fuera la primera vez — perdiendo el conocimiento acumulado de documentaciones anteriores.

**Alternativas descartadas:**
- 5000 chars: sigue siendo insuficiente para controladores PHP grandes
- Siempre reescribir la doc completa: descarta conocimiento previo válido (anotaciones manuales, contexto de sesiones pasadas)

---

## DEC-043 — generar_resumen_caso reemplaza generar_mensaje_jira

**Decisión:** `generar_mensaje_jira()` fue reemplazada por `generar_resumen_caso()` que devuelve `(jira_msg, memoria_dict, tokens)` en una sola llamada. El JSON generado tiene cuatro claves: `jira`, `investigado`, `hecho`, `tener_en_cuenta`. Si recibe `historial_previo` (caso retomado), el mensaje Jira documenta solo esa ronda, no repite el historial.

**Por qué:** Antes había dos audiencias servidas por llamadas separadas: Jira (stakeholders) y la memoria del caso (Claude en futuras sesiones). La misma llamada puede servir a ambas con el mismo contexto. Una sola llamada es más barata, más coherente, y elimina la pregunta "¿Generar mensaje de Jira?" que interrumpía el flujo sin aportar valor.

**Alternativas descartadas:**
- Mantener dos llamadas separadas: mismo costo, más lento, riesgo de inconsistencia entre el mensaje Jira y la memoria
- Eliminar el mensaje Jira: el equipo lo necesita para las transiciones de tickets

---

## DEC-044 — Case card UI: _mostrar_case_card con Rich

**Decisión:** Nueva función `_mostrar_case_card()` en `sync.py` que muestra un Panel de Rich con: archivos modificados (dim, prefijo `·`), separador Rule, y tres secciones con labels con colores distintos — `Investigado` (bold blanco), `Hecho` (bold green), `Tener en cuenta` (bold yellow). El título del panel muestra `TICKET-ID · Ronda N`.

**Por qué:** Antes el flujo pedía una "descripción breve del ticket" como campo de texto libre que nadie quería llenar manualmente. La case card auto-generada reemplaza eso con información estructurada y visualmente clara. El usuario puede verificar en 5 segundos que el resumen es correcto antes de guardar.

**Tener en cuenta:** El campo `tener_en_cuenta` tiene un paso opcional donde el usuario puede agregar contexto que el diff no muestra (restricciones del cliente, acuerdos verbales). Si escribe algo, la card se re-muestra con el contenido actualizado antes de confirmar.

---

## DEC-045 — guardar_ronda con campo memoria estructurada

**Decisión:** `guardar_ronda()` acepta `memoria: dict | None = None`. La ronda en `tickets.json` incluye el dict `{investigado, hecho, tener_en_cuenta}`. `formatear_historial()` muestra los tres campos si existen; si no (rondas viejas sin memoria), muestra el `mensaje_jira` como antes.

**Por qué:** El historial que se inyecta en `ctx retomar` ahora da a Claude los tres puntos exactos que necesita: qué se investigó, qué se hizo, y qué gotchas tener en cuenta — sin que Claude tenga que re-leer el diff completo de rondas anteriores.

**Compatibilidad:** Rondas guardadas antes de esta decisión no tienen el campo `memoria`. `formatear_historial()` maneja ambos formatos.

---

## DEC-046 — ctx retomar muestra solo ID y cantidad de rondas

**Decisión:** El selector de tickets en `ctx retomar` muestra `PROJ-1234  (2 ronda/s)` — sin la descripción del ticket.

**Por qué:** La descripción era texto libre que el usuario había ingresado manualmente y que en muchos casos era genérica o redundante con el ID. El ID del ticket es suficiente para que el desarrollador identifique el caso; el detalle está en el historial que se muestra al seleccionar.

---

## DEC-047 — ctx revision: nuevo comando para críticos de revisión de PR

**Decisión:** `ctx revision` (en `aicli/commands/revision.py`) lee el texto de una revisión de PR pegado en terminal (doble Enter para terminar), parsea únicamente la sección 🔴, y si hay críticos: extrae archivos mencionados con regex, carga el historial del ticket de `tickets.json` (ticket ID extraído del header `[PROJ-NNN]`), carga documentación de los módulos afectados, y lanza Claude Code con el contexto completo.

**Por qué:** El flujo real de trabajo incluye PRs que no pueden mergear por críticos del reviewer. Sin `ctx revision`, el desarrollador tiene que describir los problemas manualmente a Claude — que no sabe nada del ticket ni de los módulos afectados. Con el comando, Claude arranca sabiendo exactamente qué reparar, en qué archivos, y con el historial completo del ticket.

**Parsing:** Solo sección 🔴 (Problemas críticos). Los items de 🟡 con `[bloqueante]` se ignoran — solo los rojos bloquean el merge en el flujo de la empresa. Si 🔴 dice `(Ninguno)` o está vacía, muestra "El PR puede mergear" y sale.

**Alternativas descartadas:**
- Leer review desde archivo .txt: fricción innecesaria para texto que el usuario ya tiene en el clipboard
- Parsear 🟡 bloqueantes también: el equipo solo bloquea en 🔴; los amarillos son opcionales

---

## DEC-048 — QA agent eliminado de ctx sync; solo php -l

**Decisión:** La llamada Claude adversarial ("encontrá por qué puede fallar") fue removida de `ctx sync`. Queda únicamente `php -l` (verificación de sintaxis, sin tokens, sin latencia). El QA real ahora lo hace el reviewer de PR externo, y los críticos se atienden con `ctx revision`.

**Por qué:** El PR reviewer externo ya hace lo que hacía el QA agent pero en el contexto real del PR, con las reglas del equipo, y con formato estructurado. Correr el QA agent antes de subir el PR era redundante: el reviewer lo iba a correr igual. Eliminar el agente ahorra ~$0.02 y ~30 segundos por sync, y elimina una pregunta (`¿Correr QA?`) que interrumpía el flujo.

**Lo que se conservó:** `php -l` en todos los `.php` cambiados. Es gratis, instantáneo, y captura el error más común (sintaxis rota) antes de que el PR siquiera exista.

---

## DEC-049 — Carpeta evidencias/ con captura desde portapapeles y purga automática

**Decisión:** Las imágenes de evidencia se guardan en `~/.mycontext/evidencias/` con nombre `captura_YYYYMMDD_HHMMSS.png`. La captura lee el portapapeles de Windows via PowerShell subprocess (`System.Windows.Forms.Clipboard::GetImage()`), sin dependencias extra. La purga automática de archivos con más de 7 días corre al arrancar AICLI (`_purge_evidence()` en `main.py`). La función `_ask_image()` es el punto de entrada único: pregunta primero si hay captura en portapapeles; si no, cae a ruta manual como fallback.

**Por qué:** El flujo anterior pedía guardar la imagen en una carpeta, copiar la ruta con click derecho y pegarla. Con esta decisión el flujo es: Win+Shift+S → seleccioná el área → AICLI lee el portapapeles automáticamente. Cero pasos manuales. La carpeta `evidencias/` centraliza todas las capturas fuera de repos de clientes, con purga automática para no acumular archivos indefinidamente.

**Implementación:** Solo Windows (PowerShell siempre disponible). No se usa Pillow ni win32clipboard para evitar dependencias adicionales en el `.exe`.

**Alternativas descartadas:**
- Archivo fijo `captura.png`: se sobreescribe si hay dos capturas en la misma sesión
- Pillow `ImageGrab.grabclipboard()`: dependencia adicional que complica el build con PyInstaller
- Pedir ruta siempre: fricción innecesaria cuando el 90% de los casos son capturas recientes

---

## DEC-050 — Identificadores en inglés como estándar de código

**Decisión:** Todos los identificadores del proyecto (nombres de funciones, variables, parámetros, constantes) están en inglés. Los strings visibles para el usuario (mensajes Rich, prompts de questionary, comentarios) permanecen en español. La regla es: **código en inglés, UI en español**.

**Por qué:** El código mezclaba español e inglés sin criterio — `construir_contexto` junto a `build_context`, `modulos` junto a `modules`. Un lector nuevo (o Claude Code) tenía que cambiar de idioma mentalmente a mitad de una función. El estándar único elimina esa fricción y hace el código internacionalmente legible.

**Alcance del cambio aplicado (2026-06-29):** 50+ renombrados en 15 archivos. Ejemplos representativos:
- `construir_contexto` → `build_context`
- `lanzar_claude` → `launch_claude`
- `analizar_archivo_profundo` → `analyze_file_deep`
- `generar_resumen_caso` → `generate_case_summary`
- `EXTENSIONES_NO_CODIGO` → `NON_CODE_EXTENSIONS`
- `MAX_REINTENTOS` → `MAX_RETRIES`
- `obtener_arbol` → `get_tree`

**Lo que NO se renombró:** claves de JSON en disco (`investigado`, `hecho`, `tener_en_cuenta`, `descripcion`) porque cambiarlas rompería archivos `tickets.json` existentes; campos de modelos SQLModel (columnas de BD); nombres de comandos CLI (`sync`, `task`, `init` — son la interfaz pública).

**Alternativas descartadas:**
- Mantener español: incompatible con contribuciones externas y con el uso de Claude Code como asistente de desarrollo
- Todo en español: contradice las convenciones de Python y el ecosistema open source

---

## DEC-051 — Reemplazo de menú questionary por TUI Textual completa

**Decisión:** El menú interactivo con pyfiglet + questionary fue reemplazado por una TUI
completa construida en Textual. El punto de entrada pasa de un loop `questionary.select()`
a `MagnaApp().run()`. Los comandos que antes salían al terminal (suspendían la TUI) ahora
se ejecutan dentro de `CommandOutputScreen` vía `TuiConsole`.

**Por qué:** questionary no tiene acceso a widgets nativos de terminal (RichLog, OptionList,
Sparkline, TabbedContent). El menú era una lista de texto sin feedback visual sobre el
estado del contexto (módulos documentados, actividad reciente). Con Textual, el dashboard
muestra arquitectura en tiempo real, la paleta Noche Estrellada Van Gogh da identidad visual,
y el output de comandos aparece en el mismo panel sin salir a la terminal cruda.

**Arquitectura TUI (Option B — sin suspend):**
- `CommandOutputScreen` (ModalScreen): pantalla que muestra output de comandos en RichLog
- `TuiConsole`: drop-in de Rich Console — enruta `print`/`status` al RichLog vía `call_from_thread`
- `TuiConsole.request_input/confirm`: modales bloqueantes vía `run_coroutine_threadsafe`
- `TuiConsole.suspend_and_run`: `app.suspend()` solo para lanzar Claude Code (subprocess interactivo)
- `sync._sync_impl(ask_fn, confirm_fn)`: callbacks inyectables → questionary o TUI indistintamente
- `task._execute_task(suspend_fn)`: bridge desacoplado del mecanismo de lanzamiento

**Paleta Noche Estrellada (Van Gogh):**
`ACCENT=#FFB703`, `SECTION=#5B8DEF`, `BORDER=#242C45`, `SEC=#AAB4D4`, `MUTED=#5E6A94`

**Fix de concurrencia:** `@work async _worker_cmd` corría comandos directamente en el
event loop de Textual, colisionando con `asyncio.run()` interno de questionary. Solución:
`ThreadPoolExecutor` — el comando corre en un thread separado, la TUI sigue respondiendo.

**Alternativas descartadas:**
- Suspend completo para cada comando: Claude Code necesita suspend (terminal interactivo),
  pero comandos como sync/task que solo leen input y escriben output no lo necesitan.
  Suspend hace que la TUI "desaparezca" y vuelva durante el comando — experiencia rota.
- Subprocess por comando: agrega latencia de proceso, pierde el estado de la TUI entre comandos.

---

## DEC-052 — CommandOutputScreen como ModalScreen con Container 100%×100%

**Decisión:** `CommandOutputScreen` usa `ModalScreen[None]` (no `Screen`). Todos los
widgets del compose están envueltos en `Container(id="co-frame")` con `width: 100%;
height: 100%; background: #000000`. Lo mismo para `CommandScreen`: un `Container(id="cs-frame")`
con `width: 100%; height: 100%` envuelve el contenido centrado.

**Por qué:** En Textual 8.x, el `background` CSS en un `Screen` o `ModalScreen` no garantiza
pintar todas las celdas del terminal. Las celdas donde no hay widgets concretos pueden mostrar
el screen de abajo. Un widget `Container` con `width/height: 100%` sí se renderiza como widget
concreto y pinta todas sus celdas. Con `ModalScreen`, el stack de screens se compone
correctamente — el modal cubre todo el terminal sin que `MainScreen` se cuele por los bordes.

**Alternativas descartadas:**
- `background: #000000` solo en el CSS del screen: no es suficiente en Textual 8.x, el bug
  persistió aun con color opaco correcto.
- Screen regular (no Modal) con background: el Screen mostraba contenido del MainScreen
  en las áreas no cubiertas por widgets.

---

## DEC-053 — Enriquecimiento visual Noche Estrellada: gradiente, hatch y Sparkline animada

**Decisión:** Tres mejoras visuales al dashboard principal:
1. **Logo MAGNA gradiente** — `_gradient_logo()` interpola línea a línea de azul (#5B8DEF)
   a dorado (#FFB703). Devuelve un `rich.text.Text` con colores inline; el CSS de `#logo`
   no necesita `color`.
2. **Hatch puntillismo** — `#left` usa `hatch: "·" #5B8DEF 20%` en lugar de
   `background: transparent`. Los puntos azules tenues simulan la textura de pincelada.
3. **Sparkline sinusoidal animada** — `set_interval(0.25, _animate_spark)` actualiza la
   Sparkline con una doble onda sinusoidal desplazada. `_spark_phase` se incrementa en cada tick.
   El cielo parece ondular como en la pintura de Van Gogh.

**Por qué:** El terminal no puede hacer curvas ni gradientes de pantalla completa, pero sí
puede evocar la atmósfera de la pintura: misma paleta, textura donde hay caracteres (hatch),
y movimiento suave donde el terminal lo permite (Sparkline animada). La combinación de tres
efectos da profundidad visual sin depender de gráficos.

**Alternativas descartadas:**
- Gradiente horizontal (carácter a carácter): demasiado caro computacionalmente para el logo
  completo; el gradiente vertical (línea a línea) da el mismo efecto con una fracción del costo.
- Sparkline con datos reales estáticos: la data de 7 días tiene poca variación visual;
  la onda animada aprovecha mejor el widget y evoca el tema visual de la CLI.

---

## DEC-054 — magna_task_plan: card visual estructurada para el plan de implementación

**Decisión:** `magna_task_plan(console, modules, brief)` en `theme.py` reemplaza a
`magna_panel(console, "Plan de implementación", brief)` en `task.py`. La nueva función
genera un `Panel` con: línea de módulos en azul (#5B8DEF), separador, y cada línea del
plan prefijada con `◆` dorado. Subtitle muestra el modelo y extended thinking.

**Por qué:** El `magna_panel` genérico muestra el brief como texto plano sin estructura
visual. Con `magna_task_plan`, el panel comunica qué módulos están afectados, qué pasos
seguir, y con qué modelo se generó — en una sola vista antes de que Claude Code arranque.

**Alternativas descartadas:**
- Tabla Rich: rigidez de columnas; el brief es texto libre de 4-8 líneas que no encaja bien.

---

## DEC-055 — Imagen eliminada del flow TUI de ctx task; Footer simplificado en CommandOutputScreen

**Decisión A — imagen en TUI:** El flow de `_worker_cmd` para "task" ya no pregunta por imagen
(eliminados `_gather_image_async` y los dos InputModal adicionales). La feature `--imagen`
sigue disponible por CLI directa. `_gather_image_async` fue removida como dead code.

**Por qué:** La pregunta de portapapeles + ruta manual interrumpía el flow de dos pasos
(descripción + archivo) con dos modales extra que el 95% de las veces se saltean. La imagen
sigue siendo una feature válida para CLI scripted, no para el flujo interactivo TUI.

**Decisión B — Footer de CommandOutputScreen:** El widget `Footer` fue removido del
`CommandOutputScreen`. El hint de navegación se muestra en `#co-done` Static con:
`── [esc dorado] [volver en SEC]`. El `Footer` mostraba "Back" en inglés con key invisible
(`#5E6A94` sobre negro); el Static directo da control total sobre el markup.

**Alternativas descartadas:**
- Mantener Footer con CSS override: la key badge de Textual Footer tiene su propio renderizado
  interno que no respeta colores de tema sin hacks de CSS complejos.

---

## DEC-056 — Estrategia de ramas: personal + main + feature/

**Decisión:** El repositorio opera con tres tipos de ramas con roles distintos:
- `personal` — rama congelada con el estado estable actual. Es el daily driver del desarrollador.
  Nunca recibe merges automáticos desde `main`. Solo cambios manuales via cherry-pick cuando
  algo de `main` está terminado y probado.
- `main` — rama open source. Recibe todo el trabajo nuevo a través de feature branches.
  Puede tener código experimental o incompleto. No se usa como herramienta de trabajo diario.
- `feature/<nombre>` — ramas temporales de trabajo. Nacen desde `main`, mueren al mergear a `main`.

**Regla del cherry-pick:** Cuando una mejora de `main` vale la pena en `personal`, se porta con
`git cherry-pick <hash>` — solo ese commit, no un merge en bloque. Así `personal` nunca recibe
código experimental involuntariamente.

**Por qué:** MAGNA tiene dos usuarios simultáneos: el desarrollador que lo usa en producción diaria
y el proyecto open source que está en construcción activa. Mezclar ambos en la misma rama garantiza
que tarde o temprano un experimento rompe el flujo de trabajo. Las ramas separadas dan velocidad
al open source sin arriesgar la herramienta de trabajo.

**Alternativas descartadas:**
- Una sola rama `main`: el código experimental bloquea el uso diario.
- Tags para marcar versiones estables: más complejo de operar, requiere disciplina de versioning
  que no aporta valor en esta etapa.

---

## DEC-058 — ticket_activo por PID en lugar de archivo global

**Decisión:** Renombrar `ticket_activo.json` a `ticket_activo_{os.getpid()}.json` — un archivo por proceso de MAGNA.

**Por qué:** Con un archivo global, tres instancias paralelas de MAGNA se pisaban mutuamente el ticket activo. La última en escribir determinaba qué ticket pre-rellenaba `ctx sync` en todas las instancias. Con PID, cada instancia escribe y lee su propio archivo — aislamiento total sin coordinación.

**Implementación:** `_active_path()` en `tickets.py` devuelve la ruta con PID. Las tres funciones (`save_active_ticket`, `read_active_ticket`, `clear_active_ticket`) usan `_active_path()` en lugar de la constante.

**Alternativas descartadas:** Lock files o semáforos: innecesario — el problema era de naming, no de acceso concurrente al mismo archivo.

---

## DEC-059 — openpyxl para Excel adjuntos de Jira

**Decisión:** Usar `openpyxl` (local, sin API) para convertir archivos `.xlsx` adjuntos en Jira a texto markdown antes de inyectarlos en el session_context.

**Por qué:** Excel no requiere comprensión visual ni IA — es texto estructurado en celdas. `read_only=True + data_only=True` lee fila a fila sin cargar el archivo entero en memoria. Gemini u otras APIs añadirían latencia de red para un problema que Python resuelve en milisegundos.

**Límite de 200 filas por hoja:** Protege el contexto de Claude de tablas gigantes. Las primeras 200 filas entregan la estructura y datos más relevantes. Filas truncadas se indican con nota explícita.

**Alternativas descartadas:** Gemini para Excel — innecesario cuando el contenido es texto plano en celdas. Solo tiene sentido para video o PDFs escaneados donde no hay alternativa local razonable.

---

## DEC-060 — pasos_qa en generate_case_summary

**Decisión:** Agregar campo `pasos_qa` al JSON que genera `generate_case_summary()` en `indexer.py`.

**Por qué:** QA siempre pregunta cómo replicar el caso. El desarrollador debe explicarlo manualmente cada vez. Con `pasos_qa`, Claude genera los pasos automáticamente a partir de la tarea y el diff — lenguaje simple, UI-only, máx 5 pasos, sin jerga técnica.

**Formato:** Pasos numerados con acciones en UI ("Ir a X", "Hacer clic en Y", "Verificar que Z"). Orientado a alguien sin conocimientos de programación ni bases de datos.

**Impacto en el prompt:** `max_tokens` subió de 800 a 1000 para acomodar el campo adicional.

---

## DEC-061 — Auto-copy al portapapeles con clip de Windows

**Decisión:** Después de mostrar el mensaje de Jira en `ctx sync`, copiarlo automáticamente al portapapeles usando `clip` (built-in de Windows) via `subprocess.run`.

**Por qué:** La terminal no permite seleccionar texto fácilmente dentro de un Panel de Rich. El usuario tenía que tomar capturas de pantalla del mensaje. Con `clip`, el texto queda listo para Ctrl+V directamente en Jira.

**Implementación:** `subprocess.run("clip", input=full_msg.encode("utf-16le"), shell=True)` — `utf-16le` es el encoding que `clip` espera en Windows. Sin dependencia nueva.

**Contenido copiado:** Mensaje técnico Jira + pasos QA concatenados, separados por salto de línea.

---

## DEC-062 — Fallbacks estándar en @work de Textual

**Decisión:** Todos los workers `@work` async de la TUI deben tener manejo de error explícito. Patrón estandarizado según el tipo de worker.

**Por qué:** Un `@work` que lanza excepción en Textual falla silenciosamente — el usuario no ve nada y puede quedar atrapado en una pantalla sin saber qué pasó.

**Patrones aplicados:**
- `_worker_cmd`: `try/finally` garantiza que `mark_done()` siempre se llama; error visible en CommandOutputScreen antes de cerrar
- `_fill_jira_radar`: `fetch_my_issues` en try/except; error dim en el log del tab AHORA
- `_run` (OnboardingScreen): try/except con `notify()` + `switch_screen(ProjectScreen)` si `init()` o `proyecto()` fallan; pantalla de carga nunca queda colgada
- `_worker_change`: try/except con `notify()` si la BD no responde

**Regla:** Workers cosmético (`_animate_entry`, `_auto_dismiss`) no necesitan fallback — si fallan, el impacto es visual y no bloquea al usuario.

---

## DEC-057 — Transición a open source: arquitectura multi-stack dinámica

**Decisión:** La transición de MAGNA a open source se hace en tres fases. El objetivo es soportar
cualquier stack sin perder la precisión que lo hace útil. La precisión se logra con dos capas
de conocimiento separadas:

**Capa 1 — Stack profile (MAGNA lo infiere automáticamente):**
Configuración técnica por lenguaje: encoding, extensiones, patrones a buscar, ignore extras.
Se implementa como `StackProfile` dataclass en `aicli/services/`.
Perfiles built-in: `php_vanilla`, `laravel`, `nextjs`, `python`, `generic`.
El perfil PHP actual del proyecto de empresa se convierte en `php_vanilla` sin cambios.

**Capa 2 — Company profile (Claude lo genera con el código real):**
Convenciones específicas de la empresa: `$querys[]`, arquitectura multi-tenant, patrones de carpetas,
acuerdos del equipo. Se genera en `ctx init` leyendo muestras del código real y se guarda en
`role.md` y `PROYECTO.md`. Esta capa es lo que hace a MAGNA preciso para cada empresa
independientemente del stack.

**Separación conceptual clave:** Capa 1 es lo que hace a MAGNA genérico. Capa 2 es lo que lo
hace preciso. El estado actual de MAGNA tiene ambas capas pero la Capa 1 está hardcodeada para PHP.
El trabajo open source es separar las dos capas sin tocar la Capa 2 (que ya funciona bien).

**Fases de implementación:**

*OS-1 — Stack profiles como config explícita:*
`StackProfile` dataclass con `encoding`, `hints`, `role_template`, `ignore_extras`.
`ctx init` detecta el stack y selecciona el perfil. El usuario puede override con `--stack`.
La lógica de detección existente (`detectar_stack()`) alimenta la selección de perfil.

*OS-2 — `ctx init` genera role.md con el código real (DEC-036 Fase 3):*
En lugar de `_ROL_DEFAULT` hardcodeado, Claude lee una muestra del código y genera un `role.md`
específico para esa empresa. Para PHP vanilla: descubre `$querys[]`, multi-tenant, EasyUI.
Para Laravel: descubre Eloquent, controladores, blade. Para Next.js: hooks, API routes, estado.
Este `role.md` generado reemplaza al template estático solo en `main` — `personal` mantiene
el `role.md` manual actual que ya está afinado.

*OS-3 — `ctx profile` comando visible:*
Muestra al usuario qué perfil detectó MAGNA y permite editar `role.md` desde la TUI.
La transparencia que necesita una herramienta open source para que la comunidad confíe en ella.

**Por qué esta arquitectura:** La tentación open source es generalizar tanto que la herramienta
funciona para todos pero no es realmente buena para nadie. La Capa 2 (company profile generado
con IA desde el código real) es la defensa contra eso: sin importar el stack, MAGNA aprende
las convenciones específicas de esa empresa y las inyecta en cada sesión de Claude.

**Timing:**
- Ahora → crear rama `personal`, documentar, continuar usando MAGNA sin cambios.
- Próxima sesión de open source → OS-1: `StackProfile` dataclass + perfiles built-in.
- Cuando OS-1 esté estable → OS-2: role.md generado con IA.
- Cuando haya 3+ usuarios externos → OS-3: `ctx profile` comando.

**Alternativas descartadas:**
- CLAUDE.md por proyecto en el repo del cliente: contamina repos externos.
- Config YAML editable manualmente: el usuario promedio no quiere configurar nada; MAGNA
  debe funcionar bien desde el primer `ctx init` sin configuración.
- Soportar todos los stacks desde el inicio: sin usuarios reales de otros stacks, no se puede
  validar si los perfiles funcionan. PHP vanilla primero, luego iterar con feedback real.

---

## DEC-063 — JiraCardModal: card completa en lugar de resumen con conteos

**Decisión:** Rediseñar `JiraCardModal` para mostrar toda la información traída de Jira en un solo modal:
badges (ID · estado · prioridad), asignado a + reportado por, summary en bold, descripción (máx 600 chars
con indicador `(… continúa en Claude)` si se trunca), y lista de adjuntos por nombre con tipo (`[IMG]`/`[XLS]`/`[ATT]`).

**Por qué:** La versión anterior mostraba la descripción truncada a 320 chars y solo conteos de adjuntos
("2 imágenes · 1 Excel"). El usuario no podía verificar si el contenido cargado era el correcto antes de
continuar. El rediseño da visibilidad completa de lo que se inyectará a Claude Code sin requerir
confirmación paso a paso por cada campo.

**Flujo resultante:** `[Ticket ID]` → fetch Jira → `JiraCardModal` (todo en uno) → `[Archivo]` → Claude.
No hay paso de confirmación de adjuntos: siempre se incluyen todos. No hay descripción editable en el
flujo TUI cuando Jira carga correctamente.

**Alternativas descartadas:**
- Modal paso a paso (descripción → confirm → adjuntos → confirm): demasiada fricción para info que el
  usuario ya conoce del ticket.
- Checkboxes para seleccionar adjuntos: complejidad no justificada; si hay un adjunto relevante en Jira
  siempre se quiere incluir.
- Mostrar descripción completa sin límite: modales sin scroll fijo hacen la UI impredecible en terminales
  pequeñas. 600 chars cubre el 95% de descripciones útiles.

---

## DEC-064 — Hints de modales: patrón 2 teclas, colores uniformes, ctrl+enter eliminado

**Decisión:** Todos los modales de la TUI usan exactamente el mismo patrón de hint:
`[bold _ACCENT][KEY][/] [_SEC]acción[/]  [_MUTED]·[/]  [bold _ERROR][esc][/] [_SEC]cancelar[/]`

Teclas de confirmación por modal:
- `InputModal`: `↵`
- `TextAreaModal`: `ctrl+s` (único — `ctrl+enter` eliminado)
- `ConfirmModal`: `↵` (muestra "sí" o "no" según el default)
- `JiraCardModal`: `↵`

**Por qué:** La versión anterior tenía 4–5 opciones en el hint (`y`, `n`, `↵`, `ctrl+↵`, `ctrl+s`) con
colores inconsistentes (`[esc]` en `_SEC` apagado vs teclas de acción en `_ACCENT` brillante). El usuario
no podía identificar rápidamente cuál tecla usar. El nuevo patrón aplica semántica de color: dorado =
avanzar, rojo = cancelar — consistente con el resto de la paleta (ej: `[n]` rojo en ConfirmModal).

`ctrl+enter` eliminado porque Windows Terminal lo intercepta a nivel de terminal antes de que llegue a
Textual, haciendo que el binding nunca dispare. `ctrl+s` es confiable en WT y semánticamente correcto
("guardar/confirmar"). Los shortcuts `y`/`n` del ConfirmModal se mantienen funcionales pero no aparecen
en el hint para reducir ruido.

**Alternativas descartadas:**
- `alt+enter` como alternativa a `ctrl+enter`: también interceptado por WT en algunas configs.
- Mantener los 4–5 hints: cantidad de opciones visibles > 2 en un modal aumenta el tiempo de decisión
  (Ley de Hick).

---

## DEC-065 — Título de terminal: solo el ID del ticket, sin prefijo ni summary

**Decisión:** El título del tab de terminal muestra únicamente el ID del ticket Jira (ej: `SOL-1234`)
cuando se lanza Claude Code desde `ctx task`. Sin prefijo "MAGNA ·", sin summary del ticket.

**Por qué:** Los tabs de Windows Terminal son angostos. El formato anterior `MAGNA · SOL-1234 — Controles
sin tipología en la...` dejaba el ID fuera de la vista al truncarse. El objetivo es que el ID sea siempre
visible de un vistazo al cambiar de tab. El summary del ticket ya viaja en el mensaje inicial a Claude
Code: `[SOL-1234] {summary} — Read {ctx_path}...`, lo que sirve para que Claude genere un nombre de
sesión descriptivo sin contaminar el título del tab.

**Implementación:** `_set_terminal_title(tid)` usando ANSI escape `\033]0;{title}\007` + Win32
`ctypes.windll.kernel32.SetConsoleTitleW(title)` para mayor persistencia en Windows Terminal antes de que
Claude Code arranque y potencialmente sobreescriba el título.

**Alternativas descartadas:**
- Mostrar esta info en `ctx status`: mezcla dos responsabilidades distintas.
- Solo `--editar` sin `--regenerar`: obliga al usuario a saber qué escribir en rol.md.

---

## DEC-063 — JiraCardModal: card completa en lugar de resumen con conteos

**Decisión:** Rediseñar `JiraCardModal` para mostrar toda la información traída de Jira en un solo modal:
badges (ID · estado · prioridad), asignado a + reportado por, summary en bold, descripción (máx 600 chars
con indicador `(… continúa en Claude)` si se trunca), y lista de adjuntos por nombre con tipo (`[IMG]`/`[XLS]`/`[ATT]`).

**Por qué:** La versión anterior mostraba la descripción truncada a 320 chars y solo conteos de adjuntos
("2 imágenes · 1 Excel"). El usuario no podía verificar si el contenido cargado era el correcto antes de
continuar. El rediseño da visibilidad completa de lo que se inyectará a Claude Code sin requerir
confirmación paso a paso por cada campo.

**Flujo resultante:** `[Ticket ID]` → fetch Jira → `JiraCardModal` (todo en uno) → `[Archivo]` → Claude.
No hay paso de confirmación de adjuntos: siempre se incluyen todos. No hay descripción editable en el
flujo TUI cuando Jira carga correctamente.

**Alternativas descartadas:**
- Modal paso a paso (descripción → confirm → adjuntos → confirm): demasiada fricción para info que el
  usuario ya conoce del ticket.
- Checkboxes para seleccionar adjuntos: complejidad no justificada; si hay un adjunto relevante en Jira
  siempre se quiere incluir.
- Mostrar descripción completa sin límite: modales sin scroll fijo hacen la UI impredecible en terminales
  pequeñas. 600 chars cubre el 95% de descripciones útiles.

---

## DEC-064 — Hints de modales: patrón 2 teclas, colores uniformes, ctrl+enter eliminado

**Decisión:** Todos los modales de la TUI usan exactamente el mismo patrón de hint:
`[bold _ACCENT][KEY][/] [_SEC]acción[/]  [_MUTED]·[/]  [bold _ERROR][esc][/] [_SEC]cancelar[/]`

Teclas de confirmación por modal:
- `InputModal`: `↵`
- `TextAreaModal`: `ctrl+s` (único — `ctrl+enter` eliminado)
- `ConfirmModal`: `↵` (muestra "sí" o "no" según el default)
- `JiraCardModal`: `↵`

**Por qué:** La versión anterior tenía 4–5 opciones en el hint (`y`, `n`, `↵`, `ctrl+↵`, `ctrl+s`) con
colores inconsistentes (`[esc]` en `_SEC` apagado vs teclas de acción en `_ACCENT` brillante). El usuario
no podía identificar rápidamente cuál tecla usar. El nuevo patrón aplica semántica de color: dorado =
avanzar, rojo = cancelar — consistente con el resto de la paleta (ej: `[n]` rojo en ConfirmModal).

`ctrl+enter` eliminado porque Windows Terminal lo intercepta a nivel de terminal antes de que llegue a
Textual, haciendo que el binding nunca dispare. `ctrl+s` es confiable en WT y semánticamente correcto
("guardar/confirmar"). Los shortcuts `y`/`n` del ConfirmModal se mantienen funcionales pero no aparecen
en el hint para reducir ruido.

**Alternativas descartadas:**
- `alt+enter` como alternativa a `ctrl+enter`: también interceptado por WT en algunas configs.
- Mantener los 4–5 hints: cantidad de opciones visibles > 2 en un modal aumenta el tiempo de decisión
  (Ley de Hick).

---

## DEC-065 — Título de terminal: solo el ID del ticket, sin prefijo ni summary

**Decisión:** El título del tab de terminal muestra únicamente el ID del ticket Jira (ej: `SOL-1234`)
cuando se lanza Claude Code desde `ctx task`. Sin prefijo "MAGNA ·", sin summary del ticket.

**Por qué:** Los tabs de Windows Terminal son angostos. El formato anterior `MAGNA · SOL-1234 — Controles
sin tipología en la...` dejaba el ID fuera de la vista al truncarse. El objetivo es que el ID sea siempre
visible de un vistazo al cambiar de tab. El summary del ticket ya viaja en el mensaje inicial a Claude
Code: `[SOL-1234] {summary} — Read {ctx_path}...`, lo que sirve para que Claude genere un nombre de
sesión descriptivo sin contaminar el título del tab.

**Implementación:** `_set_terminal_title(tid)` usando ANSI escape `\033]0;{title}\007` + Win32
`ctypes.windll.kernel32.SetConsoleTitleW(title)` para mayor persistencia en Windows Terminal antes de que
Claude Code arranque y potencialmente sobreescriba el título.

**Alternativas descartadas:**
- `MAGNA · SOL-1234`: "MAGNA" consume espacio sin aportar información — el usuario ya sabe que está en
  MAGNA si abrió el tab desde MAGNA.
- `SOL-1234 — summary[:40]`: el summary empuja al ID fuera del área visible del tab (confirmado con
  screenshot del usuario).
