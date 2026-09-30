# 岗位发现层路线图（个人工作机会管理器）

> 本文是本 fork 的项目全貌与迭代计划。产品与架构事实源仍见 AGENTS.md §4；
> 发现层领域契约见 [ADR 0013](decisions/0013-job-discovery-candidate-pool.md)。

## 1. 项目定位

以 OfferPilot 为底座的**本地化通用工作机会管理器**（产品名 **CareerDeck · 求职驾驶舱**），
补齐"投递之前"的缺口，串成完整闭环：

```
发现岗位（多源） → AI 评分推荐 → 决定投递（晋升） → 投递→终态全链路追踪 → 每步建议
     ↑ 新增                                    OfferPilot 既有能力
```

产品口径（2026-09-30 确认）：**对外是通用应用，不内置任何个人数据**。
个人简历、地域要求、方向、薪资期望、红线由用户在使用时自行导入/填写
（`discovery_profiles` 画像 + 简历库），评分与推荐围绕该画像展开。

## 2. 组件全景

| 组件 | 位置 | 职责 | 状态 |
|---|---|---|---|
| offerPilot fork（本仓库） | github.com/costaWHLG/career-deck | 管理底座：投递看板、JD 版本、面试、Offer、谈薪、Pilot AI；发现层在 `src/offerpilot/discovery/` | 发现层 P1 已交付 |
| mcp-jobs fork | github.com/costaWHLG/mcp-jobs | 招聘平台职位查询 MCP（猎聘/Boss直聘/智联/51job），P3 crawler adapter 的数据源桥 | 城市码已修；反爬 cookie 预热待做 |
| 求职方法论 | 七维评分口径已并入 ADR 0013 §2.2 | 评分权重/评级/红线规则的产品事实源 | 已固化 |

## 3. 发现层数据流与边界

```
sources/（唯一抓取边界）
  manual.py      JD 粘贴/结构化投喂（任何路线保留的手动入口）   ✅ P1
  websearch.py   聚合搜索 + 详情页抓取管线                       ⏳ P2
  crawler.py     mcp-jobs 桥（cookie 预热后接入平台爬虫）        ⏳ P3
      │ RawJobPayload（source + source_key + raw 原文宽容保留）
      ▼
normalize.py  同义字段归一 / 缺失置空 / 未知字段进 extra
      ▼
job_candidates 候选池（(source, source_key) 去重；status: new→scored→promoted/discarded）
      ▼
scoring.py（唯一 AI 边界，complete_readonly_draft 只读调用）
  输入 = NormalizedJob + DiscoveryProfile（简历快照/城市/方向/薪资/红线）
  输出 = 七维明细 + 加权总分 + 评级 A/B/C + 逐维理由 + 红线命中
      ▼
promote.py（唯一晋升路径）→ ApplicationCreationService 单一 intake
  → Application(status=pending 待投递, source=discovery) + JD 版本
  → 之后由 OfferPilot 既有全链路接管
```

边界纪律：抓取只在 adapter 内；评分不造假（无 provider 返回 503）；
晋升幂等（键 `discovery-promote-{candidate_id}`）。

## 4. REST 面（P1）

| 端点 | 语义 |
|---|---|
| `POST /api/discovery/candidates` | 投喂（单条或 `{"jobs": [...]}` 批量），宽容摄取、原文入库 |
| `GET /api/discovery/candidates?status=` | 候选池列表 |
| `GET /api/discovery/candidates/{id}` | 候选详情 + 评分记录 |
| `POST /api/discovery/candidates/{id}/score` | AI 评分（依赖 provider 配置） |
| `POST /api/discovery/candidates/{id}/promote` | 转投递（幂等，返回 application_id） |
| `PATCH /api/discovery/candidates/{id}/status` | 状态流转（含 discard） |
| `GET/PUT /api/discovery/profile` | 评分画像（简历快照/城市/方向/薪资/红线） |

## 5. 迭代计划

- [x] **P1**（2026-09-30）：契约 + 手动投喂 + 归一化 + 七维 AI 评分 + 晋升 + REST + 20 项测试
- [ ] **P2**：`websearch` 聚合搜索 adapter（搜索引擎 + 猎聘详情页抓取管线，已验证可行性）；
  发现端点 `POST /api/discovery/search`（关键词/城市 → 拉取 → 入池）
- [ ] **P3**：`crawler` 平台 adapter（mcp-jobs 桥；前置：mcp-jobs cookie 预热突破 IP 级验证墙）；
  批量抓取 → 去重入池
- [ ] **P4**：前端"发现"页（候选池看板、评分卡、一键转投递）；web/src features + services 同步
- [ ] **导入引导**（通用化关键项）：首次使用引导——导入简历 → 填写城市/方向/薪资期望/红线 →
  写入 `discovery_profiles`；挂载到既有 `onboarding` 步骤清单（与 configure_ai、
  create_primary_resume 并列）
- [ ] **收尾**：评分链路真实 provider 验收（AGENTS.md §7 `--real-ai`）；
  发现层提 PR 回馈上游 offercontext/offerPilot（待 P2-P4 成熟后）

## 6. 开发与验证

```bash
uv sync                       # 依赖（如遇镜像 403：uv sync --index-url https://pypi.org/simple）
uv run pytest tests/test_discovery_*.py   # 发现层定向测试
uv run ruff check src/offerpilot/discovery/
uv run mypy src/offerpilot/discovery/
bash scripts/release-gate.sh  # 发布前完整门禁
```

注意：`uv sync --index-url` 会改写 uv.lock 的 registry 地址，勿提交该副作用。

## 7. 隐私边界

- **仓库公开内容**：代码、契约、方法论、市场研究（如 [research/job-market-ai-2026-09.md](../research/job-market-ai-2026-09.md)）、
  测试夹具（虚构数据）。
- **永不入库**：个人简历、期望薪资、红线、候选与投递过程数据、任何真实公司沟通记录。
  这些只存在用户本地 SQLite（用户数据目录）与用户自行维护的本地文件中。
- 产品以"通用应用"交付：一切个性化数据由用户使用时导入，引导流程见 §5"导入引导"。
