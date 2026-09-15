# ADR 03: Delegación de Identidad y Credenciales en Auth0 vs. Autenticación Interna en Auth-User-Service

- **Estado:** Aceptado
- **Fecha:** 2026-09-10
- **Servicio:** `Auth-User-Service` / API Gateway
- **Autores / Decisores:** Equipo de Desarrollo Discordia

---

## 1. Contexto del Problema

La plataforma Discordia requiere autenticar usuarios y gestionar sus perfiles de forma segura, escalable y con responsabilidades desacopladas. La especificación del proyecto establece requisitos exigentes en torno a la seguridad de la autenticación:
- Almacenamiento seguro de contraseñas con hashing adaptativo (BCrypt o Argon2id con factor de coste >= 12).
- Flujo de recuperación de contraseñas con tokens de al menos 128 bits de entropía, persistidos hasheados, con expiración máxima de 1 hora y consumo de un solo uso.
- Soporte para rotación y refresh de sesión (JWT) con tiempos de vida acotados.
- Protección contra ataques de fuerza bruta mediante Rate Limiting en endpoints de login y recuperación.
- Soporte de roles de plataforma globales (`user` / `staff`) desacoplados de los roles locales de servidor.

Frente a estos requisitos, el equipo debe definir los límites de frontera del microservicio `Auth-User-Service`:
¿Debe este microservicio implementar su propio motor de credenciales, sesiones y hashing, o debe delegar la gestión de identidad a un proveedor externo especializado (Auth0) y enfocarse exclusivamente en la entidad de negocio del usuario y su perfil en Discordia?

---

## 2. Decisión Tomada

Se decide **delegar integralmente la gestión de identidad, credenciales y autenticación en Auth0**, redefiniendo las responsabilidades de `Auth-User-Service` y el API Gateway bajo el siguiente modelo:

1. **Auth0 como Proveedor de Identidad (IdP):**
   - Es la única entidad que recibe, procesa, valida y almacena contraseñas de usuarios.
   - Aplica las políticas de contraseñas seguras (*Password Policy*: mínimo 8 caracteres, mayúscula, minúscula y número).
   - Gestiona el flujo de registro, login, recuperación de cuenta, 2FA y emisión de tokens con el flujo estándar **Authorization Code con PKCE**.
   - Emite access tokens JWT firmados asimétricamente con **RS256**, publicando sus claves públicas en un endpoint JWKS con rotación automática.
   - **Discordia no almacena contraseñas ni hashes de contraseñas en ninguna base de datos propia.**
   - Inyecta el claim de rol global (`https://discordia.app/role`) en el JWT para usuarios de staff.
2. **API Gateway (Kong) como Validador de Identidad y Autorización Perimetral:**
   - Valida criptográficamente los tokens JWT contra la JWKS de Auth0 mediante cache local (`lua-resty-openidc`).
   - Extrae el claim `sub` de Auth0 e inyecta el header confiable `X-User-Id` hacia la red interna.
   - Extrae el claim `email` e inyecta el header confiable `X-User-Email`.
   - **Aplica autorización por rol en el perímetro:** rutas como `/api/v1/audit` y `/api/v1/metrics` exigen `staff` directamente en Kong, rechazando con 403 Forbidden antes de reenviar a los microservicios.
   - Devuelve respuestas de error en formato **RFC 7807** (`application/problem+json`) ante tokens inválidos, expirados, ausentes o permisos insuficientes.
3. **`Auth-User-Service` como Entidad de Dominio y Negocio:**
   - Administra el perfil público del usuario (`username`, `bio`, `avatar_url`, estado de actividad).
   - Trata al `user_id` inyectado (`X-User-Id`) como un **identificador de texto opaco (`user_id: str`)**, sin parsear ni asumir sintaxis de Auth0 (`auth0|...`).
   - **El rol de plataforma NO se almacena en `User`:** el rol es un concepto de autorización gestionado por Auth0 y Kong en el perímetro. Eliminar la columna `role` evita el problema de *split-brain* (doble fuente de verdad desincronizada).
   - Desacopla la capa de transporte HTTP mediante la abstracción `AuthenticatedIdentity(user_id=..., email=...)`.
   - Garantiza consistencia atómica mediante el **Transactional Outbox Pattern**: en la misma transacción ACID de PostgreSQL (`BEGIN ... COMMIT`), persiste el usuario, el perfil y el evento `user.registered` en la tabla `outbox_events` para ser despachado a RabbitMQ.

---

## 3. Matriz de Decisión y Comparativa

