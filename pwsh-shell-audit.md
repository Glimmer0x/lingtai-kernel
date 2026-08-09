# LingTai Kernel shell/bash 工具 PowerShell 适配审计报告

> 审计对象：`C:\Users\zhuang\lingtai-kernel-src`（源码树，不含 `.worktrees/` 下的重复副本）
> 审计日期：2026-08-08
> 背景：Jason 要求系统性检查 PowerShell 下的灵台适配问题并提改进 PR。当前 agent 日常在 Windows PowerShell 5.1 上遇到引号嵌套易碎、CRLF/LF 问题（Windows→WSL 脚本）、rg/ripgrep 缺失、`&&` 不支持（要分号）、`ls` 输出不同、`python` 命令等痛点。

---

## 0. 摘要（TL;DR）

Kernel 已经有相当完整的方言（dialect）架构：`ShellKind` 五态（posix/powershell/cmd/gitbash/wsl）、`powershell_policy.json` 独立策略、pwsh stdin bootstrap、OEM 回退解码、Windows Job Object 进程树回收、CRLF 输出归一化。**但 PowerShell 适配整体仍存在六个系统性缺口**：

1. **PowerShell 方言只支持 pwsh 7，Windows PowerShell 5.1 完全没有方言**（`powershell.py` 明确拒绝回退 5.1）；没有 pwsh 的机器会被降级成 cmd.exe 方言，与用户的“PowerShell 5.1 日常”体验完全脱节。
2. **工具描述/提示词与策略互相矛盾**：描述教 agent“用 `;` 串联、用 `|` 管道”，但默认策略下 `;`、`|`、`&&`、`$`、`()`、`%` 全部被元字符扫描器拒绝——任何多语句/管道命令在配置策略下直接报 “PowerShell policy validation does not support this syntax”。（本次审计所用 shell 工具本身就在拒绝 `Get-ChildItem ... | Where-Object`，现场复现。）
3. **`rg --files` / `find` / `jq` / `tail -n` / `python3` 等 Unix 假设遍布工具描述、超时提示和手册**，在 Windows 上没有对应命令，且没有 PowerShell 替代指引。
4. **shell-manual 技能正文 0 处提到 Windows/PowerShell/cmd.exe/WSL**，agent 在 Windows 上得不到任何命令等价、引号、换行方面的指导。
5. **WSL 方言不归一化脚本 CRLF**，Windows→WSL 脚本 `\r` 残留会破坏 bash（只有输出侧做了 CRLF 归一化）。
6. **`python3`、`~/.lingtai-tui/runtime/venv/bin/python`、`/usr/bin/git` 等路径/命令硬编码散布在 doctor、system-manual、mcp-manual、scheduled-work 等技能文档里**，Windows 上不可执行。

下文第 3 节给出现状细节，第 4 节给出 9 个具体改进点（现状/问题/建议修复，定位到文件与代码），第 5 节给出 PR 切分建议。

---

## 1. 审计范围与方法

- 只读审计，未修改任何源码（除本报告文件）。
- 检索方式：`file grep/glob` 递归检索 `src/lingtai/`，排除 `.worktrees/` 重复副本；shell 只用于目录列举（注意：审计所用 shell 工具本身运行在 PowerShell 策略校验下，复杂管道命令会被拒绝——这本身就是问题 P2 的现场证据）。
- 重点文件清单：
  - `src/lingtai/tools/bash/`（shell 能力包：`__init__.py` ShellManager、`_shell_dialect.py`、`_tool_family.py`、`_async_process.py`、`_async_supervisor.py`、`powershell_policy.json`、`bash_policy.json`、`manual/SKILL.md`、`glossary-{en,zh,wen}.md`）
  - `src/lingtai/adapters/shell.py`（方言分类器）、`src/lingtai/adapters/windows/{powershell,cmd,gitbash,wsl}.py`、`src/lingtai/adapters/windows/windows_cmd_shim.py`
  - `src/lingtai/intrinsic_skills/`（lingtai-doctor、system-manual、nokv-workbench 等）
  - `src/lingtai/prompts/`（substrate/procedures/tools 提示词段）
  - `src/lingtai/tools/{daemon,mcp,email,knowledge,skills}/manual/` 等手册中的命令示例

---

## 2. 现状总览：shell 工具的方言架构（先弄清“它怎么工作”）

### 2.1 调用链

