import json
import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
_lambda = boto3.client('lambda')
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
    """Valida el token con ValidarTokenAcceso.
    Devuelve {'tenant_id', 'usuario_id', 'rol', ...} o None si no es valido."""
    token = _token(event)
    if not token:
        return None
    r = _lambda.invoke(FunctionName='ValidarTokenAcceso',
                       InvocationType='RequestResponse',
                       Payload=json.dumps({'token': token}))
    datos = json.loads(r['Payload'].read())
    if datos.get('statusCode') != 200:
        return None
    return datos


def proyecto_existe(event, proyecto_id):
    """Pregunta a ms-proyectos (Lambda BuscarProyecto) si el proyecto existe.
    Reusa el mismo token, asi Proyectos valida el tenant por su cuenta."""
    payload = {'headers': {'Authorization': _token(event)},
               'body': {'proyecto_id': proyecto_id}}
    r = _lambda.invoke(FunctionName='BuscarProyecto',
                       InvocationType='RequestResponse',
                       Payload=json.dumps(payload))
    datos = json.loads(r['Payload'].read())
    return datos.get('statusCode') == 200


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
