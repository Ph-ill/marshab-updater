// Real phone page and board HTTP handlers, with the deterministic duel opponent.
import {createRequire} from "module";
import assert from "node:assert/strict";
import {redactStory,assertNoStory,endingTitles} from "./shots_story.mjs";
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PW||"playwright-core");
const [port,out]=process.argv.slice(2);
const browser=await chromium.launch({executablePath:process.env.CHROME});
const ctx=await browser.newContext({viewport:{width:375,height:812},isMobile:true,hasTouch:true,timezoneId:"America/Chicago"});
const page=await ctx.newPage(),errors=[];
page.on("pageerror",e=>errors.push(e.message));
await page.addInitScript(()=>sessionStorage.setItem("lv.here","1"));
// Redact asset values before any app renderer receives them. Retain the real
// titles in memory only, for a fail-closed guard over every captured DOM.
let spoilers=[];
for(const path of ["text.json","engage.json"])await page.route("**/"+path+"*",async r=>{
  const j=await(await r.fetch()).json();
  if(path==="text.json")spoilers=endingTitles(j);
  await r.fulfill({status:200,contentType:"application/json",body:JSON.stringify(redactStory(path,j))});
});
await page.route("https://raw.githubusercontent.com/**",r=>r.abort());
async function shots(name){
  for(const width of [375,320])for(const colorScheme of ["light","dark"]){
    await page.setViewportSize({width,height:812});await page.emulateMedia({colorScheme});
    await page.evaluate(()=>scrollTo(0,0));
    assert.ok(spoilers.length>0,"ending-title guard is armed");
    assertNoStory(await page.content(),spoilers);
    assertNoStory(await page.evaluate(()=>[document.documentElement.textContent,...Array.from(document.querySelectorAll("*"),e=>Array.from(e.attributes,a=>a.value).join("\n"))].join("\n")),spoilers);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+" horizontal overflow");
    await page.screenshot({path:`${out}/${name}-${width}-${colorScheme}.png`,fullPage:true});
  }
  console.log("screens "+name);
}
async function leaveAndReturn(){
  await page.locator("#dock [data-go=home]").click();
  await page.waitForSelector("#du-home");
  await page.getByRole("button",{name:/^Settings/}).click();
  await page.waitForSelector("[data-lvset=dl]");
  await page.locator("#dock [data-go=home]").click();
  await page.waitForSelector("#du-home");
  await page.click("[data-go='duel/0']");
}
async function refreshUntil(test){
  for(let k=0;k<100;k++){await page.evaluate(()=>lvLoad());if(await page.evaluate(test))return;await page.waitForTimeout(100)}
  throw Error("duel state did not arrive");
}
try{
  await page.goto(`http://localhost:${port}/`);
  await page.waitForSelector("[data-who]");await page.click("[data-who='2']");
  for(const k of "1234")await page.click(`[data-key='${k}']`);
  await page.waitForSelector("#dock nav,.kick.big");
  if(await page.$(".kick.big")){await page.click("#dock .btn");await page.waitForSelector(".kick.big",{state:"detached"})}
  if(await page.$(".tut")){await page.click("[data-tut=skip]");await page.waitForSelector(".tut",{state:"detached"})}
  await page.waitForSelector("#du-home");await shots("home");
  await page.click("[data-go=duel]");await page.waitForSelector("[data-dunew]");await shots("pick");
  assert.ok(await page.isDisabled("[data-dunew='6']"),"old ship disabled");
  await page.click("[data-dunew='0']");await page.waitForSelector("[data-duplace]");
  await page.click("[data-duplace='0']");await page.click("[data-duplace='0']");
  assert.equal(await page.evaluate(()=>DU_POS[0][1]),1,"tap again turns");
  await page.click("[data-duship='1']");await page.click("[data-duplace='12']");
  await page.click("[data-duturn]");await page.click("[data-duship='2']");await page.click("[data-duplace='35']");
  await page.click("[data-dushuffle]");assert.ok(await page.evaluate(()=>duLegal(DU_POS)),"shuffle legal");await shots("hide");await leaveAndReturn();
  await page.click("[data-duact=invite]");
  await refreshUntil(()=>duGame(0)?.turn&&!duGame(0)?.pending);
  assert.equal(await page.evaluate(()=>duGame(0).nl),true,"opponent light off is honest");
  await shots("playing");await leaveAndReturn();
  for(const cell of [0,1,2,12,13,35]){
    await refreshUntil(()=>duGame(0)?.turn&&!duGame(0)?.pending);
    await page.click(`[data-ducell='${cell}']`);assert.ok(await page.isEnabled("[data-duact=fire]"),"tap then fire");
    await page.click("[data-duact=fire]");
    await refreshUntil(()=>!DU_BUSY&&duGame(0)?.p==null);
  }
  await refreshUntil(()=>duGame(0)?.s==="done");
  assert.deepEqual(await page.evaluate(()=>duGame(0).record),[1,0],"record");
  assert.equal(await page.locator(".du-grid").count(),2,"both reveals");await shots("ended");await leaveAndReturn();
  await page.click("[data-dunew='0']");await page.waitForSelector("[data-duplace]");assert.equal(await page.evaluate(()=>duGame(0).s),"draft","rematch");
  await page.locator("#dock [data-go=home]").click();await page.waitForSelector("#du-home");
  await page.getByRole("button",{name:/^Settings/}).click();await page.waitForSelector("[data-lvset=dl]");
  await page.click("[data-lvset=dl]");await page.waitForFunction(()=>LV.dl===false);await shots("settings-off");
  assert.deepEqual(errors,[],"no page errors");console.log("duel phone flow PASS");
}finally{await browser.close()}
