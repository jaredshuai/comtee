<!-- lazypack:start block=release-discipline src=DECISIONS.md@0.2.0 gen=aeb0254139bb9c52 input=0f7c6894fcdea705 fp=38522c60f7c90945 -->
# 发版与提交纪律 (RELEASE)

> 派生自 lazypack-discipline 固定层 DECISIONS.md@0.2.0（依据 lazypack-setup 内置快照编译，来源内容标识: 2b38b1b0543489226eda5e3bd2bf411c58c1c331；离线事实源查阅 lazypack-setup/references/DECISIONS.md）§5。

## 1. 提交与版本规则（固定段）

### 1.1 提交头 (Conventional Commits 1.0.0)
- 格式：`type(scope)!: 描述`
- 允许的 8 个 Angular type：`build`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `test`，加上 `chore`, `revert`。
- 破坏性改动使用 `!` 或正文注明 `BREAKING CHANGE`。
- 脚注使用 `Closes #n` 或 `Fixes #n` 关联票据。

### 1.2 提交正文 (Google CL 规范)
- 第一行独立说清「改了什么」。
- 正文说清「为什么做此改动」、有哪些未做完或折衷之处、关联的 Issue / Bug 号。

### 1.3 版本号映射 (SemVer 2.0.0)
- `!` 或 `BREAKING CHANGE` -> Major 升级 (`vX.0.0`)
- `feat` -> Minor 升级 (`v0.X.0`)
- `fix` / `perf` -> Patch 升级 (`v0.0.X`)
- 其他 type 不触发版本发版。
- 每次发版必须在 Git 打对应版本标签（如 `v1.2.0`）。
- 变更记录遵循 Keep a Changelog 1.1.0 格式，由提交历史自动编译生成，禁止手写篡改。

## 2. 平台打包与发布段（项目层薄草稿）

> [!WARNING]
> 以下平台打包与上传配置为项目层薄草稿，尚未经过实操自动化验证（标记为未验证）。执行打包前请人工复核。

### 平台操作指引 (Windows 桌面 (uv + NiceGUI))
- **依赖安装**：`uv sync`（发版流水线实操 [未验证]）。
- **门禁验证**：提交前 Hook（ruff format / ruff check / ty check / pytest）。
- **打包构筑**：Windows 桌面面板（NiceGUI native）；安装包方案未选定 [未验证]。
- **发布/上传**：Git 打 `vX.Y.Z` 标签；安装包分发流程 [未验证]。
<!-- lazypack:end block=release-discipline -->

## 本仓库打包（Nuitka + Inno Setup）

选定方案：Nuitka **standalone 目录** + Inno Setup 安装包。不用 onefile：串通是托盘常驻，每次自解压会拖慢登录自启。

前置：

- `uv sync --group packaging --group dev`
- Inno Setup 6 或 7（`ISCC.exe`）。未安装时 Nuitka 阶段仍可打出目录，安装包阶段会失败并提示下载地址。
- Windows 11（自带 WebView2）。

```powershell
powershell -ExecutionPolicy Bypass -File installer/build.ps1
powershell -ExecutionPolicy Bypass -File installer/build.ps1 -Stage nuitka
powershell -ExecutionPolicy Bypass -File installer/build.ps1 -Stage inno
powershell -ExecutionPolicy Bypass -File installer/build.ps1 -Stage nuitka -Force
powershell -ExecutionPolicy Bypass -File installer/build.ps1 -Stage inno -Force
powershell -ExecutionPolicy Bypass -File installer/build.ps1 -Force
powershell -ExecutionPolicy Bypass -File installer/build.ps1 -Clean
```

阶段标记在 `installer/.build-state/*.ok`。标记在、产物还在、版本没变，就跳过该阶段。失败不会清掉已经成功的阶段。已有 `main.dist` / 安装包但还没有标记时，脚本会补写 `.ok`，不会重打。

改代码后要重打 Nuitka：`-Stage nuitka -Force`（会清掉 `inno.ok`，接着跑 `-Stage inno` 或默认 `all` 才会重打安装包）。只重打安装包：`-Stage inno -Force`。`-Force` 会带 `--remove-output` 清掉旧的 standalone 目录再编；中断后续打不要加 `-Force`，让 Nuitka 复用已生成的 obj。`-Clean` 会删掉 `installer/dist` 和阶段标记。

产物：

- `installer/dist/comtee.dist/comtee.exe`（或 `main.dist`）
- `installer/dist/Comtee-Setup-<version>.exe`

安装到 `%LOCALAPPDATA%\Programs\串通`，不需要管理员。线路存档仍在 `%LOCALAPPDATA%\comtee`，卸安装包不会拆线路。登录自启由程序自己写 HKCU Run；安装包不重复写启动项。

Agent 端 MCP 不打进安装包，仍用源码 `python -m comtee.mcp` 去连已启动的串通。

首次 Nuitka 编译约 34 分钟；Inno 随后打出安装包。tag、CI、GitHub Release 不在本分支，留给后续发版工作。
