/* Real event projection shared by the live display, replay and regression tests. */
(() => {
  'use strict';
  const terminal = status => !['RUNNING', 'NEEDS_USER'].includes(status);
  function startTime(result, events) {
    if (Number.isFinite(result?.submitted_at)) return result.submitted_at;
    if (result?.finished_at != null) return result.finished_at - result.total_seconds;
    return events.length ? Date.parse(events[0].timestamp) / 1000 : 0;
  }
  function eventTime(event, result, events) {
    const time = Number.isFinite(event.elapsed_seconds) ? event.elapsed_seconds :
      Date.parse(event.timestamp) / 1000 - startTime(result, events);
    return Math.max(0, Math.min(time || 0, result?.finished_at != null ? result.total_seconds : Infinity));
  }
  function legacyStage(event) {
    return ({qwen_parser:'parse', qwen_field:'text', laya:'decide', qwen_recovery:'recovery',
      browser_startup:'browser', browser_executor:'execute', site_adapter:'calendar',
      verifier:'verify', results_wait:'results', executor_guard:'validate'})[event.actor];
  }
  function project(events, position, result = {}) {
    const view = {stage:null, current:null, active:new Map(), stages:{}, metrics:{}, status:'RUNNING',
      shown:[], decision:null, selected:null, selectedBy:'Laya', checks:null, candidates:[], legacy:!events.some(e=>e.event_type === 'operation')};
    for (const event of events) {
      if (eventTime(event, result, events) > position + 0.00001) break;
      view.shown.push(event);
      if (event.metrics) Object.assign(view.metrics, event.metrics);
      if (event.status) view.status = event.status;
      if (event.checks) view.checks = event.checks;
      if (event.candidates && event.event_type !== 'operation') view.candidates = event.candidates;
      if (event.event_type === 'operation') {
        const stats = view.stages[event.stage] ||= {visits:0, seconds:0};
        if (event.transition === 'start') {
          view.active.set(event.operation_id, event);
          stats.visits++;
        } else {
          view.active.delete(event.operation_id);
          stats.seconds += event.duration_seconds || 0;
          stats.interrupted = event.outcome === 'interrupted';
        }
        view.stage = event.stage;
        view.current = event;
        if (event.stage === 'decide') {
          view.decision = event;
          if (event.transition === 'start') view.selected = null;
          if (event.selected_action) {view.selected = event.selected_action;view.selectedBy='Laya';}
        }
      } else {
        if (view.legacy && legacyStage(event)) {
          view.stage = legacyStage(event);
          view.stages[view.stage] ||= {visits:0, seconds:null};
          view.current = event;
        }
        if (event.decision?.action) {view.selected = event.decision.action;view.selectedBy='Laya';}
        if (event.actor==='qwen_recovery' && event.selected_action) {view.selected=event.selected_action;view.selectedBy='Qwen recovery';}
        if (event.actor === 'service') view.current = event;
      }
    }
    if (view.active.size) {
      view.current = [...view.active.values()].at(-1);
      view.stage = view.current.stage;
    }
    if (result.finished_at != null && position >= result.total_seconds - .00001) {
      view.status = result.status;
      Object.assign(view.metrics, result);
      view.candidates = result.candidates || view.candidates;
    }
    if (terminal(view.status) && ['SUCCEEDED','NO_RESULTS'].includes(view.status)) {
      view.stage = 'done';
      view.stages.done = {visits:1, seconds:null};
    }
    return view;
  }
  globalThis.JetsonFlow = {project, eventTime, terminal};
  if (typeof document === 'undefined') return;

  const $ = id => document.getElementById(id);
  const nodes = [...document.querySelectorAll('[data-stage]')];
  const state = {mode:'live', id:null, result:null, events:[], cursor:0, runs:[], connected:false,
    busy:false, generation:0, position:0, playing:false, speed:1, snapAt:0, elapsed:0, previousStage:null,
    previousDetail:null, previousList:null, latest:null};
  let graphDirty = true;
  const svgNS = 'http://www.w3.org/2000/svg';
  const links = [['parse','browser'],['browser','observe'],['observe','decide'],['decide','text'],
    ['text','validate'],['validate','execute'],['execute','wait'],['wait','observe'],
    ['verify','results'],['results','sort'],['sort','fare'],['fare','done']];
  function edgePath(from, to) {
    const a = document.querySelector(`[data-stage="${from}"]`);
    const b = document.querySelector(`[data-stage="${to}"]`);
    if (!a || !b || a.hidden || b.hidden || from === to) return '';
    const root = $('graph').getBoundingClientRect(), ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
    let x1 = ar.x + ar.width / 2 - root.x, y1 = ar.y + ar.height / 2 - root.y;
    let x2 = br.x + br.width / 2 - root.x, y2 = br.y + br.height / 2 - root.y;
    if (Math.abs(y1-y2) < 8) {
      x1 += (x2>x1?1:-1)*ar.width/2; x2 -= (x2>x1?1:-1)*br.width/2;
      return `M${x1},${y1} L${x2},${y2}`;
    }
    y1 += (y2>y1?1:-1)*ar.height/2; y2 -= (y2>y1?1:-1)*br.height/2;
    return `M${x1},${y1} C${x1},${(y1+y2)/2} ${x2},${(y1+y2)/2} ${x2},${y2}`;
  }
  function drawEdges() {
    if (!graphDirty) return;
    const paths = links.map(([a,b])=>{const p=document.createElementNS(svgNS,'path');p.setAttribute('d',edgePath(a,b));return p;});
    $('structure').replaceChildren(...paths);
    graphDirty = false;
  }
  function flashEdge(from, to) {
    const path = $('event-edge');
    path.getAnimations().forEach(a=>a.cancel());
    path.setAttribute('d',edgePath(from,to));
    if (!path.getAttribute('d') || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    path.animate([{opacity:0,strokeDasharray:'8 8',strokeDashoffset:24},
      {opacity:1,offset:.25},{opacity:0,strokeDashoffset:0}], {duration:240,easing:'ease-out'});
  }
  const seconds = n => `${Math.max(0,Number(n)||0).toFixed(1)}s`;
  const spanSeconds = n => n>0&&n<.1?'<0.1s':seconds(n);
  const prettyStatus = status => ({SUCCEEDED:'Succeeded',NO_RESULTS:'No results',RUNNING:'Running',
    NEEDS_USER:'Needs user',CANCELLED:'Cancelled',FAILED:'Failed',BLOCKED:'Blocked'})[status] || status;
  function setText(id, text) { if ($(id).textContent !== String(text)) $(id).textContent = text; }
  function setPill(id, text, tone) {setText(id,text);$(id).className='pill '+tone;}
  function selectRun(id) {
    state.generation++;
    Object.assign(state,{id,result:null,events:[],cursor:0,position:0,elapsed:0,playing:false,
      previousStage:null,previousDetail:null,previousList:null});
  }
  async function get(path) {
    const controller = new AbortController();
    const timer = setTimeout(()=>controller.abort(),3000);
    try {
      const response = await fetch(path,{cache:'no-store',signal:controller.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {clearTimeout(timer);}
  }
  async function poll() {
    if (state.busy) return;
    state.busy = true;
    try {
      const health = await get('/health');
      const newest = health.active_tasks[0] || health.latest_task_id;
      if (!state.runs.length || newest !== state.latest) {
        state.runs = (await get('/runs?limit=20')).runs;
        state.latest = newest;
        const options = state.runs.map(run=>{
          const option=document.createElement('option');option.value=run.id;
          option.textContent=`${run.id} · ${prettyStatus(run.status)}`;return option;
        });
        $('runs').replaceChildren(...options);
      }
      const target = newest || state.runs[0]?.id;
      if (state.mode === 'live' && target && target !== state.id) selectRun(target);
      if (state.id) {
        const generation = state.generation, id = state.id;
        const result = await get(`/tasks/${encodeURIComponent(id)}`);
        let cursor=state.cursor, added=[];
        for (let page=0;page<30;page++) {
          const batch = await get(`/tasks/${encodeURIComponent(id)}/events?after=${cursor}`);
          added.push(...batch.events);cursor=batch.next_cursor;
          if (batch.events.length<100) break;
        }
        if (generation !== state.generation) return;
        state.result=result;state.events.push(...added);state.cursor=cursor;
        state.snapAt=performance.now();state.elapsed=result.total_seconds || 0;
        const option=[...$('runs').options].find(item=>item.value===id);
        if(option) option.textContent=`${id} · ${prettyStatus(result.status)}`;
      }
      state.connected=true;
    } catch (_) {
      if (state.connected && state.result && !terminal(state.result.status)) {
        state.elapsed+=(performance.now()-state.snapAt)/1000;state.snapAt=performance.now();
      }
      state.connected=false;state.playing=false;
    }
    finally {state.busy=false;render();}
  }
  function renderDetails(view) {
    const signature = `${state.id}:${view.decision?.sequence}:${view.selected?.id}:${view.shown.length}`;
    if (signature === state.previousDetail) return;
    state.previousDetail=signature;
    const decision=view.decision;
    setText('candidate-count',decision?.candidates ? `· ${decision.candidates.length} offered` : '');
    setText('decision-goal',decision?.goal || 'Candidate details were not recorded for this point.');
    $('candidates').replaceChildren(...(decision?.candidates || []).map(action=>{
      const li=document.createElement('li');li.textContent=`${action.kind}: ${action.label}`;
      if (action.id === view.selected?.id) {li.className='chosen';li.textContent+=' — selected';}
      return li;
    }));
    const recent = view.shown.filter(e=>e.event_type!=='operation' || e.transition==='start').slice(-6).reverse();
    $('events').replaceChildren(...recent.map(event=>{
      const li=document.createElement('li'),time=document.createElement('time'),message=document.createElement('span');
      time.textContent=seconds(eventTime(event,state.result,state.events));message.textContent=event.message;
      li.append(time,message);return li;
    }));
    setText('event-count',`${view.shown.length} events`);
  }
  function render() {
    const result=state.result;
    const live=state.mode==='live';
    document.body.dataset.disconnected=String(!state.connected);
    setPill('connection',state.connected?'Connected':'Disconnected',state.connected?'good':'bad');
    $('live').setAttribute('aria-pressed',String(live));$('replay').setAttribute('aria-pressed',String(!live));
    $('follow').hidden=live;$('playback').hidden=live;$('runs').value=state.id || '';
    if (!result) {
      setPill('status','Idle','');setText('route','Ready when you are.');
      setText('run-id',state.id || 'No task selected');
      setText('requirements',state.id?'Loading selected run…':'Enter a task in the terminal. Model loading and input waiting are excluded.');
      $('elapsed').firstChild.textContent='0.0';setText('actions','0');setText('decisions','0');
      setText('current-message',state.id?'Loading recorded events':'Waiting for a task');
      nodes.forEach(node=>node.classList.remove('active','seen','success','failure','interrupted'));
      return;
    }
    const duration=result.total_seconds || 0;
    const liveElapsed=state.elapsed+(state.connected&&!terminal(result.status)?(performance.now()-state.snapAt)/1000:0);
    const position=live?liveElapsed:state.position;
    const view=project(state.events,position,result);
    const status=live?result.status:view.status;
    const metrics=live?result:view.metrics;
    setPill('status',!state.connected&&live&&!terminal(status)?`${prettyStatus(status)} · last received`:prettyStatus(status),status==='SUCCEEDED'?'good':
      ['FAILED','BLOCKED','CANCELLED'].includes(status)?'bad':status==='NEEDS_USER'?'warn':'');
    setText('run-id',result.id);
    const task=result.task;
    setText('route',task?`${task.origin} → ${task.destination}`:result.request);
    setText('requirements',task?`${task.departure_date} · One-way · ${task.adults} adult · Economy${task.direct_only?' · Nonstop only':''}${task.price_preferred?' · Lowest price first':''}`:'Parsing the task requirements');
    $('elapsed').firstChild.textContent=position.toFixed(1);
    setText('elapsed-label',live?'Task elapsed · excludes model loading':'Replay position');
    setText('actions',metrics.browser_actions || 0);
    setText('decisions',view.stages.decide?.visits || state.events.filter(e=>e.actor==='laya'&&eventTime(e,result,state.events)<=position&&e.event_type!=='operation').length);
    setText('flow-caption',!state.connected&&live?'Disconnected · last received events':view.legacy?'Legacy record · start times not recorded':status==='NEEDS_USER'?'Waiting for user input':'Real execution events');
    for (const node of nodes) {
      const stage=node.dataset.stage, stats=view.stages[stage];
      if (['calendar','recovery'].includes(stage)) {const hidden=!stats;if(node.hidden!==hidden){node.hidden=hidden;graphDirty=true;}}
      node.classList.toggle('seen',!!stats);
      node.classList.toggle('active',stage===view.stage);
      node.classList.toggle('interrupted',!!stats?.interrupted);
      node.classList.toggle('success',stage==='done'&&status==='SUCCEEDED');
      node.classList.toggle('failure',stage===view.stage&&['FAILED','BLOCKED','CANCELLED'].includes(status));
      const active=[...view.active.values()].filter(e=>e.stage===stage);
      let label=view.legacy?'Not recorded':terminal(status)&&stage==='text'?'Not needed':'Not reached';
      if (stats?.seconds!=null) label=`${stats.visits} ${stats.visits===1?'visit':'visits'} · ${spanSeconds(stats.seconds)}`;
      if (active.length && state.connected) label=`Active · ${seconds(position-eventTime(active.at(-1),result,state.events))}`;
      if (stage==='done'&&terminal(status)) label=prettyStatus(status);
      node.querySelector('small').textContent=label;
    }
    drawEdges();
    if (state.previousStage!==view.stage) {flashEdge(state.previousStage,view.stage);state.previousStage=view.stage;}
    const current=view.current;
    setText('current-owner',status==='NEEDS_USER'?'HUMAN INPUT REQUIRED':current?.actor?.replaceAll('_',' ').toUpperCase() || 'CURRENT OPERATION');
    setText('current-message',status==='NEEDS_USER'&&live?result.message:
      current?.message || (live?result.message:view.shown.at(-1)?.message || 'No event at this replay position'));
    setText('operation-duration',current?.event_type==='operation'?
      current.transition==='start'?`Active · ${seconds(position-eventTime(current,result,state.events))}`:spanSeconds(current.duration_seconds):
      current?.elapsed_seconds!=null?`Event at ${seconds(current.elapsed_seconds)}`:'Start time: Not recorded');
    setText('selection',view.selected?`${view.selectedBy} selected: ${view.selected.label}`:'Actual model selections appear when recorded.');
    setText('query-proof',`Query: ${metrics.query_completed?'Verified':'Not verified'}`);
    setText('fare-proof',`Fare options: ${metrics.booking_options_opened?'Verified':'Not verified'}`);
    setText('sort-proof',`Price sort: ${view.stages.sort&&!view.stages.sort.interrupted?(terminal(status)&&status==='SUCCEEDED'&&result.sort_proof?'Verified':'Checked'):'Not recorded'}`);
    $('query-proof').classList.toggle('verified',!!metrics.query_completed);
    $('fare-proof').classList.toggle('verified',!!metrics.booking_options_opened);
    $('timeline').max=String(Math.max(duration,.01));$('timeline').value=String(state.position);
    setText('replay-time',`${seconds(state.position)} / ${seconds(duration)}`);
    setText('play',state.playing?'Pause':'Play');$('play').disabled=!state.events.length;
    renderDetails(view);
  }
  $('live').onclick=$('follow').onclick=()=>{state.mode='live';state.playing=false;poll();render();};
  $('replay').onclick=()=>{state.mode='replay';state.position=0;state.playing=false;render();};
  $('runs').onchange=()=>{state.mode='replay';selectRun($('runs').value);poll();};
  $('play').onclick=()=>{if(state.position>=(state.result?.total_seconds || 0))state.position=0;state.playing=!state.playing;render();};
  $('speed').onchange=()=>{state.speed=Number($('speed').value);};
  $('timeline').oninput=()=>{state.position=Number($('timeline').value);state.playing=false;render();};
  new ResizeObserver(()=>{graphDirty=true;drawEdges();}).observe($('graph'));
  let lastTick=performance.now();
  setInterval(()=>{
    const now=performance.now(),delta=Math.min(1,(now-lastTick)/1000);lastTick=now;
    if(state.playing&&state.mode==='replay'){
      state.position=Math.min(state.position+delta*state.speed,state.result?.total_seconds || 0);
      if(state.position>=(state.result?.total_seconds || 0))state.playing=false;
    }
    render();
  },100);
  setInterval(poll,500);
  poll();
})();
