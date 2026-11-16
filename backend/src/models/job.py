from sqlalchemy import String, JSON, Double, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    # 可试验人群绑定：为空表示不依赖人群方案的普通分析（兼容既有流程）
    audience_build_id: Mapped[int | None] = mapped_column(ForeignKey('audience_builds.id'), nullable=True)
    # 批准与分发资格：eligible / invalidated。上游规则更新后置为失效
    eligibility: Mapped[str] = mapped_column(String(20), default='eligible')
    invalidate_reason: Mapped[str] = mapped_column(String(500), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
