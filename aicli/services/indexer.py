from pathlib import Path

# Recorrer todo el directorio de archivos (o sea el path)

IGNORAR = {".venv", "__pycache__", ".git", "node_modules", ".idea", "dist", "build", ".gitignore", "README.md", ".env.example"}

def obtener_arbol(path: Path):
    archivos = []
    for archivo in path.rglob("*"):
        if archivo.is_file():
            partes = archivo.parts
            if any(parte in IGNORAR for parte in partes):
                continue
            archivos.append(str(archivo.relative_to(path)))
    return sorted(archivos)

# Archivos que siempre queremos leer si existen
ARCHIVOS_PRIORITARIOS = {
    "main.py", "app.py", "index.js", "index.ts",
    "requirements.txt", "package.json", "pom.xml", "composer.json",
    "README.md", "README.rst", "CLAUDE.md"
}

# Extensiones de código fuente que vale la pena incluir
EXTENSIONES_CODIGO = {".py", ".js", ".ts", ".java", ".php"}

def leer_archivos_clave(path: Path, arbol: list[str]):
    seleccionados = []

    for ruta_relativa in arbol:
        archivo = Path(ruta_relativa)
        nombre = archivo.name
        extension = archivo.suffix

        es_prioritario = nombre in ARCHIVOS_PRIORITARIOS
        es_codigo = extension in EXTENSIONES_CODIGO

        if es_prioritario or es_codigo:
            seleccionados.append(ruta_relativa)

    # Aqui se obtienen los fragmentos de textos, especificamente se leen los archivo seleccionados
    # Nos quedamos con las primeras 40 lineas de codigo para optimizar tokens
    fragmentos = []
    for ruta_relativa in seleccionados:
        ruta_completa = path / ruta_relativa
        try:
            lineas = ruta_completa.read_text(encoding="utf-8").splitlines()[:40]
            contenido = "\n".join(lineas)
            fragmentos.append(f"### {ruta_relativa}\n{contenido}")
        except Exception:
            continue
    return "\n\n".join(fragmentos)