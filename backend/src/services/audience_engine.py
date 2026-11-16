"""人群构建引擎：固定版本快照上的集合运算、读者去重、特征冲突与断点续算。"""
import time
from fastapi import HTTPException
from sqlalchemy import select, delete
from src.models import (
    Dataset, AudienceScheme, SchemeVersion, SchemeVersionRef,
    AudienceBuild, AudienceMember, FeatureConflict,
)
from src.constants.enums import BuildStatus, ConflictStatus, RefKind, SetOp
from src.utils.serialization import checksum


def _source_label(step):
    if step['kind'] == RefKind.dataset.value:
        return f"批次#{step['ref_id']}"
    return f"方案#{step['ref_id']}"


def load_source(db, step, fixed_ref_version_id=None):
    """返回 {reader_id: {features: {...}}}，来源在发布时已固定为不可变快照。

    引用其他方案时严格使用发布时固化的 fixed_ref_version_id，不动态选取最新版本，
    以保证同一方案版本的构建结果可复现、不随上游后续发布而漂移。
    """
    readers = {}
    if step['kind'] == RefKind.dataset.value:
        ds = db.get(Dataset, step['ref_id'])
        if not ds:
            raise HTTPException(409, f"来源数据批次 #{step['ref_id']} 已不存在")
        from src.services.business import FEATURES
        for row in ds.records:
            rid = str(row.get('reader_id'))
            readers[rid] = {'features': {f: float(row[f]) for f in FEATURES if f in row}}
        return readers, ds.name, checksum(ds.records)
    # 引用其他方案：固定到发布时解析的版本，取该版本已发布人群的成员
    if not fixed_ref_version_id:
        raise HTTPException(409, f"步骤 {step['key']} 缺少固定引用版本，无法构建")
    ref_version = db.get(SchemeVersion, fixed_ref_version_id)
    if not ref_version:
        raise HTTPException(409, f"步骤 {step['key']} 引用的方案版本已不存在")
    build = db.scalar(select(AudienceBuild).where(
        AudienceBuild.version_id == fixed_ref_version_id,
        AudienceBuild.status == BuildStatus.released.value
    ).order_by(AudienceBuild.id.desc()))
    if not build:
        raise HTTPException(409, f"步骤 {step['key']} 引用的方案版本尚无已发布人群，无法引用")
    for m in db.scalars(select(AudienceMember).where(
            AudienceMember.build_id == build.id, AudienceMember.included.is_(True))):
        readers[m.reader_id] = {'features': dict(m.features or {})}
    scheme = db.get(AudienceScheme, step['ref_id'])
    return readers, scheme.name if scheme else f"方案#{step['ref_id']}", build.stats.get('members_checksum', '')


def _record_conflict(db, build_id, reader_id, feature, candidates):
    """登记或更新特征冲突，候选来源去重，状态保持待裁定。"""
    existing = db.scalar(select(FeatureConflict).where(
        FeatureConflict.build_id == build_id,
        FeatureConflict.reader_id == reader_id,
        FeatureConflict.feature == feature))
    merged = {}
    for c in candidates:
        merged[c['source']] = c
    if existing:
        for c in existing.candidates:
            merged.setdefault(c['source'], c)
        existing.candidates = list(merged.values())
        existing.status = ConflictStatus.pending.value
        existing.chosen_source = None
        existing.chosen_value = None
        existing.arbitrated_by = ''
        existing.arbitrated_at = None
        return existing
    conf = FeatureConflict(build_id=build_id, reader_id=reader_id, feature=feature,
                           candidates=list(merged.values()), status=ConflictStatus.pending.value)
    db.add(conf)
    return conf


def _merge_union(db, build, members, step, readers, path_label):
    """并集：新读者纳入；已存在读者保留一份，特征取值冲突列为待裁定。"""
    for rid, payload in readers.items():
        if rid not in members:
            members[rid] = {'features': dict(payload['features']), 'path': [path_label], 'included': True}
            continue
        cur = members[rid]
        cur['path'].append(path_label)
        for feat, val in payload['features'].items():
            if feat not in cur['features']:
                cur['features'][feat] = val
            elif float(cur['features'][feat]) != float(val):
                _record_conflict(db, build.id, rid, feat, [
                    {'source': f"{step['key']}:cur", 'source_label': '当前已合并集合', 'value': float(cur['features'][feat])},
                    {'source': step['key'], 'source_label': _source_label(step), 'value': float(val)},
                ])


def _apply_intersect(members, readers, path_label):
    """交集：仅保留同时出现在来源中的读者，记录交集路径。"""
    for rid in list(members.keys()):
        if rid in readers:
            members[rid]['path'].append(path_label)
        else:
            del members[rid]


