import os
import uuid
from datetime import datetime
from comun import (dynamodb, ESTADOS, PRIORIDADES, NO_AUTORIZADO, respuesta,
                   autenticar, proyecto_existe, a_decimal, publicar)

def lambda_handler(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json)
    body = event.get('body') or {}
    titulo = body.get('titulo')
    proyecto_id = body.get('proyecto_id')
    estado = body.get('estado', 'PENDIENTE')
    prioridad = body.get('prioridad', 'MEDIA')
    if not titulo or not proyecto_id:
        return respuesta(400, mensaje='Faltan titulo o proyecto_id')
    if estado not in ESTADOS or prioridad not in PRIORIDADES:
        return respuesta(400, mensaje='Estado o prioridad no validos')
    # Proceso: el proyecto vive en otro microservicio, se consulta a ese microservicio
    if not proyecto_existe(event, proyecto_id):
        return respuesta(404, mensaje='El proyecto no existe')
    tarea_id = f'TAR-{tenant_id}-{uuid.uuid4().hex[:8]}'
    tarea = {
        'tenant_id': tenant_id,
        'tarea_id': tarea_id,
        'proyecto_id': proyecto_id,
        'titulo': titulo,
        'descripcion': body.get('descripcion', ''),
        'estado': estado,
        'prioridad': prioridad,
        'creado_en': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    for campo in ('asignado_a', 'fecha_limite', 'horas'):
        if body.get(campo) not in (None, ''):
            tarea[campo] = body[campo]
    dynamodb.Table('t_tareas').put_item(
        Item=a_decimal(tarea), ConditionExpression='attribute_not_exists(tenant_id)')
    # Eventos para Proyectos (contadores y avance)
    topic = os.environ['TOPIC_TAREAS_ARN']
    publicar(topic, 'TareaCreada', tenant_id, {'proyecto_id': proyecto_id, 'tarea_id': tarea_id})
    if estado == 'COMPLETADA':
        publicar(topic, 'TareaCompletada', tenant_id, {'proyecto_id': proyecto_id, 'tarea_id': tarea_id})
    # Salida (json)
    return respuesta(200, tarea=tarea)
