import os
from comun import (dynamodb, ESTADOS, PRIORIDADES, NO_AUTORIZADO, respuesta,
                   autenticar, a_decimal, publicar)

# proyecto_id no se puede cambiar: una tarea pertenece a un proyecto
CAMPOS = ['titulo', 'descripcion', 'estado', 'prioridad', 'asignado_a', 'fecha_limite', 'horas']

def lambda_handler(event, context):
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
