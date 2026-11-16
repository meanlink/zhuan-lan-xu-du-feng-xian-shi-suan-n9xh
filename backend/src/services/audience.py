"""可复用人群方案：版本编排、固定引用、级联失效、裁定发布与追查。"""
import time
from fastapi import HTTPException
from sqlalchemy import select
from src.models import (
    Dataset, Job, Report, AudienceScheme, SchemeVersion, SchemeVersionRef,
    AudienceBuild, AudienceMember, FeatureConflict, CascadeEvent,
)
from src.constants.enums import (
    SchemeVersionStatus, RefKind, SetOp, BuildStatus, ConflictStatus, EligibilityStatus,
)
from src.utils.serialization import checksum


# ----------------------------- 方案与版本 -----------------------------------

def create_scheme(db, data, user):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '方案名称去除空格后至少两个字符')
    if db.scalar(select(AudienceScheme).where(AudienceScheme.name == name)):
        raise HTTPException(409, '该人群方案名已存在，请修改名称')
    now = time.time()
    scheme = AudienceScheme(name=name, description=data.description, revision=1,
                            created_by=user.id, created_at=now, updated_at=now)
    db.add(scheme); db.flush()
    version = SchemeVersion(scheme_id=scheme.id, version_no=1,
                            status=SchemeVersionStatus.draft.value,
                            definition=[s.model_dump() for s in data.definition],
                            created_by=user.id, created_at=now)
    db.add(version); db.flush()
    scheme.current_version_id = version.id
    return scheme, version


def _current_draft(db, scheme):
    """返回当前草稿版本；若当前版本已发布则新建下一版草稿。"""
    cur = db.get(SchemeVersion, scheme.current_version_id) if scheme.current_version_id else None
    if cur and cur.status == SchemeVersionStatus.draft.value:
        return cur
    next_no = db.scalar(select(SchemeVersion.version_no).where(
        SchemeVersion.scheme_id == scheme.id).order_by(SchemeVersion.version_no.desc())) or 0
    draft = SchemeVersion(scheme_id=scheme.id, version_no=next_no + 1,
                          status=SchemeVersionStatus.draft.value,
                          definition=(cur.definition if cur else []),
                          created_by=scheme.created_by, created_at=time.time())
    db.add(draft); db.flush()
    scheme.current_version_id = draft.id
    return draft


def update_scheme(db, scheme_id, data, user):
    scheme = db.get(AudienceScheme, scheme_id)
    if not scheme:
        raise HTTPException(404, '人群方案不存在')
    if data.revision != scheme.revision:
        raise HTTPException(409, '方案已被他人修改，请刷新后基于最新版本编辑（拒绝覆盖）')
    if data.name is not None:
        name = data.name.strip()
        clash = db.scalar(select(AudienceScheme).where(
            AudienceScheme.name == name, AudienceScheme.id != scheme_id))
        if clash:
            raise HTTPException(409, '该人群方案名已存在，请修改名称')
        scheme.name = name
    if data.description is not None:
        scheme.description = data.description
    draft = _current_draft(db, scheme)
    if data.definition is not None:
        draft.definition = [s.model_dump() for s in data.definition]
    scheme.revision += 1
    scheme.updated_at = time.time()
    db.flush()
    return scheme, draft


def _resolve_refs(db, steps, scheme_id):
    """把编排步骤解析为具体来源，校验存在性，返回 (refs, snapshot)。"""
    refs, snapshot = [], {}
    keys = set()
    for pos, step in enumerate(steps):
        if step['key'] in keys:
            raise HTTPException(422, f"步骤键 {step['key']} 重复，请保持唯一")
        keys.add(step['key'])
        ref = {'position': pos, 'ref_key': step['key'], 'ref_kind': step['kind'],
               'set_op': step['op'], 'ref_dataset_id': None, 'ref_scheme_id': None,
               'ref_version_id': None}
        snap = {'kind': step['kind'], 'op': step['op'], 'label': step.get('label', '')}
        if step['kind'] == RefKind.dataset.value:
            ds = db.get(Dataset, step['ref_id'])
            if not ds:
                raise HTTPException(404, f"步骤 {step['key']} 引用的数据批次不存在")
            ref['ref_dataset_id'] = ds.id
            snap.update({'dataset_id': ds.id, 'name': ds.name, 'checksum': ds.checksum, 'rows': len(ds.records)})
        else:
            target = db.get(AudienceScheme, step['ref_id'])
            if not target:
                raise HTTPException(404, f"步骤 {step['key']} 引用的人群方案不存在")
            published = db.scalar(select(SchemeVersion).where(
                SchemeVersion.scheme_id == target.id,
                SchemeVersion.status == SchemeVersionStatus.published.value
            ).order_by(SchemeVersion.version_no.desc()))
            if not published:
                raise HTTPException(409, f"被引用方案「{target.name}」尚未发布，无法固定引用")
            # 被引用版本必须已有已发布人群，否则引用方即使发布也无法构建
            released_build = db.scalar(select(AudienceBuild).where(
                AudienceBuild.version_id == published.id,
                AudienceBuild.status == BuildStatus.released.value))
            if not released_build:
                raise HTTPException(
                    409, f"被引用方案「{target.name}」v{published.version_no} 尚无已发布人群，请先完成其构建与裁定发布")
            ref['ref_scheme_id'] = target.id
            ref['ref_version_id'] = published.id
            snap.update({'scheme_id': target.id, 'version_id': published.id,
                         'version_no': published.version_no, 'name': target.name,
                         'checksum': published.version_checksum})
        refs.append(ref)
        snapshot[step['key']] = snap
    return refs, snapshot


