# ADR 0013: 岗位发现层与候选池（Application 创建之前）

- 状态：已接受
- 日期：2026-09-30
- 范围：新增 `discovery` 模块（领域模型、多源接缝、AI 评分、晋升 intake）

## 1. 背景

OfferPilot 当前最早期的领域对象是 `Application`（`POST /api/applications` intake 创建，可带初始 JD）。
真实求职流程在投递之前还有一段：**多源发现岗位 → 评分筛选 → 决定是否投递**。当前产品对这段流程是空白：

- 没有"候选岗位池"概念，发现的岗位只能直接建为 Application 或流失；
- 没有岗位发现数据源的接入边界（爬虫、聚合搜索、手动投喂格式各异）；
- 没有"对照个人简历、地域要求、方向"的 AI 匹配评分与推荐。

用户工作流明确要求：原始输入为个人简历、地域要求、方向；自动查到符合的岗位；
多维打分与推荐；投递→终态全链路追踪（后段本产品已具备）；每一步给高价值建议（Pilot/材料体系已有）。
缺口精确落在**发现层**。

## 2. 决策

新增 `src/offerpilot/discovery/` 模块：Application 创建之前的**候选池**环节。
三个边界一次定死，后续数据源与评分能力只加实现、不动契约：

### 2.1 多源接入边界（数据源宽容）

`discovery/contracts.py` 定义：

- `RawJobPayload`：`source`（来源标识）+ `raw`（原始数据 dict，**宽容保留，不做清洗**）+
  `source_key`（来源内唯一键，用于去重）。
- `NormalizedJob`：规范字段（`company_name`/`position_name`/`job_url`/`city`/`salary_text`/
  `experience_text`/`education_text`/`jd_text`/`published_text`/`extra`）。
- `SourceAdapter` 协议：`name` + `fetch(query) -> list[RawJobPayload]`。
  **所有抓取行为只发生在 adapter 内**；repository 与 API 层不抓取（与
  `application_creation.py`"No fetching, model calls"同一红线）。

`discovery/normalize.py` 负责 `RawJobPayload -> NormalizedJob` 的**容错提取**：
同义字段名归一、缺失置空、原文永远保留于 `raw_payload_json`。上游格式差异全部消化在这一层，
评分层只面对 `NormalizedJob`。首批 adapter：

1. `sources/manual.py`：JD 粘贴/结构化投喂（任何路线都保留的手动入口）；
2. `sources/websearch.py`：聚合搜索 + 详情页抓取（后续阶段）；
3. `sources/crawler.py`：招聘平台爬虫桥（后续阶段，复用 mcp-jobs 修复成果）。

### 2.2 AI 评分边界（打分是 AI）

`discovery/scoring.py`：`CandidateScoringService.score(candidate, profile) -> CandidateScore`。

- 输入：`NormalizedJob` + `DiscoveryProfile`（简历快照 + 城市/方向/薪资期望/红线）；
- 输出：七维分（各 1-5）、加权总分、评级、逐维理由。权重沿用求职系统评分模型：
  技术匹配 25% / 薪资福利 20% / 业务前景 15% / 公司稳定性 10% / 成长空间 10% /
  工作强度 10% / 通勤办公 10%；总分 ≥4.0 为 A、3.0-3.9 为 B、<3.0 为 C；
  命中红线直接 C 级并注明命中项；信息不足的维度给 3 分并标注"信息不足"。
- AI 调用走 `ConfiguredAIClient.complete_readonly_draft`（只读草稿补全边界，不进 Agent 工具面）。
- 评分结果带 `model_fingerprint` 与输入快照指纹，可复算可追溯。

### 2.3 晋升边界（单一 intake 不变）

`discovery/promote.py`：候选 → 投递走既有 `ApplicationCreationService.create`，
不新增第二条 Application 写路径。候选表以 `promoted_application_id` 反向链接，
晋升后候选状态置 `promoted`。晋升是幂等的（已晋升候选重复晋升返回既有链接）。

## 3. 数据模型

新增三表（`discovery/models.py`，db.py 组合根导入注册）：

| 表 | 职责 | 关键字段 |
|---|---|---|
| `job_candidates` | 候选池 | `source`、`source_key`（联合唯一，去重）、`raw_payload_json`、规范化列、`status`（`new`/`scored`/`promoted`/`discarded`）、`promoted_application_id`、`discovered_at` |
| `job_candidate_scores` | 评分结果 | `candidate_id`、`profile_fingerprint`、`breakdown_json`（七维）、`total_score`、`grade`、`rationale_json`、`model_fingerprint`、`created_at` |
| `discovery_profiles` | 评分输入画像 | 单例行：`resume_id`（关联 resumes）、`cities_json`、`directions_json`、`salary_expectation_json`、`red_lines_json` |

## 4. 明确不做

- 不做自动投递（与 job-ops 同一结论：投递是人做决定的动作）；
- 不把候选池塞进 `ApplicationCreationWorkspace`（它是单用户标识与幂等收据，不是池）；
- 不引入第二条 Application 写路径；
- 不在 repository 层抓取外部数据；
- 面试准备/谈薪/Offer 对比不重复建设（既有模块从 Application 阶段接手）。

## 5. 备选方案

- **扩展 Application 直接承载"未投递"状态**：污染 intake 语义（status 状态机是投递生命周期），
  且无法承载"发现但未决策"的批量池化场景。否决。
- **独立项目做发现+打分，数据导出到 OfferPilot**：两套存储两套 UI，接缝变成手工导入。否决。
- **放进 knowledge/ 模块**：knowledge 的产品职责是公司/面试事实沉淀（见 knowledge-system.md），
  候选池是流程状态而非知识。否决。

## 6. 分阶段落地

1. **P1（本 ADR 范围）**：契约 + 手动投喂 adapter + 归一化 + 画像 + AI 评分 + 晋升 + REST/测试；
2. P2：`websearch` 聚合搜索 adapter（搜索+详情页抓取管线）；
3. P3：`crawler` 招聘平台 adapter（mcp-jobs 桥，cookie 预热后接入）；
4. P4：前端"发现"页（候选池看板、评分卡、一键转投递）。

P1 先落库与契约（含测试），前端消费面在 P4 补齐；期间新表暂无前端写入方，不构成契约不一致。

## 7. 验证

- 归一化容错：多源异构字段样本 → 规范字段稳定；
- 去重：同 `source`+`source_key` 重复投喂不产生第二行；
- 评分：mock AI 返回七维结构，权重/评级/红线判定正确；
- 晋升：候选 → Application 全链路（真实 SQLite + TestClient），幂等复放；
- 后端验收按 AGENTS.md §7"局部后端"：定向 pytest + ruff。
