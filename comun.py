import json
import time
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


# Cache en memoria del contenedor: evita leer t_tokens_acceso en cada peticion
_CACHE_TOKENS = {}
TTL_TOKEN = 60


def autenticar(event):
    """Valida el token leyendo t_tokens_acceso directo (sin invocar otra Lambda: cada
    peticion usa 1 sola Lambda). Devuelve {'tenant_id', 'usuario_id', 'rol'} o None."""
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    token = headers.get('authorization')
    if not token:
        return None
    ahora = time.time()
    guardado = _CACHE_TOKENS.get(token)
    if guardado and guardado[0] > ahora:
        return guardado[1]
    item = dynamodb.Table('t_tokens_acceso').get_item(Key={'token': token}).get('Item')
    if not item or datetime.now().strftime('%Y-%m-%d %H:%M:%S') > item['expires']:
        return None
    datos = {'statusCode': 200, 'tenant_id': item['tenant_id'],
             'usuario_id': item['usuario_id'], 'rol': item['rol']}
    if len(_CACHE_TOKENS) > 200:
        _CACHE_TOKENS.clear()
    _CACHE_TOKENS[token] = (ahora + TTL_TOKEN, datos)
    return datos


def proyecto_existe(event, proyecto_id):
    """Comprueba en t_proyectos (mismo tenant del token) si el proyecto existe, sin invocar otra Lambda."""
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
