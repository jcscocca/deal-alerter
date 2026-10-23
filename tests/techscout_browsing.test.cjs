const {test}=require('node:test');
const assert=require('node:assert/strict');
const B=require('../alerters/techscout/web/browsing.js');
const now=2000000000;
const browse=(changes={})=>({...B.defaults(),quality:'all',...changes});
const row=(id,changes={})=>({id,title:'RTX 5090 graphics card',facets:{kind:'Graphics cards',gpu:'RTX 5090',condition:'New'},source:'ebay',total:2000,price:2000,available:true,stock:'in_stock',expires_at:now+60,checked_at:'2026-10-07T00:00:00Z',verification_reasons:[],reasons:[],...changes});
const verdict=(name,changes={})=>({verdict:name,eligible:true,...changes});

test('home defaults to standout evidence instead of the lowest dollar price',()=>{
  const prefs=B.defaults();
  assert.equal(prefs.quality,'standout');assert.equal(prefs.sort,'best');
  assert.equal(Object.hasOwn(prefs,'reuse'),false);
  const results=B.partition([row('cheap',{total:10}),row('exceptional',{judgment:verdict('EXCEPTIONAL')})],[],prefs,'monitor',now);
  assert.deepEqual(results.current.map(r=>r.id),['exceptional']);
});

test('native standout verdicts require current qualifying exceptional or grail evidence',()=>{
  for(const name of ['EXCEPTIONAL','GRAIL'])assert.equal(B.recommendation(row(name,{judgment:verdict(name)}),now).tier,'standout');
  for(const name of ['GOOD','STRONG','FAIR','PASS'])assert.notEqual(B.recommendation(row(name,{judgment:verdict(name)}),now).tier,'standout');
  assert.notEqual(B.recommendation(row('ineligible',{judgment:verdict('GRAIL',{eligible:false})}),now).tier,'standout');
  assert.notEqual(B.recommendation(row('unknown',{judgment:{eligible:true,level:100}}),now).tier,'standout');
});

test('no favorable assessment survives stale, unconfirmed, unavailable or risky evidence',()=>{
  const deal=row('deal',{judgment:verdict('GRAIL')});
  for(const changes of [{expires_at:now-1},{available:false},{total:null},{total:0},
    {stock:'out_of_stock'},{stock:'unknown'},{stock:'preorder'},
    {verification_reasons:['Variant unverified']},{verification_reasons:['Seller needs review']}]) {
    const candidate={...deal,...changes};
    assert.equal(B.recommendation(candidate,now).tone,'watch');
    assert.equal(B.partition([candidate],[],B.defaults(),'monitor',now).current.length,0);
  }
});

test('targets stay separate from favorable price evidence',()=>{
  const target=row('target',{judgment:verdict('FAIR',{target_hit:true,target:2100})});
  const assessment=B.recommendation(target,now);
  assert.equal(assessment.tier,'target');assert.equal(assessment.tone,'watch');
  assert.match(assessment.note,/target alone does not establish/i);
  assert.equal(B.partition([target],[],B.defaults(),'parts',now).current.length,0);
  assert.equal(B.partition([target],[],browse({quality:'target'}),'parts',now).current.length,1);
  assert.equal(B.partition([{...target,judgment:verdict('FAIR',{target_hit:false})}],[],browse({quality:'target'}),'parts',now).current.length,0);
});

test('budget-only price notices never borrow their native alert verdict as deal evidence',()=>{
  for(const name of ['STRONG','EXCEPTIONAL','GRAIL']) {
    for(const fields of [{price_notice:true},{badge:'CARD PRICE WATCH'},{badge:'RAM PRICE WATCH'},{badge:'SO-DIMM PRICE WATCH'}]) {
      const notice=row('notice',{judgment:verdict(name,{target_hit:true,...fields})});
      assert.equal(B.recommendation(notice,now).tier,'target');
      assert.equal(B.recommendation(notice,now).tone,'watch');
      assert.equal(B.partition([notice],[],B.defaults(),'memory',now).current.length,0);
      assert.equal(B.partition([notice],[],browse({quality:'best'}),'memory',now).current.length,0);
    }
  }
  const benchmark=row('monitor',{facets:{kind:'Monitors'},judgment:verdict('EXCEPTIONAL',{target_hit:true})});
  assert.equal(B.recommendation(benchmark,now).tier,'standout');
  assert.equal(B.recommendation(row('not-met',{judgment:verdict('STRONG',{price_notice:true,target_hit:false})}),now).tier,'unassessed');
});

