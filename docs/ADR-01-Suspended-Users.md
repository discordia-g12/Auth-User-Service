## ADR 01: Revocación de Sesiones y Suspensión de Usuarios

**Contexto:**
Cuando el staff suspende a un usuario a nivel plataforma, la consigna exige que sus sesiones activas sean invalidadas y el usuario sea desconectado de inmediato. Dado que nuestra arquitectura utiliza el API Gateway para validar tokens JWT, surge el desafío de invalidar un token que, por su naturaleza, no guarda estado en el servidor.

**Decisión:**
Se aplicará una estrategia de seguridad en múltiples capas:

* **Tiempos de expiración cortos:** Los *Access Tokens* tendrán una vida útil breve (5 a 15 minutos) para minimizar la ventana en la que un token comprometido o suspendido siga siendo válido.
* **Revocación de Refresh Tokens:** Al suspender a un usuario, su *Refresh Token* será invalidado en la base de datos relacional del *Auth & User Service*. Esto corta de raíz la posibilidad de generar nuevos accesos.


* **Deny List por Usuario:** Se almacenará una marca de tiempo `token_revoked_at` en el perfil. Si el token JWT tiene una fecha de emisión (`iat`) anterior a este *timestamp*, el sistema rechazará la petición.
* **Blacklist Activa en Redis:** Para garantizar el bloqueo instantáneo, se guardará el identificador del token actual (`jti`) en Redis con un tiempo de expiración (TTL) igual al tiempo de vida restante del JWT.
