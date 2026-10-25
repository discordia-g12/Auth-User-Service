# ADR-003: Almacenamiento de imágenes (avatares e íconos de servidor)

- **Estado:** Aceptado, implementación parcial (ver §5)
- **Fecha:** 2026-09-27 · **Revisado:** 2026-10-24 (proveedor elegido: S3; subida a través del servicio)
- **Alcance:** `auth-user-service`, `server-roles-core-service`, clientes web y mobile, Chat Engine
- **Reemplaza a:** `ADR-02-Urls-Profile`

---

## 1. Contexto

El perfil incluye un avatar y cada servidor puede tener un ícono, ambos visibles públicamente. Por
restricción de la materia, los binarios no se persisten en bases de datos ni en el sistema de archivos de
los servidores. Otros servicios, como el historial de Chat Engine en MongoDB, pueden guardar una copia
desnormalizada de la URL que debe mantenerse actualizada.

## 2. Decisión

1. **Amazon S3, un bucket para todas las imágenes** (`discordia-g12-media`, `infra/terraform/storage.tf`),
   con un prefijo por tipo: `avatars/` (Auth) y `server-icons/` (Server-Roles). Lectura pública solo en esos
   prefijos; escritura y borrado solo para el rol IAM del nodo edge, donde corren los dos servicios. No hay
   access keys en producción: boto3 toma las credenciales del rol de la instancia.
2. **Subida a través del servicio.** El cliente manda el archivo por `multipart/form-data`
   (`PATCH /api/v1/users/me/profile/avatar`, `POST /api/v1/servers`); el servicio lo valida, lo normaliza
   y lo sube a S3. El binario pasa por el servicio pero nunca se persiste en él.
3. **Validación y normalización en el backend (Pillow):** se valida el contenido real, no el
   `Content-Type`: JPEG, PNG o WebP, hasta 5 MB y 4096×4096 px. La imagen se recorta al centro y se guarda
   como WebP de 256×256: todas pesan poco, se ven iguales y pierden los metadatos (EXIF con ubicación).
4. **Clave única por subida** (`<prefijo>/<uuid>.webp`, `Cache-Control: immutable`). Un archivo nunca
   cambia, así que nadie ve una versión vieja en caché. Al reemplazar una imagen, la anterior se borra
   recién después de confirmar el cambio en la base; si la base falla, se borra la nueva.
5. **Persistencia de la URL.** PostgreSQL guarda solo la URL pública (`user_profiles.avatar_url`,
   `servers.icon_url`).
6. **Sincronización.** Al cambiar el avatar, el servicio emite `user.profile.updated` vía Outbox (ADR-005),
   con `user_id` y `avatar_url`.
7. **Errores:** si S3 no responde (o falta `S3_BUCKET`), la operación falla con 503 y no deja nada a medias:
   no se crea el servidor ni cambia el perfil.

## 3. Alternativas descartadas

- **Cloudinary:** era la primera implementación de avatares. Se descarta para tener un solo proveedor:
  toda la infraestructura ya está en AWS, el rol de la instancia evita manejar API keys y el costo entra
  en los mismos créditos y el mismo budget. Lo que se pierde (transformaciones al vuelo) se cubre
  normalizando con Pillow al subir.
- **Subida directa del cliente con *presigned POST*:** el binario no pasaría por Kong ni por el servicio,
  pero S3 no puede validar el contenido real ni normalizar la imagen, y obliga a un segundo paso para
  confirmar la subida. Con imágenes de hasta 5 MB el costo de pasar por el servicio es bajo. Queda como
  mejora futura (ver `docs/DEUDA-TECNICA.md` del orquestador).
- **Binarios en PostgreSQL o en el filesystem:** lo prohíbe la consigna.

## 4. Consecuencias

- Cada subida ocupa memoria del servicio (hasta 5 MB por pedido) mientras se valida y se procesa.
- El módulo de storage está duplicado en Auth y Server-Roles (`storage_service.py` / `storage.py`): son
  repos separados y no hay una librería compartida.
- Las imágenes se sirven desde la URL del bucket (`*.s3.us-east-1.amazonaws.com`). `S3_PUBLIC_BASE_URL`
  permite cambiarla a un dominio propio sin tocar código.
- Los consumidores de `user.profile.updated` tienen consistencia eventual.

## 5. Estado de implementación

| Pieza | Estado |
|-------|--------|
| Bucket, policy pública por prefijo y permisos del rol edge (Terraform) | Implementado, falta `terraform apply` |
| Avatar: `PATCH /api/v1/users/me/profile/avatar` → S3 | Implementado |
| Ícono de servidor en `POST /api/v1/servers` → S3 | Implementado |
| Evento `user.profile.updated` al cambiar avatar | Implementado |
| Cambiar o quitar el ícono de un servidor existente | Pendiente |
| `avatar_url` en el alta (`POST /api/v1/users/me`) | Valida solo la longitud (≤ 500). **Todavía no restringe el dominio de la URL.** |
| Frontend (subir avatar, mandar el ícono como archivo) | Pendiente (refactor en curso) |

Lo pendiente está detallado en `docs/DEUDA-TECNICA.md` del orquestador.
