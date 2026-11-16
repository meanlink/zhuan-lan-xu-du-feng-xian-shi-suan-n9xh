from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class AudienceScheme(Base):
    """可复用人群方案：头表承载名称、乐观锁版本号与当前工作版本。"""
    __tablename__ = 'audience_schemes'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(String(500), default='')
    current_version_id: Mapped[int | None] = mapped_column(ForeignKey('scheme_versions.id'), nullable=True)
    # 乐观锁：并发修改必须携带相同 revision，否则拒绝覆盖新版本
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)


class SchemeVersion(Base):
    """方案版本：发布后不可变，固定引用版本与样本快照，构建只认版本。"""
    __tablename__ = 'scheme_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey('audience_schemes.id'))
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default='draft')
    # 有序编排步骤：[{key, kind, dataset_id/scheme_id, op: union/intersect/exclude}]
    definition: Mapped[list] = mapped_column(JSON, default=list)
    # 发布时刻固化的引用指纹：{key: {kind, dataset_id/version_id, checksum, rows}}
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    version_checksum: Mapped[str] = mapped_column(String(64), default='')
    invalidate_reason: Mapped[str] = mapped_column(String(500), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    invalidated_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    __table_args__ = (UniqueConstraint('scheme_id', 'version_no', name='uq_scheme_version_no'),)


class SchemeVersionRef(Base):
    """版本引用关系：用于循环引用检测与上游级联失效追查。"""
    __tablename__ = 'scheme_version_refs'
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('scheme_versions.id'))
    position: Mapped[int] = mapped_column(Integer)
    ref_key: Mapped[str] = mapped_column(String(40))
    ref_kind: Mapped[str] = mapped_column(String(16))          # dataset / scheme
    set_op: Mapped[str] = mapped_column(String(16))           # union / intersect / exclude
    ref_dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    ref_scheme_id: Mapped[int | None] = mapped_column(ForeignKey('audience_schemes.id'), nullable=True)
    # 发布时固定的方案版本；草稿期为空，发布解析后写入
    ref_version_id: Mapped[int | None] = mapped_column(ForeignKey('scheme_versions.id'), nullable=True)


class AudienceBuild(Base):
    """人群构建批次：固定方案版本，断点续算，重试沿用同一批次。"""
    __tablename__ = 'audience_builds'
    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey('audience_schemes.id'))
    version_id: Mapped[int] = mapped_column(ForeignKey('scheme_versions.id'))
    # 幂等批次键：同一版本重复发起构建返回同一批次，不重复建批
    batch_key: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(24), default='queued')
    # 断点：{step_index, stage}，已处理步骤及其结果落在成员/冲突表
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    resume_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class AudienceMember(Base):
    """构建成员：同一读者在同一批次只保留一份，记录纳入/排除路径。"""
    __tablename__ = 'audience_members'
    id: Mapped[int] = mapped_column(primary_key=True)
    build_id: Mapped[int] = mapped_column(ForeignKey('audience_builds.id'))
    reader_id: Mapped[str] = mapped_column(String(80))
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    # 特征采用值（裁定后定稿），含来源标注
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    # 纳入/排除路径，如 ["union:批次A", "intersect:方案B#3", "exclude:批次C"]
    path: Mapped[list] = mapped_column(JSON, default=list)
    exclude_reason: Mapped[str] = mapped_column(String(200), default='')
    __table_args__ = (UniqueConstraint('build_id', 'reader_id', name='uq_build_reader'),)


class FeatureConflict(Base):
    """同一读者同一特征在不同来源取值冲突：待裁定，选定采用来源。"""
    __tablename__ = 'feature_conflicts'
    id: Mapped[int] = mapped_column(primary_key=True)
    build_id: Mapped[int] = mapped_column(ForeignKey('audience_builds.id'))
    reader_id: Mapped[str] = mapped_column(String(80))
    feature: Mapped[str] = mapped_column(String(60))
    # 候选值：[{source: 步骤键, source_label, value}]
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    chosen_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    chosen_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    arbitrated_by: Mapped[str] = mapped_column(String(150), default='')
    arbitrated_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    __table_args__ = (UniqueConstraint('build_id', 'reader_id', 'feature', name='uq_build_reader_feature'),)


class CascadeEvent(Base):
    """上游规则更新引发的级联失效记录，用于追查受影响方案、人群与试验。"""
    __tablename__ = 'cascade_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    reason: Mapped[str] = mapped_column(String(300))
    origin_type: Mapped[str] = mapped_column(String(24))       # scheme_version / dataset
    origin_id: Mapped[int] = mapped_column(Integer)
    affected_type: Mapped[str] = mapped_column(String(24))     # scheme_version/build/job/report
    affected_id: Mapped[int] = mapped_column(Integer)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Double)
