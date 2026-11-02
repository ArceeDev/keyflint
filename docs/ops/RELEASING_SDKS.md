# Publicar los SDKs `keyflint-verify` (npm, PyPI, Go)

Workflow: `.github/workflows/publish-sdks.yml`. Un tag `sdk-vX.Y.Z` publica los tres; la versión del tag debe coincidir con `sdks/js-verify/package.json`, `sdks/python-verify/pyproject.toml` y `keyflint_verify.__version__` (el workflow falla si no).

Los tags de la app (`vX.Y.Z`, imagen GHCR) y de los SDKs (`sdk-vX.Y.Z`) son independientes.

## Configuración única (cuentas del propietario)

### PyPI — trusted publishing (sin token)
1. https://pypi.org/manage/account/publishing/ → **Add a new pending publisher** (GitHub).
2. Project name `keyflint-verify` · Owner `ArceeDev` · Repository `keyflint` · Workflow `publish-sdks.yml` · Environment `pypi`.

### npm — primera publicación + trusted publishing
npm solo permite configurar trusted publishing en un paquete que ya existe. Elige una:
- **A (recomendada):** crea un token *granular* en npmjs.com (Access Tokens → Generate → Granular, permiso *Read and write*, paquetes: todos o `keyflint-verify`, con "Bypass 2FA" para CI) y guárdalo como secret `NPM_TOKEN` en GitHub (Settings → Secrets and variables → Actions). Tras la primera publicación, configura trusted publishing (abajo) y borra el secret.
- **B:** publica 1.1.0 a mano: `cd sdks/js-verify && npm ci && npm publish --access public --otp=123456` (o `publish_registries.ps1 -NpmOtp 123456`).

Después: npmjs.com → paquete `keyflint-verify` → Settings → **Trusted Publisher** → GitHub Actions: `ArceeDev` / `keyflint` / workflow `publish-sdks.yml` / environment `npm`.

### Go
Nada que configurar: el workflow crea el tag `sdks/go-verify/vX.Y.Z` (Go exige el prefijo del subdirectorio) y pide a proxy.golang.org que lo indexe. pkg.go.dev lo muestra minutos después.

## Lanzar una versión
```bash
git checkout main && git pull
git tag sdk-v1.1.0 && git push origin sdk-v1.1.0
```
Prueba en seco antes: Actions → *Publish SDKs* → Run workflow (sin marcar `publish`) = tests + `npm publish --dry-run` + build de PyPI.

Re-ejecutar es seguro: si la versión ya existe en npm/PyPI o el tag Go ya existe, ese paso se salta.