def _detect_cycle(db, version_id, edges_by_version, same_scheme_versions=None):
    """检测发布 version_id 是否造成跨方案循环引用。

    正向边 edges: version -> 它直接引用的版本。
    环的典型形态：草稿 D 引用方案 Y 的版本，而 Y（沿引用链向下）又引用了
    D 所属方案的某个版本——于是 D 与 Y 相互依赖。由于草稿尚未发布、其自身 id
    不会出现在任何已存在的引用边里，无法靠「回到 D 自己」识别，需要借助
    same_scheme_versions：与 D 同属一个方案的全部版本 id 集合。
    判定：从 D 的任一引用目标沿引用边可达同方案版本，即成环。自引用单独拦截。
    """
    same_scheme_versions = same_scheme_versions or set()
    targets = edges_by_version.get(version_id, set())
    if version_id in targets:
        return True  # 直接自引用

    def reaches_same_scheme(start):
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            for nxt in edges_by_version.get(cur, ()):  # nxt = cur 引用的版本
                if nxt in same_scheme_versions:
                    return True
                if nxt not in seen:
                    seen.add(nxt); stack.append(nxt)
        return False

    return any(reaches_same_scheme(t) for t in targets)


def publish_scheme(db, scheme_id, revision, user):
    scheme = db.get(AudienceScheme, scheme_id)
    if not scheme:
        raise HTTPException(404, '人群方案不存在')
    if revision != scheme.revision:
        raise HTTPException(409, '方案已被他人修改，请刷新后基于最新版本发布（拒绝覆盖）')
    draft = _current_draft(db, scheme)
    if draft.status != SchemeVersionStatus.draft.value:
        draft = _current_draft(db, scheme)
    steps = draft.definition or []
    if not steps:
        raise HTTPException(422, '至少编排一个引用步骤后才能发布')
    if steps[0]['op'] != SetOp.union.value:
        raise HTTPException(422, '首个步骤必须是并集，以建立基础人群')

    refs, snapshot = _resolve_refs(db, steps, scheme.id)

    # 构建全量版本依赖边，检测循环引用
    all_refs = db.scalars(select(SchemeVersionRef)).all()
    edges = {}
    for r in all_refs:
        if r.ref_version_id:
            edges.setdefault(r.version_id, set()).add(r.ref_version_id)
    edges[draft.id] = {r['ref_version_id'] for r in refs if r['ref_version_id']}
    same_scheme_versions = set(db.scalars(select(SchemeVersion.id).where(
        SchemeVersion.scheme_id == scheme.id)).all())
    if _detect_cycle(db, draft.id, edges, same_scheme_versions):
        raise HTTPException(422, '检测到循环引用，已拒绝发布；人群方案引用不允许成环')

    # 固化草稿为不可变发布版本
    draft.status = SchemeVersionStatus.published.value
    draft.snapshot = snapshot
    draft.published_at = time.time()
    draft.version_checksum = checksum({'definition': steps, 'snapshot': snapshot})
    for r in db.scalars(select(SchemeVersionRef).where(SchemeVersionRef.version_id == draft.id)):
        db.delete(r)
    db.flush()
    for ref in refs:
        db.add(SchemeVersionRef(version_id=draft.id, **ref))
    scheme.current_version_id = draft.id
    scheme.revision += 1
    scheme.updated_at = time.time()
    db.flush()

    # 规则更新：使本方案旧版本构建与下游依赖人群、试验失效
    _invalidate_old_versions(db, scheme, draft.id, user)
    return scheme, draft


# ----------------------------- 级联失效 -------------------------------------

