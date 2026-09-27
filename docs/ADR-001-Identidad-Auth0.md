# ADR-001: Delegación de identidad en Auth0 y contrato de identidad con el Gateway

- **Estado:** Aceptado
- **Fecha:** 2026-09-10 · **Revisado:** 2026-09-27
- **Alcance:** `auth-user-service`, API Gateway (Kong), Auth0
- **Reemplaza a:** `ADR-03-Auth0-vs-Custom-Auth.md`
- **Relacionado:** ADR-001 del repositorio Gateway (validación de JWT en Kong); ADR-006 (recupero de contraseña)

---

## 1. Contexto

Discordia necesita autenticar usuarios y gestionar sus perfiles. La especificación exige:

- almacenamiento seguro de contraseñas con hashing adaptativo (BCrypt o Argon2id, costo >= 12);
- recuperación de contraseña con tokens de al menos 128 bits de entropía, hasheados, de un solo uso y con expiración de 1 hora como máximo;
- sesiones JWT con vida acotada y refresh;
- rate limiting contra fuerza bruta en login y recuperación;
- roles de plataforma globales (`user` / `staff`), desacoplados de los roles de servidor.

La pregunta es dónde termina `auth-user-service`: ¿implementa su propio motor de credenciales,
o delega la identidad en un proveedor especializado y se limita a la entidad de negocio del usuario?

## 2. Decisión

Se delega integralmente la identidad, las credenciales y la emisión de tokens en **Auth0**.
Las responsabilidades quedan repartidas así.

### 2.1 Auth0 (Identity Provider)

- Es el único componente que recibe, valida y almacena contraseñas. **Discordia no persiste contraseñas ni hashes.**
- Aplica la password policy, el registro (Universal Login con `screen_hint: "signup"`), el login, la recuperación de cuenta (disparada desde el servicio, ver ADR-006) y MFA. Usa Authorization Code con PKCE.
- Emite access tokens **RS256** para el audience de la API, verificables contra su JWKS pública, que rota claves.
- Una **Post Login Action** (`Gateway/auth0/post-login-action.js`):
  - **deniega el login si `email_verified !== true`**, así un usuario sin verificar nunca obtiene un token;
  - agrega al access token los claims namespaced `https://discordia.app/email`, `https://discordia.app/email_verified` y `https://discordia.app/role` (valor de `app_metadata.role`, con `"user"` por defecto). Se inyectan porque, con un audience de API propia, Auth0 no incluye `email` en el access token.

### 2.2 API Gateway (Kong): validación y autorización perimetral

- **Antes de validar**, elimina cualquier header `X-User-Id`, `X-User-Email`, `X-User-Email-Verified` y `X-User-Role` enviado por el cliente. Lo hace en todas las rutas, incluidas las públicas y los preflight `OPTIONS`.
- Verifica la firma contra la JWKS de Auth0 (`lua-resty-openidc`, JWKS cacheada con `jwk_expires_in = 3600`), y además `iss`, `aud`, `exp` y la presencia de `sub`.
- Propaga la identidad verificada en estos headers:

  | Header | Origen |
  |--------|--------|
  | `X-User-Id` | claim `sub` |
  | `X-User-Email` | claim namespaced de email, o `email` como fallback. Si el token no trae email, el header no se envía |
  | `X-User-Email-Verified` | `"true"` solo si el claim es el booleano `true` o el string `"true"`; en cualquier otro caso `"false"` |
  | `X-User-Role` | claim namespaced de rol, o `"user"` por defecto |

- Aplica la autorización por rol en el perímetro: `/api/v1/audit` y `/api/v1/metrics` exigen `staff` y responden `403` antes de llegar al servicio.
- Los errores de autenticación se devuelven en RFC 7807.

### 2.3 `auth-user-service`: entidad de dominio

