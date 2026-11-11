import os
from comun import dynamodb, NO_AUTORIZADO, respuesta, autenticar, publicar

def lambda_handler(event, context):
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
