from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import (
    AudienceScheme, SchemeVersion, SchemeVersionRef, AudienceBuild,
    AudienceMember, FeatureConflict, CascadeEvent,
)
from src.constants.enums import BuildStatus
from src.schemas.audience import SchemeCreate, SchemeUpdate, SchemePublish, ArbitrationInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import audience
from src.services.audit import record
from src.utils.serialization import (
    scheme_dict, version_dict, build_dict, conflict_dict, member_dict, cascade_dict,
)
router = APIRouter(prefix='/audience')


@router.get('/schemes')
def list_schemes(db=Depends(get_db), u=Depends(current_user)):
    out = []
    for s in db.scalars(select(AudienceScheme).order_by(AudienceScheme.id.desc())):
        v = db.get(SchemeVersion, s.current_version_id) if s.current_version_id else None
        out.append(scheme_dict(s, v))
    return out


@router.post('/schemes', status_code=201)
def create_scheme(data: SchemeCreate, db=Depends(get_db), u=Depends(can_write)):
    s, v = audience.create_scheme(db, data, u)
    record(db, u.email, 'audience.scheme.create', {'id': s.id})
    db.commit()
    return scheme_dict(db.get(AudienceScheme, s.id), db.get(SchemeVersion, v.id))


@router.get('/schemes/{id}')
def get_scheme(id: int, db=Depends(get_db), u=Depends(current_user)):
    s = db.get(AudienceScheme, id)
    if not s:
        raise HTTPException(404, '人群方案不存在')
    versions = db.scalars(select(SchemeVersion).where(
        SchemeVersion.scheme_id == id).order_by(SchemeVersion.version_no.desc())).all()
    refs = db.scalars(select(SchemeVersionRef).where(
        SchemeVersionRef.version_id.in_([v.id for v in versions]))).all() if versions else []
    builds = db.scalars(select(AudienceBuild).where(
        AudienceBuild.scheme_id == id).order_by(AudienceBuild.id.desc())).all()
    return {
        **scheme_dict(s, db.get(SchemeVersion, s.current_version_id)),
        'versions': [version_dict(v) for v in versions],
        'refs': [{'version_id': r.version_id, 'position': r.position, 'ref_key': r.ref_key,
                  'ref_kind': r.ref_kind, 'set_op': r.set_op, 'ref_dataset_id': r.ref_dataset_id,
                  'ref_scheme_id': r.ref_scheme_id, 'ref_version_id': r.ref_version_id} for r in refs],
        'builds': [build_dict(b) for b in builds],
    }


@router.put('/schemes/{id}')
def update_scheme(id: int, data: SchemeUpdate, db=Depends(get_db), u=Depends(can_write)):
    s, v = audience.update_scheme(db, id, data, u)
    record(db, u.email, 'audience.scheme.update', {'id': id, 'revision': s.revision})
    db.commit()
    return scheme_dict(db.get(AudienceScheme, id), db.get(SchemeVersion, v.id))


@router.post('/schemes/{id}/publish')
def publish_scheme(id: int, data: SchemePublish, db=Depends(get_db), u=Depends(can_write)):
    s, v = audience.publish_scheme(db, id, data.revision, u)
    record(db, u.email, 'audience.scheme.publish', {'id': id, 'version_id': v.id, 'version_no': v.version_no})
    db.commit()
    return scheme_dict(db.get(AudienceScheme, id), db.get(SchemeVersion, v.id))


# ----------------------------- 构建批次 -------------------------------------

@router.post('/schemes/{id}/builds', status_code=201)
def start_build(id: int, db=Depends(get_db), u=Depends(can_write)):
    build, created = audience.start_build(db, id, u)
    record(db, u.email, 'audience.build.start' if created else 'audience.build.reuse',
           {'id': build.id, 'batch_key': build.batch_key, 'created': created})
    db.commit()
    if created:
        audience.enqueue_build(build.id)
    return build_dict(db.get(AudienceBuild, build.id))


@router.post('/builds/{id}/resume')
def resume_build(id: int, db=Depends(get_db), u=Depends(can_write)):
    build = db.get(AudienceBuild, id)
    if not build:
        raise HTTPException(404, '构建批次不存在')
    if build.status == BuildStatus.invalid.value:
        raise HTTPException(409, '批次已失效，无法恢复')
    if build.status not in (BuildStatus.failed.value, BuildStatus.queued.value, BuildStatus.running.value):
        raise HTTPException(409, '该批次当前状态无需恢复')
    record(db, u.email, 'audience.build.resume', {'id': id, 'resume_count': build.resume_count})
    db.commit()
    audience.enqueue_build(id)  # 沿用原批次，不重复建批
    return build_dict(db.get(AudienceBuild, id))


@router.post('/builds/{id}/release')
def release_build(id: int, db=Depends(get_db), u=Depends(admin_only)):
    audience.release_build(db, id, u)
    record(db, u.email, 'audience.build.release', {'id': id})
    db.commit()
    return build_dict(db.get(AudienceBuild, id))


@router.get('/builds/{id}')
def get_build(id: int, db=Depends(get_db), u=Depends(current_user)):
    build = db.get(AudienceBuild, id)
    if not build:
        raise HTTPException(404, '构建批次不存在')
    conflicts = db.scalars(select(FeatureConflict).where(
        FeatureConflict.build_id == id).order_by(FeatureConflict.id)).all()
    members = db.scalars(select(AudienceMember).where(
        AudienceMember.build_id == id).order_by(AudienceMember.reader_id).limit(500)).all()
    included_count = db.query(AudienceMember).filter_by(build_id=id, included=True).count()
    return {
        **build_dict(build),
        'included_count': included_count,
        'conflicts': [conflict_dict(c) for c in conflicts],
        'members': [member_dict(m) for m in members],
    }


# ----------------------------- 裁定 -----------------------------------------

@router.post('/builds/{id}/conflicts/{cid}/arbitrate')
def arbitrate(id: int, cid: int, data: ArbitrationInput, db=Depends(get_db), u=Depends(can_write)):
    audience.arbitrate(db, id, cid, data.chosen_source, u)
    record(db, u.email, 'audience.conflict.arbitrate',
           {'build_id': id, 'conflict_id': cid, 'chosen_source': data.chosen_source})
    db.commit()
    return conflict_dict(db.get(FeatureConflict, cid))


# ----------------------------- 追查 -----------------------------------------

@router.get('/builds/{id}/trace/{reader_id}')
def trace_member(id: int, reader_id: str, db=Depends(get_db), u=Depends(current_user)):
    return audience.member_trace(db, id, reader_id)


@router.get('/schemes/{id}/experiments')
def affected_experiments(id: int, db=Depends(get_db), u=Depends(current_user)):
    if not db.get(AudienceScheme, id):
        raise HTTPException(404, '人群方案不存在')
    return audience.affected_experiments(db, id)


@router.get('/cascades')
def cascades(db=Depends(get_db), u=Depends(current_user)):
    return [cascade_dict(e) for e in db.scalars(
        select(CascadeEvent).order_by(CascadeEvent.id.desc()).limit(100))]
