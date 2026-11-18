import asyncio, json, socket, subprocess, sys, threading
from pathlib import Path
from typing import Set
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
ROOT=Path(__file__).resolve().parents[2]; UPLOADS=Path(__file__).parent/'uploads'; UPLOADS.mkdir(exist_ok=True)
app=FastAPI(title='Reliable UDP Transfer UI')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173'],allow_methods=['*'],allow_headers=['*'])
clients:Set[WebSocket]=set(); events=[]; receiver=None; sender=None; state={'receiver':'stopped','transfer':'idle'}
async def publish(event):
    events.append(event)
    if len(events)>300: del events[:-300]
    for ws in list(clients):
        try: await ws.send_json(event)
        except Exception: clients.discard(ws)
def reader(proc,source):
    for line in iter(proc.stdout.readline,''):
        line=line.strip()
        if line:
            event={'type':'log','source':source,'message':line}
            if line.startswith('EVENT '):
                try: event=json.loads(line[6:]); event['source']=source
                except json.JSONDecodeError: pass
            asyncio.run_coroutine_threadsafe(publish(event),app.state.loop)
    code=proc.wait(); asyncio.run_coroutine_threadsafe(publish({'type':'process_exit','source':source,'code':code}),app.state.loop)
    if source=='sender': state['transfer']='completed' if code==0 else 'failed'
@app.on_event('startup')
async def startup(): app.state.loop=asyncio.get_running_loop()
@app.get('/api/status')
async def status():
    c={'reachable':False,'active_path':[],'down_ports':[]}
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(.3); s.sendto(b'{"event":"status"}',('127.0.0.1',9999)); d,_=s.recvfrom(2048); c={'reachable':True,**json.loads(d)}; s.close()
    except (OSError,ValueError): pass
    return {'receiver':state['receiver'],'transfer':state['transfer'],'controller':c}
@app.post('/api/upload')
async def upload(file:UploadFile=File(...)):
    name=Path(file.filename or 'upload.bin').name; data=await file.read()
    if not data: raise HTTPException(400,'Empty file')
    p=UPLOADS/name; p.write_bytes(data); return {'path':str(p),'name':name,'size':len(data)}
@app.post('/api/receiver/start')
async def start_receiver():
    global receiver
    if receiver and receiver.poll() is None: return {'status':'already running'}
    receiver=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1); state['receiver']='running'; threading.Thread(target=reader,args=(receiver,'receiver'),daemon=True).start(); return {'status':'started'}
@app.post('/api/transfer/start')
async def start_transfer(data:dict):
    global sender
    if sender and sender.poll() is None: raise HTTPException(409,'Transfer already running')
    p=Path(data.get('path','')); host=data.get('host','127.0.0.1'); port=int(data.get('port',5001))
    if not p.is_file(): raise HTTPException(400,'Upload a file first')
    sender=subprocess.Popen([sys.executable,str(ROOT/'client.py'),str(p),host,'--port',str(port)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1); state['transfer']='running'; threading.Thread(target=reader,args=(sender,'sender'),daemon=True).start(); return {'status':'started'}
@app.websocket('/ws')
async def ws_endpoint(ws:WebSocket):
    await ws.accept(); clients.add(ws)
    for e in events[-100:]: await ws.send_json(e)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: clients.discard(ws)