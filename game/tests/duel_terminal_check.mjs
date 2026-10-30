// Terminal text comes from the board snapshot, independently of field ownership.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source=fs.readFileSync(new URL("../web/duel.js",import.meta.url),"utf8");
const context=vm.createContext({nm:()=>"Your opponent"});
vm.runInContext(source.slice(source.indexOf("function duStatus(g){"),source.indexOf("function duHome(){")),context);
const status=g=>context.duStatus({to:1,shots:[],...g});
for(const s of ["reveal","done"]){
  assert.equal(status({s,why:2,win:false,status:"Your game ended with both ships standing down. No result."}),"Your game ended with both ships standing down. No result.");
}
assert.equal(status({s:"done",why:2,win:false}),"You resigned");
assert.equal(status({s:"done",why:2,win:true}),"Your opponent resigned");
assert.equal(status({s:"reveal"}),"Checking both fields");
assert.equal(status({s:"cheat"}),"Your opponent's answers didn't match the field");
console.log("duel terminal status: 6 checks passed");
