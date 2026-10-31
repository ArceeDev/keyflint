# KeyForge v1.1.0 — Guía de Publicación Oficial (npm, PyPI y Docker GHCR)

> **Estado**: Todas las versiones sincronizadas en `1.1.0` (Servidor, SDK JS y SDK Python). Árbol de Git 100% limpio.

---

## Paso 1: Publicar el SDK en npm (`keyforge-verify`)

Abre PowerShell en tu equipo y ejecuta:

```powershell
cd C:\Users\Usuario\teamwork_projects\monetizable_project\sdks\js-verify

# 1. Iniciar sesión en tu cuenta de npmjs.com
npm login

# 2. Comprobar que estás conectado
npm whoami

# 3. Compilar y ejecutar los 57 tests
npm run build
npm test

# 4. Comprobar los archivos que se incluirán en el paquete (simulación limpia)
npm pack --dry-run

# 5. Publicar oficialmente como paquete público
npm publish --access public

# 6. Comprobar que ya está publicado en npm
npm view keyforge-verify version
```

---

## Paso 2: Publicar el SDK en PyPI (`keyforge-verify`)

En la misma ventana de PowerShell:

```powershell
cd C:\Users\Usuario\teamwork_projects\monetizable_project\sdks\python-verify

# 1. Asegurar herramientas de compilación y subida
python -m pip install -U build twine

# 2. Limpiar compilaciones anteriores si existen
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue

# 3. Compilar el paquete (genera archivo .whl y .tar.gz en dist/)
python -m build

# 4. Validar integridad de los metadatos
twine check dist/*

# 5. Subir a PyPI oficial
# Usuario: __token__
# Contraseña: tu token de PyPI (pypi-...)
twine upload dist/*

# 6. Comprobar instalación en limpio
pip install keyforge-verify==1.1.0
```

---

## Paso 3: Crear el Tag v1.1.0 y Publicar la Imagen Docker en GHCR

Regresa a la raíz del proyecto:

```powershell
cd C:\Users\Usuario\teamwork_projects\monetizable_project

# 1. Crear el tag de la versión 1.1.0
git tag -a v1.1.0 -m "KeyForge v1.1.0"

# 2. Subir commits y tags a tu repositorio de GitHub
git push origin main --follow-tags

# 3. (Opcional si tienes GitHub CLI instalado) Crear la Release oficial
gh release create v1.1.0 --title "KeyForge v1.1.0" --generate-notes --verify-tag

# 4. El workflow .github/workflows/release.yml compilará y subirá la imagen a:
# ghcr.io/<tu-usuario-github>/keyforge:1.1.0
```

### Configuración de visibilidad en GitHub:
1. Entra en tu perfil de **GitHub -> Packages**.
2. Abre el paquete **keyforge**.
3. Entra en **Package settings** y cambia la visibilidad a **Public** (para que cualquiera pueda descargarlo con `docker pull`).
4. Prueba que funciona desde cualquier máquina con:
   ```bash
   docker run --rm ghcr.io/<tu-usuario-github>/keyforge:1.1.0 --help
   ```
