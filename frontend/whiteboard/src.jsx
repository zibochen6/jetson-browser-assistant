import React, {useCallback, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Excalidraw, exportToBlob, loadFromBlob, serializeAsJSON} from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import './style.css';

const defaults={zoom:{value:1},scrollX:0,scrollY:0,currentItemFontFamily:2};
const storageKey='jetson-whiteboard-scene-v1';
function stored(){
  try{const data=JSON.parse(localStorage.getItem(storageKey));if(data?.type==='excalidraw')return {...data,appState:{...data.appState,...defaults}};}catch{}
  return {appState:defaults};
}
function App(){
  const [initial,setInitial]=useState(stored),[boardKey,setBoardKey]=useState(0);
  const [status,setStatus]=useState(null),[connected,setConnected]=useState(true),[error,setError]=useState('');
  const api=useRef(null),saveTimer=useRef(null),fileInput=useRef(null),currentVersions=useRef('');
  const attach=useCallback(value=>{
    api.current=value;
    // Public scene reads/exports only. No scene or tool mutation API is exposed.
    window.whiteboard=Object.freeze({
      read(){const s=value.getAppState();return JSON.parse(JSON.stringify({elements:value.getSceneElements(),
        appState:{scrollX:s.scrollX,scrollY:s.scrollY,zoom:s.zoom,offsetLeft:s.offsetLeft,offsetTop:s.offsetTop,
        width:s.width,height:s.height,activeTool:s.activeTool,selectedElementIds:s.selectedElementIds,
        editingTextElement:s.editingTextElement?.id||null,cursorButton:s.cursorButton},
        viewport:{screenX,screenY,outerWidth,outerHeight,innerWidth,innerHeight,devicePixelRatio}}));},
      scene(){return serializeAsJSON(value.getSceneElements(),value.getAppState(),value.getFiles(),'local');},
      async png(){const blob=await exportToBlob({elements:value.getSceneElements(),appState:{...value.getAppState(),exportBackground:true},files:value.getFiles(),mimeType:'image/png'});
        return await new Promise((resolve,reject)=>{const r=new FileReader();r.onerror=reject;r.onload=()=>resolve(r.result);r.readAsDataURL(blob);});}
    });
  },[]);
  const changed=useCallback((elements,appState,files)=>{
    currentVersions.current=JSON.stringify(elements.filter(e=>!e.isDeleted).map(e=>[e.id,e.version,e.versionNonce]).sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0));
    clearTimeout(saveTimer.current);
    saveTimer.current=setTimeout(()=>{try{localStorage.setItem(storageKey,serializeAsJSON(elements,appState,files,'local'));}catch{setError('Local autosave failed. Keep your exported scene file.');}},250);
  },[]);
  useEffect(()=>{
    let alive=true,timer;
    const get=async url=>{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error(r.status);return r.json();};
    const poll=async()=>{try{
      const h=await get('/health');const result=h.latest_task_id?await get('/tasks/'+h.latest_task_id):null;
      if(alive){setConnected(true);setStatus(result);}
    }catch{if(alive)setConnected(false);}finally{if(alive)timer=setTimeout(poll,500);}};
    poll();return()=>{alive=false;clearTimeout(timer);clearTimeout(saveTimer.current);};
  },[]);
  async function openFile(event){
    const file=event.target.files?.[0];if(!file)return;
    try{
      if(file.size>10*1024*1024)throw Error('Choose a scene under 10MB.');
      const restored=await loadFromBlob(file,null,null);
      clearTimeout(saveTimer.current);
      setInitial({...restored,appState:{...restored.appState,...defaults}});
      setBoardKey(k=>k+1);setError('');
    }catch(e){setError('Could not open scene: '+e.message);}
    event.target.value='';
  }
  const busy=['RUNNING','NEEDS_USER'].includes(status?.status);
  const canvasChanged=!busy&&status?.final_scene_versions&&JSON.stringify(status.final_scene_versions)!==currentVersions.current;
  const elapsed=status?.total_seconds;
  return <main>
    <header className="board-header">
      <div className="brand"><span className="mark">J</span><div><strong>Whiteboard</strong><small>LOCAL · QWEN + LAYA</small></div></div>
      <div className="progress" aria-live="polite"><span className={'state '+(status?.status||'READY')}>{connected?(status?.status?.replaceAll('_',' ')||'READY'):'DISCONNECTED'}</span><span className="action">{canvasChanged?'Canvas changed since the last task. Enter a task to continue.':busy?(status?.current_action||status?.message):(status?.message||'Enter a task in the terminal to begin.')}</span></div>
      <div className="metrics"><b>{elapsed===undefined?'—':elapsed.toFixed(1)+'s'}</b><small>{status?.browser_actions||0} operations · {status?.laya_calls||0} Laya calls</small></div>
      <button disabled={busy} onClick={()=>fileInput.current.click()}>Open scene</button>
      <input ref={fileInput} data-testid="open-scene-file" type="file" accept=".excalidraw,application/json" onChange={openFile} hidden/>
      <details className="run-details"><summary>Run details</summary><div><strong>{canvasChanged?'Canvas changed since verification':status?.scene_verified?'Canvas verified':'Verification pending'}</strong><p>{status?.request||'No task submitted in this session.'}</p><p>Qwen parsing: {(status?.task_parse_seconds||0).toFixed(1)}s<br/>Laya: {(status?.laya_decision_seconds||0).toFixed(1)}s<br/>UI: {(status?.ui_seconds||0).toFixed(1)}s<br/>Verification: {(status?.verification_seconds||0).toFixed(1)}s<br/>Save: {(status?.save_seconds||0).toFixed(1)}s</p><code>{status?.run_directory||'Task records appear after submission.'}</code>{!connected&&<p>Connection lost. Showing the last received state.</p>}</div></details>
    </header>
    {error&&<div role="alert" className="error">{error}</div>}
    <section className="canvas"><Excalidraw key={boardKey} excalidrawAPI={attach} onChange={changed} langCode="en" initialData={initial}
      UIOptions={{canvasActions:{loadScene:false,export:{saveFileToDisk:true},saveToActiveFile:true}}}/></section>
  </main>;
}
createRoot(document.getElementById('root')).render(<App/>);