def _log_cascade(db, reason, origin_type, origin_id, affected_type, affected_id, detail=None):
    db.add(CascadeEvent(reason=reason, origin_type=origin_type, origin_id=origin_id,
                        affected_type=affected_type, affected_id=affected_id,
                        detail=detail or {}, created_at=time.time()))


def _invalidate_job_and_reports(db, job, reason):
    """停用试验的批准/分发资格；已生成的归档资料保留不删。"""
    if job.eligibility != EligibilityStatus.invalidated.value:
        job.eligibility = EligibilityStatus.invalidated.value
        job.invalidate_reason = reason
        _log_cascade(db, reason, 'scheme_version', job.audience_build_id or 0, 'job', job.id)
    for rep in db.scalars(select(Report).where(Report.job_id == job.id, Report.enabled.is_(True))):
        rep.enabled = False
        _log_cascade(db, reason, 'job', job.id, 'report', rep.id)


def _invalidate_version_cascade(db, version, reason, seen=None):
    """从一个失效版本出发，沿引用边级联失效下游版本、构建、试验与分发。"""
    seen = seen or set()
    if version.id in seen or version.status == SchemeVersionStatus.invalid.value:
        return
    seen.add(version.id)
    version.status = SchemeVersionStatus.invalid.value
    version.invalidate_reason = reason
    version.invalidated_at = time.time()
    _log_cascade(db, reason, 'scheme_version', version.id, 'scheme_version', version.id)

    for build in db.scalars(select(AudienceBuild).where(AudienceBuild.version_id == version.id)):
        if build.status in (BuildStatus.released.value, BuildStatus.ready.value,
                            BuildStatus.awaiting_arbitration.value, BuildStatus.running.value,
                            BuildStatus.queued.value):
            build.status = BuildStatus.invalid.value
            build.error = reason
            _log_cascade(db, reason, 'scheme_version', version.id, 'build', build.id)
            for job in db.scalars(select(Job).where(Job.audience_build_id == build.id)):
                _invalidate_job_and_reports(db, job, reason)

    # 下游：引用了该版本的其它已发布版本
    dependents = db.scalars(select(SchemeVersionRef).where(
        SchemeVersionRef.ref_version_id == version.id)).all()
    for ref in dependents:
        downstream = db.get(SchemeVersion, ref.version_id)
        if downstream and downstream.status == SchemeVersionStatus.published.value:
            _invalidate_version_cascade(db, downstream, reason, seen)


def _invalidate_old_versions(db, scheme, keep_version_id, user):
    reason = f"方案「{scheme.name}」规则更新，旧引用快照已失效"
    old = db.scalars(select(SchemeVersion).where(
        SchemeVersion.scheme_id == scheme.id,
        SchemeVersion.id != keep_version_id,
        SchemeVersion.status == SchemeVersionStatus.published.value)).all()
    for version in old:
        _invalidate_version_cascade(db, version, reason)


def invalidate_by_dataset(db, dataset, reason=None):
    """数据批次层面的上游规则更新入口（批次记录被替换/重导）。"""
    reason = reason or f"数据批次「{dataset.name}」规则更新，固定样本快照失效"
    refs = db.scalars(select(SchemeVersionRef).where(
        SchemeVersionRef.ref_dataset_id == dataset.id)).all()
    seen = set()
    for ref in refs:
        version = db.get(SchemeVersion, ref.version_id)
        if version and version.status == SchemeVersionStatus.published.value:
            _invalidate_version_cascade(db, version, reason, seen)


# ----------------------------- 构建批次 -------------------------------------

def start_build(db, scheme_id, user):
    scheme = db.get(AudienceScheme, scheme_id)
    if not scheme:
        raise HTTPException(404, '人群方案不存在')
    version = db.scalar(select(SchemeVersion).where(
        SchemeVersion.scheme_id == scheme.id,
        SchemeVersion.status == SchemeVersionStatus.published.value
    ).order_by(SchemeVersion.version_no.desc()))
    if not version:
        raise HTTPException(409, '方案尚无已发布版本，不能构建人群')
    # 幂等：固定版本的批次键，重复发起沿用同一批次，不重复建批
    batch_key = f"scheme-{scheme.id}-v{version.id}"
    existing = db.scalar(select(AudienceBuild).where(AudienceBuild.batch_key == batch_key))
    if existing:
        if existing.status == BuildStatus.invalid.value:
            raise HTTPException(409, '该批次因上游规则更新已失效，请在新版本上重新发布后构建')
        return existing, False
    build = AudienceBuild(scheme_id=scheme.id, version_id=version.id, batch_key=batch_key,
                          status=BuildStatus.queued.value, checkpoint={}, stats={},
                          created_by=user.id, created_at=time.time(), updated_at=time.time())
    db.add(build); db.flush()
    return build, True


