import {datasets,jobs,audience} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
export async function workbench(){
 const [ds,sl]=await Promise.all([datasets.list(),audience.schemes()]);
 workspace.datasets=ds;
 // 收集所有已发布(released)的人群批次供绑定
 const builds=[];
 for(const s of sl){const detail=await audience.scheme(s.id);(detail.builds||[]).forEach(b=>builds.push({...b,schemeName:s.name}));}
 const released=builds.filter(b=>b.status==='released');
 const m=workspace.meta;
 return heading('04 / ANALYSIS LAB',m.workbench_title,'选择业务批次和分析口径。可绑定已发布人群作为可试验对象；参数、输入指纹与计算结论随任务保存，便于复核和复现。')+'<div class="workbench-grid"><section class="panel"><form id="job-form"><label>分析任务名称<input name="name" required minlength="2" value="'+esc(m.name)+' · 复核试算"></label><label>数据批次<select name="dataset_id" required>'+workspace.datasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · '+d.rows+' 条</option>').join('')+'</select></label><label>绑定可试验人群（可选）<select name="audience_build_id"><option value="">不绑定人群（全量批次分析）</option>'+released.map(b=>'<option value="'+b.id+'">'+esc(b.schemeName)+' · 批次#'+b.id+' · 纳入'+(b.stats?.included??0)+'人</option>').join('')+'</select></label><div class="parameter-grid">'+m.parameters.map(p=>'<label>'+esc(p.label)+(p.type==='select'?'<select name="param-'+esc(p.key)+'">'+p.options.map(o=>'<option value="'+esc(o.value)+'" '+(o.value==p.default?'selected':'')+'>'+esc(o.label)+'</option>').join('')+'</select>':'<input type="number" step="any" name="param-'+esc(p.key)+'" value="'+esc(p.default)+'" min="'+esc(p.min??'')+'" max="'+esc(p.max??'')+'" required>')+'</label>').join('')+'</div><button type="submit" class="primary" '+(session.user.role==='viewer'||!workspace.datasets.length?'disabled':'')+'>'+esc(m.action_label||'执行分析')+' ↗</button><p class="hint">绑定人群后，该试验受人群资格约束：上游规则更新会停用其批准与分发资格，历史资料留存。观察员可查看，无法提交。</p></form></section><section class="method-sheet"><p class="eyebrow">METHOD / BUSINESS RULE</p><h2>'+esc(m.method)+'</h2><p>'+esc(m.tagline)+'</p><h3>业务判读边界</h3><ul>'+m.limitations.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul><div class="method-trace"><span>输入</span><strong>'+esc(m.dataset_name)+'</strong><span>输出</span><strong>可复核结果 / 参数版本 / 分发归档</strong></div></section></div>';
}
export function bindWorkbench(){submit(document.querySelector('#job-form'),async f=>{const params={};for(const p of workspace.meta.parameters){const value=f.get('param-'+p.key);params[p.key]=p.type==='number'?Number(value):value;}const audienceBuildId=Number(f.get('audience_build_id'))||null;const j=await jobs.create({name:f.get('name'),dataset_id:Number(f.get('dataset_id')),params,audience_build_id:audienceBuildId});workspace.selectedJob=j.id;notify('分析任务已提交');location.hash='#/results/'+j.id;});}
