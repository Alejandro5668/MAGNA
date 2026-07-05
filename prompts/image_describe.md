# image_describe

**Propósito:** Envía una imagen a Claude con visión y devuelve una descripción técnica
precisa para inyectar en el session_context.md. Cubre interfaces web, diagramas
y bugs visuales.

**Usado en:** `aicli/services/indexer.py` → `describe_image()`
**Comandos:** `ctx task --imagen`, `ctx retomar`
**Modelo:** claude-sonnet-4-6 (vision)
**Parámetros:** max_tokens: 1024
**Versión:** 1.0

---

## Prompt

```
Describí esta imagen con precisión técnica para un desarrollador.
Si es una interfaz web o app: identificá elementos visibles, mensajes de error,
texto en pantalla, comportamiento observable, clases CSS o IDs visibles.
Si es un diagrama o esquema: describí la estructura y relaciones.
Si es un bug visual: describí exactamente qué está mal y dónde.
Sé específico. No uses frases genéricas.
```

**Nota de implementación:** El prompt se envía como bloque `text` junto con el bloque
`image` (base64) en un único mensaje multimodal. Soporta PNG, JPG, WEBP, GIF.

---

## Changelog

| Versión | Fecha | Cambio | Por qué |
|---------|-------|--------|---------|
| 1.0 | 2026-06-20 | Versión inicial | — |
