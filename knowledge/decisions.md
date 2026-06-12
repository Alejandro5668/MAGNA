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
