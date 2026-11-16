import {audience,datasets} from '../../api/entities.js';
import {session} from '../../stores/session.js';
import {SetOp,RefKind,SchemeVersionStatus} from '../../constants/enums.js';
import {esc,notify} from '../../utils/dom.js';

const canWrite=()=>session.user.role!=='viewer';

// 编排步骤行：可选来源（批次/方案）与集合运算
export function stepRow(step,index,dsList,schemeList,selfId){
 const opts=[
  '<optgroup label="数据批次">'+dsList.map(d=>'<option value="dataset:'+d.id+'" '+(step&&step.kind==='dataset'&&step.ref_id===d.id?'selected':'')+'>'+esc(d.name)+' · '+d.rows+'条</option>').join('')+'</optgroup>',
  '<optgroup label="人群方案">'+schemeList.filter(s=>s.id!==selfId).map(s=>'<option value="scheme:'+s.id+'" '+(step&&step.kind==='scheme'&&step.ref_id===s.id?'selected':'')+'>'+esc(s.name)+' · v'+(s.version?.version_no||'-')+'</option>').join('')+'</optgroup>'
 ].join('');
 return '<tr class="step-row" data-i="'+index+'">'
  +'<td><input class="step-key" value="'+esc(step?.key||('step'+(index+1)))+'" placeholder="步骤键" style="width:90px"></td>'
  +'<td><select class="step-ref" style="min-width:200px">'+opts+'</select></td>'
  +'<td><select class="step-op">'
  +Object.entries(SetOp).map(([k,label])=>'<option value="'+k+'" '+(step?.op===k?'selected':'')+'>'+label+'</option>').join('')
  +'</select></td>'
  +'<td><button type="button" class="text-button step-del" '+(canWrite()?'':'disabled')+'>删除</button></td></tr>';
}

export function definitionTable(steps,dsList,schemeList,selfId){
 const rows=(steps.length?steps:[null]).map((s,i)=>stepRow(s,i,dsList,schemeList,selfId)).join('');
 return '<div class="table-wrap"><table class="editor-table"><thead><tr><th>步骤键</th><th>引用来源（固定版本/批次）</th><th>集合运算</th><th></th></tr></thead><tbody id="step-tbody">'+rows+'</tbody></table></div>'
  +(canWrite()?'<button type="button" class="button small" id="add-step">+ 增加引用步骤</button><p class="hint">首个步骤必须为并集以建立基础人群；交集收窄、排除移出。引用方案固定到其当前已发布版本，循环引用将被拒绝。</p>':'');
}

// 收集表格中的编排步骤
export function collectSteps(){
 return [...document.querySelectorAll('#step-tbody .step-row')].map(tr=>{
  const [kind,id]=tr.querySelector('.step-ref').value.split(':');
  return {key:tr.querySelector('.step-key').value.trim(),kind,ref_id:Number(id),op:tr.querySelector('.step-op').value};
 }).filter(s=>s.key);
}

export async function saveOrPublish(scheme,publish,refresh){
 try{
  const definition=collectSteps();
  if(!definition.length)return notify('至少保留一个引用步骤',true);
  if(definition[0].op!=='union')return notify('首个步骤必须是并集',true);
  const keys=new Set(definition.map(s=>s.key));
  if(keys.size!==definition.length)return notify('步骤键必须唯一',true);
  const name=document.querySelector('#scheme-name').value.trim();
  const description=document.querySelector('#scheme-desc').value.trim();
  if(publish){
   const up=await audience.updateScheme(scheme.id,{revision:scheme.revision,name,description,definition});
   await audience.publishScheme(scheme.id,up.revision);
   notify('版本已发布并固定引用快照');
  }else{
   await audience.updateScheme(scheme.id,{revision:scheme.revision,name,description,definition});
   notify('草稿已保存（乐观锁版本已更新）');
  }
  await refresh();
 }catch(e){notify(e.message,true);}
}