test('real monitor benchmark evidence supports standout without inventing a higher native verdict',()=>{
  const basis='30% below this exact monitor’s dated retail quote from 2026-10-01; not a sold-price market comparison.';
  const monitor=row('monitor',{facets:{kind:'Monitors'},judgment:verdict('STRONG',{target_hit:true,standout_basis:basis})});
  const assessment=B.recommendation(monitor,now);
  assert.equal(assessment.tier,'standout');assert.equal(assessment.score,80);assert.equal(assessment.note,basis);
  assert.equal(B.partition([monitor],[],B.defaults(),'monitors',now).current.length,1);
  const withoutBasis={...monitor,judgment:{...monitor.judgment,standout_basis:''}};
  assert.equal(B.recommendation(withoutBasis,now).tier,'target');
  assert.equal(B.recommendation({...monitor,judgment:{...monitor.judgment,standout_basis:'  '}},now).tier,'target');
  for(const changes of [{available:false},{stock:'unknown'},{expires_at:now-1},{lead:true},
    {judgment:{...monitor.judgment,eligible:false}}])assert.notEqual(B.recommendation({...monitor,...changes},now).tier,'standout');
  for(const [name,score] of [['EXCEPTIONAL',90],['GRAIL',100]])assert.equal(B.recommendation({...monitor,judgment:{...monitor.judgment,verdict:name}},now).score,score);
});

test('good evidence and weak judgments remain understandable in broader browse',()=>{
  assert.equal(B.recommendation(row('good',{judgment:verdict('STRONG')}),now).tier,'good');
  assert.equal(B.recommendation(row('pass',{judgment:verdict('PASS',{eligible:false})}),now).tone,'skip');
  assert.equal(B.recommendation(row('watch',{judgment:verdict('GOOD',{eligible:false})}),now).tone,'watch');
  assert.equal(B.recommendation(row('none'),now).tone,'unassessed');
});

test('publisher reports cannot become retailer deals or gain a price verdict',()=>{
  const lead=row('lead',{lead:true,judgment:verdict('GRAIL')});
  assert.equal(B.recommendation(lead,now).tone,'unassessed');
  const result=B.partition([row('retailer'),lead,row('stale',{expires_at:now-1})],[],browse(),'monitor',now);
  assert.deepEqual(result.current.map(r=>r.id),['retailer']);
  assert.deepEqual(result.reports.map(r=>r.id),['lead']);
  assert.deepEqual(result.other.map(r=>r.id),['stale']);
  assert.equal(B.partition([lead],[],B.defaults(),'monitor',now).reports.length,0);
});

test('deal ordering favors supported exceptional value across unlike price points',()=>{
  const rows=[row('cheap-unassessed',{total:5}),row('target',{total:20,judgment:verdict('FAIR',{target_hit:true})}),
    row('good',{total:100,judgment:verdict('GOOD')}),row('exceptional',{total:2000,judgment:verdict('EXCEPTIONAL')}),
    row('grail',{total:3000,judgment:verdict('GRAIL')}),row('stale-grail',{total:1,expires_at:now-1,judgment:verdict('GRAIL')})];
  assert.deepEqual(B.sortRows(rows,B.defaults(),now).map(r=>r.id),['grail','exceptional','good','target','cheap-unassessed','stale-grail']);
  assert.equal(B.sortRows([row('b',{total:100,judgment:verdict('EXCEPTIONAL')}),row('a',{total:50,judgment:verdict('EXCEPTIONAL')})],B.defaults(),now)[0].id,'a');
});

test('complete systems stay outside every parts feed even when old snapshots remain',()=>{
  const systems=[row('desktop',{is_system:true,judgment:verdict('GRAIL')}),
    row('laptop',{facets:{kind:'Laptops'}}),row('tablet',{facets:{kind:'Tablets'}}),
    row('old-pc',{prebuilt_value:{peers:{difference_pct:-50}}})];
  const snapshot={groups:[{rows:[row('part'),...systems]}],held:[],leads:[]};
  assert.deepEqual(B.rowsOf(snapshot).map(r=>r.id),['part']);
  assert.deepEqual(B.partition(systems,[],browse(),'monitor',now).current,[]);
});

test('sold-out state stays prominent after a saved quote becomes stale',()=>{
  const sold=row('sold',{stock:'out_of_stock',available:false}),stale={...sold,id:'stale',expires_at:now-1};
  assert.equal(B.status(sold,browse(),now).label,'Out of stock');
  assert.equal(B.status(stale,browse(),now).label,'Out of stock at last check');
  assert.equal(B.priceContext(stale,now),'Saved price · out of stock at last check');
  assert.deepEqual(B.partition([sold,stale],[],browse(),'monitor',now).current,[]);
  assert.equal(B.status(row('unknown',{available:false,stock:'unknown'}),browse(),now).label,'Availability unconfirmed');
  assert.equal(B.priceContext(row('old',{expires_at:now-1}),now),'Saved price · needs a new stock check');
});

