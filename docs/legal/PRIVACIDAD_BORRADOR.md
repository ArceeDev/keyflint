# Política de Privacidad — KeyFlint

> **BORRADOR.** Redactado por una IA como punto de partida; debe revisarlo un profesional de protección de datos en España antes de publicarlo. Huecos: **[[HUECO: …]]**; datos de terceros no verificados: **[[VERIFICAR: …]]**.
> Esta política cubre los datos que KeyFlint trata **como responsable** (web, cuenta, cobro, soporte). Los datos que los clientes de KeyFlint Managed alojan en su instancia (sus propios usuarios finales) se rigen por el [Acuerdo de Encargo del Tratamiento](DPA_BORRADOR.md), donde KeyFlint es encargado.

**Última actualización:** [[HUECO: fecha]]

## 1. Responsable
[[HUECO: nombre completo o razón social, NIF, domicilio en España. El titular aún no está dado de alta como autónomo: hay que resolverlo con el gestor antes de publicar. Esta misma identificación es obligatoria en el Aviso Legal (art. 10 Ley 34/2002, LSSI).]]
Email de privacidad: [[HUECO: privacy@keyflint.dev]]
No hemos designado Delegado de Protección de Datos porque no estamos obligados (art. 37 RGPD; art. 34 LOPDGDD). [[VERIFICAR con el profesional]]

## 2. Qué datos tratamos, para qué y con qué base
| Situación | Datos | Finalidad | Base jurídica (RGPD) | Plazo de conservación |
|---|---|---|---|---|
| Visitas a la web (keyflint.dev) | IP y datos técnicos que registra el alojamiento | Servir la web y su seguridad | Interés legítimo, art. 6.1.f | Según GitHub Pages [[VERIFICAR]] |
| Compra (self-hosted o Managed) | Email, nombre, país, empresa/VAT si se facilita; datos de pago | Cobrar y entregar la licencia | Contrato, art. 6.1.b | Ver nota fiscal abajo |
| Cuenta Managed | Email de contacto, nombre, empresa, dominio, slug de la instancia, claves públicas | Prestar y administrar el servicio | Contrato, art. 6.1.b | Mientras dure el contrato + 7 días de gracia; después, ver §6 |
| Emails transaccionales | Email, contenido del mensaje (licencia, avisos) | Entregar licencias y avisos del servicio | Contrato, art. 6.1.b | [[VERIFICAR retención de logs en Resend]] |
| Soporte | Email y lo que nos escribas | Atender tu consulta | Contrato o interés legítimo | 2 años desde la última comunicación [[propuesta]] |
| Seguridad y fraude | IP, registros de acceso, eventos de webhook | Proteger el servicio y prevenir abusos | Interés legítimo, art. 6.1.f | 90 días [[propuesta]] |
| Obligaciones legales | Datos de facturación | Contabilidad y fiscalidad | Obligación legal, art. 6.1.c | 6 años (art. 30 Código de Comercio) / 4 años (Ley General Tributaria) [[VERIFICAR con gestor; depende de si facturas tú o el MoR]] |
| Novedades del producto (opcional) | Email | Enviar novedades | Consentimiento, art. 6.1.a; o art. 21.2 LSSI si ya eres cliente | Hasta que te des de baja |

No tomamos decisiones automatizadas con efectos jurídicos sobre ti ni elaboramos perfiles.
**Datos de tarjeta:** no los vemos ni los guardamos; los trata directamente el proveedor de pago.
**Cookies:** la web no usa cookies propias ni de analítica. [[VERIFICAR; si se añade analítica, hace falta banner y política de cookies.]]

