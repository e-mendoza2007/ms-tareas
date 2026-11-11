from comun import dynamodb, NO_AUTORIZADO, respuesta, autenticar

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
    r = dynamodb.Table('t_tareas').get_item(
        Key={'tenant_id': tenant_id, 'tarea_id': tarea_id})
    # Salida (json)
    if 'Item' not in r:
        return respuesta(404, mensaje='La tarea no existe')
    return respuesta(200, tarea=r['Item'])
