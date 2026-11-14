# Lambda Tareas (ms-tareas). Una sola Lambda atiende varios endpoints.
# API Gateway (integration: lambda) manda en "requestPath" la ruta del recurso.
import os
import uuid
from boto3.dynamodb.conditions import Key, Attr
from comun import dynamodb, ESTADOS, PRIORIDADES, NO_AUTORIZADO, respuesta, autenticar, proyecto_existe, a_decimal, publicar, parametros_lista
from datetime import datetime


def crear_tarea(event, context):
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


def listar_tareas(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json): todos los campos son opcionales
    body = event.get('body') or {}
    # Proceso
    kwargs = parametros_lista(body)
    if body.get('proyecto_id'):
        kwargs['IndexName'] = 'gsi_proyecto'
        kwargs['KeyConditionExpression'] = Key('tenant_id').eq(tenant_id) & Key('proyecto_id').eq(body['proyecto_id'])
    elif body.get('fecha_desde') or body.get('fecha_hasta'):
        # Vista calendario: tareas con fecha_limite dentro del rango
        desde = body.get('fecha_desde', '0000-01-01')
        hasta = body.get('fecha_hasta', '9999-12-31')
        kwargs['IndexName'] = 'gsi_fecha_limite'
        kwargs['KeyConditionExpression'] = Key('tenant_id').eq(tenant_id) & Key('fecha_limite').between(desde, hasta)
    else:
        kwargs['KeyConditionExpression'] = Key('tenant_id').eq(tenant_id)
    # Filtros extra: se aplican despues de leer, una pagina puede traer menos items que limit
    filtro = None
    if body.get('estado'):
        filtro = Attr('estado').eq(body['estado'])
    if body.get('asignado_a'):
        f = Attr('asignado_a').eq(body['asignado_a'])
        filtro = f if filtro is None else filtro & f
    if filtro is not None:
        kwargs['FilterExpression'] = filtro
    r = dynamodb.Table('t_tareas').query(**kwargs)
    # Salida (json)
    return respuesta(200, items=r['Items'], count=r['Count'],
                     last_key=r.get('LastEvaluatedKey'))


def buscar_tarea(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json)
    tarea_id = (event.get('body') or {}).get('tarea_id')
    if not tarea_id:
        return respuesta(400, mensaje='Falta tarea_id')
    # Proceso
    r = dynamodb.Table('t_tareas').get_item(
        Key={'tenant_id': tenant_id, 'tarea_id': tarea_id})
    # Salida (json)
    if 'Item' not in r:
        return respuesta(404, mensaje='La tarea no existe')
    return respuesta(200, tarea=r['Item'])


CAMPOS = ['titulo', 'descripcion', 'estado', 'prioridad', 'asignado_a', 'fecha_limite', 'horas']


def modificar_tarea(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json)
    body = event.get('body') or {}
    tarea_id = body.get('tarea_id')
    cambios = {c: body[c] for c in CAMPOS if body.get(c) not in (None, '')}
    if not tarea_id or not cambios:
        return respuesta(400, mensaje='Falta tarea_id o algun campo a modificar')
    if 'estado' in cambios and cambios['estado'] not in ESTADOS:
        return respuesta(400, mensaje='Estado no valido: ' + ', '.join(ESTADOS))
    if 'prioridad' in cambios and cambios['prioridad'] not in PRIORIDADES:
        return respuesta(400, mensaje='Prioridad no valida: ' + ', '.join(PRIORIDADES))
    # Proceso
    nombres, valores, partes = {}, {}, []
    for i, (campo, valor) in enumerate(a_decimal(cambios).items()):
        nombres[f'#c{i}'] = campo
        valores[f':v{i}'] = valor
        partes.append(f'#c{i} = :v{i}')
    try:
        r = dynamodb.Table('t_tareas').update_item(
            Key={'tenant_id': tenant_id, 'tarea_id': tarea_id},
            UpdateExpression='SET ' + ', '.join(partes),
            ConditionExpression='attribute_exists(tenant_id)',
            ExpressionAttributeNames=nombres,
            ExpressionAttributeValues=valores,
            ReturnValues='ALL_OLD'
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return respuesta(404, mensaje='La tarea no existe')
    viejo = r['Attributes']
    # Eventos: solo cuando el estado cruza la frontera de COMPLETADA
    if 'estado' in cambios:
        topic = os.environ['TOPIC_TAREAS_ARN']
        datos = {'proyecto_id': viejo['proyecto_id'], 'tarea_id': tarea_id}
        if cambios['estado'] == 'COMPLETADA' and viejo.get('estado') != 'COMPLETADA':
            publicar(topic, 'TareaCompletada', tenant_id, datos)
        elif cambios['estado'] != 'COMPLETADA' and viejo.get('estado') == 'COMPLETADA':
            publicar(topic, 'TareaReabierta', tenant_id, datos)
    # Salida (json)
    return respuesta(200, tarea={**viejo, **cambios})


def eliminar_tarea(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json)
    tarea_id = (event.get('body') or {}).get('tarea_id')
    if not tarea_id:
        return respuesta(400, mensaje='Falta tarea_id')
    # Proceso
    try:
        r = dynamodb.Table('t_tareas').delete_item(
            Key={'tenant_id': tenant_id, 'tarea_id': tarea_id},
            ConditionExpression='attribute_exists(tenant_id)',
            ReturnValues='ALL_OLD'
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return respuesta(404, mensaje='La tarea no existe')
    viejo = r['Attributes']
    # Evento para Proyectos: baja el total y, si estaba completada, tambien las completadas
    publicar(os.environ['TOPIC_TAREAS_ARN'], 'TareaEliminada', tenant_id,
             {'proyecto_id': viejo['proyecto_id'], 'tarea_id': tarea_id,
              'estaba_completada': viejo.get('estado') == 'COMPLETADA'})
    # Salida (json)
    return respuesta(200, mensaje='Tarea eliminada')


RUTAS = {
    '/tareas/crear': crear_tarea,
    '/tareas/listar': listar_tareas,
    '/tareas/buscar': buscar_tarea,
    '/tareas/modificar': modificar_tarea,
    '/tareas/eliminar': eliminar_tarea,
}

def lambda_handler(event, context):
    ruta = (event or {}).get('requestPath')
    funcion = RUTAS.get(ruta)
    if funcion is None:
        return {'statusCode': 404, 'mensaje': 'Ruta no encontrada: %s' % ruta}
    return funcion(event, context)
