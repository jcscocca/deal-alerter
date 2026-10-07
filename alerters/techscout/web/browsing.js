/* Shared, side-effect-free browsing rules, also exercised by the Node tests. */
(function(root) {
  'use strict';
  const unknown = 'Not established';
  const keys = ['kind','gpu','ram','cpu','storage','condition'];
  const labels = {kind:'Product type',gpu:'GPU',ram:'RAM',cpu:'CPU',storage:'Storage',condition:'Condition'};
  const defaults = () => ({filters:{},source:'all',budget:null,sort:'recommended',reuse:true,similar:true,quality:'all'});
  const value = (row,key) => row.facets?.[key] || unknown;
  const hasSource = (row,source) => row.source === source || (row.sources || []).includes(source);
  const fresh = (row,now=Date.now()/1000) => Number.isFinite(row.expires_at) && now <= row.expires_at;
  const numericPrice = n => Number.isFinite(n) && n >= 0;
  function budgetPrice(row) {
    if (numericPrice(row.total)) return row.total;
    const prices = (row.reported_prices || []).filter(numericPrice);
    return prices.length ? Math.max(...prices) : numericPrice(row.price) ? row.price : null;
  }
  function hardMatch(row,prefs,except='') {
    const price = budgetPrice(row);
    return (except==='source' || prefs.source==='all' || hasSource(row,prefs.source)) &&
      (except==='budget' || prefs.budget==null || price!=null && price<=prefs.budget);
  }
  function matches(row,prefs,except='',now=Date.now()/1000) {
    return qualityMatch(row,prefs,now) && hardMatch(row,prefs,except) && keys.every(key=>key===except || !prefs.filters[key] || value(row,key)===prefs.filters[key]);
  }
  function qualityMatch(row,prefs,now=Date.now()/1000) {
    if(prefs.quality==='new')return now*1000-Date.parse(row.first_seen)<86400000 && now*1000>=Date.parse(row.first_seen);
    if(['best','target'].includes(prefs.quality))return fresh(row,now) && row.available && numericPrice(row.total) && row.total>0 && !row.lead && !verification(row).length && row.judgment?.eligible===true && (prefs.quality!=='target' || row.judgment.target_hit===true);
    return true;
  }
  function verification(row) { return row.verification_reasons || row.reasons || []; }
  function preferenceReasons(row) {
    if (row.preference_reasons?.length) return row.preference_reasons;
    return value(row,'kind')==='Desktops' && (!row.fit || row.fit==='Not assessed') ? ['RAM reuse has not been assessed for this build.'] : [];
  }
  function status(row,prefs,now) {
    if (row.lead) return {label:fresh(row,now) ? 'Publisher report' : 'Publisher report · needs recheck',tone:'review'};
    if (!fresh(row,now)) return {label:'Needs recheck',tone:'review'};
    if (!row.available || !numericPrice(row.total) || row.total<=0 || verification(row).length) return {label:'Needs verification',tone:'review'};
    if (prefs.reuse && preferenceReasons(row).length) return {label:'Outside build preferences',tone:'preference'};
    return {label:'Recently checked',tone:'current'};
  }
  function sortRows(rows,prefs) {
    const total = row => numericPrice(row.total) ? row.total : Infinity;
    const checked = row => Date.parse(row.checked_at) || 0;
    return [...rows].sort((a,b)=> {
      if(prefs.sort==='best'){const diff=(b.judgment?.eligible ? b.judgment.level+1 : 0)-(a.judgment?.eligible ? a.judgment.level+1 : 0);if(diff)return diff;}
      if (prefs.sort==='newest') return checked(b)-checked(a) || a.id.localeCompare(b.id);
      if (prefs.sort==='recommended' && prefs.reuse) {
        const evidence = Number(Boolean(b.layout_documented))-Number(Boolean(a.layout_documented));
        if (evidence) return evidence;
      }
      return (total(a)-total(b) || 0) || ((budgetPrice(a) ?? Infinity)-(budgetPrice(b) ?? Infinity) || 0) || a.id.localeCompare(b.id);
    });
  }
  function rowsOf(snapshot) { return [...snapshot.groups.flatMap(g=>g.rows),...snapshot.held,...(snapshot.leads || [])]; }
  function unique(rows) {
    const ids = new Set();
    return rows.filter(row=> {
      const aliases = [row.id,...(row.aliases || [])];
      if (aliases.some(id=>ids.has(id))) return false;
      aliases.forEach(id=>ids.add(id)); return true;
    });
  }
  function partition(rows,related,prefs,category,now=Date.now()/1000) {
    const matching = rows.filter(row=>matches(row,prefs,'',now));
    const current = matching.filter(row=>status(row,prefs,now).tone==='current');
    const other = matching.filter(row=>status(row,prefs,now).tone!=='current');
    const ids = new Set(rows.map(row=>row.id));
    const fixedKinds = {'desktop-memory':['Desktops'],computers:['Desktops','Laptops'],tablets:['Tablets'],memory:['Memory']};
    const kinds = new Set(prefs.filters.kind ? [prefs.filters.kind] : fixedKinds[category] || matching.map(row=>value(row,'kind')));
    const exactIds = new Set(matching.map(row=>row.id));
    const similar = [];
    for (const row of unique([...rows,...related])) {
      if (exactIds.has(row.id) || !qualityMatch(row,prefs,now) || !hardMatch(row,prefs) || !kinds.has(value(row,'kind')) || value(row,'kind')==='Other tech') continue;
      const differences = keys.filter(key=>prefs.filters[key] && value(row,key)!==prefs.filters[key]);
      // Never broaden product type, budget, or source. Relax at most one known
      // specification and keep unestablished variants out of recommendations.
      if (differences.includes('kind') || differences.length>1 || differences.some(key=>value(row,key)===unknown)) continue;
      if (!differences.length && ids.has(row.id)) continue;
      const reasons = differences.map(key=>`${labels[key]}: ${value(row,key)} instead of ${prefs.filters[key]}`);
      if (!ids.has(row.id)) reasons.push('Outside this category');
      similar.push({...row,differences:reasons});
    }
    const ordered = sortRows(similar,prefs).sort((a,b)=>
      Number(status(b,prefs,now).tone==='current')-Number(status(a,prefs,now).tone==='current'));
    return {current:sortRows(current,prefs),other:sortRows(other,prefs),similar:ordered,similarCount:ordered.length};
  }
  function restore(raw) {
    const prefs = defaults();
    if (!raw || typeof raw!=='object') return prefs;
    for (const key of keys) if (typeof raw.filters?.[key]==='string' && raw.filters[key].length<=100) prefs.filters[key]=raw.filters[key];
    if (typeof raw.source==='string' && /^[a-z-]{1,40}$/.test(raw.source)) prefs.source=raw.source;
    if (numericPrice(raw.budget) && raw.budget<=999999) prefs.budget=raw.budget;
    if (['recommended','total','newest','best'].includes(raw.sort)) prefs.sort=raw.sort;
    if (['all','best','target','new'].includes(raw.quality)) prefs.quality=raw.quality;
    if (typeof raw.reuse==='boolean') prefs.reuse=raw.reuse;
    if (typeof raw.similar==='boolean') prefs.similar=raw.similar;
    return prefs;
  }
  const api = {unknown,keys,labels,defaults,value,hasSource,fresh,budgetPrice,matches,verification,preferenceReasons,status,sortRows,rowsOf,unique,partition,restore};
  if (typeof module==='object' && module.exports) module.exports=api;
  else root.TechScoutBrowsing=api;
})(typeof globalThis==='object' ? globalThis : this);
