# MAGNA — Flujo de resolución de casos

```mermaid
flowchart TD
    START([Caso en Jira])

    START --> CHECK{¿Módulo\ndocumentado?}

    %% ── Camino A: módulo nuevo ──────────────────────────────────────────────
    CHECK -->|No| FILE["ctx file\nDocumentar carpeta completa"]
    FILE  --> ARC1["ctx archive\nAnalizar archivo en profundidad"]
    ARC1  --> TASK1["ctx task\nDetectar módulos relevantes\nGenerar plan · Lanzar Claude"]

    %% ── Camino B: módulo existente ──────────────────────────────────────────
    CHECK -->|Sí| STALE{¿Archivo\nmodificado?}
    STALE -->|Sí| ARC2["ctx archive\nRefrescar documentación"]
    STALE -->|No| TASK2["ctx task\nDetectar módulos relevantes\nGenerar plan · Lanzar Claude"]
    ARC2  --> TASK2

    %% ── Trabajo con Claude ──────────────────────────────────────────────────
    TASK1 --> WORK["Claude Code resuelve la tarea"]
    TASK2 --> WORK

    WORK --> SYNC["ctx sync\nSincronizar documentación post-tarea"]

    SYNC --> PR[Se crea PR]

    %% ── Revisión del PR ─────────────────────────────────────────────────────
    PR --> PRCHECK{¿Hay comentarios\ncríticos?}

    PRCHECK -->|No| APPROVED([✔  PR aprobado — FIN])

    PRCHECK -->|Sí| REVISION["ctx revision\nLeer comentarios del PR\nResolver críticos con Claude"]

    REVISION --> RESOLVED{¿Críticos\nresueltos?}

    RESOLVED -->|Sí| APPROVED2([✔  PR aprobado — FIN])

    %% ── PR reabierto ────────────────────────────────────────────────────────
    RESOLVED -->|PR reabierto| RESUME["ctx resume\nRetomar ticket con historial\nde rondas anteriores"]

    RESUME --> REWORK["Claude Code retoma con\ncontexto acumulado"]

    REWORK --> SYNC2["ctx sync\nSincronizar nueva ronda"]

    SYNC2 --> PR2[Se crea nuevo PR]

    PR2 --> PRCHECK2{¿Hay comentarios\ncríticos?}

    PRCHECK2 -->|No| APPROVED3([✔  PR aprobado — FIN])

    PRCHECK2 -->|Sí — iteración| REVISION

    %% ── Estilos ─────────────────────────────────────────────────────────────
    classDef cmd    fill:#0d1a2a,stroke:#00d7ff,color:#00d7ff
    classDef gate   fill:#111111,stroke:#333333,color:#c9d1d9
    classDef end_ok fill:#0a1a0a,stroke:#00ff87,color:#00ff87
    classDef start  fill:#0a0a0a,stroke:#555555,color:#555555

    class FILE,ARC1,ARC2,TASK1,TASK2,SYNC,SYNC2,REVISION,RESUME cmd
    class WORK,REWORK cmd
    class CHECK,STALE,PRCHECK,PRCHECK2,RESOLVED gate
    class APPROVED,APPROVED2,APPROVED3 end_ok
    class START start
```

## Comandos del flujo

| Comando | Cuándo usarlo |
|---------|---------------|
| `ctx file` | Módulo nuevo — documenta toda la carpeta |
| `ctx archive` | Archivo específico nuevo o modificado |
| `ctx task` | Siempre — punto de entrada al trabajo con Claude |
| `ctx sync` | Después de completar la tarea — antes del PR |
| `ctx revision` | Al recibir comentarios críticos en el PR |
| `ctx resume` | PR reabierto — retoma con historial de rondas |

## Reglas del flujo

- `ctx task` siempre detecta los módulos relevantes con IA antes de lanzar Claude
- `ctx sync` actualiza la documentación para que la siguiente ronda tenga contexto fresco
- `ctx resume` preserva el historial completo de rondas anteriores — Claude no empieza desde cero
- Un módulo modificado por la tarea anterior necesita `ctx archive` antes de la siguiente
