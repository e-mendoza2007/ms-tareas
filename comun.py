import json
from datetime import datetime
import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
_sns = boto3.client('sns')

ESTADOS = ('PENDIENTE', 'EN_CURSO', 'COMPLETADA')
PRIORIDADES = ('BAJA', 'MEDIA', 'ALTA')

NO_AUTORIZADO = {'statusCode': 403, 'mensaje': 'Forbidden - Acceso No Autorizado'}


def limpiar(obj):
    """DynamoDB devuelve Decimal; el JSON de salida necesita int/float."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: limpiar(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [limpiar(v) for v in obj]
    return obj


def a_decimal(obj):
    """DynamoDB no acepta float; los numeros del body se convierten a Decimal."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: a_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [a_decimal(v) for v in obj]
    return obj


def respuesta(codigo, **campos):
    return {'statusCode': codigo, **limpiar(campos)}


def _token(event):
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    return headers.get('authorization')


def autenticar(event):
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    token = headers.get('authorization')
    if not token:
        return None
    item = dynamodb.Table('t_tokens_acceso').get_item(Key={'token': token}).get('Item')
    if not item or datetime.now().strftime('%Y-%m-%d %H:%M:%S') > item['expires']:
        return None
    return {'statusCode': 200, 'tenant_id': item['tenant_id'],
            'usuario_id': item['usuario_id'], 'rol': item['rol']}


def proyecto_existe(event, proyecto_id):
    sesion = autenticar(event)
    if not sesion:
        return False
    r = dynamodb.Table('t_proyectos').get_item(
        Key={'tenant_id': sesion['tenant_id'], 'proyecto_id': proyecto_id})
    return 'Item' in r


def parametros_lista(body):
    """Limit y ExclusiveStartKey para paginar un Query."""
    try:
        limit = max(1, min(int(body.get('limit', 20)), 100))
    except (TypeError, ValueError):
        limit = 20
    kwargs = {'Limit': limit}
    if body.get('last_key'):
        kwargs['ExclusiveStartKey'] = body['last_key']
    return kwargs


def publicar(topic_arn, tipo_evento, tenant_id, datos):
    """Publica un evento en SNS. Si falla, no tumba la operacion principal."""
    mensaje = {'tipo_evento': tipo_evento, 'tenant_id': tenant_id, **datos}
    try:
        _sns.publish(
            TopicArn=topic_arn,
            Message=json.dumps(mensaje),
            MessageAttributes={
                'tipo_evento': {'DataType': 'String', 'StringValue': tipo_evento},
                'tenant_id': {'DataType': 'String', 'StringValue': tenant_id}
            }
        )
    except Exception as e:
        print('Error publicando evento:', str(e))
