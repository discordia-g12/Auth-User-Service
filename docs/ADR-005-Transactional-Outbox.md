# ADR-005: Transactional Outbox para eventos de dominio

- **Estado:** Aceptado, implementación parcial (ver §4)
- **Fecha:** 2026-09-27
- **Alcance:** `auth-user-service` y consumidores de sus eventos
- **Origen:** esta decisión estaba dentro del ADR de Auth0; se separa porque es independiente de la identidad

---

## 1. Contexto

Los cambios en usuarios deben notificarse a otros servicios mediante RabbitMQ: alta de usuario,
actualización de perfil (ADR-003) y suspensión (ADR-002). Escribir en la base y publicar en el broker
son dos operaciones independientes (*dual-write*). Si la segunda falla, o el proceso muere entre
ambas, el sistema queda inconsistente.

## 2. Decisión

- El evento se persiste en la tabla `outbox_events` **dentro de la misma transacción** que el cambio de dominio. Campos: `id` (UUID), `aggregate_type`, `aggregate_id`, `event_type`, `payload` (JSON), `created_at` y `processed_at` (nulo mientras no se publicó).
- Un **relay** independiente lee los eventos con `processed_at IS NULL` en orden de `created_at` (`SELECT … FOR UPDATE SKIP LOCKED`, para permitir varias instancias), los publica en RabbitMQ y marca `processed_at`.
- La entrega es **al menos una vez**: los consumidores deben ser idempotentes y deduplicar por el `id` del evento.
- Los nombres de evento siguen la forma `<agregado>.<hecho_en_pasado>`.

### Catálogo

| Evento | Payload | Emisor | Estado |
|--------|---------|--------|--------|
| `user.registered` | `user_id`, `username`, `email` | `POST /api/v1/users/me` | Implementado (se escribe en el outbox) |
| `user.profile_updated` | `user_id`, `username`, `avatar_url` | `PATCH /api/v1/users/me` (ADR-003) | Pendiente |
| `user.suspended` | `user_id` | endpoint de staff (ADR-002) | Pendiente |

## 3. Consecuencias

- El cambio de dominio y su evento son atómicos: no hay eventos perdidos ni fantasmas.
- Hay que operar un componente más (el relay) y aceptar consistencia eventual en los consumidores.
- `user.registered` lleva `email`, que es un dato personal. Los consumidores no deben loguearlo ni persistirlo sin necesidad.

## 4. Estado de implementación

| Pieza | Estado |
|-------|--------|
| Modelo `OutboxEvent` y escritura atómica en el alta | Implementado y cubierto por tests |
| Relay hacia RabbitMQ | **Pendiente:** hoy los eventos se acumulan en `outbox_events` sin publicarse |
| Versión de esquema en el payload | Pendiente de definir |
