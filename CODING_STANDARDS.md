<!-- lazypack:start block=coding-standards src=DECISIONS.md@0.2.0 gen=aeb0254139bb9c52 input=0f7c6894fcdea705 fp=58ebb76e01028536 -->
# 编码标准与质量门禁 (CODING_STANDARDS)

> 派生自 lazypack-discipline 固定层 DECISIONS.md@0.2.0（依据 lazypack-setup 内置快照编译，来源内容标识: 2b38b1b0543489226eda5e3bd2bf411c58c1c331；离线事实源查阅 lazypack-setup/references/DECISIONS.md）§6。

## 1. 原则与职责

1. **工具能查的，不写进散文**：格式化、语法校验、类型检查由工具执行，本标准不重复复述已被 linter/formatter 覆盖的细则。
2. **审查者执行标准**：本文件由审查者（Reviewer）在代码审查时严格执行；执行者（Implementer）编码时对照执行。
3. **对抗性双跑门禁**：执行者提交前跑门禁，审查者审查时同样必须跑门禁，通过对抗性审查压低两边都没跑的概率（§6.4）。

## 2. 质量双轨制 (§6.5)

- **可测层（Domain & Data Logic）**：
  - 核心领域逻辑、状态推导、数据清洗与算法等行为改动，**必须配套自动化测试断言**。
  - 严禁提交无断言或断言被注销的可测层逻辑。
- **迭代层（UI & Pages & Components）**：
  - 页面、样式、交互组件以语法/类型检查为底线。
  - 复杂推导逻辑应下沉到可测层进行单元测试，避免页面层堆砌难以自动化测试的隐式逻辑。

## 3. 文档跟着代码改 (§7)

- 执行者提交代码时，必须同步 diff 涉及的文档行（§7.1）。
- 需求方或维护者变更决议时，新决议先进 `grill-with-docs`，落 ADR 并更新产物登记册状态（§7.3）。
<!-- lazypack:end block=coding-standards -->

## 项目补充审查规则 (comtee)

1. **审查者独立复跑门禁**：执行 `/code-review` 时，Standards 审查者须独立运行 `pwsh -NoProfile -File scripts/check.ps1`，并在报告末尾附四项门禁实跑状态（`pass` / `fail` / `not-run + 原因`）；本条优先于通用 review 技能的「跳过工具检查」指引。
2. **文档、UI 引导与实现闭环**：修改 ADR、`CONTEXT.md` 或面板引导文案声称支持的操作时，核对对应的可交互控件与领域层方法已真实接通。
3. **持久化判别值显式校验**：新增持久化判别字段（如 `device_type`）时，反序列化须对未知值显式抛 `ValueError`，并在身份对象构造入口规范化主键格式。