```
setup() (tools/bash/__init__.py:1863)
  └─ _resolve_shell_kind()  → adapters/shell.py:resolve_shell_kind()  平台探测 + LINGTAI_SHELL/shell_kind 覆盖
  └─ _select_shell_dialect() → adapters/shell.py:select_shell_dialect() → 具体方言类
  └─ 策略文件选择：powershell 方言 → powershell_policy.json，否则 bash_policy.json (__init__.py:1892)
  └─ get_description() → 工具描述（含 Host OS + Active shell + sequencing guidance）注入系统提示词

ShellManager.handle() (__init__.py:666)
  └─ _validate_command(): dialect.extract_commands() → 策略校验（拒绝/放行）
  └─ dialect.make_invocation(script) → ShellInvocation（spawn 形态）
  └─ _run_sync()/_run_sync_contained()（Windows Job Object）/ _run_async()（supervisor）
  └─ 输出侧：sanitize_output + （Windows）decode_windows_output + CRLF 归一化
```

### 2.2 方言检测（`src/lingtai/adapters/shell.py:71-104`）

`resolve_shell_kind()` 优先级：
1. `shell_kind` 覆盖（init.json `manifest.capabilities.shell.shell_kind`）或环境变量 `LINGTAI_SHELL`；
2. POSIX 平台 → `posix`；
3. Windows（`os.name == "nt"`）：先 `shutil.which("pwsh")` → `powershell`；再 Git Bash → `gitbash`；最后 `cmd`。WSL 永不自动选择（仅 `LINGTAI_SHELL=wsl` 显式开启）。

**关键事实**：Windows 上只有“有 pwsh 7 / 有 Git Bash / 退化为 cmd.exe”三种结局。**Windows PowerShell 5.1（powershell.exe）不存在于任何分支**。

### 2.3 各方言执行形态（`tools/bash/_shell_dialect.py:67-73, 129-167`）

| ShellKind | spawn argv | 说明 |
|---|---|---|
| posix | `shell=True`（历史形态） | 脚本原样交给 /bin/sh |
| powershell | `pwsh -NoLogo -NoProfile -NonInteractive -Command <bootstrap>` | 真实脚本走 stdin（`stdin_script`，见 2.4） |
| cmd | `cmd.exe /d /s /c " script"`（raw 命令行拼接，`build_cmd_command_line`） | 绕开 list2cmdline 的 MSVC 引号转义 |
| gitbash | `bash -lc <script>` | Git for Windows 的 bash |
| wsl | `wsl.exe -e bash -lc <script>` | 显式开启才可用 |

### 2.4 PowerShell 方言的已有适配（`adapters/windows/powershell.py`）——做得好的部分

- **pwsh 7 stdin bootstrap**（35-41 行 `_ASCII_BOOTSTRAP`）：命令从 stdin 以 UTF-8 读入，绕开 Windows 控制台代码页与 32768 字符命令行上限；bootstrap 里 `[Console]::Input/OutputEncoding` 强制 UTF-8。
- **原生退出码保真**（`_pwsh_invocation` 769-851 行）：`$?` + `$LASTEXITCODE` + `PSNativeCommandUseErrorActionPreference`，native 非零退出能原样返回。
- **OEM 回退解码**（`decode_windows_output` 420-446 行 + `_read_logs` 1488-1496 行）：按行尝试 UTF-8 失败后回退 cp437/cp850/cp1252；输出 CRLF→LF 归一化。
- **cmd shim 处理**（`try_cmd_shim_plan` + `_pwsh_quote_argv` 54-66 行）：npm/npx 直接转 node CLI，避免经 cmd.exe 二次解析。
- **Windows 同步执行 Job Object 进程树回收**（`_run_sync_contained` 778+ 行）+ 受限管道排空超时。
- **独立策略**（`powershell_policy.json`）：PowerShell 用自带 deny 列表，不复用 POSIX 的。
- **工具描述按 dialect 生成**（`_tool_family.py:get_description`）：描述里带 “Active shell: PowerShell. Sequence commands with ';' …” + “Host OS: Windows …” + “On Windows, sync runs are contained in a kill-on-close Job Object…”。

### 2.5 运行时技能路径

