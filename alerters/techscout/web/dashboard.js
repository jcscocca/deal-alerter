(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dollars = value => value == null ? 'Unknown' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value);
  const token = document.querySelector('meta[name="techscout-token"]').content;
  const categoryNames = {'desktop-memory':'Desktops & memory',tablets:'Tablets',computers:'Computers',supplies:'Tech supplies',memory:'Memory'};
  let category = 'desktop-memory', group = '', view = 'list', state = null, pending = false, poll = null;
  let picks = new Set();
  try { const saved = JSON.parse(localStorage.getItem('techscout-shortlist') || '[]'); if (Array.isArray(saved)) picks = new Set(saved.filter(s => typeof s === 'string' && /^\d{1,20}$/.test(s)).slice(0,3)); } catch (_) {}
  function notice(message) { el('notice').textContent = message; el('notice').hidden = !message; }
  function remember() { try { localStorage.setItem('techscout-shortlist',JSON.stringify([...picks])); } catch (_) {} }
  function allRows() { return state ? [...state.snapshot.groups.flatMap(g => g.rows),...state.snapshot.held] : []; }
  function fresh() { return state && state.snapshot.fresh && Date.now()/1000 <= state.snapshot.expires_at; }
  function price(row) { return row.total != null ? `${dollars(row.total)}<small>price + shipping · before tax</small>` : `${dollars(row.price)}<small>item price · shipping unknown</small>`; }
  function selectButton(row) { return `<button type="button" data-pick="${escape(row.id)}" aria-pressed="${picks.has(row.id)}">${picks.has(row.id) ? 'Saved ✓' : 'Save & compare'}</button>`; }
  function link(row) { return `<a href="${escape(row.url)}" target="_blank" rel="noopener noreferrer">View listing ↗</a>`; }
  function rowCard(row) {
    return `<article class="deal"><div class="rank">${String(row.rank).padStart(2,'0')}</div><div><h2 class="deal-title">${escape(row.title)}</h2><p class="small muted">Walmart · sold by ${escape(row.seller)} · ${escape(row.condition)}</p><div class="fit">${escape(row.fit_summary || 'Review the exact product specifications before choosing.')}</div><div class="actions">${selectButton(row)}${link(row)}</div></div><div class="price">${price(row)}</div><details class="why"><summary>Why this rank?</summary><p>${escape(row.why)}</p><p class="small muted">Item ${dollars(row.price)} + shipping ${dollars(row.shipping)}. CPU, storage, warranty and seller can differ within this group.</p>${row.warnings.map(w=>`<p class="small muted">${escape(w)}</p>`).join('')}</details></article>`;
  }
  function render() {
    if (!state) return;
    const data = state.snapshot, current = fresh();
    const timestamp = data.checked_at ? new Date(data.checked_at).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}) : 'Never checked';
    const badge = current ? 'Recently checked' : 'Needs a new check';
    el('status').innerHTML = `<span class="badge ${current ? '' : 'warning'}">${badge}</span><span>Last checked: ${escape(timestamp)}</span>${data.zip_code ? `<span>· ZIP ${escape(data.zip_code)}</span>` : ''}<span>· ${data.count} saved products</span>`;
    if (state.running) el('status').innerHTML += `<span class="badge">Checking ${escape(categoryNames[state.running])}…</span>`;
    el('refresh').disabled = pending || Boolean(state.running);
    el('refresh').textContent = state.running ? 'Checking…' : 'Check now';
    const heading = category === 'desktop-memory' ? 'Desktops worth a closer look' : `${categoryNames[category]} worth a closer look`;
    el('heading').textContent = heading;
    el('purpose').textContent = category === 'desktop-memory' ? 'RTX 5080/5090 · reuse your 64GB kit · aim for 96–128GB' : 'Current product research · compare the exact variant and seller';
    el('ranking-note').textContent = category === 'desktop-memory' ? 'Within each GPU/RAM group: documented layout first, then known total. CPU and storage can differ.' : 'Ordered by known total within condition. This is price order, not a performance or value ranking across different models.';
    const groups = current ? data.groups : [];
    if (!groups.some(g => g.name === group)) group = groups[0]?.name || '';
    el('groups').innerHTML = groups.map(g=>`<button data-group="${escape(g.name)}" aria-pressed="${g.name === group}">${escape(g.name)} · ${g.rows.length}</button>`).join('');
    el('group-select').innerHTML = groups.map(g=>`<option value="${escape(g.name)}" ${g.name === group ? 'selected' : ''}>${escape(g.name)} · ${g.rows.length}</option>`).join('');
    el('group-menu').hidden = !groups.length || view !== 'list';
    const rows = groups.find(g => g.name === group)?.rows || [];
    el('ranked').innerHTML = rows.length ? rows.map(rowCard).join('') : `<div class="empty">${!data.checked_at ? 'Choose Check now to create this category’s first shopping report.' : !current ? 'The saved offers need a new availability check before they can be ranked.' : 'No offers currently meet the ranking requirements. Check the held offers for missing details.'}</div>`;
    const held = current ? data.held : allRows();
    el('held-count').textContent = `· ${held.length}`;
    el('held').innerHTML = held.map(row=>`<article class="held-row"><div><h3 class="deal-title">${escape(row.title)}</h3><p class="small muted">${escape(row.seller)} · ${escape(row.condition)}</p><p class="fit">${escape(row.reasons.length ? row.reasons.join(' · ') : 'Availability needs a new check')}</p><div class="actions">${selectButton(row)}${link(row)}</div></div><div class="price">${price(row)}</div></article>`).join('') || '<p class="muted">No held offers.</p>';
    el('held-section').hidden = !held.length;
    const selected = allRows().filter(row => picks.has(row.id));
    el('compare-count').textContent = picks.size;
    el('comparison').innerHTML = selected.length ? selected.map(row => {
      const specs = [['CPU',row.cpu],['GPU',row.gpu ? `RTX ${row.gpu}` : 'See exact listing'],['Factory RAM',row.ram ? `${row.ram}GB` : 'Not established'],['Storage',row.storage],['Potential with your kit',row.potential ? `${row.potential}GB if compatible` : 'Not established'],['Seller',row.seller],['Condition',row.condition]];
      return `<article class="compare-card"><h2 class="deal-title">${escape(row.title)}</h2><div class="price">${price(row)}</div><p class="badge ${row.reasons.length || !current ? 'warning' : ''}">${escape(current && !row.reasons.length ? 'Recently available' : row.reasons.join(' · ') || 'Needs a new check')}</p>${specs.map(([label,value])=>`<div class="spec"><span>${escape(label)}</span>${escape(value)}</div>`).join('')}<p class="fit">${escape(row.fit_summary)}</p><div class="actions">${selectButton(row)}${link(row)}</div></article>`;
    }).join('') : '<div class="empty">Choose up to three products with “Save & compare.” Saved choices persist in this browser.</div>';
    if (picks.size > selected.length) el('comparison').innerHTML += '<div class="empty">Some saved products are outside this category or no longer in the latest results. <button id="clear-picks">Clear saved choices</button></div>';
    el('ranked').hidden = view !== 'list';
    el('groups').hidden = view !== 'list';
    el('comparison').hidden = view !== 'compare';
    el('list-view').setAttribute('aria-pressed',String(view === 'list'));
    el('compare-view').setAttribute('aria-pressed',String(view === 'compare'));
    const coverage = data.coverage.map(c=>`<div class="coverage-item">${escape(c.query)}: ${escape(c.returned)} of ${escape(c.total ?? 'unknown')} results inspected</div>`).join('');
    el('coverage').innerHTML = `<p class="small muted">Check now runs this category’s preset searches, with at most 10 results per query. Search discovers IDs; ZIP-specific lookups supply prices and availability. It checks only when you ask.</p>${coverage}${data.problems.map(p=>`<p class="fit">${escape(p)}</p>`).join('')}`;
  }
  async function load() {
    const requested = category;
    try {
      const response = await fetch(`/api/state?category=${encodeURIComponent(requested)}`, {cache:'no-store'});
      if (!response.ok) throw new Error('Could not read the saved research.');
      const result = await response.json();
      if (requested !== category) return;
      state = result; render();
      if (['failed','checking'].includes(state.last_check.status) && !state.running && !state.snapshot.fresh) notice('The last check failed or was interrupted. Previous results are held until a successful check. Check the local settings or try again later.');
      else if (state.last_check.status === 'partial' && state.last_check.at >= Date.parse(state.snapshot.checked_at)/1000) notice('The last check was partial. See search coverage for gaps.');
      else notice('');
      clearTimeout(poll);
      if (state.running) poll = setTimeout(load,1000);
    } catch (_) { notice('TechScout could not reach the local server. Start it again and reload this page.'); }
  }
  el('refresh').addEventListener('click',async () => {
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
    category = value; group = ''; state = null; notice('');
    clearTimeout(poll);
    el('heading').textContent = categoryNames[category];
    el('purpose').textContent = 'Loading saved research…';
    el('status').textContent = 'Loading…';
    el('groups').replaceChildren();
    el('group-menu').hidden = true;
    el('ranked').replaceChildren();
    el('comparison').replaceChildren();
    el('coverage').replaceChildren();
    el('ranking-note').textContent = '';
    el('held-section').hidden = true;
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
  el('group-select').addEventListener('change',event=>{group=event.target.value;render();});
  el('groups').addEventListener('click',event => { const b = event.target.closest('[data-group]'); if (b) {group=b.dataset.group;render();} });
  el('list-view').addEventListener('click',()=>{view='list';render();});
  el('compare-view').addEventListener('click',()=>{view='compare';render();});
  document.querySelector('main').addEventListener('click',event => {
    const button = event.target.closest('[data-pick]');
    if (event.target.id === 'clear-picks') { picks.clear();remember();render();return; }
    if (!button) return;
    const id = button.dataset.pick;
    if (picks.has(id)) picks.delete(id);
    else if (picks.size < 3) picks.add(id);
    else { notice('You have three finalists saved. Remove one before adding another.'); return; }
    remember();notice('');render();
  });
  // Reclassify expiring data locally; this timer never starts API research.
  setInterval(()=>{if (state && state.snapshot.fresh && !fresh()) {state.snapshot.fresh=false;render();}},1000);
  load();
})();
