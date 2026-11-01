# KeyForge Managed — Configurar Cloudflare R2 + Fly.io (Windows / PowerShell)

> Ejecuta todo tú con tus credenciales. Nunca pegues claves en el chat, en archivos del repo ni en la línea de comandos (quedan en el historial de PowerShell). Los comandos de abajo las piden con `Read-Host`.
> Nombres de variables tomados de `scripts/managed/kf_managed.py` y `app/bootstrap.py` (main 3e1befb).

## ⚠️ Antes de empezar: la región `mad` ya no sirve

Fly.io está cerrando Madrid (`mad`): ya no deja crear apps ni volúmenes nuevos allí ([hilo oficial](https://community.fly.io/t/mad-region-is-closed/25525)). `kf_managed.py` usa `--region mad` por defecto y `fly.toml` tiene `primary_region = "mad"`.

- **Ahora:** pasa siempre `--region cdg` (París) o `--region fra` (Fráncfort). Comprueba la lista vigente con `fly platform regions`.
- **Después (cambio de código, cuando lo apruebes):** default `--region` → `cdg` en `kf_managed.py` y `primary_region = "cdg"` en `fly.toml` (afecta también al despliegue 1 clic de Fly).

---

## 1. Cloudflare R2 (bucket privado en la UE)

### 1.1 Crear el bucket (Dashboard)
1. https://dash.cloudflare.com → **R2 Object Storage** (activa R2 si es la primera vez; pide tarjeta, el plan gratuito incluye 10 GB).
2. **Create bucket**:
   - Name: `kf-backups`
   - Location: **Specify jurisdiction → European Union (EU)**. *No se puede cambiar después* y es lo que permite decir en el DPA que las copias se quedan en la UE.
   - Storage class: Standard.
3. No actives acceso público ni dominio `r2.dev`. El bucket debe quedarse privado.
4. Apunta tu **Account ID** (columna derecha de la página de R2).

Endpoint S3 de un bucket con jurisdicción UE:
```
https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com
```
(sin `.eu.` no se ve el bucket).

### 1.2 Token S3 con alcance mínimo
1. R2 → **Manage R2 API Tokens** → **Create API token**.
2. Token name: `kf-litestream`.
3. Permissions: **Object Read & Write** (no *Admin Read & Write*).
4. Specify bucket(s): **Apply to specific buckets only → `kf-backups`**.
5. TTL: forever (o 1 año y lo rotas). Opcional: *Client IP filtering* no sirve aquí porque las IPs de salida de Fly cambian.
6. **Create** → copia **Access Key ID** y **Secret Access Key** directamente a tu gestor de contraseñas. El secret se muestra una sola vez. Ignora el "Token value" (es para la API de Cloudflare, no para S3).

> Nota: este token se copia como secreto de Fly a **cada** instancia de cliente. Es mínimo en cuanto a bucket, pero no en cuanto a prefijo: una instancia comprometida podría leer las copias de otros clientes. Mitigación futura: un token por cliente (R2 aún no restringe por prefijo; revisar) o cifrado de réplica. Lo dejo anotado como riesgo en el DPA (Anexo II).

---

## 2. Fly.io

### 2.1 Instalar flyctl y entrar
```powershell
iwr https://fly.io/install.ps1 -useb | iex
# cierra y abre PowerShell para que cargue el PATH
fly version
fly auth login          # abre el navegador
fly auth whoami
```

### 2.2 Organización y facturación
Recomendado: una org separada para clientes Managed (aisla facturación y permisos de tus pruebas).
```powershell
fly orgs list
fly orgs create keyforge-managed     # opcional; luego usa --org keyforge-managed
```
Añade tarjeta en https://fly.io/dashboard → (org) → **Billing**. Sin billing no deja crear volúmenes.

### 2.3 Imagen pública
`kf_managed.py` despliega `--image`. La imagen debe:
- existir en GHCR con Litestream dentro (build de main ≥ 3e1befb; la 1.1.0 actual **no** lo lleva),
- ser **pública** (GitHub → Packages → keyforge → Package settings → Change visibility).

Comprobar sin login:
```powershell
docker manifest inspect ghcr.io/arceedev/keyforge:<TAG>
```

---

## 3. Entorno local para `kf_managed.py`

Desde la raíz del repo (`C:\Users\Usuario\teamwork_projects\monetizable_project` o tu clon de keyforge):
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt     # el script importa el firmante Ed25519 del repo
```

### 3.1 Variables de backup (solo en esta sesión de PowerShell)
```powershell
$env:KF_BACKUP_BUCKET   = "kf-backups"
$env:KF_BACKUP_ENDPOINT = "https://" + (Read-Host "Cloudflare Account ID") + ".eu.r2.cloudflarestorage.com"
$env:KF_BACKUP_REGION   = "auto"     # R2 usa 'auto'; evita que Litestream intente detectar región

$env:LITESTREAM_ACCESS_KEY_ID = Read-Host "R2 Access Key ID"
$s = Read-Host "R2 Secret Access Key" -AsSecureString
$env:LITESTREAM_SECRET_ACCESS_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
Remove-Variable s
```
Se pierden al cerrar la ventana (es lo que queremos). No las pongas en `setx` ni en un `.env` del repo.

### 3.2 Proteger el vault en Windows
El script guarda la clave maestra de cada cliente en `%USERPROFILE%\.keyforge-managed\` y hace `chmod 0600`, que **en Windows no tiene efecto**. Restringe la ACL a tu usuario:
```powershell
$vault = "$env:USERPROFILE\.keyforge-managed"
New-Item -ItemType Directory -Force $vault | Out-Null
icacls $vault /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F"
```
Y haz copia cifrada de esa carpeta (BitLocker, VeraCrypt o adjunto en tu gestor de contraseñas). Sin vault y sin Fly, la clave de firma de un cliente no se recupera.

---

## 4. Prueba en seco (no crea nada)
```powershell
python scripts/managed/kf_managed.py --dry-run create smoke-test --region cdg --org keyforge-managed `
  --image ghcr.io/arceedev/keyforge:<TAG>
```
Debe imprimir, en orden: `fly apps create kf-smoke-test`, `fly volumes create keyforge_data ... --region cdg`, `fly secrets import --stage ... <<< [secrets via stdin, redacted]`, `fly deploy ... --primary-region cdg --ha=false`. Si dice *No backups configured*, falta alguna variable del paso 3.1.

## 5. Create de prueba real (cuesta céntimos)
```powershell
python scripts/managed/kf_managed.py create smoke-test --region cdg --org keyforge-managed `
  --image ghcr.io/arceedev/keyforge:<TAG>

python scripts/managed/kf_managed.py status smoke-test
curl.exe -s https://kf-smoke-test.fly.dev/api/v1/health
fly logs --app kf-smoke-test     # busca líneas de litestream "replicating" / sin errores S3
```
Comprueba en R2 → `kf-backups` que aparece el prefijo `smoke-test/` con `generations/...`.

Prueba de restauración (opcional pero recomendable antes del primer cliente):
```powershell
python scripts/e2e_backup.py --s3-endpoint $env:KF_BACKUP_ENDPOINT --bucket kf-backups
```

### Limpieza
```powershell
python scripts/managed/kf_managed.py destroy smoke-test --confirm smoke-test
```
Luego borra el prefijo `smoke-test/` en R2 (Dashboard → bucket → seleccionar carpeta → Delete) y los archivos `smoke-test.*.destroyed-*` del vault.

## 6. Si algo falla
| Síntoma | Causa probable |
|---|---|
| `region mad is not available` / error al crear volumen | Usa `--region cdg` o `fra` |
| `NoSuchBucket` / `AccessDenied` en logs de Litestream | Endpoint sin `.eu.`, o token no aplicado a `kf-backups` |
| El deploy no arranca y dice que la restauración falló | Comportamiento *fail-closed*: revisa credenciales R2 antes de reintentar |
| `unauthorized` al bajar la imagen | Paquete GHCR no es público |
| `flyctl failed` con un flag desconocido | Los flags de `kf_managed.py` no se verificaron contra flyctl real; pásame el error |
