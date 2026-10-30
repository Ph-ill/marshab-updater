// Real Chromium keyboard checks against the production renderer and click handler.
// Run with PW pointing to a Playwright package and CHROME to a browser if needed.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PW||'playwright-core');
const source=fs.readFileSync(process.env.DUEL_SOURCE||new URL('../web/duel.js',import.meta.url),'utf8');
const browser=await chromium.launch({headless:true,...(process.env.CHROME?{executablePath:process.env.CHROME}:{})});
try{
  const page=await browser.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<button id=outside>Outside</button><main id=v></main><div id=dock></div>');
  await page.addScriptTag({content:`
    let route='duel/0',tok=true,S={here:1,cond:[0,0]},N=2;
    let LV={duel:[{to:0,id:'focus',s:'active',turn:true,pending:false,p:null,
      shots:[],incoming:[],layout:[[0,1,2],[12,13],[35]],record:[0,0]}]};
    const $=id=>document.getElementById(id),h=String,nm=i=>'Crew '+i;
    function home(){} function lvPaint(){} function view(){} function shipTop(){}
    function dock(html){$('dock').innerHTML=html}
    function portrait(){return ''} function lvAgo(){return ''}
    async function lvLoad(){lvPaint()}
    function lvPeer(){return null} function lvOld(){return false}
    function lvOff(){return false} function lvNear(){return ''}
    ${source}
    view();
  `});
  const focus=()=>page.evaluate(()=>document.activeElement.dataset.dufocus||document.activeElement.id||document.activeElement.tagName);
  const cell=n=>page.locator('.du-grid').first().locator('.du-cell').nth(n);
  const labels=async()=>assert.deepEqual(await page.getByRole('group').evaluateAll(es=>es.map(e=>e.getAttribute('aria-label'))),['Opponent field','Your field']);
  const poll=()=>page.evaluate(()=>lvLoad());
  await labels();
  await cell(7).focus();
  await page.keyboard.press('Enter');
  assert.equal(await focus(),'opponent-7','keyboard selection retains cell focus');
  assert.equal(await cell(7).getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('[data-duact=fire]').isEnabled(),true);
  await poll();
  assert.equal(await focus(),'opponent-7','live poll retains selected cell focus');
  await page.keyboard.press('Tab');
  assert.equal(await focus(),'opponent-8','Tab advances after a rerender');
  await poll();
  assert.equal(await focus(),'opponent-8','poll preserves actual focus, not just selection');
  await page.keyboard.press('Space');
  assert.equal(await focus(),'opponent-8','Space selection retains focus');
  assert.equal(await cell(8).getAttribute('aria-pressed'),'true');
  await page.evaluate(()=>{DU_BUSY=true;view()});
  assert.equal(await focus(),'opponent-8','busy render preserves cell focus');
  assert.equal(await cell(8).getAttribute('aria-disabled'),'true');
  await page.evaluate(()=>{DU_BUSY=false;Object.assign(duGame(0),{turn:false,pending:true,p:8});lvPaint()});
  await labels();
  assert.equal(await focus(),'opponent-8','pending poll preserves focus');
  assert.match(await cell(8).getAttribute('aria-label'),/on its way/);
  assert.equal(await cell(8).getAttribute('tabindex'),'-1','inert cell is not in the tab sequence');
  await page.keyboard.press('Enter');
  await page.keyboard.press('Space');
  assert.equal(await page.evaluate(()=>DU_CELL),8,'inert keyboard activation does not change selection');
  assert.equal(await cell(8).getAttribute('data-ducell'),null,'inert cell has no action');
  for(const state of ['active','reveal','done']){
    await page.evaluate(state=>{Object.assign(duGame(0),{s:state,turn:false,pending:false,p:null,shots:[[1,8,0]]});lvPaint()},state);
    await labels();
    assert.equal(await focus(),'opponent-8',state+' poll preserves the same coordinate');
    assert.match(await cell(8).getAttribute('aria-label'),/miss/);
    assert.equal(await cell(8).getAttribute('aria-disabled'),'true');
  }
  await page.locator('#outside').focus();
  await poll();
  assert.equal(await focus(),'outside','poll does not steal external focus');
  await page.evaluate(()=>{Object.assign(duGame(0),{s:'active',turn:true,shots:[]});view()});
  await cell(9).click();
  assert.equal(await focus(),'opponent-9','pointer selection retains focus');
  await page.evaluate(()=>{duGame(0).id='replacement';view()});
  assert.equal(await focus(),'BODY','replacement duel does not inherit cell focus');
  await cell(9).focus();
  await page.evaluate(()=>{LV.duel.push({...duGame(0),to:2,id:'other'});route='duel/2';view()});
  assert.equal(await focus(),'BODY','different duel does not inherit cell focus');
  await cell(9).focus();
  await page.evaluate(()=>{route='duel';view()});
  assert.equal(await focus(),'BODY','leaving a duel does not restore grid focus');
  for(const state of ['draft','invited']){
    await page.evaluate(state=>{route='duel/0';duGame(0).s=state;view()},state);
    const placement=page.locator('[data-duplace="0"]');
    await placement.focus();
    await page.keyboard.press('Enter');
    assert.equal(await focus(),'own-0',state+' placement retains focus');
    assert.equal(await page.evaluate(()=>DU_POS[0][1]),0);
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>DU_POS[0][1]),1,'second keyboard activation turns your ship');
    await poll();
    assert.equal(await focus(),'own-0',state+' poll retains placement focus');
    assert.equal(await page.getByRole('group').getAttribute('aria-label'),'Your field');
    await page.evaluate(()=>{DU_POS=[null,null,null]});
  }
  assert.deepEqual(errors,[],'no browser errors');
  console.log('duel browser: keyboard selection, Tab, polls, pending/reveal/completion, placement and focus isolation PASS');
}finally{await browser.close()}
