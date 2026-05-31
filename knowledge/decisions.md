# Decisiones Técnicas

Registro de cada decisión de arquitectura o tecnología con su justificación.
Formato: **decisión** → **por qué** → **alternativas descartadas**.

---

## DEC-001 — SQLite sobre PostgreSQL o MongoDB

**Decisión:** Usar SQLite como almacenamiento del knowledge store.

**Por qué:** AICLI es una herramienta personal local. No hay múltiples usuarios, no hay
servidor, no hay necesidad de concurrencia pesada. SQLite funciona como un archivo en
`~/.mycontext/` — zero configuración, zero mantenimiento, portable entre máquinas.

**Alternativas descartadas:**
- PostgreSQL: requiere servidor corriendo, overkill para una CLI personal
- MongoDB: añade complejidad de schema-less que no necesitamos; nuestros datos son estructurados
- JSON plano: no tiene queries, índices, ni transacciones; escala mal cuando hay muchos módulos

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
