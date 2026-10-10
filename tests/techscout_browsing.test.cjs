const {test}=require('node:test');
const assert=require('node:assert/strict');
const B=require('../alerters/techscout/web/browsing.js');
const now=2000000000;
test('a single-stick watch excludes a same-total kit or desktop DIMM',()=>{
  const prefs={...B.defaults(),filters:{memory_layout:'DDR5 SO-DIMM 1x32GB'}};
  const good={facets:{ram:'32GB',memory_layout:'DDR5 SO-DIMM 1x32GB'}};
  const wrongKit={facets:{ram:'32GB',memory_layout:B.unknown}};
  assert.equal(B.matches(good,prefs),true);
  assert.equal(B.matches(wrongKit,prefs),false);
});
const row=(id,changes={})=>({id,title:'Desktop RTX 5090 64GB DDR5',facets:{kind:'Desktops',gpu:'RTX 5090',ram:'64GB',condition:'New'},source:'newegg',total:4000,price:4000,available:true,expires_at:now+60,checked_at:'2026-10-07T00:00:00Z',verification_reasons:[],preference_reasons:[],reasons:[],fit:'NEEDS SPECS',...changes});

test('visible recommendation separates negative verdicts, qualifying deals and unassessed builds',()=>{
  const pass=row('card',{judgment:{verdict:'PASS',eligible:false}});
  assert.deepEqual(B.recommendation(pass,now),{tone:'skip',label:'Skip — not recommended',note:''});
  const pc={...pass,is_system:true,title:'Alienware Aurora R16 i9-12900 8GB DDR5 RTX 3090 1TB M.2 SSD'};
  assert.equal(B.recommendation(pc,now).tone,'unassessed');
  assert.match(B.recommendation(pc,now).note,/Bare-GPU prices cannot rate this build/);
  assert.equal(B.recommendation({...pc,judgment:{verdict:'GRAIL',eligible:true}},now).tone,'unassessed');
  assert.equal(B.recommendation({...pass,judgment:{verdict:'STRONG',eligible:true}},now).tone,'deal');
  assert.equal(B.recommendation({...pass,judgment:{verdict:'GOOD',eligible:false}},now).tone,'watch');
  assert.equal(B.recommendation({...pass,judgment:null},now).tone,'unassessed');
  assert.equal(B.recommendation({...pass,lead:true},now).tone,'unassessed');
});

test('favorable verdicts never remain green on stale, unavailable or unverified listings',()=>{
  const deal=row('deal',{judgment:{verdict:'GRAIL',eligible:true}});
  for(const changes of [{expires_at:now-1},{available:false},{total:null},{total:0},
    {stock:'out_of_stock'},{stock:'preorder'},{verification_reasons:['Variant unverified']}]) {
    assert.equal(B.recommendation({...deal,...changes},now).tone,'watch');
  }
});

test('prebuilt colors use whole-build evidence, never a budget target or GPU verdict',()=>{
  const pc=row('pc',{is_system:true,stock:'in_stock',judgment:{verdict:'GRAIL',eligible:true,target_hit:true},prebuilt_value:{peers:{difference_pct:null},history:{difference_pct:null}}});
  assert.equal(B.recommendation(pc,now).tone,'unassessed');
  const compare=delta=>({...pc,prebuilt_value:{peers:{difference_pct:delta}}});
  assert.equal(B.recommendation(compare(-5),now).label,'Below comparable prices');
  assert.equal(B.recommendation(compare(5),now).label,'Skip — above comparable prices');
  assert.equal(B.recommendation(compare(4.9),now).tone,'watch');
  assert.equal(B.recommendation(compare(-4.9),now).tone,'watch');
  assert.equal(B.recommendation({...compare(-20),expires_at:now-1},now).tone,'watch');
  assert.equal(B.recommendation({...compare(-20),stock:'unknown'},now).tone,'watch');
  assert.equal(B.recommendation({...pc,prebuilt_value:{history:{difference_pct:-50}}},now).label,'Watch — history only');
});