def _apply_exclude(members, readers, path_label, step):
    """排除：来源命中的读者移出最终集合，保留排除原因与路径以便追查。"""
    for rid in list(members.keys()):
        if rid in readers:
            members[rid]['included'] = False
            members[rid]['path'].append(path_label)
            members[rid]['exclude_reason'] = f"被 {_source_label(step)} 排除"


def _persist_members(db, build, members):
    """把内存成员状态落库；同一读者唯一约束保证只留一份。

    交集会从内存集合移除读者、排除会把读者标记为不纳入，二者都需同步删除
    此前已落库、但当前已不属于最终集合的成员行，避免残留漏追查。
    """
    live_ids = set(members.keys())
    for stale in db.scalars(select(AudienceMember).where(AudienceMember.build_id == build.id)):
        if stale.reader_id not in live_ids:
            db.delete(stale)
    for rid, state in members.items():
        existing = db.scalar(select(AudienceMember).where(
            AudienceMember.build_id == build.id, AudienceMember.reader_id == rid))
        if existing:
            existing.features = state['features']
            existing.path = state['path']
            existing.included = state['included']
            existing.exclude_reason = state.get('exclude_reason', '')
        else:
            db.add(AudienceMember(build_id=build.id, reader_id=rid, included=state['included'],
                                  features=state['features'], path=state['path'],
                                  exclude_reason=state.get('exclude_reason', '')))
    db.flush()


def _load_members(db, build):
    members = {}
    for m in db.scalars(select(AudienceMember).where(AudienceMember.build_id == build.id)):
        members[m.reader_id] = {'features': dict(m.features or {}), 'path': list(m.path or []),
                                'included': m.included, 'exclude_reason': m.exclude_reason or ''}
    return members


def run_build(db, build):
    """执行（或断点续算）一个构建批次。返回构建状态。失效批次拒绝计算。"""
    version = db.get(SchemeVersion, build.version_id)
    if build.status == BuildStatus.invalid.value:
        return build.status
    if version.status == 'invalid':
        build.status = BuildStatus.invalid.value
        build.error = '引用的方案版本已失效'
        return build.status

    steps = version.definition or []
    # 失败重试沿用原批次但清空中间产物重新计算。
    # 中断恢复（worker 把 running 回收为 queued）：检查点作为「存在可恢复进度」的凭证，
    # 但集合运算从步骤 0 幂等重放，避免崩溃时部分落库导致成员丢失；每步仍提交以支持再次中断。
    has_checkpoint = build.checkpoint.get('step_index') is not None
    resuming = has_checkpoint and build.status in (
        BuildStatus.running.value, BuildStatus.queued.value)
    if build.status == BuildStatus.failed.value:
        db.execute(delete(AudienceMember).where(AudienceMember.build_id == build.id))
        db.execute(delete(FeatureConflict).where(FeatureConflict.build_id == build.id))
        build.checkpoint = {}
        resuming = False
    build.status = BuildStatus.running.value
    build.updated_at = time.time()
    db.commit()

    # 重放始终从步骤 0 开始；恢复场景先载入已落库成员，重放会幂等补齐缺失读者。
    members = _load_members(db, build) if resuming else {}
    # 载入发布时固化的引用版本，按步骤键定位，确保固定引用不漂移
    fixed_versions = {
        r.ref_key: r.ref_version_id
        for r in db.scalars(select(SchemeVersionRef).where(
            SchemeVersionRef.version_id == version.id))
    }

    for idx in range(len(steps)):
        step = steps[idx]
        readers, label, _ = load_source(db, step, fixed_versions.get(step['key']))
        path_label = f"{step['op']}:{_source_label(step)}({step['key']})"
        if step['op'] == SetOp.union.value:
            _merge_union(db, build, members, step, readers, path_label)
        elif step['op'] == SetOp.intersect.value:
            if not members:
                raise HTTPException(409, '交集步骤前需要先并集纳入一个基础集合')
            _apply_intersect(members, readers, path_label)
        elif step['op'] == SetOp.exclude.value:
            _apply_exclude(members, readers, path_label, step)
        _persist_members(db, build, members)
        build.checkpoint = {'step_index': idx, 'stage': 'step_done'}
        build.updated_at = time.time()
        db.commit()  # 每个步骤提交，崩溃后已处理部分不丢失

    included = {r: s for r, s in members.items() if s['included']}
    conflicts_pending = db.query(FeatureConflict).filter_by(
        build_id=build.id, status=ConflictStatus.pending.value).count()
    build.stats = {
        'total_seen': len(members),
        'included': len(included),
        'excluded': len(members) - len(included),
        'conflicts_pending': conflicts_pending,
        'members_checksum': checksum(sorted(included.keys())),
    }
    build.status = (BuildStatus.awaiting_arbitration.value if conflicts_pending
                    else BuildStatus.ready.value)
    build.updated_at = time.time()
    db.commit()
    return build.status