任务中提到的 `.library/intrinsic/capabilities/shell/SKILL.md` 是**运行时安装路径**（`src/lingtai/agent.py:442/507`、`intrinsic_skills/__init__.py:3`：每个技能子目录原样拷贝到 `.library/intrinsic/capabilities/<name>/`），其源文件即 **`src/lingtai/tools/bash/manual/SKILL.md`**（shell 工具的 `manual` action 由 `build_manual_child` 提供）。源码树里没有 `.library` 目录属正常。

---

## 3. 逐项审计结果

### 3.1 shell 工具实现（任务点 1）

**方言检测**：见 2.2。实现完整、可配置（`LINGTAI_SHELL` / `shell_kind`），但 PowerShell 分支硬编码 pwsh 7：

- `adapters/windows/powershell.py:316-326` `_find_pwsh()` 只找 `pwsh`/`pwsh.exe`（含 `%ProgramFiles%\PowerShell\7\pwsh.exe` 探测），注释明确 **“Windows PowerShell 5.1 (powershell.exe) is intentionally never used as a fallback”**；
- `PowerShellDialect.__init__`（705-714 行）找不到 pwsh 时抛 `FileNotFoundError`，错误文案直接要求装 PowerShell 7；
- `adapters/shell.py:97-103` 分类器没有 powershell.exe 分支，5.1-only 机器 → Git Bash 或 cmd.exe。

后果：**“PowerShell 5.1 日常”在 kernel 里根本不存在对应方言**；如果用户机器没装 pwsh 7，agent 实际拿到的是 cmd.exe 方言（描述显示 “Active shell: cmd.exe. cmd.exe has no ';' statement separator.”），却仍然会按 PowerShell 习惯写 `;`、`ls`、`Select-String`，全部落空。

**命令执行**：`make_invocation` → `ShellInvocation.process_args()`（`_shell_dialect.py:292-316`）统一为 argv/command_line/stdin 三种形态；PowerShell 走 stdin bootstrap（2.4）。执行本身与方言解耦干净。