test('memory specifications still distinguish single sticks from kits without a completion plan',()=>{
  const prefs=browse({filters:{memory_layout:'DDR5 SO-DIMM 1x32GB'}});
  const good=row('single',{facets:{kind:'Memory',ram:'32GB',memory_layout:'DDR5 SO-DIMM 1x32GB'}});
  const wrong=row('kit',{facets:{kind:'Memory',ram:'32GB',memory_layout:B.unknown}});
  assert.equal(B.matches(good,prefs,'',now),true);assert.equal(B.matches(wrong,prefs,'',now),false);
});

test('alternatives relax only one known specification and keep source, budget and type',()=>{
  const prefs=browse({filters:{gpu:'RTX 5090',condition:'New'},budget:3000,source:'ebay'});
  const result=B.partition([row('exact'),row('near',{facets:{kind:'Graphics cards',gpu:'RTX 5080',condition:'New'}}),
    row('two',{facets:{kind:'Graphics cards',gpu:'RTX 5080',condition:'Used'}}),
    row('unknown',{facets:{kind:'Graphics cards',condition:'New'}}),
    row('cost',{total:3001}),row('source',{source:'newegg'})],[],prefs,'parts',now);
  assert.deepEqual(result.current.map(r=>r.id),['exact']);
  assert.deepEqual(result.similar.map(r=>r.id),['near']);
  assert.deepEqual(result.similar[0].differences,['GPU: RTX 5080 instead of RTX 5090']);
});

test('outside-category alternatives cannot broaden a monitor watch into another product type',()=>{
  const prefs=browse({filters:{condition:'New'},budget:500,source:'ebay'});
  const result=B.partition([], [row('monitor',{total:300,facets:{kind:'Monitors',condition:'New'}}),
    row('gpu',{total:300}),row('expensive',{total:501,facets:{kind:'Monitors',condition:'New'}})],prefs,'monitors',now);
  assert.deepEqual(result.similar.map(r=>r.id),['monitor']);
});

test('budgets use the highest publisher quote and never treat unknown prices as free',()=>{
  const prefs=browse({budget:100});
  assert.equal(B.matches(row('unknown',{total:null,price:null}),prefs,'',now),false);
  assert.equal(B.matches(row('quotes',{total:null,price:null,reported_prices:[80,120]}),prefs,'',now),false);
  assert.equal(B.matches(row('quote',{total:null,price:99}),prefs,'',now),true);
});

test('combined publisher cards preserve source filters and do not duplicate alternatives',()=>{
  const combined=row('card',{sources:['dealnews','bensbargains'],aliases:['report'],lead:true});
  const prefs=browse({source:'dealnews'});
  assert.equal(B.matches(combined,prefs,'',now),true);
  const result=B.partition([combined],[row('report',{source:'dealnews'})],prefs,'parts',now);
  assert.equal(result.reports.length,1);assert.equal(result.similar.length,0);
});

test('explicit lowest-total and newest sorts remain available with deterministic ties',()=>{
  const rows=[row('unknown',{total:null}),row('high',{total:5000,checked_at:'2026-10-07T02:00:00Z'}),row('low',{total:1000})];
  assert.deepEqual(B.sortRows(rows,browse({sort:'total'}),now).map(r=>r.id),['low','high','unknown']);
  assert.equal(B.sortRows(rows,browse({sort:'newest'}),now)[0].id,'high');
  const quotes=[row('high',{total:null,reported_prices:[50,90]}),row('low',{total:null,price:60}),row('unknown',{total:null,price:null})];
  assert.deepEqual(B.sortRows(quotes,browse({sort:'total'}),now).map(r=>r.id),['low','high','unknown']);
});

test('restoring preferences drops retired build intent and retains valid zero-result filters',()=>{
  const saved=B.restore({filters:{gpu:'RTX 5090',kind:'Desktops'},source:'ebay',budget:3000,sort:'recommended',reuse:true,similar:false});
  assert.equal(saved.sort,'best');assert.equal(Object.hasOwn(saved,'reuse'),false);assert.equal(Object.hasOwn(saved.filters,'kind'),false);
  assert.equal(saved.filters.gpu,'RTX 5090');assert.equal(saved.similar,false);
  assert.deepEqual(B.partition([row('x')],[],saved,'parts',now).current,[]);
  assert.deepEqual(B.restore({budget:-1,source:'<script>',filters:{gpu:[]},sort:'invalid'}),B.defaults());
});

