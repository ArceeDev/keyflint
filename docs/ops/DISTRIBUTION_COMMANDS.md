# KeyFlint v1.1.0 — Guía de Publicación Oficial

> **Estado Actual**:
> - ✅ Repositorio público en GitHub: `https://github.com/ArceeDev/keyflint`
> - ✅ GitHub Release v1.1.0 creada y publicada: `https://github.com/ArceeDev/keyflint/releases/tag/v1.1.0`
> - ✅ Contenedor Docker v1.1.0 compilado y publicado en GHCR: `ghcr.io/arceedev/keyflint:1.1.0`
> - ✅ Binarios SDK (.whl, .tar.gz, .tgz) generados y subidos como Release Assets
> - ✅ Instalación directa lista para usuarios:
>   - `pip install https://github.com/ArceeDev/keyflint/releases/download/v1.1.0/keyflint_verify-1.1.0-py3-none-any.whl`
>   - `npm install https://github.com/ArceeDev/keyflint/releases/download/v1.1.0/keyflint-verify-1.1.0.tgz`

---

## Para publicar en los registros públicos globales (npm y PyPI)

Cuando tengas 30 segundos, dispones de dos caminos automáticos:

### Método 1: Script local rápido en 1 línea
En la raíz de `monetizable_project`:

```powershell
# Para publicar en npm usando tu código de 6 dígitos del móvil:
.\publish_registries.ps1 -NpmOtp 123456

# O para publicar en PyPI con tu token:
.\publish_registries.ps1 -PypiToken pypi-xxxxxxxx

# O ambos a la vez:
.\publish_registries.ps1 -NpmOtp 123456 -PypiToken pypi-xxxxxxxx
```

### Método 2: 100% Automático vía GitHub Actions
Si prefieres no tocar más la consola:
1. Ve a `https://github.com/ArceeDev/keyflint/settings/secrets/actions`
2. Añade los dos secretos:
   - `NPM_TOKEN`: Tu Granular Access Token de npmjs.com (con permiso Read/Write y Bypass 2FA).
   - `PYPI_API_TOKEN`: Tu token de API de pypi.org (`pypi-...`).
3. Ve a la pestaña **Actions** -> **Publish Client SDKs to npm and PyPI** -> Clic en **Run workflow**. Se publicará solo en la nube.

---

## Paso 1: Publicar el SDK en npm (`keyflint-verify`)

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
npm view keyflint-verify version
```

---

## Paso 2: Publicar el SDK en PyPI (`keyflint-verify`)

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
pip install keyflint-verify==1.1.0
```

---

## Paso 3: Crear el Tag v1.1.0 y Publicar la Imagen Docker en GHCR

Regresa a la raíz del proyecto:

```powershell
cd C:\Users\Usuario\teamwork_projects\monetizable_project

# 1. Crear el tag de la versión 1.1.0
git tag -a v1.1.0 -m "KeyFlint v1.1.0"

# 2. Subir commits y tags a tu repositorio de GitHub
git push origin main --follow-tags

# 3. (Opcional si tienes GitHub CLI instalado) Crear la Release oficial
gh release create v1.1.0 --title "KeyFlint v1.1.0" --generate-notes --verify-tag

# 4. El workflow .github/workflows/release.yml compilará y subirá la imagen a:
# ghcr.io/<tu-usuario-github>/keyflint:1.1.0
```

### Configuración de visibilidad en GitHub:
1. Entra en tu perfil de **GitHub -> Packages**.
2. Abre el paquete **keyflint**.
3. Entra en **Package settings** y cambia la visibilidad a **Public** (para que cualquiera pueda descargarlo con `docker pull`).
4. Prueba que funciona desde cualquier máquina con:
   ```bash
   docker run --rm ghcr.io/<tu-usuario-github>/keyflint:1.1.0 --help
   ```