**PowerShell 特定处理**：见 2.4。注意一个矛盾：`_SEQUENCING_GUIDANCE[POWERSHELL]`（`_shell_dialect.py:88-91`）告诉模型“用 `;` 串联、用 `|` 分管道阶段”，但 `powershell.py` 的 `is_unsafe_windows_command`（458-529 行）把 `;`、`|`、`&`、`$`、`(`、`)`、`%`、`` ` ``、`!` 全部标记 unsafe，`extract_commands`（716-735 行）在**配置了 allow/deny 策略时直接拒绝**这类脚本——**描述推荐的做法恰恰是策略拒绝的做法**（详见 4.2）。

### 3.2 系统提示词 / 工具描述中的 shell 说明（任务点 2）

系统提示词的 tools 段由工具注册表生成（`prompts/tools/tools.yaml`：内容来自 active tool schema + `get_description` + glossary），因此 shell 在提示词里的“正文”就是 `_tool_family.py:get_description()` 的输出 + glossary。现状：

- 准确的部分：会注入 `Active shell dialect: <state_key>`、`Host OS: <describe_host_os()>`、sequencing guidance、Windows Job Object 提示（128-152 行）；“dialect 在 setup 时检测，调用不能选择”也准确。
- **不准确/误导的部分**：
  1. `RUN_INPUT_SCHEMA.working_dir` 描述给出示例 `cd /absolute/path && ...`（`_tool_family.py:52-62`，尤其 60 行）——`&&` 在 PowerShell 5.1/cmd 之外的所有方言都被策略拒绝，示例对 Windows 无效；`_validate_working_dir` 的错误文案同样用 `cd {resolved} && ...`（`__init__.py:584`）。
  2. “prefer `rg --files`”（`_tool_family.py:149`）对 Windows 无 `rg` 的机器不可执行，也没有 PowerShell 替代（`Select-String` / `Get-ChildItem -Recurse` / file 工具自带 grep）。
  3. sequencing guidance 说 PowerShell 用 `;`/`|`（`_shell_dialect.py:88-91`），与默认策略的拒绝行为冲突（见 4.2）；且文案写“`&&` 不被 Windows PowerShell 5.1 支持”——对实际引擎 pwsh 7（7.0+ 支持 `&&`/`||`）而言理由不准确，真正拒绝 `&&` 的是策略扫描器，不是 shell。
  4. 描述里没有任何“命令等价表”（`ls`→`Get-ChildItem`、`cat`→`Get-Content`、`grep`→`Select-String`、`rm -rf`→`Remove-Item -Recurse -Force`、`python`→`python`/venv `Scripts\python.exe` 等），Windows agent 只能自己试错。

### 3.3 shell-manual 技能（任务点 3）

- 位置：源码 `src/lingtai/tools/bash/manual/SKILL.md`（运行时 `.library/intrinsic/capabilities/shell/SKILL.md`），v1.10.0。
- **正文与全部 3 个 reference 子页（scheduled-work / notification-reminders / debugging-cleanup）对 Windows/PowerShell/cmd.exe/WSL 的提及次数为 0**（已用 grep 验证）。
- Unix 假设密集：
  - “Avoid broad recursive scans”一节（143-149 行）推荐 `rg --files ...`，回退建议是 `find <root> -type f ...`——**Windows 上 `find` 是不同语义的过滤工具，两者都不可用**；
  - “Parse JSONL”一节（153-159 行）推荐 `jq -c .` 和 `tail -n`——Windows 无 jq（默认）、`tail` 不存在；
  - “Reading command results”一节（131-135 行）说 “Use the venv interpreter… Bare `python3` lacks…”——Windows 上 `python3` 常常不存在，且 venv 路径是 `Scripts\python.exe` 而非 `bin/python`；
  - 正文示例（176 行等）全是 `claude -p '...' --output-format json` 这类 Unix 引号风格。
- 结论：**shell-manual 对 PowerShell 的指导为零**，需要新增一节（见 4.6）。

### 3.4 kernel 中其他硬编码 bash/Unix 假设（任务点 4）

| 位置 | 假设 | 影响 |
|---|---|---|
| `tools/bash/__init__.py:210-215` `_BROAD_SCAN_HINT` | 超时提示无条件推荐 `rg --files ...` | Windows 无 rg 时提示不可执行；且 hint 不区分方言 |
| `tools/bash/glossary-zh.md` / `glossary-wen.md`（18 行） | “宜先用 `rg --files`” | 中文/文言 glossary 同样假设 rg |
| `tools/bash/manual/SKILL.md`（145/148/158 行） | `rg --files` / `find ...` / `jq -c` / `tail -n` | 见 3.3 |
| `intrinsic_skills/lingtai-doctor/SKILL.md`（33-37、56-58 行） | `python3 src/.../doctor.py`、`~/.lingtai-tui/runtime/venv/bin/python`、`ps` 扫描 | Windows 上 `python3` 无、路径是 `Scripts\`、进程扫描是 `Get-Process` |
| `intrinsic_skills/system-manual/reference/sqlite-log-query/SKILL.md`（530-531 行） | `python3 scripts/event_summary.py` | 同上 |
| `intrinsic_skills/system-manual/reference/refresh-precheck/SKILL.md`（79/344/384 行） | `PYTHON=${LINGTAI_RUNTIME_PYTHON:-$HOME/.lingtai-tui/runtime/venv/bin/python}` | bash 语法 + Unix 路径 |
| `intrinsic_skills/nokv-workbench/assets/PREFLIGHT.md`（17/29/56 行） | `~/.lingtai-tui/runtime/venv/bin/python - <<'PY'` | heredoc 是 bash 语法，PowerShell 无 heredoc |
| `tools/bash/manual/reference/scheduled-work/SKILL.md`（137-359 行） | `#!/bin/bash`、`/usr/bin/git`、`/opt/homebrew/bin/gh`、launchd/systemd/cron 全套 | 全部 Unix/macOS；Windows 无对应章节（任务计划程序） |
| `tools/bash/manual/reference/notification-reminders/SKILL.md`（95/129 行） | `/usr/bin/python3`、`nohup /bin/bash -lc` | Windows 不可用 |
| `tools/bash/manual/reference/debugging-cleanup/SKILL.md`（54/111 行） | `python3 -c ...`、`python3 - <<'PY'` | 同上 |
| `tools/daemon/manual/reference/inspection/SKILL.md`（113/117 行） | `tail -n 20/10 ...jsonl` | Windows 无 tail |
| `tools/mcp/manual/SKILL.md`（97 行）与 `reference/curated-addons.md`（25/119 行） | `~/.lingtai-tui/runtime/venv/bin/python3` | Unix 路径 |
| `prompts/`（substrate.md、procedures.md、meta_guidance） | 只泛称 `bash`/`shell`，无 Unix 命令 | 中性，无需改 |

此外 `bash_policy.json` 的 deny 列表（`rm`/`chmod`/`apt` 等）是 POSIX 语义，PowerShell 方言已用独立 `powershell_policy.json` 规避——这个设计是对的。

