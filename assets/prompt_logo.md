# AICLI — Prompt para generación de logo

## Qué es el proyecto

AICLI es un motor de contexto inteligente para Claude Code.
Elimina el tiempo perdido re-explicando arquitectura, stack y convenciones en cada sesión de IA.
Documenta el proyecto una vez y entrega a Claude exactamente el contexto que necesita — ni más ni menos.

---

## Prompt principal (Midjourney / DALL-E 3 / Ideogram / Recraft)

```
Minimal professional logo for a developer CLI tool called "AICLI".

Concept: A single sharp geometric symbol — a clean hexagon or
diamond shape with a bold ">" terminal cursor at its center,
radiating three thin concentric rings outward, suggesting
context flowing into a core. The symbol feels precise, loaded,
inevitable.

Style: Ultra-minimal. One symbol, no text, no decoration.
Flat vector. Zero gradients. Pure geometric.

Colors: Deep matte black background (#0A0A0F).
Electric cyan symbol (#00E5FF) with a subtle inner glow —
the kind that makes it feel like it's powered on.
No other colors.

Mood: Imposing. Silent authority. A tool that knows exactly
what it's doing. Like a scalpel, not a hammer.

Output: Centered on square canvas. Lots of breathing room
around the symbol. The symbol takes up 40% of the space —
no more, no less.

Do NOT include: gradients, shadows, lens flares, 3D effects,
letters, wordmarks, sparkles, brains, robots, or anything
that looks like generic AI iconography.
```

**Midjourney:** agregá `--ar 1:1 --style raw --v 6` al final del prompt.

---

## Por qué este concepto

| Elemento | Significado |
|----------|-------------|
| `>` terminal cursor | Identifica la herramienta como CLI en un vistazo |
| Anillos concéntricos | El contexto expandiéndose desde un punto preciso — lo que hace AICLI |
| Hexágono / diamante | Estructura y peso visual sin decoración |
| Cyan `#00E5FF` sobre negro `#0A0A0F` | Paleta oficial de la CLI |
| 40% del canvas | Respiración visual — el símbolo impone sin gritar |

---

## Variantes a pedir

Una vez elegido el concepto base, pedir estas variantes:

1. **Ícono solo** — símbolo sin texto, fondo negro (para favicon y avatar)
2. **Ícono + wordmark** — símbolo a la izquierda, "AICLI" a la derecha en tipografía monospace fina
3. **Fondo claro** — mismo símbolo sobre blanco `#FAFAFA` para contextos con fondo claro
4. **Tamaño pequeño** — verificar que el símbolo sigue leyéndose a 64×64 px

---

## Lo que no queremos

- Cerebros, robots, engranajes — sobreusado en herramientas de IA
- Gradientes o glassmorphism
- Más de 2 colores
- Cualquier texto que no sea "AICLI" si se incluye
- Complejidad que no se lea a 64×64 px