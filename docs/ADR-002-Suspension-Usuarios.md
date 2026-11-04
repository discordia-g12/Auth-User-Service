# ADR-002: Suspensión de usuarios y corte de sesiones

- **Estado:** Aceptado. Implementado en este servicio (endpoint, Auth0, lista de bloqueados y evento); el
  chequeo en Kong y los consumidores de Chat y Voz van en sus repos (ver §5)
- **Fecha:** 2026-09-27
- **Alcance:** `auth-user-service`, API Gateway (Kong), Auth0, Chat Engine, Voice Signaling
- **Reemplaza a:** `ADR-01-Suspended-Users.md`, que suponía refresh tokens y un `token_revoked_at` almacenados en este servicio. Eso es incompatible con ADR-001: las sesiones y los refresh tokens viven en Auth0.

---

## 1. Contexto

Cuando el staff suspende a un usuario, la consigna exige invalidar sus sesiones y desconectarlo
**de inmediato**. Con ADR-001:

- las sesiones y los refresh tokens son de Auth0, no de Discordia;
- los access tokens son JWT sin estado, validados por Kong hasta su `exp`;
- las conexiones WebSocket (chat y voz) se autentican una sola vez, en el handshake, y después no vuelven a pasar por la validación de Kong.

Cortar el acceso requiere entonces actuar en tres frentes: la emisión de tokens nuevos, los access
tokens todavía vigentes y las conexiones abiertas.

## 2. Decisión

| # | Frente | Mecanismo |
|---|--------|-----------|
| 1 | Tokens nuevos | Bloquear al usuario en **Auth0** (`blocked: true` vía Management API) y revocar sus refresh tokens y sesiones. Auth0 deja de emitirle tokens por login o refresh. |
| 2 | Access tokens vigentes | Mantener la vida del access token **corta** (configurada en la API de Auth0, orden de 5–15 min) y agregar una **denylist por usuario en el Redis del Gateway**: clave `suspended:<sub>` con TTL igual a la vida máxima del access token. `auth0_validator.lua` la consulta después de verificar la firma y responde `403` (RFC 7807). |
| 3 | Conexiones abiertas | Evento de dominio `user.suspended`, publicado vía Outbox (ADR-005). Chat Engine y Voice Signaling cierran las conexiones de ese `user_id`. |
| 4 | Registro de negocio | `auth-user-service` persiste `users.is_suspended = true`, que sirve para backoffice, auditoría y reactivación. |

La denylist va por usuario (`sub`) y no por token (`jti`): Auth0 no avisa cuando emite un token,
así que Discordia no puede conocer de antemano los `jti` a bloquear. El TTL de la clave igual a la
vida del access token alcanza, porque después de ese plazo ningún token previo a la suspensión
sigue siendo válido y el bloqueo en Auth0 impide emitir tokens nuevos.

La operación de suspensión será un endpoint exclusivo de staff (autorizado en Kong por rol). Orden
de pasos: bloqueo en Auth0 → clave en Redis → `is_suspended` + evento `user.suspended` en la misma
transacción. Si falla alguno de los dos primeros pasos, la operación falla completa y se reintenta.
La reactivación hace lo inverso.

### Detalles de la implementación (03/11/2026)

- **Endpoints** (solo staff, con segundo chequeo de `X-User-Role` en el servicio):
  `POST /api/v1/admin/users/suspensions` (`{"user": "email, @usuario o id", "reason": "..."}`),
  `DELETE /api/v1/admin/users/{user_id}/suspension` y `GET /api/v1/admin/users/suspended`. El motivo, la fecha
  y quién suspendió se guardan en `users` (`suspension_reason`, `suspended_at`, `suspended_by`).
- **Identidades federadas.** Una persona puede tener varias identidades de Auth0 con el mismo email
  (contraseña y Google), unificadas como alias. Se bloquean en Auth0 y se agregan a la lista **todas**:
  el id del usuario y sus alias. El evento las manda en `identities`.
- **Claves en el Redis del Gateway:**
  - `suspended:sub:<id>` por identidad, con TTL igual a la vida del access token
    (`SUSPENSION_DENYLIST_TTL_SECONDS`, por defecto 86400, el valor por defecto de Auth0);
  - `suspended:email:<email en minúsculas>`, **sin TTL** hasta la reactivación. Cubre una identidad federada
    nueva con el mismo email, que Auth0 no sabe que está suspendida.
  Kong rechaza el pedido si existe cualquiera de las dos.
- **Perfil.** `GET /users/me` de una cuenta suspendida responde `403` con `type` `account-suspended`, y
  `POST /users/bulk` devuelve solo su nombre con `is_suspended: true` (perfil no disponible). El nombre se
  conserva para que los mensajes anteriores sigan mostrando quién los escribió.
- **Redis con política de evicción.** El Redis del Gateway se usa también para el rate limiting. Con
  `allkeys-lru` podría descartar una clave de suspensión al llenarse; por eso pasa a `volatile-lru`, que solo
  descarta claves con TTL. La clave por email, sin TTL, nunca se descarta.

## 3. Alternativas descartadas

- **Blacklist por `jti`:** exige conocer cada token emitido, lo que es inviable con Auth0 como emisor.
- **`token_revoked_at` comparado contra `iat` en cada servicio:** obliga a que todos los servicios consulten el estado de este servicio en cada request, o lo cacheen. Es la misma idea que la denylist, pero repartida en N servicios en lugar de resuelta una vez en el perímetro.
- **Guardar refresh tokens en la base de este servicio:** contradice ADR-001.
- **Depender solo de la expiración corta:** no cumple el "de inmediato" y no corta las conexiones WebSocket abiertas.

## 4. Consecuencias

- El corte es inmediato para REST (denylist) y para las conexiones vivas (evento), y definitivo para la emisión de tokens nuevos (Auth0).
- `auth-user-service` pasa a depender de la Management API de Auth0 (credenciales M2M con alcance mínimo) y del Redis del Gateway.
- Kong suma una lectura de Redis por request autenticado. El Redis ya existe para rate limiting.
- Chat Engine y Voice Signaling deben consumir `user.suspended`.

## 5. Estado de implementación

| Pieza | Estado |
|-------|--------|
| Columna `users.is_suspended`, más motivo, fecha y quién suspendió | Implementado |
| Endpoints de suspensión, reactivación y listado (staff) | Implementado (con tests) |
| Integración con Auth0 Management API | Implementado; falta crear la aplicación M2M en Auth0 y cargar sus credenciales |
| Escritura de la lista de bloqueados en Redis | Implementado |
| Chequeo de la lista en `auth0_validator.lua` | En el repo del Gateway |
| Evento `user.suspended` / `user.reactivated` | Publicado por el Outbox (ADR-005) |
| Consumidores en Chat Engine y Voice Signaling | En sus repos |
| Vida del access token en Auth0 | Pendiente de acortar (5–15 min); hoy se asume el valor por defecto, 24 h |