---

## 4. 具体改进点（9 项，按优先级排序）

### P1【高】Windows PowerShell 5.1 无方言支持，5.1-only 机器被降级为 cmd.exe

- **现状**：`adapters/shell.py:97-103` 的 Windows 分支只认 pwsh/Git Bash/cmd；`adapters/windows/powershell.py:316-326` 明确拒绝 powershell.exe 5.1；`PowerShellDialect.__init__`（705-714）找不到 pwsh 直接 `FileNotFoundError`。用户“日常 PowerShell 5.1”在 kernel 里对应的是 cmd.exe 方言或直接报错。
- **问题**：① 5.1 与 pwsh 语法大部分相同，但 `&&`、`$_`、`-ErrorAction`、别名等有差异，没有 5.1 方言意味着 agent 无法用 PowerShell 语义工作；② 降级到 cmd.exe 后，`;`（PowerShell 习惯）在 cmd 里是参数分隔符，行为更怪；③ 工具描述会宣称 “Active shell: cmd.exe”，与用户认知（PowerShell）冲突。
- **建议修复**：
  1. `ShellKind` 增加 `POWERSHELL51 = "powershell51"`（`_shell_dialect.py:11-23`），`resolve_shell_kind` 在 `_discover_pwsh()` 失败后探测 `powershell.exe`（`shutil.which("powershell")` 或 `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`），命中则返回 `POWERSHELL51`；
  2. 新增 `adapters/windows/powershell51.py`（或给 `PowerShellDialect` 加 `version` 参数）：spawn 用 `powershell.exe -NoLogo -NoProfile -NonInteractive -Command`（5.1 无 `$PSNativeCommandUseErrorActionPreference`，需去掉该段 wrapper，改用 `$?`/`$LASTEXITCODE` 的 5.1 兼容写法）；`-EncodedCommand` 或 stdin bootstrap 在 5.1 下 `[Console]::In.ReadToEnd()` 同样可用；
  3. `_SEQUENCING_GUIDANCE` 增加 `POWERSHELL51` 条目（“无 `&&`，用 `;`；无 `??` 等新语法”），并让 5.1 复用 `powershell_policy.json`（`__init__.py:1892` 的判断改为 `state_key() in {"powershell", "powershell51"}`）；
  4. 至少：把 `powershell.py:710-713` 的报错文案改为给出可操作选项（“未找到 pwsh。可安装 PowerShell 7（winget install Microsoft.PowerShell），或设置 LINGTAI_SHELL=cmd/gitbash/wsl 显式选择其他 shell”），并在 shell-manual 里说明 5.1 的现状与绕行。

### P2【高】工具描述与默认策略自相矛盾：教 agent 用 `;`/`|`，策略却全部拒绝

- **现状**：`_shell_dialect.py:88-91` POWERSHELL 引导句：“Sequence commands with ';' … separate pipeline stages with '|'”；而 `powershell.py:458-463` `WINDOWS_UNSUPPORTED_TOKENS = {"&","|","<",">",";","^","(",")","%","!","`","\n","\r"}`，`extract_commands`（716-735）在配置了 allow/deny 策略时对任何含这些字符的脚本返回 `__powershell_unsupported__`，`__init__.py:611-626` 于是拒绝整条命令（“PowerShell policy validation does not support this syntax; refusing to run it”）。默认配置下 powershell_policy.json 有 deny 列表 → 策略“已配置” → 生效。
- **问题**：多语句（`;`）、管道（`|`）、链式（`&&`）、变量（`$x`）、子表达式（`$(...)`）、控制流（`if(...)`）、乃至 `git log --format=%h` 里的 `%` 全部被拒。agent 照着描述写 `cmd1; cmd2` 立刻被拒，只能退化成一次一条命令，或者用户被迫开 yolo。本次审计的 shell 工具环境本身就拒绝了 `Get-ChildItem ... | Where-Object`，是活生生的复现。
- **建议修复**：
  1. 最小改动：把引导句改为与策略一致的表述：“Windows 方言在策略校验下拒绝 `;`/`|`/`&&`/`$`/`%` 等元字符；请一次执行一条简单命令，或用 `shell` 多次调用”。避免模型学到必然失败的模式；
  2. 更好的方案：恢复 `powershell.py` 中注释提到的**递归提取器**（`_commands` 已有 `$()`/`{}`/`()` 递归能力，见 194-295 行），让 `extract_commands` 只在无法静态证明时 fail-closed：`;`/`&&`/`|` 作为语句分隔符提取（`_split_statements` 155-158 行已能切分 `&&`），`$x`/`$(...)` 递归检查内容，仅对 `& $x` 动态调用、`%VAR%`、`-EncodedCommand`、`-File`、profile 启动等真正不可见/不可审的形态拒绝；
  3. 若坚持 fail-closed：至少让拒绝信息带上“安全替代”（如“PowerShell 策略拒绝含 `;` 的命令，可改为逐条执行；`Select-String` 可替代 `grep`；管道可用临时文件分步”），并让 `get_description` 把这层限制写进描述（`_tool_family.py:140-152`）。

