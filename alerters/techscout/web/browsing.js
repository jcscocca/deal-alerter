/* Shared, side-effect-free browsing rules, also exercised by the Node tests. */
(function(root) {
  'use strict';
  const unknown = 'Not established';
  const keys = ['kind','gpu','ram','memory_layout','cpu','storage','condition'];
  const labels = {kind:'Product type',gpu:'GPU',ram:'Memory capacity',memory_layout:'Memory modules',cpu:'CPU',storage:'Storage',condition:'Condition',ports:'Ports'};
  const defaults = () => ({filters:{},source:'all',budget:null,sort:'best',similar:true,quality:'standout'});
  const value = (row,key) => row.facets?.[key] || unknown;
  const hasSource = (row,source) => row.source === source || (row.sources || []).includes(source);
  const fresh = (row,now=Date.now()/1000) => Number.isFinite(row.expires_at) && now <= row.expires_at;
  const numericPrice = n => Number.isFinite(n) && n >= 0;
  const supported = row => !row.is_system && !row.prebuilt_value && !['Desktops','Laptops','Tablets','Computers'].includes(value(row,'kind'));
  function budgetPrice(row) {
    if (numericPrice(row.total)) return row.total;
    const prices = (row.reported_prices || []).filter(numericPrice);
    return prices.length ? Math.max(...prices) : numericPrice(row.price) ? row.price : null;
  }
  function hardMatch(row,prefs,except='') {
    const price = budgetPrice(row);
    return supported(row) && (except==='source' || prefs.source==='all' || hasSource(row,prefs.source)) &&
      (except==='budget' || prefs.budget==null || price!=null && price<=prefs.budget);
  }
  function matches(row,prefs,except='',now=Date.now()/1000) {
    return qualityMatch(row,prefs,now) && hardMatch(row,prefs,except) && keys.every(key=>key===except || !prefs.filters[key] || value(row,key)===prefs.filters[key]);
  }
  function verification(row) { return row.verification_reasons || row.reasons || []; }
  function currentOffer(row,now=Date.now()/1000) {
    return supported(row) && !row.lead && fresh(row,now) && row.available===true && row.stock==='in_stock' &&
      numericPrice(row.total) && row.total>0 && !verification(row).length;
  }
  function qualityMatch(row,prefs,now=Date.now()/1000) {
    if(prefs.quality==='new')return now*1000-Date.parse(row.first_seen)<86400000 && now*1000>=Date.parse(row.first_seen);
    if(prefs.quality==='standout')return recommendation(row,now).tier==='standout';
    if(prefs.quality==='best')return ['standout','good'].includes(recommendation(row,now).tier);
    if(prefs.quality==='target')return currentOffer(row,now) && row.judgment?.eligible===true && row.judgment.target_hit===true;
    return true;
  }
  function status(row,prefs,now) {
    if (row.lead) return {label:fresh(row,now) ? 'Publisher report · unverified' : 'Publisher report · needs recheck',tone:'review'};
    if (row.stock==='out_of_stock') return {label:fresh(row,now) ? 'Out of stock' : 'Out of stock at last check',tone:'unavailable'};
    if (row.stock==='preorder') return {label:fresh(row,now) ? 'Preorder' : 'Preorder at last check',tone:'review'};
    if (!fresh(row,now)) return {label:'Needs recheck',tone:'review'};
    if (!row.available || row.stock!=='in_stock') return {label:'Availability unconfirmed',tone:'review'};
    if (!numericPrice(row.total) || row.total<=0 || verification(row).length) return {label:'Needs verification',tone:'review'};
    return {label:'Recently checked · in stock',tone:'current'};
  }
  function priceContext(row,now) {
    if (row.lead) return '';
    if (row.stock==='out_of_stock') return 'Saved price · out of stock at last check';
    if (!fresh(row,now)) return 'Saved price · needs a new stock check';
    if (!row.available || row.stock!=='in_stock') return 'Quoted price · availability unconfirmed';
    return '';
  }
  function recommendation(row,now=Date.now()/1000) {
    const result=(tone,label,note='',tier='unassessed',score=20)=>({tone,label,note,tier,score});
    const j=row.judgment;
    if(!supported(row))return result('unassessed','Outside current scope','Only standalone parts, monitors and accessories are shown.','unassessed',0);
    if(row.lead)return result('unassessed','Unverified deal report','Publisher reports have not established retailer price, stock or value.','unassessed',10);
    if(!currentOffer(row,now))return result('watch','Review — needs verification','Check the saved price, stock and listing details before relying on this assessment.','unassessed',5);
    if(!j)return result('unassessed','Price unassessed','No supported price comparison is available.');
    const standoutBasis=typeof j.standout_basis==='string' ? j.standout_basis.trim() : '';
    if(j.eligible===true && standoutBasis)return result('deal','Standout deal',standoutBasis,'standout',j.verdict==='GRAIL' ? 100 : j.verdict==='EXCEPTIONAL' ? 90 : 80);
    const priceNotice=j.price_notice===true || /(?:CARD|RAM|SO-DIMM) PRICE WATCH/i.test(j.badge || '');
    if(priceNotice)return j.target_hit===true
      ? result('watch','Target price met','This is a configured price watch. Meeting its target does not establish independent deal value.','target',45)
      : result('watch','Price watch','No independent deal-value comparison is available for this price watch.','unassessed',25);
    if(j.eligible===true && ['EXCEPTIONAL','GRAIL'].includes(j.verdict))return result('deal','Standout deal',j.verdict==='GRAIL' ? 'The engine’s highest qualifying price verdict, with current retailer evidence.' : 'Exceptional qualifying price evidence, with current retailer availability.','standout',j.verdict==='GRAIL' ? 100 : 90);
    if(j.eligible===true && j.target_hit===true)return result('watch','Target price met','Your target was met. A target alone does not establish an exceptional deal.','target',45);
    if(j.eligible===true && ['GOOD','STRONG'].includes(j.verdict))return result('deal','Good price evidence','The current offer qualifies under the engine’s price rules; it is below the standout tier.','good',j.verdict==='STRONG' ? 70 : 60);
    if(j.verdict==='PASS')return result('skip','Skip — not recommended',j.reason || '','skip',0);
    if(['WATCH','FAIR','GOOD','STRONG','EXCEPTIONAL','GRAIL'].includes(j.verdict))return result('watch','Watch / review','The current offer does not have a qualifying standout verdict.','unassessed',30);
    return result('unassessed','Price unassessed','No supported price comparison is available.');
  }
  function sortRows(rows,prefs,now=Date.now()/1000) {
    const total = row => numericPrice(row.total) ? row.total : Infinity;
    const checked = row => Date.parse(row.checked_at) || 0;
    return [...rows].sort((a,b)=> {
      if(prefs.sort==='best'){const diff=recommendation(b,now).score-recommendation(a,now).score;if(diff)return diff;}
      if (prefs.sort==='newest') return checked(b)-checked(a) || a.id.localeCompare(b.id);
      return (total(a)-total(b) || 0) || ((budgetPrice(a) ?? Infinity)-(budgetPrice(b) ?? Infinity) || 0) || a.id.localeCompare(b.id);
    });
  }
  function rowsOf(snapshot) { return [...snapshot.groups.flatMap(g=>g.rows),...snapshot.held,...(snapshot.leads || [])].filter(supported); }
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
    const current = matching.filter(row=>currentOffer(row,now));
    const other = matching.filter(row=>!row.lead && !currentOffer(row,now));
    const reports = matching.filter(row=>row.lead);
    const ids = new Set(rows.map(row=>row.id));
    const fixedKinds = {monitors:['Monitors'],memory:['Memory']};
    const kinds = new Set(prefs.filters.kind ? [prefs.filters.kind] : fixedKinds[category] || matching.map(row=>value(row,'kind')));
    const exactIds = new Set(matching.map(row=>row.id));
    const similar = [];
    for (const row of unique([...rows,...related])) {
      if (row.lead || exactIds.has(row.id) || !qualityMatch(row,prefs,now) || !hardMatch(row,prefs) || !kinds.has(value(row,'kind')) || value(row,'kind')==='Other tech') continue;
      const differences = keys.filter(key=>prefs.filters[key] && value(row,key)!==prefs.filters[key]);
      // Never broaden product type, budget, or source. Relax at most one known
      // specification and keep unestablished variants out of recommendations.
      if (differences.includes('kind') || differences.length>1 || differences.some(key=>value(row,key)===unknown)) continue;
      if (!differences.length && ids.has(row.id)) continue;
      const reasons = differences.map(key=>`${labels[key]}: ${value(row,key)} instead of ${prefs.filters[key]}`);
      if (!ids.has(row.id)) reasons.push('Outside this category');
      similar.push({...row,differences:reasons});
    }
    const ordered = sortRows(similar,prefs,now).sort((a,b)=>
      Number(status(b,prefs,now).tone==='current')-Number(status(a,prefs,now).tone==='current'));
    return {current:sortRows(current,prefs,now),other:sortRows(other,prefs,now),reports:sortRows(reports,prefs,now),similar:ordered,similarCount:ordered.length};
  }
  function restore(raw) {
    const prefs = defaults();
    if (!raw || typeof raw!=='object') return prefs;
    for (const key of keys) if (typeof raw.filters?.[key]==='string' && raw.filters[key].length<=100 && !['Desktops','Laptops','Tablets','Computers'].includes(raw.filters[key])) prefs.filters[key]=raw.filters[key];
    if (typeof raw.source==='string' && /^[a-z-]{1,40}$/.test(raw.source)) prefs.source=raw.source;
    if (numericPrice(raw.budget) && raw.budget<=999999) prefs.budget=raw.budget;
    if (['total','newest','best'].includes(raw.sort)) prefs.sort=raw.sort;
    if (['all','standout','best','target','new'].includes(raw.quality)) prefs.quality=raw.quality;
    if (typeof raw.similar==='boolean') prefs.similar=raw.similar;
    return prefs;
  }
  const api = {unknown,keys,labels,defaults,value,hasSource,fresh,supported,budgetPrice,matches,verification,currentOffer,status,priceContext,recommendation,sortRows,rowsOf,unique,partition,restore};
  if (typeof module==='object' && module.exports) module.exports=api;
  else root.TechScoutBrowsing=api;
})(typeof globalThis==='object' ? globalThis : this);
