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

## DEC-019 — Diagnóstico automático de Claude Code no encontrado

**Decisión:** Cuando `lanzar_claude()` falla con FileNotFoundError, en vez de mostrar
un error genérico, busca `claude.cmd` en rutas conocidas de Windows (APPDATA/npm/,
LOCALAPPDATA/Programs/Claude/), muestra diagnóstico específico y ofrece reintentar.
Si encuentra `claude.cmd` aunque no esté en PATH, lo lanza directamente con ruta completa.

**Por qué:** El `.exe` de AICLI corre con un PATH diferente al de la terminal del usuario.
Claude puede estar instalado y funcionar en PowerShell pero ser invisible para el `.exe`.
El diagnóstico elimina la fricción de arranque para usuarios nuevos.