### P3【中】`&&` 引导文案不准确：pwsh 7 本身支持 `&&`，拒绝它的是策略扫描器

- **现状**：`_shell_dialect.py:89-90` 写“`&&` is not supported by Windows PowerShell 5.1 and is unsafe to assume”。实际上 PowerShell 7.0+ 原生支持 `&&`/`||`；`&&` 被拒是 `powershell.py` 元字符扫描把 `&` 列入 unsafe（458-460 行）导致（yolo 模式下 pwsh 7 能正常跑 `a && b`）。
- **问题**：给模型的理由与引擎事实不符，模型会把“不能连写”错误归因于 shell 能力，而不是策略校验；同时 `extract_commands`/`_split_statements` 明明已支持切分 `&&`（155-158 行），策略层却一刀切。
- **建议修复**：
  1. 引导句改为：“PowerShell 7 支持 `&&`/`||`，但默认策略校验会拒绝含 `&` 的命令（fail-closed 安全模型）；请用 `;` 或分次调用”；
  2. 若 P2 的递归提取器落地，则在 `is_unsafe_windows_command` 前先做结构化解析，`&&`/`;`/`|` 作为分隔符处理后不再整条拒绝。

### P4【中】`%` 一刀切拒绝误伤大量合法命令（git format、findstr、date 等）

- **现状**：`powershell.py:463` `WINDOWS_ALWAYS_UNSAFE_TOKENS` 含 `%`，`is_unsafe_windows_command` 在单引号、双引号内都拒绝 `%`（498-512 行），理由是“引号内容可能经 cmd.exe 二次解析”。于是 `git log --pretty=format:"%h %s"`、`Get-Date -Format "%Y-%m-%d"`、`findstr /C:"%s"` 在默认策略下全部被拒。
- **问题**：`%` 只有在真正路由到 cmd.exe shim（`.cmd`/`.bat`/npm）时才危险；对直接由 pwsh 执行的 native 命令（git.exe 等）`%` 是字面量。
- **建议修复**：`PowerShellDialect.make_invocation`（737-767 行）已有 `try_cmd_shim_plan` 判定是否走 cmd shim；把 `%` 的拒绝范围收窄到“实际走 cmd shim 的命令”，或在 `extract_commands` 中仅当 `try_cmd_shim_plan(script)` 非 None 时才应用 `%` 规则（否则 `%` 视为字面量通过）。

### P5【中】`rg --files` / `find` / `jq` / `tail -n` 建议无 Windows 替代，且提示不区分方言

- **现状**：`__init__.py:210-215` `_BROAD_SCAN_HINT` 无条件推荐 `rg --files ...`；`_tool_family.py:149` 描述同样；`manual/SKILL.md:143-149` 的 fallback 是 `find <root> -type f ...`（Windows 的 `find` 语义不同）、158 行推荐 `jq`/`tail -n`；glossary-zh/wen 亦然。
- **问题**：Windows 机器普遍没有 rg（任务背景明确提到），`find`/`tail`/`jq` 也不存在；agent 照着做必然失败，转而乱试 `Select-String` 或超时。
- **建议修复**：
  1. `_broad_scan_hint` 与描述/手册的宽泛扫描建议按方言分支：PowerShell → `Get-ChildItem -Recurse -File -Filter '*.py'`（并说明用 `-Exclude`/`-Depth` 收窄）或直接用 file 工具 `grep`/`glob`（kernel 自带 Rust 搜索 sidecar，跨平台且无 rg 依赖）；cmd → `dir /s /b`；
  2. `_BROAD_SCAN_HINT` 变为函数 `_broad_scan_hint(command, dialect_state_key)`（`__init__.py:218-224` 已接收 command，把 `self._dialect.state_key()` 传进去即可）；
  3. JSONL 解析建议改为与平台无关的写法（“用 file 工具按行读，逐行 json.loads”，不依赖 jq）。

