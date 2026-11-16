import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const audience={
 schemes:()=>api('/audience/schemes'),
 scheme:id=>api('/audience/schemes/'+id),
 createScheme:data=>api('/audience/schemes',{method:'POST',body:JSON.stringify(data)}),
 updateScheme:(id,data)=>api('/audience/schemes/'+id,{method:'PUT',body:JSON.stringify(data)}),
 publishScheme:(id,revision)=>api('/audience/schemes/'+id+'/publish',{method:'POST',body:JSON.stringify({revision})}),
 startBuild:id=>api('/audience/schemes/'+id+'/builds',{method:'POST'}),
 build:id=>api('/audience/builds/'+id),
 resumeBuild:id=>api('/audience/builds/'+id+'/resume',{method:'POST'}),
 releaseBuild:id=>api('/audience/builds/'+id+'/release',{method:'POST'}),
 arbitrate:(buildId,conflictId,chosen_source)=>api('/audience/builds/'+buildId+'/conflicts/'+conflictId+'/arbitrate',{method:'POST',body:JSON.stringify({chosen_source})}),
 trace:(buildId,readerId)=>api('/audience/builds/'+buildId+'/trace/'+encodeURIComponent(readerId)),
 experiments:id=>api('/audience/schemes/'+id+'/experiments'),
 cascades:()=>api('/audience/cascades'),
};
