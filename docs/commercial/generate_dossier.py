import os
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)

def create_document():
    doc = Document()
    
    # Page Margins
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        
    # Styles
    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Calibri'
    normal_style.font.size = Pt(11)
    normal_style.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
    
    # Document Title
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(4)
    run_title = p_title.add_run("KEYFLINT v1.1.0")
    run_title.font.name = 'Arial'
    run_title.font.size = Pt(26)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(0x0B, 0x0D, 0x17)
    
    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(20)
    run_sub = p_sub.add_run("Manual Técnico Integral, Capacidades Funcionales y Arquitectura de Producto")
    run_sub.font.size = Pt(14)
    run_sub.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    
    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_after = Pt(24)
    run_meta = p_meta.add_run("Fecha: Noviembre 2026 | Autor: ArceeDev | Entorno: Producción v1.1.0 | Licencia: BSL 1.1 / MIT SDKs")
    run_meta.font.size = Pt(9.5)
    run_meta.font.italic = True
    run_meta.font.color.rgb = RGBColor(0x77, 0x77, 0x77)
    
    def add_h1(text):
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(20)
        h.paragraph_format.space_after = Pt(8)
        h.paragraph_format.keep_with_next = True
        r = h.add_run(text)
        r.font.name = 'Arial'
        r.font.size = Pt(16)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x0B, 0x0D, 0x17)
        return h

    def add_h2(text):
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(14)
        h.paragraph_format.space_after = Pt(4)
        h.paragraph_format.keep_with_next = True
        r = h.add_run(text)
        r.font.name = 'Arial'
        r.font.size = Pt(12.5)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x2E, 0x35, 0x50)
        return h

    def add_p(text, bold_prefix=""):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.15
        if bold_prefix:
            r_pre = p.add_run(bold_prefix)
            r_pre.font.bold = True
            r_pre.font.color.rgb = RGBColor(0x0B, 0x0D, 0x17)
        p.add_run(text)
        return p

    def add_bullet(text, bold_prefix=""):
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.15
        if bold_prefix:
            r_pre = p.add_run(bold_prefix)
            r_pre.font.bold = True
            r_pre.font.color.rgb = RGBColor(0x0B, 0x0D, 0x17)
        p.add_run(text)
        return p

    # 1. Resumen Ejecutivo
    add_h1("1. Resumen Ejecutivo y Propósito")
    add_p("KeyFlint es una pasarela de software integral para la emisión, validación criptográfica y medición de uso (créditos) de software moderno, diseñada de forma nativa para herramientas de agentes de inteligencia artificial (Model Context Protocol - MCP), aplicaciones de terminal (CLIs) y software de escritorio.")
    add_p("Resuelve el conflicto histórico entre la monetización del software y la experiencia de usuario: permite a cualquier desarrollador vender licencias y cobrar micropagos por llamada sin intermediarios, sin comisiones de marketplace del 10% al 30%, y sin depender de servidores de licencias SaaS de pago mensual recurrente ($49-$99/mes).")

    # 2. Arquitectura Offline-First
    add_h1("2. Arquitectura de Verificación Offline (Zero Phone-Home)")
    add_p("El pilar tecnológico fundamental de KeyFlint es su modelo 'Offline-First' basado en firmas criptográficas sobre curvas elípticas de última generación:")
    add_bullet("Los clientes de tu software jamás llaman al servidor de licencias para comprobar si tienen permiso de uso. Tu app comprueba la firma digital de forma local en la memoria de su propio proceso.", "Cero llamadas de red (Air-Gapped): ")
    add_bullet("Una verificación completa toma 0,004 ms en Node.js y 0,06 ms en Python (con aceleración OpenSSL). Es tan ligero que puede ejecutarse antes de cada tool call de un agente de IA sin introducir latencia perceptible.", "Latencia sub-milisegundo: ")
    add_bullet("El token de licencia tiene la estructura LIC-<TIER>-<PAYLOAD_BASE64>.<SIGNATURE_HEX>. Es matemáticamente imposible alterar el tier, la fecha de caducidad o las funciones permitidas sin invalidar la firma.", "Firma asimétrica Ed25519 (RFC 8032): ")
    add_bullet("Cada token incluye un identificador de clave (kid). Esto permite rotar la clave privada maestra en producción sin romper las licencias antiguas que compraron los usuarios meses atrás.", "Rotación de claves (Key Ring): ")
    add_bullet("Si la fecha de emisión del token supera en más de 300 segundos el reloj del ordenador local, se rechaza de inmediato (ERR_CLOCK_BEFORE_ISSUANCE) para impedir trampas mediante retraso artificial del reloj.", "Protección contra manipulación de reloj: ")

    # 3. Restricciones y Candados
    add_h1("3. Mecanismos de Control y Candados de Licencia")
    add_p("KeyFlint permite emitir licencias universales flotantes o licencias ultra-específicas con candados de seguridad:")
    add_bullet("Permite vincular una licencia a una máquina física específica mediante una huella hardware criptográfica (hash seguro del ID de placa/sistema). Si el token se copia a otro ordenador, el SDK arroja ERR_NODE_LOCK_VIOLATION.", "Vinculación a Dispositivo (Node-Locking): ")
    add_bullet("Permite restringir la validez de la licencia a un dominio web específico o subdominios autorizados (incluyendo soporte para comodines como *.empresa.com y puertos específicos).", "Vinculación a Dominio Web: ")
    add_bullet("El creador puede definir listas de capacidades (features) permitidas (ej. ['core', 'export_pdf', 'fast_search']). El SDK comprueba si el usuario tiene derecho antes de abrir cada módulo.", "Segmentación por Módulos (Feature Flags): ")
    add_bullet("Soporta licencias de pago único que nunca expiran (perpetual: true) o licencias con fecha límite de vencimiento estricta calculada al segundo en formato Unix Epoch.", "Expiración Temporal o Perpetua: ")

    # 4. Sistema Metered MCP
    add_h1("4. Pasarela de Créditos y Cuotas por Uso (@metered)")
    add_p("Para herramientas de IA donde el desarrollador incurre en costes de cómputo o APIs de LLM, KeyFlint incorpora un taxímetro transaccional atómico:")
    add_bullet("Basta añadir el decorador @kf.metered(credits=5) encima de la función. El SDK descuenta los créditos de la cuenta del usuario en una sola llamada ultraligera antes de ejecutar la acción.", "Descuento por llamada: ")
    add_bullet("Cada petición genera un identificador único Idempotency-Key. Si la red falla y el agente reintenta la misma llamada, el servidor jamás cobra dos veces.", "Idempotencia estricta: ")
    add_bullet("Si la función de la herramienta lanza una excepción, se cuelga o devuelve isError, el SDK solicita inmediatamente un reembolso atómico (POST /api/v1/quota/refund). Tus usuarios nunca pagan por tus errores o caídas de APIs externas.", "Reembolso automático por fallo: ")
    add_bullet("KeyFlint rechaza cualquier deducción que intente procesarse después de que ya se haya emitido su reembolso, impidiendo que agentes maliciosos intenten 'jugar gratis' manipulando la latencia de red.", "Ventana de seguridad y anti-repetición (900s): ")

    # 5. Integración con Claude Desktop y Cursor
    add_h1("5. Integración con el Ecosistema MCP y JSON-RPC")
    add_p("KeyFlint ha sido diseñado para acoplarse con la especificación oficial de Anthropic / Model Context Protocol:")
    add_bullet("El usuario final de Cursor o Claude Desktop solo añade su clave en la sección 'env' de su archivo de configuración (ej. KEYFLINT_LICENSE=LIC-PRO-...). No requiere instalar programas adicionales ni interactuar con interfaces complejas.", "Experiencia de usuario sin fricción: ")
    add_bullet("-32060 (Licencia inválida), -32061 (Función no incluida en el plan), -32062 (Créditos agotados con URL de recarga directa), -32063 (Error de pasarela). Evitan colisionar con los códigos nativos de MCP (como el -32042).", "Códigos de error estándar JSON-RPC: ")

    # 6. Pasarelas de Pago
    add_h1("6. Motor de Facturación y Pasarelas de Pago")
    add_p("KeyFlint se conecta directamente a pasarelas de pago de clase mundial con arquitectura 'Una compra = Una licencia':")
    add_bullet("Recibe eventos firmados criptográficamente de checkout.session.completed, suscripciones creadas, renovadas o canceladas.", "Webhooks de Stripe y LemonSqueezy: ")
    add_bullet("Cada nuevo pago genera una licencia independiente con su propio saldo de créditos. Comprar una licencia de menor valor jamás degrada el tier de una licencia superior previa.", "Aislamiento de compras: ")
    add_bullet("Si un usuario registrado en la modalidad gratuita 'Community' compra una licencia de pago, su clave actual se actualiza automáticamente al nuevo tier sin obligarle a cambiar su configuración.", "Promoción in situ de cuentas Community: ")
    add_bullet("Las licencias perpetuas (Indie, Agency, Lifetime) quedan blindadas ante eventos de suscripción. La cancelación de un plan mensual jamás revoca una compra de por vida.", "Blindaje de compras perpetuas: ")
    add_bullet("Si un reembolso es ambiguo (el correo coincide con varias licencias distintas), KeyFlint prefiere no revocar ninguna de forma automática y emite una alerta a los administradores para evitar cancelaciones injustas.", "Manejo conservador de reembolsos: ")

    # 7. Operaciones y Respaldo
    add_h1("7. Operaciones, Alta Disponibilidad y Respaldo (DR)")
    add_p("La infraestructura del servidor está optimizada para funcionar de forma desatendida y autosuficiente:")
    add_bullet("FastAPI + SQLite en modo WAL (Write-Ahead Logging). Cero necesidad de mantener servidores pesados de Postgres o Redis.", "Contenedor único ultraligero: ")
    add_bullet("Cada cambio en la base de datos se transmite de manera continua a un bucket S3/R2 en Europa mediante Litestream.", "Replicación en tiempo real (Litestream): ")
    add_bullet("Cada hora, un proceso en segundo plano restaura la copia de seguridad más reciente en una base de datos temporal, comprueba que los recuentos de licencias y clientes sean íntegros y reporta 'status: ok'.", "Simulacro de restauración por hora: ")
    add_bullet("El endpoint /api/v1/health avisa si el sistema está operativo y si la copia de seguridad se validó con éxito en la última hora. Incluye latido automático a Healthchecks.io.", "Monitorización continua (Health Checks): ")
    add_bullet("Tras arrancar la máquina, espera 60 segundos antes de la primera prueba para permitir que el disco y los túneles se asienten limpiamente sin falsas alarmas.", "Retardo inteligente de arranque: ")

    # 8. Seguridad y Privacidad
    add_h1("8. Seguridad, Privacidad y Cumplimiento Normativo (RGPD)")
    add_bullet("KeyFlint nunca ve, procesa ni almacena números de tarjeta de crédito. Todo el cobro bancario queda en el entorno PCI-DSS Nivel 1 de Stripe o LemonSqueezy.", "Cero datos bancarios sensibles: ")
    add_bullet("Toda la computación y las copias de seguridad de KeyFlint Managed se alojan estrictamente en centros de datos de la Unión Europea (París / Fráncfort).", "Soberanía de datos en la UE: ")
    add_bullet("Cuenta con Data Processing Agreement conforme al Artículo 28 del RGPD y Política de Privacidad pública en la web oficial.", "DPA y Privacidad formalizados: ")
    add_bullet("Los límites de peticiones (Rate Limiting) inspeccionan la cabecera real de red Fly-Client-IP, impidiendo que usuarios malintencionados eludan bloqueos falseando cabeceras X-Forwarded-For.", "Defensa estricta contra ataques de fuerza bruta: ")

    # 9. SDKs Oficiales
    add_h1("9. Ecosistema de SDKs de Verificación (Licencia MIT)")
    add_p("Los desarrolladores integran KeyFlint en sus proyectos mediante paquetes oficiales publicados en los registros de software de referencia:")
    add_bullet("pip install keyflint-verify (puro Python estándar sin compiladores C; soporte opcional acelerado con cryptography).", "Python SDK (PyPI): ")
    add_bullet("npm install keyflint-verify (soporte completo para Node.js, TypeScript, ES Modules y CommonJS).", "JavaScript / TypeScript SDK (npm): ")
    add_bullet("go get github.com/ArceeDev/keyflint/sdks/go-verify@v1.1.0 (módulo Go nativo con soporte Go 1.20+).", "Go SDK (proxy.golang.org): ")
    add_bullet("Los 3 lenguajes se prueban de forma cruzada contra una suite de 47 vectores de prueba criptográficos idénticos en cada versión.", "Garantía de paridad (Vectores de Conformance): ")

    # Save
    out_dir = r"C:\Users\Usuario\teamwork_projects\monetizable_project\docs\commercial"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "KEYFLINT_DOSSIER_COMPLETO.docx")
    doc.save(out_path)
    
    # Also save in User's home for easy drag & drop to Google Drive
    home_path = os.path.join(os.path.expanduser("~"), "KeyFlint_Dossier_Completo.docx")
    doc.save(home_path)
    
    print(f"Document created successfully at:\n1. {out_path}\n2. {home_path}")

create_document()
