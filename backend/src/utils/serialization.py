import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','audience_build_id','eligibility','invalidate_reason','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def scheme_dict(s, version=None):
    return {'id':s.id,'name':s.name,'description':s.description,'revision':s.revision,
            'current_version_id':s.current_version_id,'created_at':s.created_at,'updated_at':s.updated_at,
            'version': version_dict(version) if version else None}
def version_dict(v):
    if v is None:return None
    return {'id':v.id,'scheme_id':v.scheme_id,'version_no':v.version_no,'status':v.status,
            'definition':v.definition,'snapshot':v.snapshot,'version_checksum':v.version_checksum,
            'invalidate_reason':v.invalidate_reason,'created_at':v.created_at,
            'published_at':v.published_at,'invalidated_at':v.invalidated_at}
def build_dict(b):
    return {'id':b.id,'scheme_id':b.scheme_id,'version_id':b.version_id,'batch_key':b.batch_key,
            'status':b.status,'checkpoint':b.checkpoint,'stats':b.stats,'error':b.error,
            'resume_count':b.resume_count,'created_at':b.created_at,'updated_at':b.updated_at,
            'published_at':b.published_at}
def conflict_dict(c):
    return {'id':c.id,'build_id':c.build_id,'reader_id':c.reader_id,'feature':c.feature,
            'candidates':c.candidates,'status':c.status,'chosen_source':c.chosen_source,
            'chosen_value':c.chosen_value,'arbitrated_by':c.arbitrated_by,'arbitrated_at':c.arbitrated_at}
def member_dict(m):
    return {'id':m.id,'build_id':m.build_id,'reader_id':m.reader_id,'included':m.included,
            'features':m.features,'path':m.path,'exclude_reason':m.exclude_reason}
def cascade_dict(e):
    return {'id':e.id,'reason':e.reason,'origin_type':e.origin_type,'origin_id':e.origin_id,
            'affected_type':e.affected_type,'affected_id':e.affected_id,'detail':e.detail,'created_at':e.created_at}