def enqueue_build(build_id):
    try:
        from redis import Redis
        from src.config.settings import REDIS_URL
        r = Redis.from_url(REDIS_URL)
        r.rpush('audience:queue', build_id)
        r.close()
    except Exception:
        pass  # 数据库 queued 状态作为持久兜底


def arbitrate(db, build_id, conflict_id, chosen_source, user):
    build = db.get(AudienceBuild, build_id)
    if not build:
        raise HTTPException(404, '构建批次不存在')
    if build.status == BuildStatus.invalid.value:
        raise HTTPException(409, '批次已失效，裁定不再生效')
    conflict = db.get(FeatureConflict, conflict_id)
    if not conflict or conflict.build_id != build_id:
        raise HTTPException(404, '特征冲突不存在')
    if conflict.status == ConflictStatus.resolved.value:
        raise HTTPException(409, '该冲突已裁定')
    chosen = next((c for c in conflict.candidates if c['source'] == chosen_source), None)
    if not chosen:
        raise HTTPException(422, '选定来源不在候选范围内')
    conflict.status = ConflictStatus.resolved.value
    conflict.chosen_source = chosen_source
    conflict.chosen_value = float(chosen['value'])
    conflict.arbitrated_by = user.email
    conflict.arbitrated_at = time.time()
    # 定稿到成员特征
    member = db.scalar(select(AudienceMember).where(
        AudienceMember.build_id == build_id, AudienceMember.reader_id == conflict.reader_id))
    if member:
        feats = dict(member.features or {})
        feats[conflict.feature] = float(chosen['value'])
        feats[conflict.feature + '__source'] = chosen_source
        member.features = feats
    db.flush()
    # 全部裁定完成才进入可发布；同步刷新统计，避免残留旧的待裁定计数
    pending = db.query(FeatureConflict).filter_by(
        build_id=build_id, status=ConflictStatus.pending.value).count()
    stats = dict(build.stats or {})
    stats['conflicts_pending'] = pending
    build.stats = stats
    if pending == 0 and build.status == BuildStatus.awaiting_arbitration.value:
        build.status = BuildStatus.ready.value
    build.updated_at = time.time()
    return conflict


def release_build(db, build_id, user):
    build = db.get(AudienceBuild, build_id)
    if not build:
        raise HTTPException(404, '构建批次不存在')
    if build.status == BuildStatus.invalid.value:
        raise HTTPException(409, '批次已失效，不能发布')
    pending = db.query(FeatureConflict).filter_by(
        build_id=build_id, status=ConflictStatus.pending.value).count()
    if pending:
        raise HTTPException(409, f'仍有 {pending} 项特征冲突待裁定，全部裁定完成才能发布')
    if build.status != BuildStatus.ready.value:
        raise HTTPException(409, '仅就绪批次可发布为可试验人群')
    build.status = BuildStatus.released.value
    build.published_at = time.time()
    build.updated_at = time.time()
    return build


# ----------------------------- 追查 -----------------------------------------

def member_trace(db, build_id, reader_id):
    member = db.scalar(select(AudienceMember).where(
        AudienceMember.build_id == build_id, AudienceMember.reader_id == reader_id))
    if not member:
        raise HTTPException(404, '该读者不在本批次范围内')
    conflicts = db.scalars(select(FeatureConflict).where(
        FeatureConflict.build_id == build_id, FeatureConflict.reader_id == reader_id)).all()
    return {
        'reader_id': member.reader_id, 'included': member.included,
        'features': member.features, 'path': member.path,
        'exclude_reason': member.exclude_reason,
        'conflicts': [{'id': c.id, 'feature': c.feature, 'status': c.status,
                       'candidates': c.candidates, 'chosen_source': c.chosen_source} for c in conflicts],
    }


def affected_experiments(db, scheme_id):
    """返回某方案所有受影响试验及其资格、分发状态。"""
    builds = db.scalars(select(AudienceBuild).where(AudienceBuild.scheme_id == scheme_id)).all()
    out = []
    for b in builds:
        for job in db.scalars(select(Job).where(Job.audience_build_id == b.id)):
            reports = db.scalars(select(Report).where(Report.job_id == job.id)).all()
            out.append({
                'job_id': job.id, 'job_name': job.name, 'build_id': b.id,
                'build_status': b.status, 'approved': job.approved,
                'eligibility': job.eligibility, 'invalidate_reason': job.invalidate_reason,
                'reports': [{'id': r.id, 'name': r.name, 'enabled': r.enabled} for r in reports],
            })
    return out
