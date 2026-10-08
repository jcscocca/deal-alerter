(() => {
  'use strict';
  const B=window.TechScoutBrowsing, el=id=>document.getElementById(id);
  const escape=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dollars=value=>value==null ? 'Unknown' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value);
  const date=value=>value ? new Date(value).toLocaleString([],{year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}) : 'No successful check';
  const rowFresh=B.fresh, token=document.querySelector('meta[name="techscout-token"]').content;
  const categoryNames={'desktop-memory':'Desktops',tablets:'Tablets',computers:'Computers',supplies:'Tech supplies',memory:'Memory',amazon:'Amazon deals',monitor:'All deals'};
  const allLabels={kind:'All product types',gpu:'All GPUs',ram:'Any included RAM',cpu:'All CPUs',storage:'All storage',condition:'All conditions'};
  let category='monitor',view='list',state=null,related=[],pending=false,poll=null,version=0;
  let savedViews={},prefs=B.defaults(),picks=new Set(),expanded=new Set(),expandedReports=new Set(),limits={current:12,other:12,similar:6};
  try {
    const saved=JSON.parse(localStorage.getItem('techscout-browsing') || '{}');
    if(Object.hasOwn(categoryNames,saved.category))category=saved.category;
    for(const key of Object.keys(categoryNames))if(saved.views?.[key])savedViews[key]=B.restore(saved.views[key]);
    const ids=JSON.parse(localStorage.getItem('techscout-shortlist') || '[]');
    if(Array.isArray(ids))picks=new Set(ids.filter(id=>typeof id==='string' && /^(?:\d{1,20}|[a-z-]+:[a-f0-9]{24})$/.test(id)).slice(0,3));
  } catch(_) {}
  function defaults(){return {...B.defaults(),reuse:category==='desktop-memory'};}
  function saveView(){savedViews[category]=prefs;try{localStorage.setItem('techscout-browsing',JSON.stringify({category,views:savedViews}));}catch(_) {}}
  function remember(){try{localStorage.setItem('techscout-shortlist',JSON.stringify([...picks]));}catch(_) {}}
  function notice(message){el('notice').textContent=message;el('notice').hidden=!message;}
  function rows(){return state ? B.rowsOf(state.snapshot) : [];}
  function candidates(){return B.unique([...rows(),...related]);}
  function activeFilters(){return prefs.quality!=='all' || prefs.source!=='all' || prefs.budget!=null || Object.values(prefs.filters).some(Boolean);}
  function changed(){limits={current:12,other:12,similar:6};saveView();render();}
  function resetFilters(){prefs.filters={};prefs.source='all';prefs.budget=null;prefs.quality='all';changed();}
  function renderFilters(){
    const data=rows();
    for(const key of B.keys){
      const pool=data.filter(row=>B.matches(row,prefs,key));
      const values=[...new Set(data.map(row=>B.value(row,key)).concat(prefs.filters[key] || []))];
      values.sort((a,b)=>(a===B.unknown)-(b===B.unknown) || a.localeCompare(b,undefined,{numeric:true}));
      el(`${key}-filter`).hidden=!prefs.filters[key] && !values.some(v=>v!==B.unknown && v!=='Other tech');
      el(`${key}-select`).innerHTML=`<option value="">${allLabels[key]} · ${pool.length}</option>`+values.map(value=>{
        const count=pool.filter(row=>B.value(row,key)===value).length;
        return `<option value="${escape(value)}" ${prefs.filters[key]===value ? 'selected' : ''}>${escape(value)} · ${count}</option>`;
      }).join('');
    }
    const pool=data.filter(row=>B.matches(row,prefs,'source'));
    const sources=state.snapshot.sources.filter(s=>data.some(row=>B.hasSource(row,s.source)) || s.source===prefs.source);
    if(prefs.source!=='all' && !sources.some(s=>s.source===prefs.source))sources.push({source:prefs.source,label:prefs.source});
    el('source-select').innerHTML=`<option value="all">All sources · ${pool.length}</option>`+sources.map(s=>{
      const count=pool.filter(row=>B.hasSource(row,s.source)).length;
      return `<option value="${escape(s.source)}" ${prefs.source===s.source ? 'selected' : ''}>${escape(s.label)} · ${count}</option>`;
    }).join('');
    if(document.activeElement!==el('budget'))el('budget').value=prefs.budget ?? '';
    el('quality-select').value=prefs.quality;el('sort-select').value=prefs.sort;el('reuse').checked=prefs.reuse;
    el('sort-select').querySelector('[value="recommended"]').textContent=prefs.reuse ? 'RAM evidence, then price' : 'Recommended · known total';
    el('reuse-option').hidden=!['desktop-memory','computers','monitor'].includes(category);
    el('reset-filters').disabled=!activeFilters();
    const chips=Object.entries(prefs.filters).filter(([,v])=>v).map(([key,value])=>[key,`${B.labels[key]}: ${value}`]);
    if(prefs.source!=='all')chips.push(['source',sources.find(s=>s.source===prefs.source).label]);
    if(prefs.quality!=='all')chips.push(['quality',el('quality-select').selectedOptions[0].textContent]);
    if(prefs.budget!=null)chips.push(['budget',`Up to ${dollars(prefs.budget)}`]);
    el('filter-chips').innerHTML=chips.length ? chips.map(([key,label])=>`<button class="chip" data-remove="${key}" aria-label="Remove ${escape(label)} filter">${escape(label)} <span aria-hidden="true">×</span></button>`).join('') : '<span class="small muted">All configurations</span>';
    el('filter-summary').textContent=`${data.filter(row=>B.matches(row,prefs)).length} of ${data.length} products match. Included RAM is what comes with the product; your 64GB kit is separate. Budget uses the known total, or item price / highest publisher quote when the total is unknown. Shipping may add to the cost.`;
  }
  function price(row) {
    const context=B.priceContext(row);
    const checked=`<small class="checked-time">${row.lead ? 'Source checked' : 'Price &amp; stock checked'} ${escape(date(row.checked_at))}${row.source==='walmart' ? '<br>Walmart checks run on demand' : ''}</small>`;
    const note=context ? `<small class="price-context">${escape(context)}</small>` : '';
    if (row.reported_prices?.length > 1) return `${dollars(row.reported_prices[0])}–${dollars(row.reported_prices.at(-1))}<small>reported prices differ · see source reports</small>${checked}`;
    const amount=row.total != null ? `${dollars(row.total)}<small>${escape(row.cost_note || 'price + shipping · before tax')}</small>` : `${dollars(row.price)}<small>${row.lead ? 'publisher-quoted price · unverified' : 'item price · shipping unknown'}</small>`;
    return amount+note+checked;
  }
  function selectButton(row) { return `<button type="button" data-pick="${escape(row.id)}" aria-pressed="${picks.has(row.id)}">${picks.has(row.id) ? 'Saved ✓' : 'Save & compare'}</button>`; }
  function link(row) { return `<a href="${escape(row.url)}" target="_blank" rel="noopener noreferrer">View listing ↗</a>`; }
  function reports(row) {
    if (!row.reports?.length) return '';
    return `<details class="source-reports" data-report-id="${escape(row.id)}" ${expandedReports.has(row.id) ? 'open' : ''}><summary>${row.reports.length} source report${row.reports.length === 1 ? '' : 's'}${row.sources.length > 1 ? ` · ${row.sources.length} publishers` : ''}</summary><p class="small muted">${escape(row.match_basis)}. Each publisher's price and requirements remain separate.</p>${row.reports.map(r=>`<div class="source-report"><a href="${escape(r.url)}" target="_blank" rel="noopener noreferrer">${escape(r.retailer)} ↗</a><strong>${dollars(r.price)} quoted</strong><p class="small muted">${r.published_at ? `Posted ${escape(date(r.published_at))} · ` : ''}Checked ${escape(date(r.checked_at))}${rowFresh(r) ? '' : ' · Needs a new check'}</p><p>${escape(r.title)}</p>${(r.terms || []).map(t=>`<span class="badge">${escape(t)}</span>`).join('')}${r.description ? `<p class="publisher-text">${escape(r.description)}</p>` : ''}</div>`).join('')}</details>`;
  }

  function specStrip(row){return ['gpu','cpu','ram','storage'].filter(key=>B.value(row,key)!==B.unknown).map(key=>`<span><small>${B.labels[key]}</small>${escape(B.value(row,key))}</span>`).join('');}
  function rowCard(row){
    const status=B.status(row,prefs),title=row.product_name || row.title;
    const short=title.length>110 ? title.slice(0,107).replace(/\s+\S*$/,'')+'…' : title;
    const preferences=B.preferenceReasons(row),checks=B.verification(row),reuse=prefs.reuse ? B.ramReuse(row) : null;
    const concerns=row.lead ? row.reasons : [...(prefs.reuse ? preferences : []),...checks];
    return `<article class="deal ${status.tone}" data-product-id="${escape(row.id)}"><div class="deal-main"><div class="card-meta"><span class="badge ${status.tone}">${status.label}</span><span>${escape(row.retailer)} · ${escape(row.condition)}</span></div><h3 class="deal-title">${escape(short)}</h3><div class="spec-strip">${specStrip(row)}</div>${row.differences?.length ? `<p class="differences">${row.differences.map(escape).join(' · ')}</p>` : ''}${reuse ? `<div class="ram-reuse"><p class="small"><strong>${escape(reuse.total)}</strong></p><p class="small muted">${escape(reuse.check)}</p></div>` : ''}${window.TechScoutWorkspace.judgmentCard(row)}${concerns.length ? `<p class="concern">${escape(concerns[0])}${concerns.length>1 ? ` (+${concerns.length-1} more in details)` : ''}</p>` : ''}<p class="small muted">Sold by ${escape(row.seller)}</p></div><div class="price">${price(row)}</div><div class="card-actions">${selectButton(row)}<button data-watch-product="${escape(row.id)}">Watch product</button><a href="${escape(row.url)}" target="_blank" rel="noopener noreferrer">${row.lead ? 'Read source' : 'View listing'} ↗</a></div><details class="listing-details" data-detail="${escape(row.id)}" ${expanded.has(row.id) ? 'open' : ''}><summary>Listing details${row.why ? ' & ranking' : ''}</summary><p>${escape(row.title)}</p>${row.fit_summary ? `<p>RAM reuse: ${escape(row.fit_summary)}</p>` : ''}${[...new Set([...checks,...preferences,...(row.warnings || [])])].map(w=>`<p class="small muted">${escape(w)}</p>`).join('')}${row.why ? `<p class="small muted">Original group rank ${row.rank}: ${escape(row.why)}</p>` : ''}<p class="small muted">Item ${dollars(row.price)} · shipping ${dollars(row.shipping)} · tax excluded</p></details>${reports(row)}</article>`;
  }
  function sectionCards(id,list){
    const limit=limits[id];el(`${id}-cards`).innerHTML=list.slice(0,limit).map(rowCard).join('');
    el(`${id}-more`).hidden=list.length<=limit;el(`${id}-more`).textContent=`Show ${Math.min(12,list.length-limit)} more · ${limit} of ${list.length} shown`;el(`${id}-count`).textContent=list.length;
  }
  function renderCompare(){
    const selected=candidates().filter(row=>picks.has(row.id));el('compare-count').textContent=picks.size;
    el('comparison').innerHTML=selected.length ? selected.map(row=>`<article class="compare-card"><h2>${escape(row.product_name || row.title)}</h2><div class="price">${price(row)}</div><p class="badge ${B.status(row,prefs).tone}">${B.status(row,prefs).label}</p>${[['Source',row.retailer],...B.keys.filter(k=>k!=='kind').map(k=>[B.labels[k],B.value(row,k)]),['Potential with your kit',row.potential ? `${row.potential}GB if compatible` : B.unknown]].map(([label,value])=>`<div class="spec"><span>${label}</span>${escape(value)}</div>`).join('')}<p class="small muted">${escape(row.fit_summary)}</p><div class="card-actions">${selectButton(row)}${link(row)}</div>${reports(row)}</article>`).join('') : '<p class="empty">Save up to three products to compare their specifications here. Filters will not hide your saved comparisons.</p>';
    if(picks.size>selected.length)el('comparison').innerHTML+='<p class="empty">Some saved products are outside the loaded categories or no longer appear in the latest results. <button data-clear-picks>Clear saved choices</button></p>';
  }
  function render(){
    if(!state)return;
    expanded=new Set([...document.querySelectorAll('[data-detail][open]')].map(node=>node.dataset.detail));
    expandedReports=new Set([...document.querySelectorAll('.source-reports[open]')].map(node=>node.dataset.reportId));
    const remapped=new Set([...picks].map(id=>candidates().find(r=>(r.aliases || []).includes(id))?.id || id));
    if([...picks].some(id=>!remapped.has(id))){picks=remapped;remember();}
    const data=state.snapshot,results=B.partition(rows(),related,prefs,category);
    window.TechScoutWorkspace.update({category,prefs,rows:candidates(),snapshot:data});
    renderFilters();renderCompare();sectionCards('current',results.current);sectionCards('other',results.other);
    el('current-empty').hidden=Boolean(results.current.length);
    el('current-empty').textContent=results.other.length ? 'No current offers meet all preferences. Continue below for other matching products.' : 'No exact matches right now. Nearby alternatives appear below when available.';
    el('current-section').hidden=category==='amazon' && !results.current.length && Boolean(results.other.length);
    el('other-section').hidden=!results.other.length;el('other-heading').textContent=category==='amazon' ? 'Published deal reports' : 'Other matching products';
    const unavailable=results.other.filter(row=>!row.lead && row.stock==='out_of_stock').length;
    const outside=results.other.filter(row=>B.status(row,prefs).tone==='preference').length,publisher=results.other.filter(row=>row.lead).length;
    el('other-note').textContent=`${unavailable} out of stock at last check · ${outside} outside build preferences · ${results.other.length-outside-publisher-unavailable} need verification · ${publisher} publisher reports. These match your filters; check the status on each card.`;
    el('similar-section').hidden=!results.similar.length;el('similar-count').textContent=results.similarCount;
    el('similar-cards').hidden=!prefs.similar;el('similar-cards').innerHTML=prefs.similar ? results.similar.slice(0,limits.similar).map(rowCard).join('') : '';
    el('similar-more').hidden=!prefs.similar || results.similarCount<=limits.similar;
    el('similar-more').textContent=`Show ${Math.min(6,results.similarCount-limits.similar)} more alternatives`;
    el('toggle-similar').textContent=prefs.similar ? 'Hide alternatives' : 'Show alternatives';el('toggle-similar').setAttribute('aria-expanded',String(prefs.similar));
    el('similar-note').textContent=`${prefs.similar ? Math.min(limits.similar,results.similarCount) : 0} of ${results.similarCount} nearby options shown. Differences are labeled; your budget, source and product type stay in effect.`;
    el('status').innerHTML=`<a href="#current-section" ${category==='amazon' ? 'hidden' : ''}>${results.current.length} current offers</a><a href="#other-section" ${results.other.length ? '' : 'hidden'}>${results.other.length} other matches</a><a href="#similar-section" ${results.similar.length ? '' : 'hidden'}>${results.similarCount} alternatives</a>${data.zip_code ? `<span>Walmart ZIP ${escape(data.zip_code)}</span>` : ''}`;
    el('results').hidden=view!=='list';el('comparison').hidden=view!=='compare';el('compare-note').hidden=view!=='compare';
    el('list-view').setAttribute('aria-pressed',String(view==='list'));el('compare-view').setAttribute('aria-pressed',String(view==='compare'));
    el('refresh').disabled=pending || Boolean(state.running);el('refresh').textContent=['monitor','amazon'].includes(category) ? 'Reload saved results' : state.running ? 'Checking Walmart…' : 'Check Walmart now';
    el('heading').textContent=category==='amazon' ? 'Amazon deals, sources combined' : category==='monitor' ? 'Deals across your sources' : `${categoryNames[category]} worth a closer look`;
    el('purpose').textContent=category==='amazon' ? 'Published discoveries · original quotes and requirements stay on each card' : prefs.reuse ? 'Your build preference: reuse your 64GB kit · aim for 96–128GB' : 'Browse complete products · compare the exact variant, seller and condition';
    el('ranking-note').textContent=prefs.sort==='best' ? 'Eligible alerter verdicts first within each section, then known total. Unassessed research stays labeled.' : prefs.sort==='newest' ? 'Newest checks first within each section. A recent publisher check does not confirm retailer stock.' : prefs.sort==='recommended' && prefs.reuse ? 'Documented RAM layouts first, then known total within each section. Mixed-kit compatibility still needs verification.' : 'Lowest known totals first, then item or publisher quotes where totals are unknown. Different models can differ in performance and value.';
    el('coverage').innerHTML='<p>Saved results update every 15 seconds. Publisher feeds update every 15 minutes while the dashboard runs. The Walmart button checks only this category’s preset searches. Browsing, filtering and alternatives do not start retailer searches or send alerts.</p>'+data.coverage.map(c=>`<p>Walmart ${escape(c.query)}: ${escape(c.returned)} of ${escape(c.total ?? 'unknown')} results inspected</p>`).join('')+data.problems.map(p=>`<p>${escape(p)}</p>`).join('');
  }
  async function load(){
    const requested=category,requestVersion=++version;
    try {
      const read=async key=>{const response=await fetch(`/api/state?category=${encodeURIComponent(key)}`,{cache:'no-store'});if(!response.ok)throw new Error('Read failed');return response.json();};
      const [result,other]=await Promise.all([read(requested),['monitor','amazon'].includes(requested) ? null : read('monitor').catch(()=>null)]);
      if(requested!==category || requestVersion!==version)return;
      state=result;related=other ? B.rowsOf(other.snapshot) : [];render();
      if(['failed','checking'].includes(state.last_check.status) && !state.running)notice('The last Walmart check failed or was interrupted. Those results need verification; other sources remain independent.');
      else if(state.last_check.status==='partial')notice('The last Walmart check was partial. See source coverage for gaps.');else notice('');
      clearTimeout(poll);poll=setTimeout(load,state.running ? 1000 : 15000);
    } catch(_){if(requestVersion!==version)return;notice('TechScout could not reach the local server. Retrying saved results shortly.');clearTimeout(poll);poll=setTimeout(load,15000);}
  }
  function chooseCategory(value){
    if(!Object.hasOwn(categoryNames,value))return;
    category=value;prefs=savedViews[value] ? B.restore(savedViews[value]) : defaults();saveView();state=null;related=[];limits={current:12,other:12,similar:6};expanded.clear();expandedReports.clear();clearTimeout(poll);notice('');
    el('heading').textContent=categoryNames[value];el('purpose').textContent='Loading saved results…';el('status').textContent='Loading…';
    el('results').hidden=true;el('comparison').hidden=true;el('refresh').disabled=true;el('category-select').value=value;
    document.querySelectorAll('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===value)));load();
  }
  el('refresh').addEventListener('click',async()=>{
    if(['monitor','amazon'].includes(category)){await load();return;}
    pending=true;notice('');render();
    try{const response=await fetch('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json','X-TechScout-Token':token},body:JSON.stringify({category})});const result=await response.json();await load();if(!response.ok)notice(result.error || 'The check could not start.');}
    catch(_){notice('The check could not start. Reload the local page and try again.');}finally{pending=false;render();}
  });
  el('categories').addEventListener('click',event=>{const b=event.target.closest('[data-category]');if(b)chooseCategory(b.dataset.category);});
  el('category-select').addEventListener('change',event=>chooseCategory(event.target.value));
  for(const key of B.keys)el(`${key}-select`).addEventListener('change',event=>{prefs.filters[key]=event.target.value;changed();});
  el('quality-select').addEventListener('change',event=>{prefs.quality=event.target.value;changed();});
  el('source-select').addEventListener('change',event=>{prefs.source=event.target.value;changed();});
  el('sort-select').addEventListener('change',event=>{prefs.sort=event.target.value;changed();});
  el('reuse').addEventListener('change',event=>{prefs.reuse=event.target.checked;changed();});
  el('budget').addEventListener('input',event=>{if(!event.target.validity.valid)return;prefs.budget=event.target.value==='' ? null : event.target.valueAsNumber;changed();});
  el('budget').addEventListener('change',event=>event.target.reportValidity());
  el('reset-filters').addEventListener('click',resetFilters);
  el('toggle-similar').addEventListener('click',()=>{prefs.similar=!prefs.similar;saveView();render();});
  el('list-view').addEventListener('click',()=>{view='list';render();});el('compare-view').addEventListener('click',()=>{view='compare';render();});
  el('status').addEventListener('click',event=>{if(event.target.closest('a')){view='list';render();}});
  el('edit-filters').addEventListener('click',()=>{el('filters').open=true;el('filters').scrollIntoView({block:'start'});});
  document.querySelector('main').addEventListener('click',event=>{
    const chip=event.target.closest('[data-remove]');if(chip){const key=chip.dataset.remove;if(key==='quality')prefs.quality='all';else if(key==='source')prefs.source='all';else if(key==='budget')prefs.budget=null;else delete prefs.filters[key];changed();return;}
    const more=event.target.closest('[data-more]');if(more){limits[more.dataset.more]+=more.dataset.more==='similar' ? 6 : 12;render();return;}
    if(event.target.closest('[data-clear-picks]')){picks.clear();remember();render();return;}
    const button=event.target.closest('[data-pick]');if(!button)return;const id=button.dataset.pick;
    if(picks.has(id))picks.delete(id);else if(picks.size<3)picks.add(id);else{notice('Three finalists are saved. Remove one before adding another.');return;}remember();notice('');render();
  });
  window.addEventListener('techscout:open-product',event=>{view='list';chooseCategory('monitor');prefs={...defaults(),reuse:false};limits={current:2500,other:2500,similar:6};window.TechScoutWorkspace.focusId=event.detail;});
  window.addEventListener('techscout:browse-watch',event=>{const w=event.detail;view='list';chooseCategory(w.category);prefs={...defaults(),filters:{...w.filters},source:w.source,budget:w.budget,reuse:w.reuse};if(w.product_id){limits={current:2500,other:2500,similar:6};window.TechScoutWorkspace.focusId=w.product_id;}});
  // Reclassify expired offers even if the local server stops responding.
  setInterval(()=>{if(state)render();},15000);
  if(window.matchMedia('(max-width:760px)').matches)el('filters').open=false;
  chooseCategory(category);
})();
