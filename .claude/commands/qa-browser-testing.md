Ejecutá un pase completo de QA (funcional + revisión de código) sobre el bug/feature/cambio indicado, y una vez terminado el análisis completo, aplicá la corrección.

## Reglas duras
- Contra CUALQUIER base de datos de PRODUCCIÓN: solo lectura, siempre, sin excepción. Contra bases LOCALES o de TEST: lectura y escritura libres.
- El análisis (repro, verify, review de código) es de SOLO LECTURA: no edites, no hagas `git add/commit`, no corras migraciones. Recién editás en la Etapa de Corrección, y solo después de terminar repro + verify + review.
- Los logs de debug que agregues durante la Etapa de Corrección son temporales: quitalos todos antes de reportar terminado — el diff final no debe tener prints/console.logs de depuración ni comentarios "// removed".
- Nunca hagas `git commit`/`push`/`fetch`/`pull`/`reset --hard`/`checkout <otra rama>` vos mismo — aplicá la corrección y avisá; el usuario revisa y commitea.
- Nunca inventes un resultado: si quedás bloqueado (login, datos faltantes, red caída, alcance ambiguo), reportá `blocked` y por qué.
- No dispares diálogos nativos de JS (`alert/confirm/prompt`) — congelan la sesión del navegador. Usá `console.log` + lectura de consola en su lugar.

## Detección de entorno y herramientas
- URL: tomala automática de la configuración del proyecto (env vars, `.env`, `docker-compose.yml`). Si no está configurada en ningún lado, preguntá.
- Base de datos: preguntá SIEMPRE, en cada corrida — mostrá la configurada por defecto como sugerencia, pero nunca la asumas sin confirmación explícita.
- Si el proyecto tiene sus propios comandos de lint/test/typecheck (Makefile, scripts de package.json, config de CI), corrélos primero — señal rápida y gratis antes de tocar el navegador a mano.
- Si hay índice de CodeGraph (`.codegraph/`), usalo para blast radius — encontrar callers reales en vez de adivinar qué más revisar.
- Cualquier otro dato que falte para probar (credenciales, pasos del ticket, fixture de test): preguntá, no asumas.

## Pasos
1. Cargá las herramientas core de claude-in-chrome (`tabs_context_mcp`, `navigate`, `computer`, `read_page`, `tabs_create_mcp`) más `read_console_messages`/`read_network_requests` para debug.
2. Setup eficiente: corré los comandos propios del proyecto (test/lint/typecheck) y sacá el blast radius de CodeGraph de lo que cambió.
3. Resolvé el entorno: URL automática, BD siempre preguntada. Iniciá sesión si el flujo lo requiere (preguntá credenciales si no las tenés).
4. Reproducí los pasos reportados tal cual, sin acortar el camino.
5. Verificá de forma exhaustiva: camino feliz + edge cases obligatorios (input vacío/inválido, permisos, concurrencia, recarga a mitad de flujo, límites/paginación) + regresión en features adyacentes al código tocado + confirmación de datos vía DB de solo lectura cuando aplique.
6. Si hubo código tocado, corré una revisión de:
   - **Seguridad** — categorías bloqueantes: `sql_injection`, `command_injection`, `path_traversal`, `unsafe_deserialization`, `credential_exposure`, `sensitive_data_exposure`, `auth_bypass`, `authorization_bypass`, `xss`, `ssrf`, `exceptional_conditions` (manejo de errores: excepciones tragadas en silencio, fail-open, lógica que sigue de largo tras un error que debería frenar — categoría nueva de OWASP Top 10 2025). Si ya hay una skill `security-review`/`simplify`/`ponytail-review` disponible en la sesión, usala en vez de reinventar esto.
   - **Calidad/reutilización** — duplicación (indicá qué lógica ya existente debió reutilizarse en vez de crear código nuevo), código muerto (verificá con CodeGraph antes de marcarlo), abstracciones innecesarias, desvíos de convención. Esto es siempre asesoramiento, nunca bloquea el veredicto por sí solo.
   - Alcance SIEMPRE limitado al diff/archivos tocados, nunca el repo completo.
7. Ante cualquier falla o hallazgo: capturá screenshot + consola + red antes de reportar — la evidencia no es opcional.
8. Si algún paso falla 2-3 veces seguidas, parate y preguntá en vez de reintentar a ciegas.
9. **Etapa de Corrección** — solo después de que los pasos 5 y 6 estén completos y se haya confirmado un problema real. Usá todo lo que tengas a mano para encontrar la causa raíz: agregá logging temporal (Python `logging`, `console.log` + lectura de consola, lecturas extra de DB) alrededor de la zona sospechosa, reproducí de nuevo, leé los logs, acotá la causa. Aplicá la corrección solo en los archivos realmente implicados — sin limpieza no relacionada. Después quitá todos los logs de debug que agregaste y reproducí una vez más limpio para confirmar que la corrección se sostiene sin el andamiaje de debug. Además, volvé a pasar el checklist de regresión del paso 5 (features adyacentes al código que tocaste) sobre el código YA corregido — no alcanza con que el bug original quede resuelto, la corrección no debe romper nada de lo que sí funcionaba.
10. Si el fix fue grande o el hallazgo de seguridad era serio, corré `/judgment-day` sobre el diff de la corrección antes de avisar que terminaste — es un chequeo adversarial opcional (dos jueces ciegos independientes), autocontenido, no hace falta para fixes chicos.
11. Avisá explícitamente cuando la corrección esté terminada: qué estaba mal, qué archivos cambiaron, y que queda lista para revisión/commit del usuario — nunca un simple "listo" sin resumen.

## Formato de salida
Reportá de forma estructurada:
- `status`: `pass` | `fail` | `blocked`
- `steps`: qué se hizo realmente
- `expected` vs `actual`
- `evidence`: referencias a screenshots/consola/red
- `db_reads`: queries de solo lectura ejecutadas, si aplica
- `security`: hallazgos (categoría, archivo, línea, detalle)
- `quality`: hallazgos (tipo, archivo, línea, detalle, `existing`: qué lógica reutilizable ya cubría esto)
- `fix`: `{applied, files, root_cause, summary}` — solo una vez corrida la Etapa de Corrección
- `blocked_reason`: solo si `status: blocked`
