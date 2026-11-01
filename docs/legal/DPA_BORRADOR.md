# Acuerdo de Encargo del Tratamiento (DPA) — KeyForge Managed

> **BORRADOR, NO FIRMAR TAL CUAL.** Redactado por una IA como punto de partida. Debe revisarlo un abogado o consultor de protección de datos en España antes de usarlo. Los huecos van marcados con **[[HUECO: …]]** y las afirmaciones sobre terceros que no he verificado con **[[VERIFICAR: …]]**.

**Versión:** 0.1 · **Fecha:** [[HUECO: fecha]]

---

## Partes

**Responsable del tratamiento («el Cliente»):** la persona física o jurídica que contrata KeyForge Managed, identificada en el pedido o en su cuenta: [[nombre / razón social]], [[NIF/VAT]], [[domicilio]], [[email de contacto de privacidad]].

**Encargado del tratamiento («KeyForge»):** [[HUECO: identidad del prestador. Hoy el titular sería una persona física en España que aún no está dada de alta como autónomo. Hace falta nombre completo, NIF, domicilio y email de contacto. El alta en RETA/Hacienda (o constituir una sociedad) debe resolverse con el gestor ANTES de firmar un DPA con clientes; si se constituye una sociedad, el encargado será la sociedad.]]
Contacto de privacidad: [[HUECO: p. ej. privacy@arceedev.com]]

Este Acuerdo forma parte de los Términos del Servicio de KeyForge Managed y prevalece sobre ellos en materia de protección de datos.

## 1. Objeto
KeyForge presta al Cliente un servicio alojado de emisión, firma (Ed25519) y validación de licencias de software y de medición de cuotas/créditos de uso («el Servicio»). Para ello trata datos personales por cuenta del Cliente. Este Acuerdo regula ese tratamiento conforme al art. 28 del Reglamento (UE) 2016/679 («RGPD») y a la Ley Orgánica 3/2018 («LOPDGDD»).

## 2. Descripción del tratamiento (art. 28.3 RGPD)
| Elemento | Detalle |
|---|---|
| Naturaleza | Alojamiento, almacenamiento, registro, consulta, firma criptográfica, copia de seguridad y supresión. |
| Finalidad | Prestar el Servicio: emitir y validar licencias, medir cuotas, procesar webhooks de pago del Cliente, enviar las licencias por email (si el Cliente lo activa) y mantener copias de seguridad. |
| Duración | La del contrato, más los plazos de devolución y borrado de la cláusula 10. |
| Categorías de interesados | Clientes finales y usuarios del software del Cliente; personal del Cliente que usa la consola. |
| Categorías de datos | Email y, en su caso, nombre del cliente final; identificadores de cliente/pago de la pasarela del Cliente (p. ej. ID de cliente de Stripe, sin datos de tarjeta); claves de licencia y su estado; huella técnica del dispositivo (hash) si el Cliente usa vinculación a máquina; contadores y eventos de uso; direcciones IP y metadatos técnicos en registros. [[VERIFICAR con el esquema actual de la BD: `customers`, `licenses`, `usage`, `webhooks`]] |
| Categorías especiales | Ninguna. El Cliente se compromete a no introducir datos del art. 9 RGPD. |

## 3. Instrucciones
3.1 KeyForge tratará los datos solo siguiendo instrucciones documentadas del Cliente. Este Acuerdo, la configuración que el Cliente haga en el Servicio y sus peticiones por escrito son esas instrucciones.
3.2 Si KeyForge considera que una instrucción infringe el RGPD u otra norma, lo comunicará inmediatamente al Cliente (art. 28.3 *in fine*).
3.3 Si el Derecho de la UE o de un Estado miembro obliga a KeyForge a tratar los datos de otra forma, informará al Cliente antes, salvo que la ley lo prohíba.

## 4. Confidencialidad
Toda persona autorizada por KeyForge para tratar los datos está sujeta a un deber de confidencialidad, también después de terminar su relación. [[Hoy solo el titular tiene acceso; actualizar si entra personal.]]

## 5. Seguridad (art. 32 RGPD)
KeyForge aplica las medidas del **Anexo II**, y podrá actualizarlas siempre que no reduzcan el nivel de seguridad.

