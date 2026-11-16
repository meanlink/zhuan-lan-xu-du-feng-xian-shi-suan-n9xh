from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class SchemeVersionStatus(str, Enum):
    draft = 'draft'           # 草稿，可反复编辑，不可建批
    published = 'published'   # 已发布，不可变快照，可建批
    invalid = 'invalid'       # 上游规则更新，快照失效
class RefKind(str, Enum):
    dataset = 'dataset'       # 引用数据批次（固定批次与样本）
    scheme = 'scheme'         # 引用其他人群方案（固定版本）
class SetOp(str, Enum):
    union = 'union'           # 并集
    intersect = 'intersect'   # 交集
    exclude = 'exclude'       # 排除
class BuildStatus(str, Enum):
    queued = 'queued'                       # 已建批，等待 worker
    running = 'running'                     # 计算中（可断点续算）
    awaiting_arbitration = 'awaiting_arbitration'  # 存在特征冲突，等待裁定
    ready = 'ready'                         # 全部裁定完成，可发布
    released = 'released'                   # 已发布为可试验人群
    failed = 'failed'                       # 计算失败，可沿原批次重试
    invalid = 'invalid'                     # 上游规则更新导致失效
class ConflictStatus(str, Enum):
    pending = 'pending'     # 待裁定
    resolved = 'resolved'   # 已选定采用来源
class EligibilityStatus(str, Enum):
    eligible = 'eligible'     # 具备批准与分发资格
    invalidated = 'invalidated'  # 上游规则更新，资格失效
