"""
Protocolo de verificación QA para tareas clasificadas como bug, más la
heurística que decide cuándo aplicarlo. Módulo stdlib-only — sin dependencias
nuevas, sin estado mutable a nivel de módulo (corre desde el thread de fondo
del TUI).
"""
import re
import unicodedata
from pathlib import Path

QA_PROTOCOL = """# Protocolo de verificación QA — obligatorio en este caso

Esta tarea fue clasificada como bug. Nada de lo que sigue es opcional.
Un fix sin verificar no está terminado, no importa lo obvio que parezca el cambio.

## 1. Plan de pruebas — antes de verificar
Escribí el plan antes de ejecutarlo, como lista numerada:
- Camino feliz: el flujo exacto que el ticket dice que falla.
- Casos borde que identifiques para ESTE bug: roles y permisos distintos, datos
  vacíos, datos con volumen, estados previos del registro, filtros por empresa.
Seguí el plan punto por punto y reportá el resultado de cada punto.
Si aparece un caso nuevo durante la verificación, agregalo al plan y decilo.

## 2. Reproducí antes de creerle al ticket
- Reproducí el bug vos mismo, desde cero, antes de proponer un fix.
- El diagnóstico del ticket es una hipótesis, no un hecho: confirmalo o descartalo con evidencia.
- Si no lográs reproducirlo, decilo explícitamente en vez de arreglar a ciegas.

## 3. Verificación en navegador real
- Verificá con `claude-in-chrome` sobre la app corriendo, no leyendo código.
- Revisá la consola (errores JS) y la pestaña de red (status, payload, respuesta),
  además del estado visual.
- Un mensaje de éxito en la UI no es evidencia suficiente.

## 4. Verificación en base de datos
- Si el bug involucra escrituras (INSERT/UPDATE/DELETE), consultá la tabla real
  y mostrá el SELECT y su resultado.
- Verificá el dato, no el mensaje.

## 5. Producción es solo lectura
- En producción: SELECT únicamente.
- Cualquier escritura en producción requiere autorización explícita del usuario
  para este caso puntual. No la asumas.

## 6. Si falta información, pará y preguntá
- Si te falta algo para verificar (backup de la BD del cliente, credenciales,
  usuario de prueba con cierto rol, entorno levantado), pará y pedilo explícitamente.
- No inventes datos ni asumas el estado del entorno.

## 7. Reintentos y escalamiento
- Si la verificación falla, no repitas el mismo intento: usá la evidencia nueva
  (consola, red, BD) para formular una hipótesis distinta.
- Máximo 3 ciclos de fix + verificación.
- Al tercer ciclo fallido, pará y escalá al usuario con: hipótesis actual,
  evidencia recolectada, qué descartaste y qué falta.
- Nunca declares el caso resuelto sin verificación exitosa. Si no verificaste, decilo.

## 8. Suite de regresión (Playwright)
Ubicación obligatoria: `<E2E_DIR>`
- Ese directorio es un proyecto Node independiente, con su propio `package.json`.
- **Nunca** crees `package.json`, `node_modules` ni tests de Playwright dentro del
  repositorio del cliente.
- Si Playwright o sus navegadores no están instalados ahí, instalalos vos en ese
  directorio sin preguntar.
- Si el módulo afectado ya tiene tests ahí, corré esa suite ANTES de confiar en
  una verificación nueva.
- Después de un fix verificado, generá o actualizá el test que cubre este bug y
  dejalo pasando.
- Si la ruta de arriba todavía contiene `<project_id>`, preguntá al usuario cuál
  es antes de crear nada.

## 9. Resultado de la verificación — al cerrar la sesión
Antes de terminar, escribí este archivo:
`<QA_RESULT_DIR>/TICKET.json`, donde `TICKET` es el ticket de Jira de esta tarea
en MAYÚSCULAS (por ejemplo `ABC-123.json`).

    {
      "verified": true,
      "attempts": 2,
      "ticket_id": "ABC-123",
      "test_plan": ["camino feliz: ...", "borde: rol supervisor ..."],
      "evidence": "qué probaste y cómo confirmaste el resultado"
    }

- `verified`: `true` solo si la verificación en navegador (y en BD si aplica) pasó.
  Si falló o no llegaste a verificar, `false`.
- `attempts`: cantidad de ciclos fix + verificación que hiciste (1 a 3).
- Si esta tarea no tiene ticket de Jira, no escribas el archivo.
- No lo escribas antes de terminar de verificar.
"""


def render_qa_protocol(project_id: int | None = None) -> str:
    """Resuelve los sentinelas de rutas del protocolo. str.replace, no format —
    el bloque contiene llaves literales del ejemplo JSON."""
    base = Path.home() / ".mycontext"
    pid = str(project_id) if project_id is not None else "<project_id>"
    return (
        QA_PROTOCOL
        .replace("<E2E_DIR>", str(base / "projects" / pid / "e2e"))
        .replace("<QA_RESULT_DIR>", str(base / "qa_results"))
    )


_REOPEN_MARKER = "ticket reabierto"

_BUG_KEYWORDS = (
    # sustantivos
    "bug", "bugs", "error", "errores", "falla", "fallas", "fallo", "fallos",
    "defecto", "incidencia", "incidente", "regresion", "excepcion", "traceback",
    # verbos / acciones
    "arreglar", "arregla", "corregir", "corrige", "correccion", "fix", "hotfix",
    "solucionar", "reparar", "reabierto", "reabrir", "rechazado", "devuelto",
    # síntomas
    "roto", "rota", "rompe", "rompio", "crashea", "se cae", "se cuelga",
    "se traba", "no funciona", "no anda", "no carga", "no guarda", "no muestra",
    "no aparece", "no actualiza", "no elimina", "no envia", "no responde",
    "no valida", "no filtra", "no deja", "no calcula", "no coincide",
    "pantalla en blanco", "error 500", "timeout", "duplicado", "duplicados",
    "incorrecto", "incorrecta", "mal calculado", "dato erroneo",
)

_BUG_RE = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in _BUG_KEYWORDS) + r")\b")


def _normalize(text: str) -> str:
    """Minúsculas, sin acentos y con espacios colapsados — para que 'corrección'
    y 'correccion' matcheen igual y las frases de varias palabras funcionen."""
    folded = unicodedata.normalize("NFD", text.lower())
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return " ".join(folded.split())


def is_bug_task(desc: str, jira_data: dict | None = None) -> bool:
    """Heurística por palabras clave sobre la descripción de la tarea y, si hay,
    el summary/description de Jira. Función pura: sin estado, sin I/O —
    corre en el thread de fondo del TUI."""
    parts: list[str] = [desc or ""]
    if isinstance(jira_data, dict):
        for key in ("summary", "description"):
            value = jira_data.get(key)
            if isinstance(value, str):
                parts.append(value)

    text = _normalize(" ".join(parts))
    if not text:
        return False
    # Una reapertura es, casi siempre, un fix que falló — señal positiva por sí sola
    if _REOPEN_MARKER in text:
        return True
    return bool(_BUG_RE.search(text))