## 6. Subencargados
6.1 El Cliente da una autorización general para que KeyForge recurra a los subencargados del **Anexo III**.
6.2 KeyForge avisará por email al Cliente con al menos **30 días** de antelación de cualquier alta o sustitución de subencargado. El Cliente podrá oponerse por motivos razonables de protección de datos dentro de ese plazo; si no hay acuerdo, el Cliente podrá resolver el contrato y se le devolverá la parte prorrateada del periodo pagado no disfrutado.
6.3 KeyForge impondrá a cada subencargado obligaciones de protección de datos equivalentes a las de este Acuerdo y responderá ante el Cliente de su cumplimiento (art. 28.4).

## 7. Transferencias internacionales
7.1 Los datos de producción del Cliente se alojan en la UE: instancia en Fly.io región [[cdg París / fra Fráncfort]] y copias de seguridad en Cloudflare R2 con jurisdicción UE.
7.2 Fly.io, Inc. y Cloudflare, Inc. son sociedades de EE. UU. y pueden acceder a los datos desde fuera del EEE (soporte, operación, requerimientos legales). Estas transferencias se amparan en el Marco de Privacidad de Datos UE-EE. UU. cuando el proveedor esté certificado [[VERIFICAR certificación DPF vigente de cada uno en dataprivacyframework.gov]] y, en su defecto o además, en las Cláusulas Contractuales Tipo (Decisión (UE) 2021/914) incorporadas en sus DPA [[VERIFICAR: módulo aplicable y que los DPA estén aceptados en ambas cuentas]].
7.3 KeyForge no realizará otras transferencias fuera del EEE sin el aviso de la cláusula 6.2.

## 8. Asistencia al Cliente
8.1 **Derechos de los interesados:** el Servicio permite al Cliente consultar, exportar, revocar y borrar licencias y clientes finales. Si KeyForge recibe directamente una solicitud de un interesado, la remitirá al Cliente en un plazo de **5 días hábiles** sin responderla.
8.2 **Evaluaciones de impacto y consultas previas:** KeyForge facilitará la información razonable que tenga disponible (arts. 35 y 36).

## 9. Violaciones de seguridad
9.1 KeyForge notificará al Cliente cualquier violación de seguridad de los datos personales sin dilación indebida y, en todo caso, en un máximo de **48 horas** desde que tenga conocimiento, para que el Cliente pueda cumplir el plazo de 72 h del art. 33.
9.2 La notificación incluirá, en la medida en que se conozca: naturaleza de la violación, categorías y número aproximado de interesados y registros, consecuencias probables, medidas adoptadas o propuestas, y un contacto. La información que no esté disponible se facilitará por fases.
9.3 KeyForge documentará todas las violaciones, aunque no sean notificables.

## 10. Fin del servicio: devolución y borrado
10.1 Al terminar el contrato, el Cliente dispone de **7 días** de gracia para exportar sus datos (o migrar a la edición autoalojada) desde la consola o pidiéndolo a KeyForge.
10.2 Pasado ese plazo, KeyForge:
- elimina la aplicación de Fly.io y su volumen en un máximo de **7 días**;
- elimina el prefijo del Cliente en el almacenamiento de copias en un máximo de **30 días**;
- las copias de seguridad incrementales que quedaran caducan automáticamente a los **30 días** (retención configurada de Litestream: `720h`);
- conserva cifrada la clave de firma y los secretos de la instancia durante [[HUECO: 90 días, para poder reactivar la cuenta si el Cliente lo pide; o borrar a la vez — decidir]], y después los destruye;
- los registros técnicos del proveedor de alojamiento se borran según su propia política de retención [[VERIFICAR plazo de logs de Fly.io]].
10.3 Si el Cliente lo pide por escrito, KeyForge certificará el borrado.
10.4 Esta cláusula no afecta a los datos que KeyForge trate como responsable (facturación, cuenta), regulados en su Política de Privacidad.

## 11. Auditoría
11.1 KeyForge pondrá a disposición del Cliente la información necesaria para demostrar el cumplimiento de este Acuerdo (art. 28.3.h): este Acuerdo, el Anexo II actualizado y las certificaciones/informes de los subencargados disponibles públicamente.
11.2 El Cliente podrá realizar una auditoría, por sí o mediante un auditor sujeto a confidencialidad, como máximo **una vez al año**, con **30 días** de preaviso, en horario laboral y a su costa, salvo que exista una violación de seguridad o un requerimiento de una autoridad. Las auditorías sobre subencargados se harán mediante sus informes (SOC 2, ISO 27001) [[VERIFICAR disponibilidad]].