### P6【中】shell-manual 正文零 PowerShell 内容，需要新增 Windows/PowerShell 章节

- **现状**：`tools/bash/manual/SKILL.md`（342 行）与其 3 个 reference 子页中无一处 Windows/PowerShell/cmd/WSL；示例全部 Unix 风格（`claude -p '...'`、`tail -n`、heredoc）。
- **问题**：agent 在 Windows 上读 manual 得不到任何有效指导，所有命令等价关系都要自己试错——这正是“shell tool 在 Windows PowerShell 上很难用”的直接来源之一。
- **建议修复**：在 `manual/SKILL.md` 新增 `## Windows / PowerShell 快速参考`（或独立 `reference/windows-powershell/SKILL.md` 子页），内容包括：
  - 命令等价表：`ls`→`Get-ChildItem`（`ls` 是别名，输出格式不同）、`cat`→`Get-Content`、`grep`→`Select-String`、`find`→`Get-ChildItem -Recurse -Filter`、`rm -rf`→`Remove-Item -Recurse -Force`、`env`→`Get-ChildItem Env:`、`head/tail`→`Get-Content -TotalCount/-Tail`、`curl`→`curl.exe`（或 `Invoke-WebRequest`，注意 5.1 里 `curl` 是别名）、`python`→venv 的 `Scripts\python.exe`；
  - 引号规则：PowerShell 单引号字面量/双引号插值、`''` 转义、反引号转义；给外部程序传参时用 `--%` 或 `& 'path' args` 形式，避免嵌套引号碎裂；
  - 无 heredoc：`python - <<'PY'` 在 PowerShell 无效，改用 `@'...'@` here-string 写临时文件或直接用 file 工具写脚本再执行；
  - 换行与编码：脚本经 stdin 传输、输出已归一化 LF；若在 WSL 里跑脚本注意 CRLF（见 P7）；
  - 策略限制：默认策略拒绝 `;`/`|`/`$`/`%` 等元字符，长命令分次执行或配置 yolo/自定义策略；
  - `LINGTAI_SHELL` 环境变量与 init.json `shell_kind` 覆盖（`adapters/shell.py:91-94`），说明 5.1 现状与 pwsh 安装方法。

### P7【中】WSL 方言不归一化脚本 CRLF，Windows→WSL 脚本直接坏

- **现状**：`adapters/windows/wsl.py:39-42` `WslDialect.make_invocation` 把脚本原样交给 `wsl.exe -e bash -lc <script>`；CRLF 归一化只存在于**输出**侧（`__init__.py:1496` `text.replace("\r\n", "\n")`），**输入**脚本没有任何处理。cmd 方言的 `build_cmd_command_line`（`_shell_dialect.py:105-126`）同样不处理脚本内的 `\r\n`。
- **问题**：若模型生成的命令串含 `\r\n`（从 Windows 文件复制内容、或拼接了 CRLF 文本），bash 会把 `\r` 当作命令/参数的一部分，报 `$'\r': command not found` 之类的错——正是背景里“CRLF/LF 问题（Windows→WSL 脚本）”。
- **建议修复**：
  1. `WslDialect.make_invocation` 中先 `script = script.replace("\r\n", "\n").replace("\r", "\n")` 再构造 invocation（`wsl.py:39-42`）；
  2. 同理在 `build_cmd_command_line`（`_shell_dialect.py:126`）拼接前归一化脚本换行；
  3. 若脚本来自文件（file 工具写入），`file/_write.py:37` 走 `agent._file_io.write`，写入内容原样保存——建议 file 工具文档注明“脚本文件建议用 LF”，或在写 `.sh` 时按平台选择换行（需与 Rust sidecar 行为对齐，先文档化即可）。

### P8【中】`python3` / `~/.lingtai-tui/runtime/venv/bin/python` 等命令与路径硬编码在技能文档