test('explicit sold-out stock stays prominent after a quote becomes stale',()=>{
  const sold=row('sold',{stock:'out_of_stock',available:false});
  const stale={...sold,id:'stale',expires_at:now-1};
  assert.equal(B.status(sold,B.defaults(),now).label,'Out of stock');
  assert.equal(B.status(stale,B.defaults(),now).label,'Out of stock at last check');
  assert.equal(B.priceContext(stale,now),'Saved price · out of stock at last check');
  assert.deepEqual(B.partition([sold,stale],[],B.defaults(),'monitor',now).current,[]);
  const unknown=row('unknown',{available:false,stock:'unknown'});
  assert.equal(B.status(unknown,B.defaults(),now).label,'Availability unconfirmed');
  assert.doesNotMatch(B.priceContext(unknown,now),/out of stock/);
  assert.equal(B.priceContext(row('old',{expires_at:now-1}),now),'Saved price · needs a new stock check');
  assert.equal(B.priceContext(row('current'),now),'');
  assert.equal(B.status({...sold,lead:true},B.defaults(),now).label,'Publisher report');
});
test('matching outside-plan offers remain visible, independently of stale and publisher evidence',()=>{
  const pref=row('outside',{preference_reasons:['96GB is outside reuse plan']});
  const stale=row('stale',{expires_at:now-1});
  const lead=row('lead',{lead:true,total:null});
  const result=B.partition([row('current'),pref,stale,lead],[],B.defaults(),'desktop-memory',now);
  assert.deepEqual(result.current.map(r=>r.id),['current']);
  assert.equal(result.other.length,3);
  assert.equal(B.status(pref,B.defaults(),now).label,'Outside build preferences');
  assert.equal(B.status(stale,B.defaults(),now).label,'Needs recheck');
  assert.equal(B.status(lead,B.defaults(),now).label,'Publisher report');
});
test('turning off reuse never promotes expired, failed, unknown-total, or publisher rows',()=>{
  const prefs={...B.defaults(),reuse:false};
  const input=[row('outside',{preference_reasons:['Outside plan']}),row('expired',{expires_at:now-1}),row('failed',{verification_reasons:['Last check failed']}),row('total',{total:null}),row('publisher',{lead:true})];
  assert.deepEqual(B.partition(input,[],prefs,'desktop-memory',now).current.map(r=>r.id),['outside']);
});
test('5090 spans RAM capacities, while alternatives relax only one known specification',()=>{
  const prefs={...B.defaults(),filters:{gpu:'RTX 5090',ram:'96GB'}};
  const exact=row('exact',{facets:{kind:'Desktops',gpu:'RTX 5090',ram:'96GB'}});
  const double=row('two',{facets:{kind:'Desktops',gpu:'RTX 5080',ram:'32GB'}});
  const unknown=row('unknown',{facets:{kind:'Desktops',gpu:'RTX 5090'}});
  const result=B.partition([exact,row('near'),double,unknown],[],prefs,'desktop-memory',now);
  assert.deepEqual(result.current.map(r=>r.id),['exact']);
  assert.deepEqual(result.similar.map(r=>r.id),['near']);
  assert.deepEqual(result.similar[0].differences,['Includes 64GB of system RAM']);
  assert.deepEqual(prefs.filters,{gpu:'RTX 5090',ram:'96GB'});
});
test('budget and source are hard constraints even for outside-category alternatives',()=>{
  const prefs={...B.defaults(),filters:{ram:'96GB'},budget:5000,source:'newegg'};
  const result=B.partition([], [row('ok'),row('cost',{total:5001}),row('source',{source:'ebay'}),row('tablet',{facets:{kind:'Tablets',ram:'64GB'}})],prefs,'desktop-memory',now);
  assert.deepEqual(result.similar.map(r=>r.id),['ok']);
  assert.ok(result.similar[0].differences.includes('Outside this category'));
});
test('budget uses the highest publisher quote and never treats unknown prices as free',()=>{
  const prefs={...B.defaults(),budget:100};
  assert.equal(B.matches(row('unknown',{total:null,price:null}),prefs),false);
  assert.equal(B.matches(row('quotes',{total:null,price:null,reported_prices:[80,120]}),prefs),false);
  assert.equal(B.matches(row('quote',{total:null,price:99}),prefs),true);
});
test('combined source cards retain overlap under publisher filters and never duplicate as alternatives',()=>{
  const combined=row('card',{sources:['dealnews','bensbargains'],aliases:['report'],lead:true});
  const prefs={...B.defaults(),source:'dealnews'};
  assert.equal(B.matches(combined,prefs),true);
  const result=B.partition([combined],[row('report',{source:'dealnews'})],prefs,'desktop-memory',now);
  assert.equal(result.other.length,1);assert.equal(result.similar.length,0);
});
test('lowest total and newest checked have deterministic order, unknown totals last',()=>{
  const rows=[row('unknown',{total:null}),row('high',{total:5000,checked_at:'2026-10-07T02:00:00Z'}),row('low',{total:1000})];
  assert.deepEqual(B.sortRows(rows,{...B.defaults(),sort:'total'}).map(r=>r.id),['low','high','unknown']);
  assert.equal(B.sortRows(rows,{...B.defaults(),sort:'newest'})[0].id,'high');
  const quotes=[row('high',{total:null,reported_prices:[50,90]}),row('low',{total:null,price:60}),row('unknown',{total:null,price:null})];
  assert.deepEqual(B.sortRows(quotes,{...B.defaults(),sort:'total'}).map(r=>r.id),['low','high','unknown']);
});
test('saved zero-result selections persist and malformed storage is sanitized',()=>{
  const saved=B.restore({filters:{gpu:'RTX 5090',ram:'96GB'},source:'ebay',budget:3000,sort:'newest',reuse:false,similar:false});
  assert.deepEqual(B.partition([row('x')],[],saved,'desktop-memory',now).current,[]);
  assert.equal(saved.filters.ram,'96GB');
  assert.deepEqual(B.restore({budget:-1,source:'<script>',filters:{gpu:[]},sort:'invalid'}),B.defaults());
});

