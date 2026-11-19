import React,{useEffect,useMemo,useState} from 'react';
import{createRoot}from'react-dom/client';
import{Activity,ArrowDown,ArrowUp,CheckCircle,ChevronRight,Copy,FileUp,Play,RefreshCw,Server,ShieldCheck,Wifi,WifiOff}from'lucide-react';
import'./style.css';
const API=import.meta.env.VITE_API_URL||'http://localhost:8000'; const WS=API.replace(/^http/,'ws')+'/ws';
const experiments=[
 {id:'fail',name:'Link failure',desc:'Break primary route S1–S2. Controller should move traffic through S3.',cmd:'link s1 s2 down',recover:'link s1 s2 up'},
 {id:'loss',name:'Packet loss',desc:'Drop 5% of packets on the sender link and observe retransmissions.',cmd:'h1 tc qdisc add dev h1-eth0 root netem loss 5%',recover:'h1 tc qdisc del dev h1-eth0 root'},
 {id:'delay',name:'Network delay',desc:'Add 100 ms delay to see ACK timing and sliding-window behaviour.',cmd:'h1 tc qdisc add dev h1-eth0 root netem delay 100ms',recover:'h1 tc qdisc del dev h1-eth0 root'},
 {id:'corrupt',name:'Packet corruption',desc:'Corrupt 2% of packets. Invalid CRC packets should be discarded and recovered by retransmission.',cmd:'h1 tc qdisc add dev h1-eth0 root netem corrupt 2%',recover:'h1 tc qdisc del dev h1-eth0 root'},
 {id:'receiver',name:'Receiver failure',desc:'Stop the receiver process to demonstrate sender timeout and retry limit.',cmd:'h2 pkill -f server.py',recover:'h2 python3 server.py &'}
];
function App(){
 const[file,setFile]=useState(null),[path,setPath]=useState(''),[host,setHost]=useState('127.0.0.1'),[events,setEvents]=useState([]),[status,setStatus]=useState({receiver:'stopped',transfer:'idle',controller:{}}),[experiment,setExperiment]=useState('fail'),[lastPacket,setLastPacket]=useState(null),[lastAck,setLastAck]=useState(null),[error,setError]=useState(''),[copied,setCopied]=useState('');
 useEffect(()=>{const poll=()=>fetch(API+'/api/status').then(r=>r.json()).then(setStatus).catch(()=>{});poll();const timer=setInterval(poll,1800);const ws=new WebSocket(WS);ws.onmessage=e=>{const v=JSON.parse(e.data);setEvents(old=>[...old,v].slice(-300));if(v.type==='transfer_state')setStatus(old=>({...old,transfer:v.state}));if(v.type==='receiver_state')setStatus(old=>({...old,receiver:v.state}));if(v.type==='data_sent'||v.type==='retransmit')setLastPacket(v);if(v.type==='ack_received'||v.type==='ack_sent')setLastAck(v);if(v.type==='transfer_completed')setError('');};return()=>{clearInterval(timer);ws.close()}},[]);
 async function upload(f){if(!f)return;const d=new FormData();d.append('file',f);const r=await fetch(API+'/api/upload',{method:'POST',body:d});const x=await r.json();if(!r.ok)return alert(x.detail);setFile({name:x.name,size:x.size});setPath(x.path)}
 async function post(url,body){const r=await fetch(API+url,{method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok){setError(d.detail||d.error||'Request failed');return}setError('');return d;}
 async function runExperiment(recover=false){const action=experiment==='fail'?(recover?'link_up':'link_down'):experiment==='receiver'?(recover?'receiver_start':'receiver_stop'):(recover?'clear_netem':experiment);if(action==='receiver_start'){await post('/api/receiver/start');return;}await post('/api/experiment',{action});}
 const exp=experiments.find(x=>x.id===experiment),ctl=status.controller||{},active=ctl.active_path||[];
 const packets=events.filter(e=>e.type==='data_sent'),acks=events.filter(e=>e.type==='ack_received'),retries=events.filter(e=>e.type==='retransmit');
 const latest=events.filter(e=>e.type==='transfer_started').at(-1),total=latest?.total_packets??lastPacket?.total??0,base=events.filter(e=>e.type==='ack_received').at(-1)?.ack??0;
 
 const activeNodes=ctl.reachable?['h1',...active.map(n=>'s'+n),'h2']:[]; const pathActive=(a,b)=>activeNodes.some((n,i)=>(n===a&&activeNodes[i+1]===b)||(n===b&&activeNodes[i+1]===a));
 const coords={1:[245,150],2:[430,70],3:[430,230],4:[620,150]}; const routePoints=active.length?[[90,150],...active.map(n=>coords[n]),[800,150]]:[[90,150],[245,150],[430,70],[620,150],[800,150]]; const routeD=routePoints.map((p,i)=>(i?'L':'M')+p[0]+','+p[1]).join(' '); const reverseD=[...routePoints].reverse().map((p,i)=>(i?'L':'M')+p[0]+','+p[1]).join(' ');
 const node=(id,x,y,label,sub)=> <g key={id} transform={'translate('+x+' '+y+')'}><rect x="-43" y="-24" width="86" height="48" rx="9" className={id[0]==='h'?'host':'sw'}/><text y="-2" textAnchor="middle" className="nt">{label}</text><text y="12" textAnchor="middle" className="ns">{sub}</text></g>;
 const link=(a,b,x1,y1,x2,y2)=>{const hot=pathActive(a,b);return <g key={a+b}><line x1={x1} y1={y1} x2={x2} y2={y2} className={'edge '+(hot?'hot':'')}/>{hot&&<circle r="5" className="moving"><animateMotion dur="1.6s" repeatCount="indefinite" path={'M'+x1+','+y1+' L'+x2+','+y2}/></circle>}</g>};
 const copy=async text=>{await navigator.clipboard.writeText(text);setCopied(text);setTimeout(()=>setCopied(''),1500)};
 const eventsList=events.slice(-70).reverse();
 return <main>
 <header><div className="brand"><div className="mark">⇄</div><div><small>COMPUTER NETWORKS PROJECT</small><h1>Reliable UDP + SDN</h1></div></div><div className="headStatus"><i className={ctl.reachable?'green':'grey'}/>{ctl.reachable?'Controller connected':'Controller not connected'}</div></header>
 <section className="welcome"><div><h2>File Transfer & Experiments</h2><p>Send a file, watch DATA and ACK packets, then break the network and see how it recovers.</p></div><span className={'state '+status.transfer}>{status.transfer}</span></section>
 <section className="top panel"><div className="sectionTitle"><div><b>1. Network topology</b><p>Four-switch diamond topology used in Mininet</p></div><span className="smalltag">OPENFLOW 1.3</span></div>
 <div className="diagram"><svg viewBox="0 0 900 300" aria-label="Four switch diamond network">
 {link('h1','s1',90,150,245,150)}{link('s1','s2',245,150,430,70)}{link('s1','s3',245,150,430,230)}{link('s2','s4',430,70,620,150)}{link('s3','s4',430,230,620,150)}{link('s4','h2',620,150,800,150)}
 {node('h1',90,150,'SENDER','H1 · 10.0.0.1')}{node('s1',245,150,'S1','switch 1')}{node('s2',430,70,'S2','primary path')}{node('s3',430,230,'S3','backup path')}{node('s4',620,150,'S4','switch 4')}{node('h2',800,150,'RECEIVER','H2 · 10.0.0.2')}
 {lastPacket&&<circle key={'data-'+events.length+'-'+active.join('-')} r="7" className="dataDot"><animateMotion dur="1.1s" repeatCount="1" path={routeD}/></circle>}
 {lastAck&&<circle key={'ack-'+events.length+'-'+active.join('-')} r="7" className="ackDot"><animateMotion dur="1.1s" repeatCount="1" path={reverseD}/></circle>}
 </svg></div>
 <div className="legend"><span><i className="dataKey"/> DATA →</span><span><i className="ackKey"/> ← ACK</span><span><i className="routeKey"/> Controller active route</span><span className="routeText">{ctl.reachable?'Active path: '+(active.join(' → ')||'No path'):'Waiting for controller status'}</span></div>
 </section>
 <section className="grid2">
 <article className="panel"><div className="sectionTitle"><div><b>2. Send a file</b><p>Runs client.py on Mininet H1 and server.py on Mininet H2</p></div><FileUp/></div>
 <label className="filebox"><input type="file" onChange={e=>upload(e.target.files[0])}/><FileUp/><strong>{file?.name||'Choose file'}</strong><small>{file?file.size.toLocaleString()+' bytes':'Click to select a file'}</small></label>
 <label className="field">MININET RECEIVER<input value="10.0.0.2" readOnly/></label>
 <div className="btns"><button onClick={()=>post('/api/receiver/start')}><Server size={16}/> Start H2 receiver</button><button className="primary" disabled={!path||status.transfer==='running'} onClick={()=>post('/api/transfer/start',{path,host,port:5001})}><Play size={16}/> Send file</button></div>
 {error&&<p className="error">{error}</p>}<p className="tip">Mininet destination: 10.0.0.2. This dashboard sends through the live Mininet H1 → H2 topology.</p>
 </article>
 <article className="panel"><div className="sectionTitle"><div><b>3. Transfer progress</b><p>Live values from sender events</p></div><Activity/></div>
 <div className="progress"><div className="progressText"><b>{base} / {total||'—'}</b><span>Packets cumulatively acknowledged</span></div><div className="bar"><i style={{width:(total?Math.min(100,base/total*100):0)+'%'}}/></div></div>
 <div className="stats"><div><b>{packets.length}</b><small>DATA sent</small></div><div><b>{acks.length}</b><small>ACK received</small></div><div><b>{retries.length}</b><small>Retransmits</small></div></div>
 <div className="packetNow"><div><ArrowUp/><span>Last DATA</span><b>{lastPacket?'seq '+lastPacket.seq:'—'}</b></div><div><ArrowDown/><span>Last ACK</span><b>{lastAck?'ACK '+(events.filter(e=>e.type==='ack_received').at(-1)?.ack??lastAck.ack):'—'}</b></div></div>
 </article></section>
 <section className="panel packets"><div className="sectionTitle"><div><b>4. Sliding window & packet timeline</b><p>Watch sequence numbers move through the sender window</p></div><span className="smalltag">WINDOW SIZE · 32</span></div>
 <div className="windowInfo"><span>Base = <b>{base}</b></span><span>Next DATA = <b>{lastPacket?lastPacket.seq+1:0}</b></span><span>Window end = <b>{Math.min(base+31,total?total-1:31)}</b></span></div>
 <div className="packetGrid">{Array.from({length:Math.min(Math.max(total,16),32)},(_,i)=>{const seq=Math.floor(base/32)*32+i;const sent=events.some(e=>(e.type==='data_sent'||e.type==='retransmit')&&e.seq===seq),acked=seq<base;const retry=retries.some(e=>e.seq===seq);return <div key={seq} className={'packet '+(acked?'acked':retry?'retry':sent?'sent':'waiting')}><b>{seq}</b><small>{acked?'ACKED':retry?'RETRY':sent?'SENT':'WAIT'}</small></div>})}</div>
 <div className="packetLegend"><span>Green: acknowledged</span><span>Blue: sent / in flight</span><span>Orange: retransmitted</span><span>Grey: waiting</span></div>
 </section>
 <section className="panel experiments"><div className="sectionTitle"><div><b>5. Experiments</b><p>Choose an experiment, run the command in the Mininet CLI, then observe the result here.</p></div><span className="smalltag">MININET CLI</span></div>
 <div className="expLayout"><div className="expList">{experiments.map(e=><button key={e.id} className={experiment===e.id?'selected':''} onClick={()=>setExperiment(e.id)}><b>{e.name}</b><small>{e.desc}</small></button>)}</div><div className="expDetail"><h3>{exp.name}</h3><p>{exp.desc}</p><label>RUN IN MININET CLI</label><div className="command"><code>{exp.cmd}</code><button onClick={()=>copy(exp.cmd)}><Copy size={15}/>{copied===exp.cmd?'Copied':'Copy'}</button></div><label>UNDO / RECOVER</label><div className="command"><code>{exp.recover}</code><button onClick={()=>copy(exp.recover)}><Copy size={15}/>{copied===exp.recover?'Copied':'Copy'}</button></div><div className="btns"><button className="primary" onClick={()=>runExperiment(false)}>Apply experiment in Mininet</button><button onClick={()=>runExperiment(true)}>Recover / reset</button></div><p className="tip">These controls act on the live Ubuntu Mininet topology; commands above are also available for manual use.</p></div></div>
 </section>
 <section className="panel"><div className="sectionTitle"><div><b>6. Live event log</b><p>Real events emitted by the sender and receiver processes</p></div><button onClick={()=>setEvents([])} className="plain"><RefreshCw size={14}/> Clear</button></div>
 <div className="logHead"><span>TYPE</span><span>DETAIL</span><span>SOURCE</span></div><div className="logList">{eventsList.length?eventsList.map((e,i)=><div className="logRow" key={i}><b className={'tag '+e.type}>{(e.type||'log').replaceAll('_',' ')}</b><span>{e.message||JSON.stringify(e)}</span><small>{e.source||'backend'}</small></div>):<div className="empty">No events yet. Start a receiver and send a file to see packet activity.</div>}</div></section>
 <section className="panel integrity"><ShieldCheck/><div><b>File integrity check</b><p>The receiver verifies file size and SHA-256 before saving. A successful transfer prints the matching hash in the event log.</p></div></section>
 <footer>Reliable UDP file transfer · SDN failover · Mininet + OS-Ken</footer>
 </main>
}
createRoot(document.getElementById('root')).render(<App/>);