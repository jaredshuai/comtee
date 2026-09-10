<!-- lazypack:start block=artifacts-register src=DECISIONS.md@0.2.0 gen=aeb0254139bb9c52 input=8e522686f1937df1 fp=d57c9f04d33478cc -->
# 产物登记册 (ARTIFACTS)

> 派生自 lazypack-discipline 固定层 DECISIONS.md@0.2.0（依据 lazypack-setup 内置快照编译，来源内容标识: 2b38b1b0543489226eda5e3bd2bf411c58c1c331；离线事实源查阅 lazypack-setup/references/DECISIONS.md）§4。
> 原则：一个东西只有一个家；能推导出来的不手写；有生命周期的写清何时死。

## 1. 产物状态词与流转规则

| 状态词 | 含义 | 流转约束 |
|---|---|---|
| `current` | 当前唯一的现行有效基准 | **在同一类别产物中全局唯一**。新产物标为 `current` 时，旧产物必须降级为 `superseded` |
| `reference` | 外部素材、外部规范、参考设计 | 永久作为参照依据 |
| `exploration` | 探索方案、对比调研 | 仅供比对，不作为实现基准 |
| `superseded` | 已废弃或被取代的旧产物 | `git mv` 归档至 `docs/archive/`，登记行同步更新，互指新产物 |
| `pipeline` | 由源文件生成的派生品（图标、数据） | 登记源与生成器命令；严禁手工修改派生文件，重新运行 pipeline 生成 |
| `wip` | 正在编写或设计中的未决草案 | 完成后裁决为 `current` 或归档 |

> [!IMPORTANT]
> **未登记产物视为未决**：册上查不到的产物，先向维护者核实，严禁按文件名或创建日期猜测新旧！

## 2. 现存产物登记表

| 产物相对路径 | 类别 | 状态 | 来源/对应票/ADR | 说明 |
|---|---|---|---|---|
| `docs/agents/issue-tracker.md` | 任务跟踪 | `current` | setup-matt-pocock-skills | GitHub Issues (`jaredshuai/comtee`) 操作指引 |
| `CODING_STANDARDS.md` | 编码规范 | `current` | lazypack-setup | 质量双轨制与审查者对抗性门禁 |
| `RELEASE.md` | 发版规范 | `current` | lazypack-setup | Conventional Commits 与 SemVer 发版纪律 |
| `docs/agents/roles.md` | 角色映射 | `current` | lazypack-setup | 六角色职责与防撞车边界 |
<!-- lazypack:end block=artifacts-register -->
