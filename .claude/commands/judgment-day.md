Corré una revisión ciega adversarial de dos jueces sobre: $ARGUMENTS (si no se especifica nada, usá `git diff` — y `git diff --cached` si hay algo staged — como alcance: los cambios sin commitear en el working tree).

Versión autocontenida de "Judgment Day": no depende de ningún plugin, skill externa, CodeGraph ni Engram — solo usa el tool Agent (Task) que ya viene con Claude Code. Portable a cualquier instalación, sin instalar nada.

## Reglas duras
- Alcance SIEMPRE limitado al target indicado (el diff/archivos en cuestión) — nunca el repo completo.
- Los dos jueces son de SOLO LECTURA: no editan, no commitean, no corren nada destructivo.
- Un hallazgo solo se corrige si AMBOS jueces lo confirman de forma independiente, sin haber visto el veredicto ni el resultado del otro.
- Un hallazgo reportado por un solo juez queda como "sospechoso" — se registra, no se corrige solo.
- Si los jueces se contradicen entre sí sobre el mismo punto (uno dice que está mal, el otro lo revisó y no está de acuerdo), no decidas vos: escalá al usuario.
- Máximo 2 rondas en total (juicio inicial + un re-juicio después del fix). Si después de la ronda 2 sigue habiendo algo severo sin resolver, PARÁ y escalá — nunca hay una tercera ronda.

## Pasos
1. Fijá el target inmutable: si viene `$ARGUMENTS` (una descripción, un archivo, un rango de commits), usalo tal cual. Si no viene nada, corré `git diff` (y `git diff --cached` si aplica) y usá esos archivos/líneas exactos como alcance — nunca "todo el repo".
2. Lanzá EN PARALELO, con el tool Agent, dos jueces ciegos (Juez A y Juez B) en llamadas independientes — ninguno ve el prompt ni el resultado del otro. Dale a cada uno EXACTAMENTE el mismo prompt, solo cambiando la letra:

   > Sos el Juez {A|B} en una revisión ciega adversarial. Alcance exacto: {target — paths/diff pegado literal}. Criterios: corrección, edge cases, manejo de errores, performance, seguridad, y convenciones del proyecto (mirá el `CLAUDE.md` del repo si existe). Hacé un barrido exhaustivo de SOLO LECTURA — no edites nada, no delegues a otro agente, no mires nada fuera del alcance dado. Devolvé ÚNICAMENTE este JSON, sin prosa ni explicación fuera del JSON: `{"findings":[{"location":"archivo:linea","severity":"CRITICAL|WARNING|SUGGESTION","claim":"comportamiento incorrecto observable","evidence":"por qué es un problema real, con prueba concreta del código"}],"evidence":["qué inspeccionaste"]}`. Si no encontrás nada, devolvé `{"findings":[],"evidence":["qué inspeccionaste"]}`.

3. Esperá a que terminen AMBOS jueces antes de seguir — nunca aceptes un veredicto parcial ni sigas con uno solo.
4. Mergeá los hallazgos comparando ambos JSON:
   - **Confirmado** — el mismo hallazgo en esencia (mismo archivo/línea/claim), reportado por los dos jueces, con severidad `CRITICAL` o `WARNING`.
   - **Sospechoso** — reportado por un solo juez. Se registra en el output final, no se corrige automáticamente.
   - **Contradicción** — un juez señala algo como problema y el otro, habiendo mirado lo mismo, explícitamente no está de acuerdo. Escalá al usuario, no lo resuelvas vos.
5. Si hay hallazgos **confirmados**: mostraselos al usuario (archivo, línea, claim, evidencia de ambos jueces) y preguntá si aplicás la corrección antes de tocar nada.
6. Si el usuario aprueba: aplicá SOLO los fixes de los hallazgos confirmados, como unidades atómicas independientes — nada de refactors no relacionados, nada de tocar los "sospechosos" sin que se confirmen primero.
7. Repetí el juicio — los mismos dos jueces, ciegos entre sí de nuevo — pero con el alcance acotado SOLO al delta de la corrección que acabás de aplicar. Esta es la ronda 2, la última posible.
8. Si la ronda 2 sale limpia (o solo quedan `WARNING`/`SUGGESTION` informativos, nunca bloqueantes): reportá `JUDGMENT: APPROVED` con el resumen. Si sigue habiendo algo `CRITICAL` confirmado tras la ronda 2: reportá `JUDGMENT: ESCALATED`, parate, y explicá qué quedó sin resolver — nunca inicies una ronda 3 ni seguís corrigiendo por tu cuenta.

## Formato de salida
- `target`: qué se revisó exactamente
- `round`: `1` o `2`
- `confirmed`: hallazgos confirmados por ambos jueces (archivo, línea, claim)
- `suspect`: hallazgos reportados por un solo juez
- `contradictions`: puntos donde los jueces no coincidieron
- `fix_applied`: qué se corrigió, si aplica (o `null`)
- veredicto final, siempre como última línea: `JUDGMENT: APPROVED` o `JUDGMENT: ESCALATED`
