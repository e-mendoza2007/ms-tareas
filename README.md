# ms-tareas

Microservicio de Tareas del SaaS PPM (multi-tenant, serverless).

## Despliegue

1. Antes deben estar desplegados `ms-auth` y `ms-proyectos`
   (Tareas invoca `ValidarTokenAcceso` y `BuscarProyecto`, y se suscribe a `cola-proyectos-eventos`).
2. `serverless deploy`

Crea: 1 Lambda, la tabla `t_tareas` (con GSI por proyecto y por fecha_limite),
el tema SNS `tema-tareas` y la suscripcion de `cola-proyectos-eventos` a ese tema.

## Rutas (todas piden la cabecera `Authorization`)

| Ruta | Lambda | Cuerpo |
| --- | --- | --- |
| POST /tareas/crear | Tareas (`tareas.py`) | titulo, proyecto_id, estado?, prioridad?, asignado_a?, fecha_limite?, horas?, descripcion? |
| POST /tareas/listar | Tareas (`tareas.py`) | proyecto_id?, fecha_desde?, fecha_hasta?, estado?, asignado_a?, limit?, last_key? |
| POST /tareas/buscar | Tareas (`tareas.py`) | tarea_id |
| PUT /tareas/modificar | Tareas (`tareas.py`) | tarea_id + titulo/descripcion/estado/prioridad/asignado_a/fecha_limite/horas |
| DELETE /tareas/eliminar | Tareas (`tareas.py`) | tarea_id |

Estados: PENDIENTE, EN_CURSO, COMPLETADA. Prioridades: BAJA, MEDIA, ALTA.
Fechas en formato `YYYY-MM-DD`. `proyecto_id` no se puede cambiar.

## Eventos que publica (tema-tareas)

| Evento | Cuando |
| --- | --- |
| TareaCreada | al crear una tarea |
| TareaCompletada | al crear con estado COMPLETADA, o al pasar a COMPLETADA |
| TareaReabierta | al salir de COMPLETADA |
| TareaEliminada | al eliminar (lleva `estaba_completada`) |

`ProcesarEventosProyectos` (en ms-proyectos) los consume y actualiza `tareas_total`,
`tareas_completadas` y `avance_pct` del proyecto.

## Prueba rapida

1. Login (`POST /auth/login`) y poner el token en `Authorization`.
2. `POST /tareas/crear` con `{"titulo": "Disenar BD", "proyecto_id": "<id de un proyecto>", "fecha_limite": "2026-11-20"}`.
3. `PUT /tareas/modificar` con `{"tarea_id": "<id>", "estado": "COMPLETADA"}`.
4. `POST /proyectos/buscar` en ms-proyectos: `tareas_total` = 1, `tareas_completadas` = 1, `avance_pct` = 100.
   (el contador tarda unos segundos: el evento viaja por SNS y SQS)

## Estructura de Lambdas (1)

Una Lambda atiende varios endpoints: el codigo elige la funcion segun la ruta (`requestPath` de API Gateway).

- `tareas.py` -> Lambda **Tareas**: /tareas/crear, /tareas/listar, /tareas/buscar, /tareas/modificar, /tareas/eliminar

`comun.py` es codigo compartido (token, respuestas, helpers), no es una Lambda.