## 12. Responsabilidad
Cada parte responde de acuerdo con el art. 82 RGPD. [[HUECO: límite de responsabilidad alineado con los Términos del Servicio; p. ej. el importe pagado en los 12 meses anteriores, salvo dolo o negligencia grave. A decidir con el abogado.]]

## 13. Duración, ley y jurisdicción
Este Acuerdo dura lo que dure el contrato principal y las obligaciones de la cláusula 10. Se rige por la legislación española y la normativa de la UE. [[HUECO: tribunales competentes — p. ej. los del domicilio del encargado; para clientes consumidores no aplica, pero Managed es B2B.]]

---

## Anexo I — Lista de partes y contacto
Ver encabezado. Autoridad de control: Agencia Española de Protección de Datos (www.aepd.es), salvo que corresponda otra al Cliente.

## Anexo II — Medidas técnicas y organizativas
| Ámbito | Medida |
|---|---|
| Aislamiento | Una instancia por cliente: aplicación, volumen, clave de firma y prefijo de copias propios. Sin multi-tenencia. |
| Cifrado en tránsito | HTTPS/TLS en el endpoint público (certificados gestionados por Fly.io); conexión TLS a R2. |
| Cifrado en reposo | Volúmenes de Fly.io cifrados [[VERIFICAR]]; objetos en R2 cifrados por Cloudflare (AES-256) [[VERIFICAR]]. |
| Gestión de claves | Clave privada Ed25519, `SECRET_KEY` y clave de administración generadas en local por el operador y guardadas como *secrets* de Fly.io, fuera del volumen; nunca se pasan por la línea de comandos. Copia maestra en un almacén local con acceso restringido y copia de seguridad cifrada. |
| Control de acceso | Consola y API de administración protegidas con clave de administración propia de cada cliente. Acceso operativo limitado al titular, con 2FA en Fly.io, Cloudflare, GitHub y Stripe [[HUECO: confirmar que 2FA está activo en todas]]. |
| Mínimo privilegio | Token de copias de seguridad limitado a lectura/escritura de objetos en un único bucket. **Riesgo conocido:** el mismo token se usa en todas las instancias; mitigación prevista: un token por cliente o cifrado de réplica. |
| Copias y continuidad | Replicación continua con Litestream (sincronización ~1 s, snapshot diario, retención 30 días). Restauración automática al arrancar sin base de datos; si falla, la instancia no arranca vacía (*fail-closed*). Prueba de restauración mensual. |
| Integridad | Licencias firmadas con Ed25519 y verificables sin conexión; webhooks de pago verificados por firma HMAC. |
| Actualizaciones | Imagen de contenedor versionada; actualizaciones de seguridad aplicadas con `upgrade`. |
| Registro | Registros de la aplicación en la plataforma de alojamiento [[VERIFICAR retención]]. |
| Organizativas | Procedimiento de notificación de violaciones (cláusula 9); registro de actividades de tratamiento como encargado (art. 30.2) [[HUECO: crearlo]]. |

## Anexo III — Subencargados autorizados
| Subencargado | Servicio | Ubicación de los datos | Garantía de transferencia |
|---|---|---|---|
| Fly.io, Inc. (EE. UU.) | Alojamiento de la instancia y volumen | UE, región [[cdg/fra]] | DPF [[VERIFICAR]] / SCC en el DPA de Fly.io [[VERIFICAR]] |
| Cloudflare, Inc. (EE. UU.) | Almacenamiento de copias de seguridad (R2) | Bucket con jurisdicción UE | DPF [[VERIFICAR]] / SCC en el DPA de Cloudflare |
| [[Resend / proveedor SMTP]] | Envío de licencias por email | [[VERIFICAR región]] | [[VERIFICAR]] — **solo si el email lo envía una cuenta de KeyForge.** Si el Cliente configura su propia cuenta de Resend/SMTP, ese proveedor es encargado del Cliente, no subencargado de KeyForge; borrar esta fila. |

**No son subencargados:**
- **Stripe** (o LemonSqueezy) cuando cobra al Cliente por KeyForge: actúa como responsable independiente / *Merchant of Record* para los datos de pago del Cliente (ver Política de Privacidad).
- **La pasarela de pago del propio Cliente** que envía webhooks a su instancia: es proveedor del Cliente.
- **GitHub (GHCR)**: solo aloja la imagen del software; no recibe datos del Cliente.
