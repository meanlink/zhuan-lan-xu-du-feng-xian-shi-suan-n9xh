import {audience} from '../../api/entities.js';
import {session} from '../../stores/session.js';
import {BuildStatus,ConflictStatus} from '../../constants/enums.js';
import {esc,date,notify} from '../../utils/dom.js';

const canWrite=()=>session.user.role!=='viewer';
const isAdmin=()=>session.user.role==='admin';

export function buildStatusPill(status){
 return '<span class="status '+esc(status)+'">'+esc(BuildStatus[status]||status)+'</span>';
}

export function buildPanel(build){
 if(!build)return '<div class="empty">该版本尚未构建人群。发布版本后可发起构建，重复发起沿用同一批次。</div>';
 const st=build.stats||{};
 return '<section class="panel"><div class="section-title"><h2>构建批次 #'+build.id+'</h2>'+buildStatusPill(build.status)+'</div>'
  +'<div class="metrics audience-metrics">'
  +'<div><span>批次键</span><strong style="font-size:13px">'+esc(build.batch_key)+'</strong></div>'
  +'<div><span>纳入读者</span><strong>'+esc(st.included??'-')+'</strong></div>'
  +'<div><span>排除</span><strong>'+esc(st.excluded??'-')+'</strong></div>'
  +'<div><span>待裁定冲突</span><strong>'+esc(st.conflicts_pending??build.conflicts?.filter(c=>c.status==='pending').length??0)+'</strong></div>'
  +'<div><span>恢复次数</span><strong>'+esc(build.resume_count)+'</strong></div></div>'
  +(build.error?'<p class="warning">'+esc(build.error)+'</p>':'')
  +'<div class="action-row">'
  +(build.status==='failed'||build.status==='queued'||build.status==='running'?'<button class="button small" data-resume="'+build.id+'" '+(canWrite()?'':'disabled')+'>恢复 / 重试（沿用原批次）</button>':'')
  +(build.status==='ready'?'<button class="primary small" data-release="'+build.id+'" '+(isAdmin()?'':'disabled')+'>发布为可试验人群</button>':'')
  +(build.status==='released'?'<span class="approval">已发布：可用于创建续读风险试验</span>':'')
  +(build.status==='invalid'?'<span class="warning">上游规则更新，本批次已失效；历史资料留存</span>':'')
  +' <button class="button small" data-refresh-build="'+build.id+'">刷新状态 ↻</button></div>'
  +(build.checkpoint&&build.checkpoint.step_index!==undefined?'<p class="hint">检查点：已处理到第 '+(build.checkpoint.step_index+1)+' 步，中断后从已落库部分恢复。</p>':'')
  +'</section>';
}

export function conflictPanel(build){
 const pending=(build.conflicts||[]).filter(c=>c.status===ConflictStatus.pending.value);
 const resolved=(build.conflicts||[]).filter(c=>c.status===ConflictStatus.resolved.value);
 if(!build.conflicts||!build.conflicts.length)return '';
 const card=c=>'<article class="conflict-card '+(c.status==='resolved'?'resolved':'')+'">'
  +'<header><strong>'+esc(c.reader_id)+'</strong><span class="status '+esc(c.status)+'">'+esc(ConflictStatus[c.status])+'</span></header>'
  +'<p class="hint">特征 <strong>'+esc(c.feature)+'</strong> 在不同来源取值冲突，请选定采用来源：</p>'
  +'<div class="candidate-list">'+c.candidates.map(opt=>'<label class="candidate"><input type="radio" name="cf-'+c.id+'" value="'+esc(opt.source)+'" '+(c.chosen_source===opt.source?'checked':'')+' '+(c.status==='resolved'||!canWrite()?'disabled':'')+'><span><strong>'+esc(opt.source_label)+'</strong><small>'+esc(opt.source)+' = '+esc(opt.value)+'</small></span></label>').join('')+'</div>'
  +(c.status==='pending'&&canWrite()?'<button class="button small" data-arbitrate="'+c.id+'" data-build="'+build.id+'">裁定采用所选来源</button>':'')
  +(c.status==='resolved'?'<p class="hint">已采用：'+esc(c.chosen_source)+' = '+esc(c.chosen_value)+'（'+esc(c.arbitrated_by||'')+'）</p>':'')
  +'</article>';
 return '<section class="panel"><div class="section-title"><h2>特征冲突裁定</h2><span>'+pending.length+' 待裁定 / '+resolved.length+' 已裁定</span></div>'
  +(pending.length?'<p class="warning">全部冲突裁定完成后，批次才进入可发布状态；同一读者始终只保留一份。</p>':'')
  +'<div class="conflict-grid">'+build.conflicts.map(card).join('')+'</div></section>';
}

export function memberPanel(build){
 const members=build.members||[];
 if(!members.length)return '';
 return '<section class="panel"><div class="section-title"><h2>成员与纳入/排除路径</h2><span>前 '+members.length+' 条</span></div>'
  +'<div class="table-wrap"><table><thead><tr><th>读者</th><th>状态</th><th>路径（可追查）</th><th>排除原因</th><th></th></tr></thead><tbody>'
  +members.map(m=>'<tr class="'+(m.included?'':'row-excluded')+'"><td>'+esc(m.reader_id)+'</td><td>'+(m.included?'<span class="approval">纳入</span>':'<span class="status failed">排除</span>')+'</td><td>'+esc((m.path||[]).join('  →  '))+'</td><td>'+esc(m.exclude_reason||'—')+'</td><td><button class="text-button" data-trace="'+esc(m.reader_id)+'" data-build="'+build.id+'">追查</button></td></tr>').join('')
  +'</tbody></table></div><div id="trace-out"></div></section>';
}

export function bindBuild(buildId,refresh){
 document.querySelector('[data-refresh-build]')?.addEventListener('click',refresh);
 document.querySelectorAll('[data-resume]').forEach(b=>b.onclick=async()=>{try{await audience.resumeBuild(b.dataset.resume);notify('已提交恢复，沿用原批次');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-release]').forEach(b=>b.onclick=async()=>{try{await audience.releaseBuild(b.dataset.release);notify('已发布为可试验人群');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-arbitrate]').forEach(b=>b.onclick=async()=>{
  const picked=document.querySelector('input[name="cf-'+b.dataset.arbitrate+'"]:checked');
  if(!picked)return notify('请先选择一个采用来源',true);
  try{await audience.arbitrate(b.dataset.build,b.dataset.arbitrate,picked.value);notify('冲突已裁定');await refresh();}catch(e){notify(e.message,true);}
 });
 document.querySelectorAll('[data-trace]').forEach(b=>b.onclick=async()=>{try{const t=await audience.trace(b.dataset.build,b.dataset.trace);document.querySelector('#trace-out').innerHTML='<div class="method-sheet compact"><h3>'+esc(t.reader_id)+' 的完整追查</h3><p>'+esc((t.path||[]).join(' → '))+'</p><pre>'+esc(JSON.stringify(t.features,null,2))+'</pre>'+(t.conflicts.length?'<p class="hint">关联冲突 '+t.conflicts.length+' 项</p>':'')+'</div>';}catch(e){notify(e.message,true);}});
}