- **现状**：见 3.4 表格——lingtai-doctor、sqlite-log-query、refresh-precheck、nokv-workbench PREFLIGHT、mcp-manual、scheduled-work、notification-reminders、debugging-cleanup、daemon inspection 等 9+ 处。
- **问题**：Windows 上 `python3` 常不存在（只有 `python` 启动器）、venv 解释器在 `Scripts\python.exe` 而非 `bin/python`、`~/.lingtai-tui` 展开为 `C:\Users\<you>\.lingtai-tui`（路径分隔符不同）；bash heredoc（`<<'PY'`）在 PowerShell 中不存在。
- **建议修复**：
  1. 关键技能（lingtai-doctor、sqlite-log-query）改为“优先用 `$LINGTAI_RUNTIME_PYTHON`/`LINGTAI_AGENT_DIR` 环境变量，或从 `lingtai` 包内解析解释器”，并给出 Windows 写法（`%LINGTAI_RUNTIME_PYTHON%` 或 `python`）；
  2. heredoc 示例统一改为“用 file 工具写临时脚本再执行”的跨平台写法；
  3. scheduled-work 增加 Windows 任务计划程序（schtasks）章节，至少注明 launchd/systemd/cron 章节仅适用 macOS/Linux。

### P9【低】`powershell_policy.json` deny 列表把 `curl`/`wget` 与真实可执行文件混淆

- **现状**：`tools/bash/powershell_policy.json:8` deny 了 `curl`、`wget`（还有 `iwr`/`Invoke-WebRequest`）。
- **问题**：pwsh 7 中 `curl`/`wget` 别名已被移除，`curl` 解析到 Windows 10+ 自带的 `curl.exe`（合法网络工具）；拒绝它等于把合法工具当成攻击面，agent 只能用 `Invoke-WebRequest`（也被拒）或绕道。该列表更像是从 5.1 时代（`curl` 是 `Invoke-WebRequest` 别名）照搬，与方言实际引擎（pwsh 7）不匹配。
- **建议修复**：`powershell_policy.json` 删除 `curl`/`wget`，或改为 deny 别名形态（如 `Invoke-WebRequest`/`iwr` 保留、`curl.exe` 放行）；如担心 `curl.exe` 下载执行链，可单独 deny `curl` + `|` 组合而非一刀切。顺带在 `get_description`/policy describe 中把 deny 摘要展示给模型，避免 agent 反复撞墙。

---

## 5. 给 Jason 的 PR 切分建议

按“先让 agent 不犯错，再补能力”的顺序：

1. **PR-A（文案一致性，纯文档/描述改动，低风险）**：P2.1 + P3.1（修正 sequencing guidance 与描述里的 `;`/`|`/`&&` 表述）；`_tool_family.py:60`、`__init__.py:584` 的 working_dir 示例改跨方言写法（`cd <dir>` 后分号/换行，或直接说“用 shell 自己的 cd”）；P5 的超时提示按方言分支。
2. **PR-B（shell-manual Windows 章节）**：P6 + P8 的文档部分——manual 新增 Windows/PowerShell 参考子页，批量修正 doctor/sqlite-log-query/mcp-manual 等的 `python3`/路径/heredoc。
3. **PR-C（策略扫描器收窄）**：P4（`%` 仅对 cmd-shim 命令拒绝）+ P2.2（恢复递归提取器，`;`/`&&`/`|` 作为分隔符解析、`$x`/`$()` 递归检查）——这是让 PowerShell 日常“能用”的关键改动，需补 extract_commands 的单元测试矩阵。
4. **PR-D（PowerShell 5.1 方言）**：P1——工作量最大，先做分类器探测 + 5.1 spawn 形态 + 引导文案；若暂不做，至少改进报错文案并文档化。
5. **PR-E（CRLF 输入归一化）**：P7——`wsl.py`/`build_cmd_command_line` 两三行改动 + 测试，独立小 PR。
6. **PR-F（策略列表修正）**：P9——一行 JSON 改动 + describe 展示。

## 6. 结论

Kernel 的方言架构本身是好的（检测、执行、策略、输出解码分层清晰），PowerShell 适配的**工程骨架已具备**；主要短板在**模型可见层**（描述/手册/提示词与策略不一致、无 Windows 指导）和**方言覆盖层**（5.1 缺失、WSL 输入 CRLF）。按 PR-A→PR-F 顺序推进，可以在不破坏 POSIX 路径的前提下显著改善 Windows PowerShell 上的 agent 体验。建议 PR 里给每条改动配一个“在 5.1 无 pwsh 机器 + pwsh7 机器 + POSIX 机器”三态验证用例，防止回归。
