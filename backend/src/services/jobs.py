import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, AudienceBuild
from src.constants.enums import BuildStatus, EligibilityStatus
from src.services.business import metadata
def create(db, data, user):
    if not db.get(Dataset,data.dataset_id): raise HTTPException(404,'数据批次不存在')
    build=None
    if data.audience_build_id is not None:
        build=db.get(AudienceBuild,data.audience_build_id)
        if not build: raise HTTPException(404,'人群批次不存在')
        if build.status==BuildStatus.invalid.value:
            raise HTTPException(409,'该人群批次已因上游规则更新失效，不能创建试验')
        if build.status!=BuildStatus.released.value:
            raise HTTPException(409,'仅已发布的可试验人群可用于创建试验')
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    j=Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id,
          created_at=time.time(), status='queued', audience_build_id=data.audience_build_id,
          eligibility=EligibilityStatus.eligible.value)
    db.add(j); db.flush()
    return j
def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
