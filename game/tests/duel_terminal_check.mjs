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
// A mismatch reads the same from both sides and blames nobody (review 0.3.1-4 #4).
assert.equal(status({s:"cheat"}),"Your ship couldn't check Your opponent's field. No result.");
assert.equal(status({s:"cheat",doubt:1}),"Your opponent's ship couldn't check your field. No result.");
assert.equal(status({s:"done",win:true,doubt:1,shots:[1,2,3,4,5,6]}),"You sank Your opponent's fleet in 6 shots. Your opponent's ship couldn't check your field.");
assert.equal(status({s:"done",win:true,shots:[1,2,3,4,5,6]}),"You sank Your opponent's fleet in 6 shots");
console.log("duel terminal status: 9 checks passed");
