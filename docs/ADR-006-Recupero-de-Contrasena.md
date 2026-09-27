# ADR-006: Recupero de contraseña

- **Estado:** Aceptado
- **Fecha:** 2026-09-27
- **Alcance:** `auth-user-service`, API Gateway (Kong), Auth0, clientes web y mobile
- **Relacionado:** ADR-001 (identidad delegada en Auth0)

---

## 1. Contexto

Historia "Recupero de contraseña". Criterios de aceptación:

| CA | Exigencia |
|----|-----------|
| CA1 | Email con enlace de recupero de uso único que vence en ≤ 1 hora |
| CA2 | Un enlace vencido o ya usado se informa como inválido y permite pedir otro |
| CA3 | Al definir una contraseña válida, se actualiza y el enlace queda invalidado |
| CA4 | Un email no registrado recibe la misma respuesta genérica de éxito |
| CA5 | Se limita la frecuencia de envío de emails para prevenir abuso |

Por ADR-001, las contraseñas son de Auth0: Discordia no las recibe ni las almacena. Auth0 ofrece
el reseteo interactivo (`POST /dbconnections/change_password`): envía un email con un enlace de un
solo uso y hospeda la página donde se elige la nueva contraseña.

La pregunta es quién dispara ese reseteo y dónde se aplica el límite de CA5.

## 2. Decisión

Los clientes llaman a un **endpoint público de `auth-user-service`**, que aplica un límite propio y
recién después le pide el reseteo a Auth0.

```
cliente ──POST /api/v1/auth/password-reset──▶ Kong ──▶ auth-user-service ──▶ Auth0 /dbconnections/change_password
            { email }                    límite por IP    límite por email        (envía el email)
```

### 2.1 Endpoint `POST /api/v1/auth/password-reset`

- Es público: no requiere JWT, y Kong elimina cualquier header `X-User-*`.
- Solo recibe el email. **Nunca pasa una contraseña por Discordia**: la nueva se ingresa en la página de Auth0.
- Respuestas:

  | Status | Cuándo |
  |--------|--------|
  | `202` | Pedido aceptado. Mismo cuerpo exista o no la cuenta |
  | `422` | Email con formato inválido |
  | `429` | Se superó el límite por email. `type: https://discordia.app/problems/password-reset-throttled` y header `Retry-After` |
  | `503` | Auth0 no respondió o rechazó el pedido. Sin detalles; la causa queda en el log |

### 2.2 Cómo se cumple cada criterio

- **CA1:** Auth0 envía el email, y el enlace es de un solo uso. Pedir uno nuevo invalida los anteriores. El vencimiento se configura en la plantilla *Change Password* con `URL Lifetime = 3600` (el default de Auth0 es 5 días).
- **CA2:** ante un enlace vencido o usado, Auth0 muestra su pantalla `reset-password-error`, con textos personalizados (`descriptionExpired`, `descriptionUsed`) que indican cómo pedir otro desde "¿Olvidaste tu contraseña?" en la app. El email repite esa indicación.
- **CA3:** la página de Auth0 valida la contraseña contra la password policy de la conexión, invalida el enlace, muestra la confirmación y cierra la sesión del usuario. Si la aplicación tiene configurado un *Application Login URI* `https`, la pantalla de éxito ofrece además un botón para volver a Discordia.
- **CA4:** el servicio **no consulta si la cuenta existe**. Todo pedido aceptado se reenvía a Auth0 y recibe el mismo `202`, y Auth0 también responde 200 aunque el email no exista. Como siempre se hace la llamada, el tiempo de respuesta tampoco delata la existencia de la cuenta.
- **CA5:** hay dos límites.
  - **Por email**, en el servicio: 3 pedidos por ventana deslizante de 15 minutos (`PASSWORD_RESET_MAX_REQUESTS`, `PASSWORD_RESET_WINDOW_SECONDS`). Se aplica a cualquier email, esté registrado o no, así que el `429` no revela nada. El pedido se registra **antes** de llamar a Auth0, así que los intentos fallidos también cuentan.
  - **Por IP**, en Kong: 5 pedidos por minuto y 30 por hora en la ruta, con contador en Redis.

### 2.3 Datos

La tabla `password_reset_requests` (`id`, `email_hash`, `requested_at`) guarda el **SHA-256 del
email normalizado** (trim y minúsculas), nunca el email. Los registros más viejos que la ventana se
borran en cada pedido. Los logs tampoco incluyen el email: usan un prefijo del hash.

## 3. Alternativa descartada

**Que los clientes llamen directo a Auth0**, como hacen hoy el login y el registro. Es más simple,
pero para CA5 depende del rate limit interno de Auth0, cuyos umbrales no están publicados, no se
pueden configurar y no se pueden testear. El límite quedaría fuera del sistema y sin forma de
demostrarlo.

Esto no es la alternativa "backend como proxy de credenciales" que descarta ADR-001: acá solo pasa
el email, y la contraseña se ingresa directamente en la página de Auth0.

## 4. Consecuencias y riesgos

- **Todas las llamadas a Auth0 salen de la IP del servicio.** Un ataque distribuido que agote el límite de Auth0 para esa IP dejaría el recupero sin funcionar para todos. Lo atenúan los dos límites propios; el riesgo se acepta por el bajo volumen esperado.
- **Hay un nuevo endpoint público,** con su propia configuración en Kong.
- **Hay que configurar el tenant de Auth0 a mano** (ver `Gateway/auth0/password-reset.md`). Personalizar plantillas, incluido `URL Lifetime`, **requiere un proveedor de email propio**. Sin él, CA1 no se cumple.
- **El usuario no vuelve automáticamente a la web.** El *Redirect To* de las plantillas (`resultUrl`) solo existe en tenants Enterprise, así que el resultado del reseteo lo informan las pantallas de Auth0 y la web no recibe ningún parámetro de retorno. El botón "volver a la aplicación" depende del *Application Login URI*, que exige `https` y no acepta `localhost`: en desarrollo local no aparece.
- **Condición de carrera aceptada:** el conteo y el alta no son atómicos, así que una ráfaga simultánea de pedidos para el mismo email podría superar el límite por muy pocos. El límite por IP en Kong acota ese caso.
