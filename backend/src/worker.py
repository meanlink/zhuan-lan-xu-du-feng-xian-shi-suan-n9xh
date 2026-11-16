import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, AudienceBuild
from src.constants.enums import BuildStatus, EligibilityStatus
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
from src.services.audience_engine import run_build
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        # 依赖人群已失效的试验不再计算，旧计算晚回也不得恢复其资格
        if j.eligibility==EligibilityStatus.invalidated.value:
            j.status='failed'; j.error='依赖人群已失效，试验资格停用'
            j.finished_at=time.time(); record(db,'worker','job.skipped_invalid',{'id':j.id})
            db.commit(); return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            # 计算期间资格被上游规则更新失效：结果保留但不恢复批准/分发资格
            if j.eligibility==EligibilityStatus.invalidated.value:
                record(db,'worker','job.completed_but_invalid',{'id':j.id})
            else:
                record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def execute_build(build_id):
    with Session() as db:
        build=db.get(AudienceBuild,build_id)
        if not build:return
        if build.status==BuildStatus.invalid.value:return
        # 仅排队/运行中/失败（重试沿用原批次）状态进入引擎
        if build.status not in (BuildStatus.queued.value,BuildStatus.running.value,BuildStatus.failed.value):
            return
        if build.status==BuildStatus.failed.value:
            build.resume_count+=1
        try:
            status=run_build(db,build)
            record(db,'worker','audience.build.progress',{'id':build.id,'status':status})
        except Exception as e:
            logging.exception('Audience build failed')
            build.status=BuildStatus.failed.value
            build.error=str(e)[:990]; build.updated_at=time.time()
            record(db,'worker','audience.build.failed',{'id':build.id,'error':build.error})
        db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        # 兜底：未走 Redis 的人群排队任务
        builds=list(db.scalars(select(AudienceBuild.id).where(AudienceBuild.status=='queued').limit(3)))
    for build_id in builds:execute_build(build_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        # 中断的人群构建回到排队，引擎依据检查点续算，不重复建批
        for b in db.scalars(select(AudienceBuild).where(AudienceBuild.status=='running')):
            b.status='queued';record(db,'worker','audience.build.recovered',{'id':b.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            bitem=r.blpop('audience:queue',timeout=1)
            if bitem:execute_build(int(bitem[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
