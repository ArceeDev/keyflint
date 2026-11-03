# KeyFlint v1.1.0 — Manual Técnico Integral, Capacidades y Arquitectura

**Fecha:** Noviembre 2026  
**Autor:** ArceeDev  
**Estado:** Producción v1.1.0  
**Licencia:** Servidor BSL 1.1 · SDKs MIT  
**Plataforma Web:** [keyflint.dev](https://keyflint.dev) · Gateway: [licenses.keyflint.dev](https://licenses.keyflint.dev)

---

## 1. Resumen Ejecutivo y Propósito

**KeyFlint** es una pasarela de software de alto rendimiento para la emisión, validación criptográfica y medición de uso (créditos) de software moderno. Ha sido diseñada de forma nativa para herramientas de agentes de inteligencia artificial (**Model Context Protocol - MCP**), aplicaciones de terminal (**CLIs**) y software de escritorio.

### El problema que resuelve
Monetizar herramientas de software independiente y servidores MCP hoy en día implica tres alternativas deficientes:
1. **Alquilar un SaaS de licencias:** Costes mensuales fijos de entre $49 y $99/mes (ej. Keygen.sh), independientemente del volumen de facturación.
2. **Marketplaces con comisiones elevadas:** Retienen entre el 10% y el 30% del volumen bruto de ventas (ej. Gumroad).
3. **Desarrollo propio:** Semanas de trabajo resolviendo criptografía asimétrica, reintentos de red de agentes de IA, reembolsos atómicos y resiliencia de bases de datos.

KeyFlint ofrece una pasarela completa, con la opción de autoalojarla en un único contenedor o utilizar la instancia gestionada, con pagos directos a la cuenta de Stripe del desarrollador y sin comisiones intermedias.

---

## 2. Arquitectura de Verificación Offline (Zero Phone-Home)

El núcleo tecnológico de KeyFlint se basa en un modelo **Offline-First** mediante firmas criptográficas en curva elíptica:

* **Cero llamadas de red (Air-Gapped):**  
  Las aplicaciones cliente jamás contactan al servidor de licencias para comprobar si el usuario tiene permiso de uso. La comprobación se ejecuta íntegramente en la memoria local del proceso cliente utilizando una clave pública de 32 bytes.
* **Latencia sub-milisegundo:**  
  La validación matemática toma **0,004 ms en Node.js** y **0,06 ms en Python** (con aceleración OpenSSL). Es lo suficientemente rápida como para ejecutarse antes de cada llamada de herramienta (*tool call*) de un agente de IA sin introducir latencia perceptible.
* **Firma asimétrica Ed25519 (RFC 8032):**  
  El token de licencia tiene el formato `LIC-<TIER>-<PAYLOAD_BASE64>.<SIGNATURE_HEX>`. Es imposible alterar el tier, la fecha de caducidad o las funciones autorizadas sin invalidar matemáticamente la firma.
* **Rotación de claves (Key Ring):**  
  Cada token incluye un identificador de clave (`kid`). Esto permite rotar la clave privada maestra en producción sin invalidar las licencias emitidas con claves anteriores, permitiendo a los clientes mantener un listado o diccionario de claves históricas autorizadas.
* **Protección contra manipulación de reloj (Clock Skew):**  
  Si la fecha de emisión del token (`issued_at`) supera en más de 300 segundos el reloj del ordenador local, se rechaza de inmediato (`ERR_CLOCK_BEFORE_ISSUANCE`) para prevenir fraudes por retraso artificial del reloj.

---

## 3. Mecanismos de Control y Candados de Licencia

KeyFlint permite emitir tanto licencias flotantes genéricas como licencias altamente restringidas:

* **Vinculación a Dispositivo (Node-Locking):**  
  Permite asociar una licencia a una máquina física específica mediante una huella hardware criptográfica (hash seguro del identificador de placa o sistema operativo). Si el token se copia a otro equipo, el SDK arroja `ERR_NODE_LOCK_VIOLATION`.
* **Vinculación a Dominio Web:**  
  Permite limitar el uso de la licencia a dominios específicos o subdominios autorizados (con soporte para comodines como `*.empresa.com` y especificación de puertos).
* **Segmentación por Funcionalidades (Feature Flags):**  
  El desarrollador puede incluir una lista de funciones permitidas (ej. `["core", "export_pdf", "batch_processing"]`). El SDK verifica localmente si la función requerida está incluida en el plan antes de desbloquear el módulo.
* **Modalidad Temporal o Perpetua:**  
  Soporta licencias de pago único que nunca caducan (`perpetual: true`) o licencias sujetas a una fecha de vencimiento estricta calculada en formato Unix Epoch.

---

## 4. Pasarela de Créditos y Cuotas por Uso (`@metered`)

Para herramientas de IA donde cada llamada supone un coste de computación o de APIs de modelos fundacionales, KeyFlint incorpora un taxímetro transaccional atómico:

* **Descuento por llamada:**  
  Mediante el decorador `@kf.metered(credits=N)`, el SDK descuenta los créditos de la cuenta del usuario antes de ejecutar la función.
* **Idempotencia estricta:**  
  Cada deducción viaja acompañada de una cabecera `Idempotency-Key`. Si se produce una pérdida de conexión y el agente de IA reintenta la llamada, el servidor jamás cobra dos veces por la misma petición.
* **Reembolso automático por error:**  
  Si la herramienta lanza una excepción, se interrumpe o devuelve `isError`, el SDK solicita inmediatamente un reembolso atómico (`POST /api/v1/quota/refund`). Los usuarios nunca pagan por errores del código del desarrollador o caídas de APIs de terceros.
* **Ventana de seguridad y protección anti-repetición (900 s):**  
  KeyFlint rechaza cualquier deducción que intente procesarse después de que ya se haya emitido su reembolso, impidiendo ataques de repetición basados en manipular la latencia de red.

---

## 5. Integración con el Ecosistema MCP (Anthropic / Claude / Cursor)

KeyFlint está diseñado para acoplarse con la especificación oficial de Anthropic / Model Context Protocol:

* **Configuración transparente para el usuario final:**  
  El usuario final de Cursor o Claude Desktop solo debe pegar su clave en el bloque `env` de su archivo de configuración (ej. `KEYFLINT_LICENSE=LIC-PRO-...`). No requiere software adicional.
* **Códigos de error estándar JSON-RPC:**  
  Diseñados específicamente para no colisionar con los códigos nativos de MCP (como el `-32042` reservado para URLs):
  - `-32060`: Licencia inválida o expirada.
  - `-32061`: Función (*feature*) no incluida en el plan contratado.
  - `-32062`: Créditos agotados (HTTP 402, incluye enlace de recarga en el cuerpo).
  - `-32063`: Error de comunicación con la pasarela.

---

## 6. Motor de Facturación y Pasarelas de Pago

KeyFlint se sincroniza con pasarelas de pago estándar bajo el principio de **"Una compra = Una licencia"**:

* **Webhooks de Stripe y LemonSqueezy:**  
  Procesa eventos firmados de compras completadas, suscripciones creadas, renovaciones y cancelaciones.
* **Aislamiento de compras:**  
  Cada nuevo pago genera una licencia independiente con su propio saldo de créditos. Adquirir una licencia de menor tier jamás degrada una licencia superior previa.
* **Promoción in situ de cuentas Community:**  
  Si un usuario registrado en la modalidad gratuita *Community* adquiere una licencia de pago, su clave actual se actualiza automáticamente al nuevo tier sin obligarle a cambiar su configuración.
* **Protección de compras perpetuas:**  
  Las licencias perpetuas (*Indie*, *Agency*, *Lifetime*) quedan protegidas ante eventos de suscripción. La cancelación de una suscripción mensual jamás afecta a una licencia de pago único.
* **Manejo conservador de reembolsos:**  
  Si una devolución es ambigua (el correo coincide con múltiples licencias activas), KeyFlint prefiere no revocar ninguna de forma automática y emite una alerta a los administradores para evitar cancelaciones erróneas.

---

## 7. Operaciones, Respaldo y Recuperación ante Desastres (DR)

La infraestructura del servidor está optimizada para operar de manera autónoma con costes mínimos:

* **Contenedor único ultraligero:**  
  Construido con FastAPI y SQLite en modo WAL (Write-Ahead Logging). No requiere servidores externos de PostgreSQL ni Redis.
* **Replicación continua en tiempo real (Litestream):**  
  Cada transacción de la base de datos se transmite de manera continua a un bucket S3/R2 en la Unión Europea.
* **Simulacro de restauración automático cada hora:**  
  Un proceso en segundo plano restaura periódicamente la copia de seguridad más reciente en una base de datos efímera, verifica la integridad de los registros de licencias y clientes, y reporta su estado en el endpoint de salud.
* **Monitorización continua (Health Checks):**  
  El endpoint `/api/v1/health` supervisa el estado operativo general y reporta latidos continuos hacia Healthchecks.io.

---

## 8. Seguridad, Privacidad y Cumplimiento Normativo (RGPD)

* **Cero datos bancarios sensibles:**  
  KeyFlint nunca almacena números de tarjeta bancaria. El procesamiento se delega por completo en entornos con certificación PCI-DSS Nivel 1 (Stripe / LemonSqueezy).
* **Soberanía de datos en la UE:**  
  Las instancias gestionadas y las copias de seguridad de KeyFlint Managed se alojan estrictamente en centros de datos de la Unión Europea (París / Fráncfort).
* **Marco Legal Formalizado:**  
  Dispone de Acuerdo de Encargo de Tratamiento (*Data Processing Agreement - DPA*) conforme al Artículo 28 del RGPD y Política de Privacidad pública.
* **Defensa de red:**  
  El sistema de limitación de tasa (*Rate Limiting*) inspecciona la cabecera real de red `Fly-Client-IP`, evitando que clientes maliciosos eludan las restricciones manipulando cabeceras `X-Forwarded-For`.

---

## 9. Ecosistema de SDKs Oficiales (Licencia MIT)

Todos los SDKs de verificación offline son de código abierto y están publicados en los registros oficiales:

* **Python:** `pip install keyflint-verify` (disponible en [PyPI](https://pypi.org/project/keyflint-verify/)).
* **Node.js / TypeScript:** `npm install keyflint-verify` (disponible en [npm](https://www.npmjs.com/package/keyflint-verify)).
* **Go:** `go get github.com/ArceeDev/keyflint/sdks/go-verify@v1.1.0` (disponible en [proxy.golang.org](https://proxy.golang.org)).
* **Garantía de paridad:** Los tres paquetes superan una batería compartida de 47 vectores de prueba de conformidad criptográfica en cada versión.