test('qualifying and target views require current retailer evidence as well as a verdict',()=>{
  const eligible=row('qualified',{judgment:{eligible:true,level:3,target_hit:true}});
  const rows=[eligible,row('unassessed'),{...eligible,id:'stale',expires_at:now-1},
    {...eligible,id:'lead',lead:true},{...eligible,id:'held',verification_reasons:['Shipping unknown']},
    {...eligible,id:'no-total',total:null},{...eligible,id:'sold',available:false},
    {...eligible,id:'not-qualified',judgment:{eligible:false,target_hit:true}}];
  for(const quality of ['best','target'])assert.deepEqual(B.partition(rows,[],{...B.defaults(),quality},'monitor',now).current.map(r=>r.id),['qualified']);
  assert.equal(B.partition([{...eligible,judgment:{eligible:true,target_hit:false}}],[],{...B.defaults(),quality:'target'},'monitor',now).current.length,0);
});

test('new finds use first sighting, not a repeated check, and exclude unknown or future times',()=>{
  const rows=[row('new',{first_seen:new Date((now-3600)*1000).toISOString()}),
    row('old',{first_seen:new Date((now-90000)*1000).toISOString()}),
    row('future',{first_seen:new Date((now+1)*1000).toISOString()}),row('unknown')];
  assert.deepEqual(B.partition(rows,[],{...B.defaults(),quality:'new'},'monitor',now).current.map(r=>r.id),['new']);
});

test('RAM reuse separates included capacity, potential total and missing compatibility evidence',()=>{
  const pc=row('pc',{facets:{kind:'Desktops',ram:'32GB'},fit:'NEEDS SPECS'});
  assert.equal(B.ramReuse(pc).total,'32GB included + your 64GB kit = 96GB potential.');
  assert.match(B.ramReuse(pc).check,/Compatibility unconfirmed/);
  const blocked=B.ramReuse({...pc,fit:'NO REUSE PATH',fit_summary:'DDR4 board cannot accept your DDR5 kit.'});
  assert.match(blocked.total,/blocked/);
  assert.match(blocked.check,/DDR4/);
  assert.doesNotMatch(blocked.total,/96GB potential/);
  const outside=B.ramReuse({...pc,fit:'OUTSIDE REUSE WATCH'});
  assert.match(outside.check,/has not been established/);
  assert.equal(B.ramReuse({...pc,facets:{kind:'Memory',ram:'32GB'}}),null);
});
