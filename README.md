# 专栏续读风险试算

分类与阈值选择的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 人群方案（可复用编排、固定引用版本、交集/并集/排除、循环引用拒绝、断点构建、特征冲突裁定、级联失效）→ 参数化分析（异步 Python worker，可绑定已发布人群）→ 结果复核（指标、图形、明细、解释、批准与资格）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；人群域含 AudienceScheme/SchemeVersion/SchemeVersionRef/AudienceBuild/AudienceMember/FeatureConflict/CascadeEvent；辅助 User、Audit、Delivery。

## 可复用人群方案
- 方案以草稿/版本管理，发布后版本不可变，固定每个引用的批次指纹或被引用方案的发布版本与样本快照；再次编辑生成新草稿，并发修改靠 `revision` 乐观锁拒绝覆盖（409）。
- 编排步骤支持引用数据批次或其他人群方案，运算为并集（首步必须并集）、交集、排除；发布前在版本依赖图上检测循环引用（含自引用与跨方案折回环），成环拒绝。
- 构建按固定版本产生幂等批次（`scheme-{id}-v{version}`），重复发起沿用同一批次不重复建批；逐步骤提交并记录检查点，worker 中断后从已落库部分幂等重放恢复，失败重试不新建批次。
- 同一读者在一个批次只保留一份；不同来源同名特征取值冲突列为待裁定，逐项选定采用来源，全部裁定完成才允许由负责人发布为可试验人群。
- 上游规则更新（方案发布新版本或数据批次重导）沿引用边级联失效下游版本、构建与试验：试验 `eligibility` 置为 invalidated，停用其批准与新建分发资格、暂停启用中的分发计划；计算结果与已生成归档资料留存，旧计算晚回不恢复失效资格，全过程写入 CascadeEvent 可追查。
- 页面「人群方案」（#/audience）支持编排、构建、恢复、裁定、发布，并可追查任一读者的纳入/排除路径与方案下受影响试验。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18207；后端文档 http://localhost:19207/docs；数据库宿主端口 17707。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；MySQL 8.0；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed；人群域另有 SchemeVersionStatus、RefKind、SetOp、BuildStatus、ConflictStatus、EligibilityStatus。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=reader-risk；FRONTEND_PORT=18207；BACKEND_PORT=19207；DB_PORT=17707；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1008/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