test('qualifying and target views never promote stale, unverified or publisher evidence',()=>{
  const eligible=row('qualified',{judgment:verdict('GRAIL',{target_hit:true})});
  const rows=[eligible,row('unassessed'),{...eligible,id:'stale',expires_at:now-1},
    {...eligible,id:'lead',lead:true},{...eligible,id:'held',verification_reasons:['Shipping unknown']},
    {...eligible,id:'no-total',total:null},{...eligible,id:'sold',available:false},
    {...eligible,id:'not-qualified',judgment:verdict('GRAIL',{eligible:false,target_hit:true})}];
  for(const quality of ['standout','best','target'])assert.deepEqual(B.partition(rows,[],browse({quality}),'monitor',now).current.map(r=>r.id),['qualified']);
});

test('new finds use first sighting rather than repeated checks or future timestamps',()=>{
  const rows=[row('new',{first_seen:new Date((now-3600)*1000).toISOString()}),
    row('old',{first_seen:new Date((now-90000)*1000).toISOString()}),
    row('future',{first_seen:new Date((now+1)*1000).toISOString()}),row('unknown')];
  assert.deepEqual(B.partition(rows,[],browse({quality:'new'}),'monitor',now).current.map(r=>r.id),['new']);
});

test('dashboard ignores retired local preferences and keeps broader browse one click away',async()=>{
  const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
  const directory=path.resolve(__dirname,'../alerters/techscout/web');
  const html=fs.readFileSync(path.join(directory,'index.html'),'utf8');
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(new Set(ids).size,ids.length,'DOM IDs must be unique');
  const element=id=>({id,hidden:false,value:'',innerHTML:'',textContent:'',handlers:{},
    selectedOptions:[{textContent:'Standout deals'}],setAttribute(){},scrollIntoView(){},
    addEventListener(type,handler){(this.handlers[type] ||= []).push(handler)},classList:{add(){}}});
  const elements=new Map(ids.map(id=>[id,element(id)])),main=element('main');
  const live={...row('exceptional',{judgment:verdict('EXCEPTIONAL')}),expires_at:Date.now()/1000+60,retailer:'eBay',seller:'Trusted seller',url:'https://example.com/item'};
  const snapshot={groups:[{rows:[live,{...live,id:'target',judgment:verdict('STRONG',{price_notice:true,target_hit:true})}]}],held:[],
    leads:[{...live,id:'lead',lead:true}],sources:[{source:'ebay',label:'eBay',ready:1,jobs:1,count:3}],coverage:[],problems:[]};
  const retired={'techscout-browsing':JSON.stringify({category:'desktop-memory',views:{monitor:{reuse:true,sort:'total',quality:'all'}}}),'techscout-shortlist':JSON.stringify(['123'])};
  const context={document:{activeElement:null,getElementById(id){assert.ok(elements.has(id),'missing DOM element '+id);return elements.get(id)},
    querySelector(selector){return selector==='main' ? main : {content:'test-token'}},querySelectorAll(){return []}},
    localStorage:{getItem(key){return retired[key] || null},setItem(){}},Intl,Date,Set,Map,URL,URLSearchParams,
    crypto:require('node:crypto').webcrypto,setInterval(){},setTimeout(){},clearTimeout(){},
    matchMedia(){return {matches:false}},addEventListener(){},scrollTo(){},
    fetch:async url=>({ok:true,json:async()=>url==='/api/workspace'
      ? {supported:true,revision:'test',settings:{version:2,mode:'all',watches:[]},activity:[]}
      : {snapshot,last_check:{status:'success'},running:false}})};
  context.window=context;vm.createContext(context);
  for(const name of ['browsing.js','workspace.js','dashboard.js'])vm.runInContext(fs.readFileSync(path.join(directory,name),'utf8'),context,{filename:name});
  await new Promise(setImmediate);
  assert.equal(elements.get('heading').textContent,'Standout deals');
  assert.equal(elements.get('current-count').textContent,1);
  assert.equal(elements.get('compare-count').textContent,0,'old whole-PC shortlist must not return');
  assert.equal(elements.get('reports-section').hidden,true);
  assert.match(elements.get('current-cards').innerHTML,/Standout deal/);
  for(const handler of elements.get('browse-all').handlers.click)handler();
  assert.equal(elements.get('current-count').textContent,2);
  assert.equal(elements.get('reports-count').textContent,1);
  assert.equal(elements.get('reports-section').hidden,false);
  assert.match(elements.get('reports-cards').innerHTML,/Unverified deal report/);
  assert.doesNotMatch(elements.get('current-cards').innerHTML,/Unverified deal report/);
  assert.doesNotMatch(html,/reuse your|RAM reuse|96–128|Potential with your kit|prebuilt/i);
});
