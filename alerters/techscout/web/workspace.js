(() => {
  'use strict';
  const el=id=>document.getElementById(id),B=window.TechScoutBrowsing;
  const esc=v=>String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dollars=v=>v==null ? 'Unknown' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(v);
  const date=v=>v ? new Date(v).toLocaleString() : 'Unknown';
  const categoryNames={monitor:'All deals','desktop-memory':'Desktops',computers:'Computers',tablets:'Tablets',memory:'Memory',supplies:'Tech supplies',amazon:'Amazon deals'};
  let allRows=[],allSnapshot=null,openJudgments=new Set();
  let data=null,context=null,pane='deals',draft=null,saving=false,sequence=0;
  function notice(message){el('workspace-notice').textContent=message;el('workspace-notice').hidden=!message;}
  function show(value){pane=value;for(const name of ['deals','watching','alerts','sources'])el(`${name}-pane`).hidden=name!==value;document.querySelectorAll('[data-pane]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.pane===value)));render();window.scrollTo({top:0});}
  async function refresh(){
    if(saving)return;
    const version=++sequence;
    try{const [response,snapshotResponse]=await Promise.all([fetch('/api/workspace',{cache:'no-store'}),fetch('/api/state?category=monitor',{cache:'no-store'})]);if(!response.ok || !snapshotResponse.ok)throw Error();const result=await response.json(),snapshot=await snapshotResponse.json();if(version!==sequence)return;data=result;allSnapshot=snapshot.snapshot;allRows=B.rowsOf(allSnapshot);render();}
    catch(_){notice('Could not load watch settings or alert activity. Retrying shortly.');}
  }
  async function save(settings){
    if(!data || saving)return false;saving=true;sequence++;el('notification-mode').disabled=true;
    try{
      const response=await fetch('/api/watches',{method:'POST',headers:{'Content-Type':'application/json','X-TechScout-Token':document.querySelector('meta[name="techscout-token"]').content},body:JSON.stringify({revision:data.revision,settings})});
      const result=await response.json();if(!response.ok)throw Error(result.error || 'Could not save watches');
      data={...data,...result,error:null};notice('Watch settings saved. The monitor applies them on its next job.');return true;
    }catch(error){notice(error.message);el('watch-error').textContent=error.message;saving=false;await refresh();return false;}
    finally{saving=false;render();}
  }
  function description(watch){
    return [watch.product_id ? 'Exact product' : categoryNames[watch.category],...Object.entries(watch.filters).map(([k,v])=>`${B.labels[k]}: ${v}`),watch.source!=='all' ? watch.source : '',watch.budget!=null ? `Up to ${dollars(watch.budget)}` : '',watch.reuse ? 'RAM reuse preference' : ''].filter(Boolean).join(' · ');
  }
  function openWatch(watch){
    if(!data?.supported){notice('The installed monitor needs the integration update before watches can be saved.');return;}
    draft=structuredClone(watch);el('watch-name').value=draft.name;el('watch-budget').value=draft.budget ?? '';el('watch-enabled').checked=draft.enabled;el('watch-description').textContent=description(draft);el('watch-error').textContent='';
    el('watch-dialog-title').textContent=data.settings.watches.some(w=>w.id===draft.id) ? 'Edit watch' : draft.product_id ? 'Watch this product' : 'Watch this search';
    const select=(key,label,values,value)=>`<label>${label}<select data-watch-field="${key}">${values.map(v=>`<option value="${esc(v)}" ${v===value ? 'selected' : ''}>${esc(key==='category' ? categoryNames[v] : v==='all' ? 'All sources' : v || 'Any')}</option>`).join('')}</select></label>`;
    el('watch-criteria').innerHTML=draft.product_id ? '' : select('category','Category',['monitor','desktop-memory','computers','tablets','memory','supplies','amazon'],draft.category)+select('source','Source',[...new Set(['all',...context.rows.map(r=>r.source),draft.source])],draft.source)+B.keys.map(key=>select(key,B.labels[key],[...new Set(['',...context.rows.map(r=>B.value(r,key)),draft.filters[key] || ''])],draft.filters[key] || '')).join('');
    el('watch-reuse').checked=draft.reuse;el('watch-reuse-label').hidden=Boolean(draft.product_id);el('watch-dialog').showModal();
  }
  function newWatch(product){
    if(!context)return;
    const p=context.prefs;
    openWatch({id:crypto.randomUUID().replaceAll('-',''),name:product ? (product.product_name || product.title).slice(0,80) : `${categoryNames[context.category]} ${Object.values(p.filters).filter(Boolean).join(' ')}`.slice(0,80),enabled:true,category:product ? 'monitor' : context.category,filters:product ? {} : Object.fromEntries(Object.entries(p.filters).filter(([,v])=>v)),source:product ? product.source : p.source,budget:p.budget,reuse:product ? false : p.reuse,product_id:product?.id || ''});
  }
  function renderWatches(){
    el('notification-mode').disabled=!data?.supported || saving;
    if(!data){el('watch-status').textContent='Loading monitor settings…';return;}
    el('notification-mode').value=data.settings.mode;
    el('watch-status').textContent=data.error || (!data.supported ? 'Install the monitor integration to enable watch controls.' : data.settings.mode==='all' ? 'Existing monitor rules are active. Saved watches are ready to browse; choose Only enabled watches to restrict alerts.' : data.settings.mode==='paused' ? 'Deal notifications are paused. Collection continues.' : 'Only enabled watches can pass already-qualified deals to notifications. No enabled watches means no deal notifications.');
    el('watch-list').innerHTML=data.settings.watches.length ? data.settings.watches.map(w=>`<article class="watch-card"><h2>${esc(w.name)}</h2><p>${esc(description(w))}</p><span class="badge">${w.enabled ? 'Enabled' : 'Paused'}</span><div class="card-actions"><button data-edit-watch="${w.id}">Edit</button><button data-toggle-watch="${w.id}">${w.enabled ? 'Pause' : 'Enable'}</button><button data-browse-watch="${w.id}">Browse matches</button><button data-delete-watch="${w.id}">Remove</button></div></article>`).join('') : '<p class="empty">No saved watches yet. In Deals, choose Watch this search or Watch product on a card.</p>';
  }
  function renderAlerts(){
    const decisions=el('alert-filter').value==='decisions';
    const rows=decisions ? allRows.flatMap(r=>(r.judgment?.decisions || []).filter(d=>d.status!=='sent').map(d=>({...d,id:r.id,title:r.title,url:r.url,price:r.total,checked_at:r.checked_at}))) : data?.activity || [];
    el('alert-list').innerHTML=rows.length ? rows.map(r=>`<article class="watch-card"><span class="badge ${r.status==='failed' ? 'review' : ''}">${esc(r.label)}</span><h2>${esc(r.title)}</h2><p>${esc(r.channel)} · ${esc(date(r.at))} · ${dollars(r.price)} ${decisions ? 'at last assessment' : 'at event time'}</p><div class="card-actions"><button data-open-product="${esc(r.id)}">Open current card</button><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">View source ↗</a></div></article>`).join('') : `<p class="empty">${decisions ? 'No decisions in the loaded results yet. All deals includes the full monitor snapshot.' : 'No retained sends or failures yet. Activity appears after the upgraded monitor runs; existing delivery receipts are preserved.'}</p>`;
  }
  function render(){renderWatches();if(pane==='alerts')renderAlerts();if(allSnapshot){el('source-health').innerHTML=allSnapshot.sources.map(s=>`<div class="source-card"><strong>${esc(s.label)}</strong><span class="badge ${s.ready ? 'current' : 'review'}">${esc(s.status)}</span><p class="small muted">${s.ready}/${s.jobs} checks current · ${s.count} products/leads<br>${esc(date(s.checked_at))}</p></div>`).join('');}}

  function recommendationBadge(row){
    const r=B.recommendation(row),symbol={deal:'✓',skip:'×',watch:'!',unassessed:'?'}[r.tone];
    return `<span class="recommendation verdict-${r.tone}"><span aria-hidden="true">${symbol}</span> ${esc(r.label)}</span>`;
  }
  function judgmentCard(row){
    const j=row.judgment,r=B.recommendation(row),note=r.note ? `<p class="small verdict-note">${esc(r.note)}</p>` : '';
    if(!j)return note;
    // Preserve notification status, but do not display a GPU-only baseline as
    // evidence about a complete PC, including in the expandable explanation.
    if(row.is_system && !row.prebuilt_value)return `${note}<p class="small muted">${j.eligible ? 'Meets deal notification rules' : 'Does not meet deal notification rules'}</p>`;
    const prebuilt=Boolean(row.prebuilt_value), current=B.fresh(row) && row.available && row.stock==='in_stock' && !B.verification(row).length;
    const budget=prebuilt ? (j.target==null ? 'No configured budget target' : !current ? 'Budget check needs current quote' : row.total<=j.target ? 'Within configured budget' : 'Above configured budget') : '';
    return `<div class="deal-judgment">${note}${budget ? `<p class="small">${esc(budget)}</p>` : ''}<p class="small muted">${j.eligible ? 'Meets deal notification rules' : 'Does not meet deal notification rules'}${j.target_hit && !prebuilt ? ' · Target price met' : ''}</p>${prebuilt ? '' : `<p class="small">${esc(j.headline || j.reason)}</p>`}<details data-judgment="${esc(row.id)}" ${openJudgments.has(row.id) ? 'open' : ''}><summary>${prebuilt ? 'Notification rules & budget target' : 'Why this verdict?'}</summary><p>${esc(j.reason)}</p>${j.target!=null ? `<p>Engine target: ${dollars(j.target)}</p>` : ''}${[...j.facts,...j.warnings].map(v=>`<p class="small muted">${esc(v)}</p>`).join('')}${j.decisions.map(d=>`<p class="small">${esc(d.channel)}: ${esc(d.label)} · ${esc(date(d.at))}</p>`).join('')}</details></div>`;
  }
  window.TechScoutWorkspace={judgmentCard,recommendationBadge,focusId:null,update(value){openJudgments=new Set([...document.querySelectorAll('[data-judgment][open]')].map(e=>e.dataset.judgment));context=value;render();if(this.focusId){const id=this.focusId;this.focusId=null;setTimeout(()=>{const card=document.querySelector(`[data-product-id="${CSS.escape(id)}"]`);if(card){card.scrollIntoView({block:'center'});card.classList.add('focused-deal');}else notice('This product is no longer in current results. The alert retains its original source link.');},0);}}};
  el('workspace-nav').addEventListener('click',event=>{const b=event.target.closest('[data-pane]');if(b)show(b.dataset.pane);});
  el('watch-search').addEventListener('click',()=>newWatch());
  el('watch-cancel').addEventListener('click',()=>el('watch-dialog').close());
  el('watch-form').addEventListener('submit',async event=>{event.preventDefault();if(!draft || !el('watch-form').reportValidity())return;draft.name=el('watch-name').value.trim();draft.budget=el('watch-budget').value==='' ? null : el('watch-budget').valueAsNumber;draft.enabled=el('watch-enabled').checked;if(!draft.product_id){draft.filters={};for(const field of el('watch-criteria').querySelectorAll('select')){const key=field.dataset.watchField;if(['category','source'].includes(key))draft[key]=field.value;else if(field.value)draft.filters[key]=field.value;}draft.reuse=el('watch-reuse').checked;}const settings=structuredClone(data.settings);const index=settings.watches.findIndex(w=>w.id===draft.id);if(index<0)settings.watches.push(draft);else settings.watches[index]=draft;if(await save(settings)){el('watch-dialog').close();show('watching');}});
  el('notification-mode').addEventListener('change',()=>save({...data.settings,mode:el('notification-mode').value}));
  el('alert-filter').addEventListener('change',renderAlerts);
  document.querySelector('main').addEventListener('click',async event=>{
    const product=event.target.closest('[data-watch-product]');if(product){newWatch(context.rows.find(r=>r.id===product.dataset.watchProduct));return;}
    const current=event.target.closest('[data-open-product]');if(current){show('deals');window.dispatchEvent(new CustomEvent('techscout:open-product',{detail:current.dataset.openProduct}));return;}
    const button=event.target.closest('[data-edit-watch],[data-toggle-watch],[data-delete-watch],[data-browse-watch]');if(!button || !data)return;
    const id=Object.values(button.dataset)[0],watch=data.settings.watches.find(w=>w.id===id);if(!watch)return;
    if(button.dataset.editWatch){openWatch(watch);return;}
    if(button.dataset.browseWatch){show('deals');window.dispatchEvent(new CustomEvent('techscout:browse-watch',{detail:watch}));return;}
    const settings=structuredClone(data.settings);
    if(button.dataset.deleteWatch)settings.watches=settings.watches.filter(w=>w.id!==id);else settings.watches.find(w=>w.id===id).enabled=!watch.enabled;
    await save(settings);
  });
  refresh();setInterval(refresh,15000);
})();
