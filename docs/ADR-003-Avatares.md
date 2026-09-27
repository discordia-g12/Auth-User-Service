# ADR-003: Almacenamiento y gestión de avatares

- **Estado:** Aceptado, implementación parcial (ver §5)
- **Fecha:** 2026-09-27
- **Alcance:** `auth-user-service`, clientes web y mobile, Chat Engine
- **Reemplaza a:** `ADR-02-Urls-Profile`

---

## 1. Contexto

El perfil incluye un avatar visible públicamente. Por restricción de la materia, los binarios no se
persisten en bases de datos ni en el sistema de archivos de los servidores. Otros servicios, como el
historial de Chat Engine en MongoDB, guardan una copia desnormalizada del avatar que debe
mantenerse actualizada.

## 2. Decisión

1. **Almacenamiento de objetos externo.** Las imágenes viven en un servicio de object storage (Cloudinary o AWS S3; la elección del proveedor sigue pendiente).
2. **Subida directa del cliente, con firma emitida por el backend.** `auth-user-service` entrega una autorización de subida de corta duración (firma de Cloudinary o *presigned POST* de S3) y el cliente sube el archivo directamente al storage. **El binario nunca pasa por Discordia.**
3. **Validación en la política de subida firmada:** solo JPEG, PNG o WebP, y hasta 5 MB. El storage rechaza lo que no cumple, así que la validación no depende del cliente.
4. **Persistencia de la URL.** PostgreSQL guarda solo la URL pública (`user_profiles.avatar_url`, hasta 500 caracteres). El servicio debe aceptar únicamente URLs del dominio del storage propio, para evitar URLs arbitrarias (tracking, contenido externo).
5. **Sincronización.** Al actualizar el perfil, el servicio emite `user.profile_updated` vía Outbox (ADR-005), con `user_id`, `username` y `avatar_url`. Chat Engine actualiza su copia desnormalizada.

## 3. Alternativas descartadas

- **Subida a través del servicio (proxy hacia el storage):** cumple la restricción si no se persiste nada, pero hace pasar cada binario por Kong y por el servicio, con más ancho de banda y más memoria, sin ventaja de seguridad frente a la política firmada.
- **Binarios en PostgreSQL o en el filesystem:** lo prohíbe la consigna.

## 4. Consecuencias

- El servicio no maneja binarios ni necesita límites de payload grandes.
- Aparece una dependencia con el proveedor de storage (credenciales para firmar).
- Los consumidores de `user.profile_updated` tienen consistencia eventual.

## 5. Estado de implementación

| Pieza | Estado |
|-------|--------|
| `avatar_url` en el alta (`POST /api/v1/users/me`) | Implementado, pero valida solo la longitud (≤ 500). **Todavía no restringe el dominio de la URL.** |
| Elección del proveedor de storage | Pendiente |
| Endpoint de firma de subida | Pendiente |
| Actualización de perfil (`PATCH /api/v1/users/me`) | Pendiente |
| Evento `user.profile_updated` | Pendiente (requiere `PATCH` y el relay de ADR-005) |