- Administra el registro de negocio (`User`: `id`, `email`, `is_active`, `is_suspended`, `created_at`) y el perfil público (`UserProfile`: `username`, `bio`, `avatar_url`, `activity_status`, `custom_status`).
- Trata `X-User-Id` como **identificador opaco** (`users.id: String`), sin asumir el formato `auth0|...`.
- Abstrae el transporte HTTP en `AuthenticatedIdentity(user_id, email, email_verified)`:
  - sin `X-User-Id` responde `401`;
  - `email_verified` es fail-closed: solo el literal `true` (sin distinguir mayúsculas) cuenta como verificado.
- **Segunda barrera de verificación de email.** `POST /api/v1/users/me` exige `email` (`400` si falta) y `email_verified` (`403` con `type` `https://discordia.app/problems/email-not-verified`). La primera barrera es la Action de Auth0; esta segunda protege ante una mala configuración de la Action o del Gateway. Así se evita que alguien reserve (*squatting*) un email ajeno sin verificar. `GET /me` no exige verificación.
- **No almacena el rol de plataforma** e ignora `X-User-Role`. El rol es un concepto de autorización que emite Auth0 y aplica Kong. Guardarlo acá crearía una segunda fuente de verdad (*split-brain*).
- El alta de `User`, `UserProfile` y el evento `user.registered` se hace en una única transacción (ADR-005).

## 3. Supuesto de confianza

El modelo depende de que **solo Kong pueda alcanzar el servicio**: el servicio no valida el JWT y
confía en los headers `X-User-*`. Por eso:

- en la red `discordia-net` el servicio no se expone públicamente, y Kong lo alcanza como `auth-service:8000`;
- el puerto de host `8004` publicado por `discordia-orchestrator` existe solo para desarrollo y **no debe publicarse** en ningún entorno desplegado.

## 4. Comparativa

| Criterio | IdP propio en `auth-user-service` | Auth0 + dominio en backend (elegida) |
|----------|-----------------------------------|--------------------------------------|
| Superficie de ataque | Alta: hashes en BD, logs, ataques de temporización y fuerza bruta | Mínima: Discordia nunca toca contraseñas |
| Mantenimiento | Muy alto: hashing, recuperación, refresh, rate limiting por cuenta y MFA | Bajo: el esfuerzo va a mensajería, WebSockets y roles de servidor |
| Fuente de verdad del rol | Fragmentada entre BD y token | Única: Auth0 emite el claim y Kong lo aplica |
| Vendor lock-in | Nulo | Medio y acotado al Gateway: aguas abajo solo se consume un `user_id` opaco |

## 5. Alternativas descartadas

- **Backend como proxy de credenciales** (`POST /api/v1/auth/register` que llama a la Authentication API de Auth0): hace pasar contraseñas en texto plano por un intermediario, lo que viola las prácticas de OAuth2/OIDC. Además, todo el tráfico saldría de una única IP y agotaría el rate limiting de Auth0.
- **IdP interno con BCrypt y JWT HS256 propios:** el costo de oportunidad es desproporcionado. Implica reimplementar recuperación segura, rotación, mitigación de enumeración de cuentas y MFA.

## 6. Supuesto crítico sobre el requisito de contraseñas

Se asume que el requisito de hashing adaptativo queda cumplido por **delegación en el IdP**. Si la
evaluación exigiera que el propio servicio implemente el hashing, esta decisión debe reconsiderarse.

## 7. Consecuencias

**Positivas**

- Una filtración de la base de datos de Discordia no expone contraseñas.
- La identidad es inmutable: `user_id` y `email` salen del token validado, nunca del payload JSON.
- Hay una sola fuente de verdad para el rol.
- El servicio respeta SRP: solo se ocupa de perfil y eventos de dominio.

**Riesgos y mitigaciones**

- **Disponibilidad de Auth0:** la JWKS se cachea en Kong (`lua_shared_dict jwks`, TTL de 3600 s). Los tokens firmados con claves ya cacheadas se siguen validando aunque Auth0 no responda, siempre que no aparezca un `kid` nuevo.
- **Sincronización de claims:** los nombres de los claims namespaced deben coincidir entre la Action y las variables `AUTH0_*_CLAIM` del Gateway.
- **Revocación:** un access token es válido hasta su `exp`. La suspensión de usuarios se trata en ADR-002.
