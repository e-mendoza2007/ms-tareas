from boto3.dynamodb.conditions import Key, Attr
from comun import dynamodb, NO_AUTORIZADO, respuesta, autenticar, parametros_lista

def lambda_handler(event, context):
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
