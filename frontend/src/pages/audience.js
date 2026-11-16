import {audience,datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {definitionTable,collectSteps,saveOrPublish} from '../components/audience/editor.js';
import {buildPanel,conflictPanel,memberPanel,bindBuild,buildStatusPill} from '../components/audience/build.js';
import {SchemeVersionStatus,EligibilityStatus,BuildStatus} from '../constants/enums.js';

const canWrite=()=>session.user.role!=='viewer';

export async function audiencePage(id){
 const [schemeList,dsList,cascades]=await Promise.all([audience.schemes(),datasets.list(),audience.cascades()]);
 workspace.schemes=schemeList; workspace.datasets=dsList;
 const sid=id?Number(id):(workspace.selectedScheme||schemeList[0]?.id);
 const scheme=sid?await audience.scheme(sid):null;
 workspace.selectedScheme=scheme?.id||null;
 workspace.selectedBuild=scheme?.builds?.[0]?.id||null;
 const build=scheme&&workspace.selectedBuild?await audience.build(workspace.selectedBuild):null;
 const experiments=scheme?await audience.experiments(scheme.id):[];

 const listPanel='<section class="panel"><div class="section-title"><h2>可复用人群方案</h2><span>'+schemeList.length+' 个</span></div><div class="batch-list">'
  +(schemeList.length?schemeList.map(s=>'<button class="batch-item" data-scheme="'+s.id+'" '+(s.id===sid?'style="border-left:3px solid var(--accent)"':'')+'><strong>'+esc(s.name)+'</strong><span>v'+(s.version?.version_no||'-')+' · '+(SchemeVersionStatus[s.version?.status]||'草稿')+' · 修订号 '+s.revision+'</span><small>'+esc(s.description||'无描述')+'</small></button>').join(''):'<p class="empty">尚无方案，先在右侧编排。</p>')+'</div>'
  +(canWrite()?'<form id="new-scheme-form"><label>新方案名称<input name="name" required minlength="2" placeholder="例如：高活跃回访人群"></label><button class="button small" type="submit">新建方案</button></form>':'')+'</section>';

 if(!scheme){
  return heading('06 / AUDIENCE','可复用人群方案','把反复筛人的编排沉淀为可引用、可版本化的人群方案；支持批次与方案的交集、并集、排除，循环引用拒绝。')
   +'<div class="dataset-grid">'+listPanel+'<section class="panel empty">选择或新建一个方案开始编排。</section></div>';
 }

 const cur=scheme.version||{};
 const editor='<section class="panel"><div class="section-title"><h2>方案编排</h2><span>当前 v'+esc(cur.version_no)+' · '+(SchemeVersionStatus[cur.status]||'草稿')+' · 修订号 '+scheme.revision+'</span></div>'
  +'<form id="scheme-form"><label>方案名称<input id="scheme-name" value="'+esc(scheme.name)+'" '+(canWrite()?'':'disabled')+'></label>'
  +'<label>说明<textarea id="scheme-desc" rows="2" '+(canWrite()?'':'disabled')+'>'+esc(scheme.description||'')+'</textarea></label>'
  +definitionTable(cur.definition||[],dsList,schemeList,scheme.id)
  +(canWrite()?'<div class="action-row"><button type="button" class="button" id="save-draft">保存草稿</button><button type="button" class="primary" id="publish-version">发布版本（固定引用）</button></div>':'')
  +'<p class="hint">发布后版本不可变；再次编辑生成新草稿，规则更新会使旧版本的依赖人群与未批准试验失效。乐观锁修订号 '+scheme.revision+'。</p></form></section>';

 const versionHistory='<section class="panel"><div class="section-title"><h2>版本与引用</h2><span>'+scheme.versions.length+' 版</span></div>'
  +'<div class="schedule-list">'+scheme.versions.map(v=>'<article><div><strong>v'+v.version_no+' · '+(SchemeVersionStatus[v.status]||v.status)+'</strong><p>'+(v.snapshot?Object.keys(v.snapshot).length+' 个固定引用':'草稿未发布')+'</p><small>'+(v.invalidate_reason?esc(v.invalidate_reason):('发布于 '+(v.published_at?date(v.published_at):'—')))+'</small></div>'+(v.id===workspace.selectedBuild?null:null)+'</article>').join('')+'</div></section>';

 const buildEntry='<section class="panel"><div class="section-title"><h2>人群构建</h2><span>固定版本与样本</span></div>'
  +'<div class="action-row"><select id="build-select">'+scheme.builds.map(b=>'<option value="'+b.id+'" '+(b.id===workspace.selectedBuild?'selected':'')+'>批次 #'+b.id+' · '+(BuildStatus[b.status]||b.status)+'</option>').join('')+'</select>'
  +(cur.status==='published'&&canWrite()?'<button class="primary small" id="start-build">发起 / 复用构建</button>':'')
  +(cur.status!=='published'?'<span class="hint">方案发布后才能构建人群</span>':'')+'</div></section>';

 const expPanel='<section class="panel"><div class="section-title"><h2>受影响试验追查</h2><span>'+experiments.length+' 个试验</span></div>'
  +(experiments.length?'<div class="table-wrap"><table><thead><tr><th>试验</th><th>人群状态</th><th>批准</th><th>资格</th><th>分发</th></tr></thead><tbody>'
   +experiments.map(e=>'<tr><td>'+esc(e.job_name)+' #'+e.job_id+'</td><td>'+esc(e.build_status)+'</td><td>'+(e.approved?'已批准':'未批准')+'</td><td><span class="status '+(e.eligibility==='eligible'?'':'failed')+'">'+esc(EligibilityStatus[e.eligibility]||e.eligibility)+'</span></td><td>'+e.reports.map(r=>(r.enabled?'启用':'停用')+'#'+r.id).join('，')+'</td></tr>').join('')
   +'</tbody></table></div>':'<p class="empty">该方案尚未关联试验。发布人群后可在分析工作台绑定。</p>')
  +(experiments.some(e=>e.invalidate_reason)?'<p class="warning">'+esc(experiments.find(e=>e.invalidate_reason).invalidate_reason)+'</p>':'')+'</section>';

 const cascadePanel='<section class="panel"><div class="section-title"><h2>级联失效事件</h2><span>最近 '+cascades.length+' 条</span></div>'
  +(cascades.length?'<div class="schedule-list">'+cascades.slice(0,8).map(e=>'<article><div><strong>'+esc(e.affected_type)+' #'+e.affected_id+'</strong><p>'+esc(e.reason)+'</p><small>'+date(e.created_at)+' · 来源 '+esc(e.origin_type)+'#'+e.origin_id+'</small></div></article>').join('')+'</div>':'<p class="empty">暂无失效事件。</p>')+'</section>';

 return heading('06 / AUDIENCE','可复用人群方案','引用批次或其他方案做交集、并集、排除；固定引用版本与样本，循环引用拒绝，规则更新可级联追溯。')
  +'<div class="audience-layout"><div>'+listPanel+versionHistory+cascadePanel+'</div><div>'+editor+buildEntry
  +(build?buildPanel(build)+conflictPanel(build)+memberPanel(b):'')+expPanel+'</div></div>';
}

export function bindAudience(refresh){
 document.querySelector('#new-scheme-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);
  try{const s=await audience.createScheme({name:f.get('name'),description:'',definition:[]});workspace.selectedScheme=s.id;notify('方案已创建，请编排引用步骤');location.hash='#/audience/'+s.id;await refresh();}catch(err){notify(err.message,true);}});
 document.querySelectorAll('[data-scheme]').forEach(b=>b.onclick=()=>{workspace.selectedScheme=Number(b.dataset.scheme);location.hash='#/audience/'+b.dataset.scheme;});
 document.querySelector('#add-step')?.addEventListener('click',()=>{const tbody=document.querySelector('#step-tbody');const i=tbody.children.length;
  // 新增空行：复用表格首行结构，通过临时数据集渲染
  const tr=document.createElement('tr');tr.className='step-row';tr.dataset.i=i;
  tr.innerHTML='<td><input class="step-key" value="step'+(i+1)+'" style="width:90px"></td><td><select class="step-ref" style="min-width:200px">'+document.querySelector('.step-ref').innerHTML+'</select></td><td><select class="step-op">'+document.querySelector('.step-op').innerHTML+'</select></td><td><button type="button" class="text-button step-del">删除</button></td>';
  tbody.appendChild(tr);bindDel();});
 function bindDel(){document.querySelectorAll('.step-del').forEach(b=>b.onclick=()=>{b.closest('.step-row').remove();});}
 bindDel();
 const scheme=workspace.schemes.find(s=>s.id===workspace.selectedScheme);
 document.querySelector('#save-draft')?.addEventListener('click',()=>saveOrPublish(scheme,false,refresh));
 document.querySelector('#publish-version')?.addEventListener('click',()=>saveOrPublish(scheme,true,refresh));
 document.querySelector('#build-select')?.addEventListener('change',e=>{workspace.selectedBuild=Number(e.target.value);refresh();});
 document.querySelector('#start-build')?.addEventListener('click',async()=>{try{const b=await audience.startBuild(workspace.selectedScheme);workspace.selectedBuild=b.id;notify('构建已提交，后台按固定版本计算');await refresh();}catch(e){notify(e.message,true);}});
 if(workspace.selectedBuild)bindBuild(workspace.selectedBuild,refresh);
}
