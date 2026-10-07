(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dollars = value => value == null ? 'Unknown' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value);
  const token = document.querySelector('meta[name="techscout-token"]').content;
  const categoryNames = {'desktop-memory':'Desktops & memory',tablets:'Tablets',computers:'Computers',supplies:'Tech supplies',memory:'Memory',amazon:'Amazon deals',monitor:'All deals'};
  const facetNames = {gpu:'All GPUs',ram:'All RAM capacities',cpu:'All CPUs',storage:'All storage',condition:'All conditions'};
  let filters = {};
  let category = 'desktop-memory', view = 'list', state = null, pending = false, poll = null, source = 'all';
  let picks = new Set();
  let expandedReports = new Set();
  try { const saved = JSON.parse(localStorage.getItem('techscout-shortlist') || '[]'); if (Array.isArray(saved)) picks = new Set(saved.filter(s => typeof s === 'string' && /^(?:\d{1,20}|[a-z-]+:[a-f0-9]{24})$/.test(s)).slice(0,3)); } catch (_) {}
  function notice(message) { el('notice').textContent = message; el('notice').hidden = !message; }
  function remember() { try { localStorage.setItem('techscout-shortlist',JSON.stringify([...picks])); } catch (_) {} }
  function allRows() { return state ? [...state.snapshot.groups.flatMap(g => g.rows),...state.snapshot.held,...(state.snapshot.leads || [])] : []; }
  function rowFresh(row) { return Number.isFinite(row.expires_at) && Date.now()/1000 <= row.expires_at; }
  function date(value) { return value ? new Date(value).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}) : 'No successful check'; }
  function hasSource(row, value) { return row.source === value || (row.sources || []).includes(value); }
  function facetValue(row, key) { return row.facets?.[key] || 'Not established'; }
  function matches(row, except = '') {
    return (except === 'source' || source === 'all' || hasSource(row,source)) &&
      Object.keys(facetNames).every(key=>key === except || !filters[key] || facetValue(row,key) === filters[key]);
  }
  function hasFilters() { return source !== 'all' || Object.values(filters).some(Boolean); }
  function resetFilters() { filters={};source='all';render(); }
  function renderFilters() {
    const rows = allRows();
    for (const [key, label] of Object.entries(facetNames)) {
      // Count with the other filters applied; keep zero-result selections across
      // polling so missing offers never silently broaden the user's request.
      const candidates = rows.filter(row=>matches(row,key));
      const values = [...new Set(rows.map(row=>facetValue(row,key)).concat(filters[key] || []))];
      values.sort((a,b)=>(a==='Not established')-(b==='Not established') || a.localeCompare(b,undefined,{numeric:true}));
      el(`${key}-select`).innerHTML = `<option value="">${label} · ${candidates.length}</option>` + values.map(value=>{
        const count = candidates.filter(row=>facetValue(row,key)===value).length;
        return `<option value="${escape(value)}" ${filters[key]===value ? 'selected' : ''} ${!count && filters[key]!==value ? 'disabled' : ''}>${escape(value)} · ${count}</option>`;
      }).join('');
    }
    const candidates = rows.filter(row=>matches(row,'source'));
    const options = state.snapshot.sources.filter(s=>rows.some(r=>hasSource(r,s.source)) || s.source===source);
    if (source !== 'all' && !options.some(s=>s.source===source)) options.push({source,label:source});
    el('source-select').innerHTML = `<option value="all">All sources · ${candidates.length}</option>` + options.map(s=>{
      const count = candidates.filter(row=>hasSource(row,s.source)).length;
      return `<option value="${escape(s.source)}" ${source===s.source ? 'selected' : ''} ${!count && source!==s.source ? 'disabled' : ''}>${escape(s.label)} · ${count}</option>`;
    }).join('');
    el('reset-filters').disabled = !hasFilters();
    const count = rows.filter(row=>matches(row)).length;
    const selected = Object.values(filters).filter(Boolean);
    if (source !== 'all') selected.push(options.find(s=>s.source===source).label);
    el('filter-summary').textContent = view === 'compare' ? 'Filters apply to the shortlist and reported deals. Saved comparisons stay visible.' : `${count} of ${rows.length} products match · ${selected.length ? selected.join(' · ') : 'All configurations shown'}. Counts include held offers and reported deals.`;
  }
  function price(row) {
    if (row.reported_prices?.length > 1) return `${dollars(row.reported_prices[0])}–${dollars(row.reported_prices.at(-1))}<small>reported prices differ · see source reports</small>`;
    return row.total != null ? `${dollars(row.total)}<small>${escape(row.cost_note || 'price + shipping · before tax')}</small>` : `${dollars(row.price)}<small>${row.lead ? 'publisher-quoted price · unverified' : 'item price · shipping unknown'}</small>`;
  }
  function selectButton(row) { return `<button type="button" data-pick="${escape(row.id)}" aria-pressed="${picks.has(row.id)}">${picks.has(row.id) ? 'Saved ✓' : 'Save & compare'}</button>`; }
  function link(row) { return `<a href="${escape(row.url)}" target="_blank" rel="noopener noreferrer">View listing ↗</a>`; }
  function reports(row) {
    if (!row.reports?.length) return '';
    return `<details class="source-reports" data-report-id="${escape(row.id)}" ${expandedReports.has(row.id) ? 'open' : ''}><summary>${row.reports.length} source report${row.reports.length === 1 ? '' : 's'}${row.sources.length > 1 ? ` · ${row.sources.length} publishers` : ''}</summary><p class="small muted">${escape(row.match_basis)}. Each publisher's price and requirements remain separate.</p>${row.reports.map(r=>`<div class="source-report"><a href="${escape(r.url)}" target="_blank" rel="noopener noreferrer">${escape(r.retailer)} ↗</a><strong>${dollars(r.price)} quoted</strong><p class="small muted">${r.published_at ? `Posted ${escape(date(r.published_at))} · ` : ''}Checked ${escape(date(r.checked_at))}${rowFresh(r) ? '' : ' · Needs a new check'}</p><p>${escape(r.title)}</p>${(r.terms || []).map(t=>`<span class="badge">${escape(t)}</span>`).join('')}${r.description ? `<p class="publisher-text">${escape(r.description)}</p>` : ''}</div>`).join('')}</details>`;
  }
  function rowCard(row) {
    return `<article class="deal"><div class="rank">${String(row.rank).padStart(2,'0')}</div><div><h2 class="deal-title">${escape(row.title)}</h2><p class="small muted">${escape(row.retailer)} · sold by ${escape(row.seller)} · ${escape(row.condition)}<br>Checked ${escape(date(row.checked_at))}</p><div class="fit">${escape(row.fit_summary || 'Review the exact product specifications before choosing.')}</div><div class="actions">${selectButton(row)}${link(row)}</div></div><div class="price">${price(row)}</div><details class="why"><summary>Why this rank?</summary><p>${escape(row.why)}</p><p class="small muted">Item ${dollars(row.price)} + shipping ${dollars(row.shipping)}. CPU, storage, warranty and seller can differ within this group.</p>${row.warnings.map(w=>`<p class="small muted">${escape(w)}</p>`).join('')}</details></article>`;
  }
  function render() {
    if (!state) return;
    expandedReports = new Set([...document.querySelectorAll('.source-reports[open]')].map(d=>d.dataset.reportId));
    const data = state.snapshot;
    // Preserve saved choices when their individual reports become one shared card.
    const remapped = new Set([...picks].map(id=>allRows().find(r=>(r.aliases || []).includes(id))?.id || id));
    if ([...picks].some(id=>!remapped.has(id))) { picks=remapped;remember(); }
    renderFilters();
    const recent = data.groups.flatMap(g=>g.rows).filter(r=>rowFresh(r)&&matches(r)).length;
    el('status').innerHTML = `<span class="badge ${recent ? '' : 'warning'}">${recent} ranked offers</span><span>${allRows().filter(matches).length} products & leads in this view</span>${data.zip_code ? `<span>· Walmart ZIP ${escape(data.zip_code)}</span>` : ''}`;
    if (category === 'amazon') el('status').innerHTML = `<span class="badge">${allRows().filter(matches).length} product cards</span><span>Published deal leads · prices unverified</span>`;
    const overlaps = (data.leads || []).filter(matches).reduce((n,r)=>n + Math.max(0,(r.reports?.length || 1)-1),0);
    if (overlaps) el('status').innerHTML += `<span class="badge">${overlaps} overlapping reports combined</span>`;
    if (state.running) el('status').innerHTML += `<span class="badge">Checking Walmart ${escape(categoryNames[state.running])}…</span>`;
    el('refresh').disabled = pending || Boolean(state.running);
    el('refresh').textContent = ['monitor','amazon'].includes(category) ? 'Reload results' : state.running ? 'Checking Walmart…' : 'Check Walmart now';
    el('source-health').innerHTML = data.sources.map(s=>`<div class="source-card"><strong>${escape(s.label)}</strong><span class="badge ${s.ready ? '' : 'warning'}">${s.ready ? `${s.ready}/${s.jobs} checks current` : s.jobs ? 'Waiting / unavailable' : 'Not enabled'}</span><div class="small muted">${escape(date(s.checked_at))} · ${s.count} products/leads${s.truncated ? ' · result cap reached' : ''}</div></div>`).join('') || '<p class="fit">Monitor export unavailable. Update the installed monitor to connect its results.</p>';
    const heading = category === 'amazon' ? 'Amazon deals, sources combined' : category === 'monitor' ? 'Deals across your sources' : category === 'desktop-memory' ? 'Desktops worth a closer look' : `${categoryNames[category]} worth a closer look`;
    el('heading').textContent = heading;
    el('purpose').textContent = category === 'amazon' ? 'Tech deals from Ben’s Bargains, DealNews and 9to5Toys · every source kept on the card' : category === 'desktop-memory' ? 'RTX 5080/5090 · reuse your 64GB kit · aim for 96–128GB' : category === 'monitor' ? 'Your existing hardware watchlist · current offers and discovery leads' : 'Current product research · compare the exact variant and seller';
    el('ranking-note').textContent = category === 'amazon' ? 'Matches use exact Amazon product IDs or exact product names and retailer. Different prices, dates and coupon requirements remain visible in source reports. Confirm the final offer at Amazon.' : category === 'desktop-memory' ? 'Within each GPU/RAM group: documented layout first, then known total. CPU and storage can differ.' : 'Ordered by known total within condition. This is price order, not a performance or value ranking across different models.';
    el('list-view').textContent = category === 'amazon' ? 'Reported deals' : 'Ranked shortlist';
    const groups = data.groups.map(g=>({...g,rows:g.rows.filter(r=>rowFresh(r)&&matches(r))})).filter(g=>g.rows.length);
    const noMatches = !allRows().some(row=>matches(row));
    const empty = noMatches && hasFilters() ? 'No products match these filters. Clear a filter to broaden the results.' : 'No current offers meet this view’s ranking requirements. See held offers, reported deals, and source coverage below.';
    el('ranked').innerHTML = groups.length ? groups.map(g=>`<section class="rank-group" aria-label="${escape(g.name)}"><h2>${escape(g.name)} · ${g.rows.length} offer${g.rows.length===1 ? '' : 's'}</h2>${g.rows.map(rowCard).join('')}</section>`).join('') : `<div class="empty">${empty}${hasFilters() ? ' <button data-reset-filters>Clear filters</button>' : ''}</div>`;
    const held = [...data.held,...data.groups.flatMap(g=>g.rows).filter(r=>!rowFresh(r))].filter(matches);
    el('held-count').textContent = `· ${held.length}`;
    el('held').innerHTML = held.map(row=>`<article class="held-row"><div><h3 class="deal-title">${escape(row.title)}</h3><p class="small muted">${escape(row.retailer)} · ${escape(row.seller)} · ${escape(row.condition)}<br>Checked ${escape(date(row.checked_at))}</p><p class="fit">${escape(row.reasons.length ? row.reasons.join(' · ') : 'Availability needs a new check')}</p><div class="actions">${selectButton(row)}${link(row)}</div></div><div class="price">${price(row)}</div></article>`).join('') || '<p class="muted">No held offers.</p>';
    el('held-section').hidden = !held.length;
    const selected = allRows().filter(row => picks.has(row.id));
    el('compare-count').textContent = picks.size;
    el('comparison').innerHTML = selected.length ? selected.map(row => {
      const specs = [['Retailer / source',row.retailer],['Last checked',date(row.checked_at)],['CPU',row.cpu],['GPU',row.gpu ? `RTX ${row.gpu}` : 'See exact listing'],['Factory RAM',row.ram ? `${row.ram}GB` : 'Not established'],['Storage',row.storage],['Potential with your kit',row.potential ? `${row.potential}GB if compatible` : 'Not established'],['Seller',row.seller],['Condition',row.condition]];
      return `<article class="compare-card"><h2 class="deal-title">${escape(row.title)}</h2><div class="price">${price(row)}</div><p class="badge ${row.reasons.length || !rowFresh(row) ? 'warning' : ''}">${escape(rowFresh(row) && !row.reasons.length ? 'Recently available' : row.reasons.join(' · ') || 'Needs a new check')}</p>${specs.map(([label,value])=>`<div class="spec"><span>${escape(label)}</span>${escape(value)}</div>`).join('')}<p class="fit">${escape(row.fit_summary)}</p><div class="actions">${selectButton(row)}${link(row)}</div>${reports(row)}</article>`;
    }).join('') : '<div class="empty">Choose up to three products with “Save & compare.” Saved choices persist in this browser.</div>';
    if (picks.size > selected.length) el('comparison').innerHTML += '<div class="empty">Some saved products are outside this category or no longer in the latest results. <button id="clear-picks">Clear saved choices</button></div>';
    el('ranked').hidden = view !== 'list' || category === 'amazon';
    el('comparison').hidden = view !== 'compare';
    el('list-view').setAttribute('aria-pressed',String(view === 'list'));
    el('compare-view').setAttribute('aria-pressed',String(view === 'compare'));
    const leads = (data.leads || []).filter(matches);
    el('leads-count').textContent = `· ${leads.length}`;
    el('leads-section').hidden = (!leads.length && category !== 'amazon') || category === 'amazon' && view !== 'list';
    el('leads').innerHTML = leads.map(row=>`<article class="held-row"><div class="lead-content"><h3>${escape(row.product_name || row.title)}</h3><p class="small muted">${escape(row.retailer)} · Found via ${escape([...new Set((row.reports || []).map(r=>r.retailer))].join(', ') || row.retailer)}</p><p class="fit">${escape(row.reasons.join(' · '))}${!rowFresh(row) ? ' · Needs a new source check' : ''}</p><div class="actions">${selectButton(row)}${link(row)}</div>${reports(row)}</div><div class="price">${price(row)}</div></article>`).join('');
    if (!leads.length) el('leads').innerHTML = `<div class="empty">${hasFilters() ? 'No reported deals match these filters. <button data-reset-filters>Clear filters</button>' : 'No reported deals in this category yet.'}</div>`;
    const coverage = data.coverage.map(c=>`<div class="coverage-item">Walmart ${escape(c.query)}: ${escape(c.returned)} of ${escape(c.total ?? 'unknown')} results inspected</div>`).join('');
    el('coverage').innerHTML = `<p class="small muted">Local results update here every 15 seconds. While this dashboard server runs, public deal feeds are checked every 15 minutes, with a bounded metadata pass on linked publisher pages. No Amazon product pages are polled and no alerts are sent. “Check Walmart now” runs only Walmart’s preset searches (up to 10 results each).</p><p class="small muted">Amazon coverage uses recent tech posts from Ben’s Bargains, DealNews and 9to5Toys. Exact product matches share a card; uncertain matches and distinct variants stay separate. Overlapping reports are discovery evidence, not independent confirmation of stock or a market average. Original publisher links and quoted descriptions are retained.</p><p class="small muted">Monitor scope: watched hardware, Newegg desktop discovery, Apple Mac mini/Studio/Pro, and the latest Slickdeals Computers page. Missing search results do not prove a product is sold out.</p>${coverage}${data.problems.map(p=>`<p class="fit">${escape(p)}</p>`).join('')}`;

  }
  async function load() {
    const requested = category;
    try {
      const response = await fetch(`/api/state?category=${encodeURIComponent(requested)}`, {cache:'no-store'});
      if (!response.ok) throw new Error('Could not read the saved research.');
      const result = await response.json();
      if (requested !== category) return;
      state = result; render();
      if (['failed','checking'].includes(state.last_check.status) && !state.running ) notice('The last Walmart check failed or was interrupted. Its previous results are held; monitor sources remain independent.');
      else if (state.last_check.status === 'partial' ) notice('The last Walmart check was partial. See source coverage for gaps.');
      else notice('');
      clearTimeout(poll);
      poll = setTimeout(load,state.running ? 1000 : 15000);
    } catch (_) { notice('TechScout could not reach the local server. Start it again and reload this page.'); }
  }
  el('refresh').addEventListener('click',async () => {
    if (['monitor','amazon'].includes(category)) { await load(); return; }
    pending = true; notice(''); render();
    try {
      const response = await fetch('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json','X-TechScout-Token':token},body:JSON.stringify({category})});
      const result = await response.json();
      if (!response.ok) {
        await load();
        notice(response.status === 403 ? 'The local page authorization changed. Reload this page and try again.' : result.error || 'The check could not start.');
        return;
      }
      await load();
    } catch (_) { notice('The check could not start. Reload the local page and try again.'); }
    finally { pending = false; render(); }
  });
  function chooseCategory(value) {
    if (!Object.hasOwn(categoryNames,value)) return;
    category = value; filters = {}; source = 'all'; state = null; notice('');
    clearTimeout(poll);
    el('heading').textContent = categoryNames[category];
    el('purpose').textContent = 'Loading saved research…';
    el('status').textContent = 'Loading…';
    for (const [key,label] of Object.entries(facetNames)) el(`${key}-select`).innerHTML = `<option value="">${label}</option>`;
    el('source-select').innerHTML = '<option value="all">All sources</option>';
    el('filter-summary').textContent = 'Loading filters…';
    el('reset-filters').disabled = true;
    el('ranked').replaceChildren();
    el('comparison').replaceChildren();
    el('coverage').replaceChildren();
    el('ranking-note').textContent = '';
    el('held-section').hidden = true;
    el('leads-section').hidden = true;
    el('leads-section').open = category === 'amazon';
    el('source-health').replaceChildren();
    el('refresh').disabled = true;
    el('category-select').value = category;
    document.querySelectorAll('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category === category)));
    load();
  }
  el('categories').addEventListener('click',event => {
    const button = event.target.closest('[data-category]');
    if (button) chooseCategory(button.dataset.category);
  });
  el('category-select').addEventListener('change',event=>chooseCategory(event.target.value));
  el('source-select').addEventListener('change',event=>{source=event.target.value;render();});
  for (const key of Object.keys(facetNames)) el(`${key}-select`).addEventListener('change',event=>{filters[key]=event.target.value;render();});
  el('reset-filters').addEventListener('click',resetFilters);
  el('list-view').addEventListener('click',()=>{view='list';render();});
  el('compare-view').addEventListener('click',()=>{view='compare';render();});
  document.querySelector('main').addEventListener('click',event => {
    const button = event.target.closest('[data-pick]');
    if (event.target.closest('[data-reset-filters]')) { resetFilters();return; }
    if (event.target.id === 'clear-picks') { picks.clear();remember();render();return; }
    if (!button) return;
    const id = button.dataset.pick;
    if (picks.has(id)) picks.delete(id);
    else if (picks.size < 3) picks.add(id);
    else { notice('You have three finalists saved. Remove one before adding another.'); return; }
    remember();notice('');render();
  });
  // Reclassify expiring data locally; this timer never starts API research.
  setInterval(()=>{if (state && state.snapshot.groups.some(g=>g.rows.some(r=>!rowFresh(r)))) render();},1000);
  load();
})();
