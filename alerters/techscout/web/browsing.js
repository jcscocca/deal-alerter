/* Shared, side-effect-free browsing rules, also exercised by the Node tests. */
(function(root) {
  'use strict';
  const unknown = 'Not established';
  const keys = ['kind','gpu','ram','memory_layout','cpu','storage','condition'];
  const labels = {kind:'Product type',gpu:'GPU',ram:'Included RAM',memory_layout:'Memory modules',cpu:'CPU',storage:'Storage',condition:'Condition'};
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
  function ramReuse(row) {
    if(value(row,'kind')!=='Desktops')return null;
    if(row.fit==='NO REUSE PATH')return {total:'RAM reuse blocked for the planned layout.',check:row.fit_summary || 'The published layout does not support the planned combination.'};
    if(row.fit==='OUTSIDE REUSE WATCH')return {total:'Outside the current 32GB/64GB reuse preference.',check:'Compatibility with your kit has not been established. See the included RAM capacity and listing details.'};
    const included=Number(/^(\d+)GB$/.exec(value(row,'ram'))?.[1]);
    const total=included>0 ? `${included}GB included + your 64GB kit = ${included+64}GB potential.` : 'Combined capacity unknown: included system RAM is not established.';
    const check=row.fit==='POSSIBLE REUSE' ? 'Slot and capacity requirements documented; mixed-kit stability is unverified.' : `Compatibility unconfirmed. ${row.fit_summary || 'Verify DDR5, space for both of your modules, and supported capacity.'}`;
    return {total,check};
  }
  function status(row,prefs,now) {
    if (row.lead) return {label:fresh(row,now) ? 'Publisher report' : 'Publisher report · needs recheck',tone:'review'};
    if (row.stock==='out_of_stock') return {label:fresh(row,now) ? 'Out of stock' : 'Out of stock at last check',tone:'unavailable'};
    if (row.stock==='preorder') return {label:fresh(row,now) ? 'Preorder' : 'Preorder at last check',tone:'review'};
    if (!fresh(row,now)) return {label:'Needs recheck',tone:'review'};
    if (!row.available) return {label:'Availability unconfirmed',tone:'review'};
    if (!numericPrice(row.total) || row.total<=0 || verification(row).length) return {label:'Needs verification',tone:'review'};
    if (prefs.reuse && preferenceReasons(row).length) return {label:'Outside build preferences',tone:'preference'};
    return {label:'Recently checked',tone:'current'};
  }
  function priceContext(row,now) {
    if (row.lead) return '';
    if (row.stock==='out_of_stock') return 'Saved price · out of stock at last check';
    if (!fresh(row,now)) return 'Saved price · needs a new stock check';
    if (!row.available) return 'Quoted price · availability unconfirmed';
    return '';
  }
  function recommendation(row,now=Date.now()/1000) {
    const result=(tone,label,note='')=>({tone,label,note});
    const j=row.judgment,v=row.prebuilt_value;
    if(row.lead)return result('unassessed','Value unassessed','Publisher reports have not been independently rated.');
    // A component verdict cannot rate the complete computer containing it.
    if(row.is_system && !v)return result('unassessed','Value unassessed','Whole-PC comparison unavailable. Bare-GPU prices cannot rate this build.');
    if(!j && !v)return result('unassessed','Value unassessed','No supported price comparison is available.');
    const current=fresh(row,now) && row.available && numericPrice(row.total) && row.total>0 && !verification(row).length && !['out_of_stock','preorder'].includes(row.stock);
    if(!current)return result('watch','Review — needs a new check','Recheck price, stock and listing details before relying on the saved assessment.');
    if(v) {
      if(row.stock!=='in_stock')return result('watch','Review — stock unconfirmed');
      const peer=v.peers?.difference_pct,history=v.history?.difference_pct;
      if(Number.isFinite(peer)) {
        if(peer>=5)return result('skip','Skip — above comparable prices','At least 5% above the median of comparable available builds.');
        if(peer<=-5)return result('deal','Below comparable prices','At least 5% below the matched-build median; component quality and suitability still need review.');
        return result('watch','Typical price — no clear deal','Within 5% of the matched-build median.');
      }
      if(Number.isFinite(history))return result('watch','Watch — history only','Exact-build price history is available, but there are not enough comparable builds to establish value.');
      return result('unassessed','Value unassessed','Not enough whole-build price evidence. A budget target alone does not establish a deal.');
    }
    if(j.verdict==='PASS')return result('skip','Skip — not recommended');
    if(j.eligible===true && ['GOOD','STRONG','EXCEPTIONAL','GRAIL'].includes(j.verdict))return result('deal',`Deal — ${j.verdict==='STRONG' ? 'Strong buy' : j.verdict[0]+j.verdict.slice(1).toLowerCase()}`);
    if(['FAIR','GOOD','STRONG','EXCEPTIONAL','GRAIL'].includes(j.verdict))return result('watch','Watch — no qualifying deal');
    return result('unassessed','Value unassessed');
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
      const reasons = differences.map(key=>key==='ram' ? `Includes ${value(row,key)} of system RAM` : `${labels[key]}: ${value(row,key)} instead of ${prefs.filters[key]}`);
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
  const api = {unknown,keys,labels,defaults,value,hasSource,fresh,budgetPrice,matches,verification,preferenceReasons,ramReuse,status,priceContext,recommendation,sortRows,rowsOf,unique,partition,restore};
  if (typeof module==='object' && module.exports) module.exports=api;
  else root.TechScoutBrowsing=api;
})(typeof globalThis==='object' ? globalThis : this);