## 3. Quién recibe los datos
| Destinatario | Rol | Para qué | Ubicación / garantías |
|---|---|---|---|
| Stripe (Managed Payments) | **Responsable independiente / Merchant of Record**: es el vendedor ante ti y emite la factura | Cobro, impuestos, facturación, prevención de fraude | [[VERIFICAR entidad contratante para la UE y transferencias]]. Consulta su política: stripe.com/privacy |
| [[LemonSqueezy, si se usa como MoR en lugar de Stripe]] | Responsable independiente / MoR | Igual que arriba | [[VERIFICAR]] |
| Fly.io, Inc. | Encargado | Alojamiento de las instancias Managed y del servidor de licencias | UE ([[cdg/fra]]); empresa de EE. UU.: DPF/SCC [[VERIFICAR]] |
| Cloudflare, Inc. | Encargado | Copias de seguridad (R2, jurisdicción UE) | UE; empresa de EE. UU.: DPF/SCC [[VERIFICAR]] |
| Resend (o proveedor SMTP) | Encargado | Envío de emails transaccionales | [[VERIFICAR región y garantías]] |
| GitHub, Inc. | Encargado (alojamiento de la web) | Servir arceedev.github.io | EE. UU.: DPF/SCC [[VERIFICAR]] |
| Proveedor de email del responsable | Encargado | Correspondencia de soporte | [[HUECO: Gmail/Google Workspace u otro]] |
| Gestoría | Encargado | Contabilidad | [[HUECO, cuando exista]] |
| Autoridades | — | Solo cuando lo exija la ley | — |

No vendemos tus datos.

## 4. Transferencias internacionales
Algunos proveedores son empresas de EE. UU. Cuando haya transferencia fuera del EEE, se ampara en el Marco de Privacidad de Datos UE-EE. UU. (si el proveedor está certificado) o en las Cláusulas Contractuales Tipo de la Comisión Europea. Puedes pedir una copia de las garantías escribiendo al email de privacidad.

## 5. Tus derechos
Puedes ejercer acceso, rectificación, supresión, oposición, limitación del tratamiento y portabilidad, y retirar tu consentimiento en cualquier momento, escribiendo a [[email de privacidad]] con una forma razonable de identificarte. Respondemos en un mes (ampliable dos meses en casos complejos, art. 12.3 RGPD).
Si no estás conforme, puedes reclamar ante la **Agencia Española de Protección de Datos** (www.aepd.es) o la autoridad de tu país en la UE.

**Si eres usuario final de un software que usa KeyFlint Managed:** el responsable de tus datos es la empresa que te vendió ese software, no KeyFlint. Dirígete a ella; si nos escribes a nosotros, le reenviaremos tu solicitud.

## 6. Fin del servicio Managed
Al cancelar, tienes 7 días para exportar o migrar. Después eliminamos tu instancia y su volumen (≤ 7 días) y tus copias de seguridad (≤ 30 días). Conservamos solo lo necesario para obligaciones legales (facturación) y, si así se decide, los secretos cifrados de la instancia durante [[HUECO: plazo]] para permitir reactivarla.

## 7. Seguridad
Cada cliente Managed tiene su propia instancia aislada, su propia clave de firma y sus propias copias de seguridad cifradas en reposo; las comunicaciones van por TLS. Detalle en el Anexo II del DPA.

## 8. Menores
El servicio es para profesionales y empresas. No está dirigido a menores de 14 años (art. 7 LOPDGDD).

## 9. Cambios
Si cambiamos esta política de forma relevante, avisaremos por email a los clientes con al menos 30 días de antelación y actualizaremos la fecha de arriba.

---

### Pendientes antes de publicar
1. Identidad del responsable (alta de autónomo o sociedad) → también Aviso Legal (LSSI) y Términos del Servicio.
2. Decidir MoR definitivo (Stripe Managed Payments vs. LemonSqueezy) y quitar el que no se use.
3. Aceptar los DPA de Fly.io, Cloudflare y Resend en las cuentas y verificar DPF/SCC y regiones.
4. Crear el registro de actividades de tratamiento (art. 30.1 como responsable y 30.2 como encargado).
5. Revisión por un profesional.