| Criterio de Evaluación | Alternativa 1: IdP Propio en `Auth-User-Service` | Alternativa 2: Delegación en Auth0 + Negocio en Backend (Elegida) |
| :--- | :--- | :--- |
| **Superficie de Ataque y Seguridad** | **Alta:** Riesgo de fugas de contraseñas en dumps de BD, logs o ataques de temporización/fuerza bruta. | **Mínima:** Discordia nunca toca ni almacena contraseñas. El proveedor cumple ISO 27001 / SOC 2. |
| **Complejidad de Mantenimiento** | **Muy Alta:** Requiere implementar y auditar hashing, revocación, blacklist, recuperación con 128 bits de entropía, refresh tokens y rate limiting por cuenta. | **Baja:** La lógica de autenticación está resuelta y auditada; el equipo invierte esfuerzo en consistencia distribuida, WebSockets y roles de servidor. |
| **Fuente de Verdad de Roles de Plataforma** | Fragmentada entre BD y tokens. | **Única:** Auth0 emite el claim y Kong lo valida en el perímetro para rutas de backoffice (`/audit`, `/metrics`). `Auth-User-Service` no duplica el estado. |
| **Consistencia Transaccional (DoD)** | Compleja de desacoplar del login. | **Excelente:** Flujo claro en `Auth-User-Service` usando `User + UserProfile + OutboxEvent` en 1 TX ACID. |
| **Vendor Lock-in** | Nulo. | **Medio / Mitigado:** El acoplamiento a Auth0 se aísla en el Gateway; los microservicios aguas abajo consumen un `user_id` opaco. |
| **Alineación con el Alcance del Proyecto** | Diluye el foco construyendo infraestructura genérica de seguridad. | **Óptima:** Permite concentrar el esfuerzo arquitectónico en microservicios, eventos, colas y resiliencia. |

---

## 4. Alternativas Descartadas

### Alternativa A: Backend como Proxy de Credenciales (`POST /api/v1/auth/register`)
- **Descripción:** El cliente envía email y password a `Auth-User-Service`, y este invoca la Authentication API de Auth0 por detrás.
- **Motivo de Descarte:** Viola las mejores prácticas de OAuth2 / OIDC al hacer pasar credenciales en texto plano por servidores intermediarios. Además, todas las peticiones hacia Auth0 provendrían de una única dirección IP (el contenedor del backend), agotando rápidamente las cuotas de rate limiting de Auth0 en tiers de desarrollo.

### Alternativa B: Implementación de IdP Interno con BCrypt y JWT Propios
- **Descripción:** Desarrollar tablas de usuarios con `hashed_password`, endpoints de `/login`, `/refresh`, `/recover-password`, y generación de JWT firmados con clave simétrica HS256.
- **Motivo de Descarte:** El costo de oportunidad es desproporcionado. Implica destinar gran parte del tiempo de desarrollo a resolver problemas resueltos (recuperación segura de contraseñas, sanitización, mitigación de enumeración de cuentas) en lugar de optimizar la mensajería distribuida, RabbitMQ, WebSockets y la observabilidad de Discordia.

---

## 5. Riesgos y Supuestos

> **Supuesto Crítico sobre el Requisito de Contraseñas (BCrypt/Argon2id):**
> La utilización de un IdP externo supone que el requisito de almacenamiento seguro de contraseñas de la especificación se satisface mediante la **responsabilidad delegada al IdP especializado** y no mediante almacenamiento directo en las bases de datos de Discordia.
>
> Discordia **no almacena credenciales ni hashes de contraseñas**. Si la consigna de evaluación académica exigiese explícitamente que `Auth-User-Service` implemente el algoritmo de hashing dentro de su propio código, esta decisión arquitectónica debería reconsiderarse para incorporar un motor de hashing local con BCrypt.

---

## 6. Consecuencias

### Positivas
- **Cero Riesgo de Exposición de Credenciales:** La base de datos de Discordia no posee hashes ni contraseñas. Si la base de datos se viera comprometida, ninguna contraseña de usuario queda expuesta.
- **Sin Doble Fuente de Verdad:** Al no almacenar `role` en la base de datos de usuarios, no existen discrepancias entre el token JWT y la base de datos. Kong aplica la regla perimetral y Auth0 mantiene la identidad.
- **Identidad Inmutable y Confiable:** Al extraer el correo electrónico y el identificador desde el token validado por Kong, se elimina cualquier vector de suplantación de identidad en el payload JSON.
- **Arquitectura Limpia y Desacoplada:** `Auth-User-Service` es un servicio de dominio centrado en perfiles y eventos de negocio, cumpliendo estrictamente con el principio de responsabilidad única (SRP).
- **Consistencia Distribuida:** El uso del Transactional Outbox Pattern garantiza que todo registro de usuario emita un evento confiable hacia RabbitMQ sin fallos de doble escritura (*dual-write problem*).

### Desafíos y Mitigaciones
- **Dependencia de la Disponibilidad de Auth0:** Si el endpoint de JWKS de Auth0 se cae, la validación de tokens en Kong podría verse afectada.
  - *Mitigación:* Se utiliza el caché en memoria compartida de `lua-resty-openidc` en Kong (`nginx/shared-dicts.conf`) con un TTL de 3600 segundos para validar tokens ya emitidos sin llamadas I/O repetidas.
- **Mitigación de Vendor Lock-in:** El campo `users.id` se modela como un identificador de texto genérico (`String`), permitiendo sustituir el IdP en el futuro simplemente actualizando el módulo de validación del Gateway.
