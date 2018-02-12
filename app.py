from chalice import Chalice
import requests
import boto3
import uuid
import nexmo
import sys

if sys.version_info[0] == 3:
    from urllib.parse import urlparse, parse_qsl
else:
    from urlparse import urlparse, parse_qsl

NAME = "TTSPrompt"

app = Chalice(app_name=NAME)
app.debug = True  

DB_CLIENT = boto3.client('dynamodb')
DB_RES = boto3.resource('dynamodb')
MAXAGE = 3600


    
    
@app.route('/setup')
def setup():
        table = DB_CLIENT.create_table(
            TableName=NAME,
            KeySchema=[
                {
                    'AttributeName': 'tid',
                    'KeyType': 'HASH'  #Partition key
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'tid', 'AttributeType': 'S'
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )
        return table


@app.route('/call', methods=['POST'], content_types=['application/x-www-form-urlencoded', 'application/json'])
def call():
    req = app.current_request.headers
    if req['content-type'] == 'application/json':
        data = app.current_request.json_body
    else:
        data = dict(parse_qsl(app.current_request.raw_body.decode()))
    tid = str(uuid.uuid4())
    item={
        'tid': {'S':tid},
        'text':{'S':data['text']},
        'to' : {'S':data['to']},
        'pin_code':{'S':data['pin_code']},
        'callback':{'S':data['callback']},
        'callback_method':{'S':data['callback_method'].upper()},
        'failed_text':{'S':data['failed_text']},
        'bye_text':{'S':data['bye_text']},
        'stage':{'S':'error'}
    }
    r = DB_CLIENT.put_item(TableName=NAME, Item=item)
    call = {'to': [{'type': 'phone', 'number': data['to']}],
      'from': {'type': 'phone', 'number': data['from']},
      'answer_url': [req['x-forwarded-proto'] + "://" + req['host'] + "/api/answer/"+tid],
      'event_url' : [req['x-forwarded-proto'] + "://" + req['host'] + "/api/event/" + tid ]
    }
    if 'authorization' in req.keys():
        headers = {}
        headers['authorization'] = req['authorization']
        response = requests.post('https://api.nexmo.com/v1/calls', json=call, headers=headers)
    else:
        print(data['private_key'])
        client = nexmo.Client(application_id=data['app_id'], private_key=data['private_key'], key='dummy', secret='dummy')
        response = client.create_call(call)
    return {"tid" : tid}
    


@app.route('/answer/{tid}')
def answer(tid):
    req = app.current_request.to_dict()
    r = DB_CLIENT.get_item(TableName=NAME, Key={'tid':{'S':tid}})
    data = r['Item']
    ncco = []
    n = {}
    n['action'] = "talk"
    n['text'] = data['text']['S']
    n['bargeIn'] = True
    ncco.append(n)
    n = {}
    n['action'] = "input"
    n['maxDigits'] = len(data['pin_code']['S'])
    n['eventUrl'] = [req['headers']['x-forwarded-proto'] + "://" + req['headers']['host'] + "/api/input/" + tid + "?count=1"]
    ncco.append(n)
    return ncco

@app.route('/event/{tid}', methods=['POST'])
def event(tid):
    data = app.current_request.json_body
    if data['status'] == "completed":
        callback(tid)
    
    
    
@app.route('/input/{tid}', methods=['POST'])
def input(tid):
    count = int(app.current_request.query_params['count'])
    req = app.current_request.to_dict()
    dtmf = app.current_request.json_body['dtmf']
    r = DB_CLIENT.get_item(TableName=NAME, Key={'tid':{'S':tid}})
    data = r['Item']
    if dtmf == data['pin_code']['S']:
        ncco = []
        n = {}
        n['action'] = "talk"
        n['text'] = data['bye_text']['S']
        ncco.append(n)
        update(tid, 'ok')
    elif count < 3:
        ncco = []
        n = {}
        n['action'] = "talk"
        n['text'] = data['failed_text']['S']
        n['bargeIn'] = True
        ncco.append(n)
        n = {}
        n['action'] = "input"
        n['maxDigits'] = len(data['pin_code']['S'])
        count += 1
        n['eventUrl'] = [req['headers']['x-forwarded-proto'] + "://" + req['headers']['host'] + "/api/input/" + tid + "?count="+str(count)]
        ncco.append(n)
    else:
        ncco = []
        update(tid, 'failed')
    return ncco
    
def callback(tid):
    r = DB_CLIENT.get_item(TableName=NAME, Key={'tid':{'S':tid}})
    data = r['Item']
    url = data['callback']['S']
    method = data['callback_method']['S']
    result = data['stage']['S']
    payload = {'tid' : tid, 'status' : result, 'to' : data['to']['S']}
    if method == 'GET':
        resp = requests.get(url, params=payload)
    elif method == 'POST':
        resp = requests.post(url, data=payload)
    print(resp)

    
def update(tid, stage):
    r = DB_CLIENT.update_item(
        TableName=NAME,
        Key={'tid':{'S':tid}},
        UpdateExpression="set stage = :s",
        ExpressionAttributeValues={':s': {'S':stage} },
        ReturnValues="UPDATED_NEW"
    )
    print(r)
