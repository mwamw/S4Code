# S4Code

S4Code 是一个本地优先的代码 Agent CLI/TUI。它面向真实工程仓库工作：能读取和修改文件、运行命令、管理会话、处理权限确认、加载项目技能、启动后台任务、调用子 Agent、展示工具 diff、追踪每个模型 cycle 的指标，并把这些运行状态集中在一个终端产品里。

S4Code 的设计目标不是做一个简单聊天壳，而是把代码 Agent 需要的闭环能力产品化：

- 让模型能通过工具真正操作本地项目。
- 让用户能看到每轮模型 cycle、工具调用、耗时、token、cost、文件变更和 runtime 状态。
- 让每次写入、命令执行、权限确认、会话恢复、checkpoint rewind 都有可观察结果。
- 让交互式 TUI 和一次性 CLI 都能使用同一套会话、配置、工具和权限模型。

## 快速启动

### 1. 安装

在本地开发环境中安装 EasyAgent 和 S4Code：

```bash
pip install -e /home/wxd/LLM/EasyAgent
pip install -e /home/wxd/LLM/S4Code
```

安装后会得到两个命令：

```bash
s4code
s4
```

两者等价。

### 2. 配置模型

S4Code 不内置默认模型、默认 API 地址或默认 API Key。首次运行前必须提供模型配置，否则会直接报错。

全局配置默认路径：

```text
~/.config/s4code/config.yaml
```

项目级配置默认路径：

```text
<project>/.s4code/config.yaml
```

项目级配置会覆盖全局配置。最小可用配置示例：

```yaml
active_model_profile: default

model_profiles:
  default:
    provider: openai
    model: gpt-4.1
    api_key: null
    base_url: null
    temperature: 0.2
    max_tokens: null
    timeout: 120
    reasoning_effort: null
    reasoning_summary: null

context:
  enabled: true
  max_tokens: 24000
  history_compactor: llm
  recent_turns: 4

product:
  permission_mode: accept_edits
  enable_codeintel: true
  enable_mcp: true
  enable_worktree: true
  git_binary: git
  shell: bash
  command_timeout_ms: 120000
  max_background_tasks: 4
  session_auto_save: true
  default_review_depth: full
  enable_verifier: true

ui:
  theme: s4
  show_thinking: true
  right_panel_open: false

mcp_servers: []
```

如果 `api_key` 或 `base_url` 写成 `null`，底层模型客户端可以继续从环境变量读取，例如：

```bash
export LLM_API_KEY="your-key"
export LLM_BASE_URL="https://api.example.com/v1"
export LLM_MODEL_ID="gpt-4.1"
```

常见 provider 名称取决于 EasyAgent 当前支持的模型后端，例如 `openai`、`openai_responses`、`anthropic_native`、`google_native` 或其他兼容 provider。

### 3. 启动交互式 TUI

在项目目录运行：

```bash
s4code
```

指定工作目录：

```bash
s4code --cwd /path/to/repo
```

启动后可以直接输入自然语言任务，也可以输入 `/help` 查看命令。

### 4. 一次性运行 Prompt

```bash
s4code -p "总结当前仓库结构"
s4code --prompt "修复测试失败并解释改动"
s4code --cwd /path/to/repo -p "检查当前 diff 是否有明显 bug"
```

### 5. 常用工作流命令

```bash
s4code review
s4code review src/parser.py
s4code commit
s4code config
s4code doctor
s4code session list
s4code --resume <session_id>
```

## 核心交互方式

### TUI 主界面

S4Code 的 TUI 由四部分组成：

- Transcript：显示用户输入、模型回复、思考流、工具调用、工具结果、diff、checkpoint、runtime snapshot 和错误。
- Command Palette：输入 `/` 后展示命令和可选项，支持选择模型、session、skill、agent、task、checkpoint 等。
- Prompt Input：输入自然语言或 slash command。
- Sidebar：显示项目、分支、模型、权限、session、restore 状态、worktree、skills、context、任务和 Agent 状态。

快捷键：

- `Ctrl+C`：退出。
- `Ctrl+L`：清空当前屏幕 transcript。
- `Ctrl+Shift+C`：复制完整 transcript。
- `Ctrl+Alt+C`：复制最后一个卡片。
- `Up` / `Down`：在命令面板里移动选择。
- `Tab`：补全或插入命令面板选中的项目。

每次模型 invoke 完成后，TUI 会追加一条灰色分隔线，用于区分不同轮次的执行结果。

### Cycle 卡片

模型每轮执行会显示 `Cycle N` 卡片。Cycle 卡片实时更新，直到该轮模型完成或暂停。

Cycle 指标包括：

- 已运行时间。
- 工具调用数量。
- 正在运行的工具数量。
- 工具错误数量。
- pending confirmation 数量。
- 模型耗时。
- 工具耗时。
- input/output/total token。
- 估算 cost。
- 本轮使用过的工具。
- 本轮变更过的文件数量。

### 工具调用卡片

每次工具调用都会显示：

- 工具名称。
- 关键参数，例如 `file_path`、`command`、`cwd`、`agent_id`、`task_id` 等。
- 执行状态：running、done、pending、error。
- 结果摘要。
- 如果工具修改了文件，会显示结构化 diff。

文件 diff 展示包括：

- `+` 新增行绿色前缀。
- `-` 删除行红色前缀。
- 新增行整行偏绿背景。
- 删除行整行偏红背景。
- 按 hunk 独立块展示。
- 基于文件类型做语法高亮。

Bash 命令如果导致 git working tree 变化，S4Code 会在 Bash 工具结果里自动展示执行后的 working tree diff。

## 命令行入口

### `s4code`

启动交互式 TUI。

```bash
s4code
s4code --cwd /path/to/repo
s4code --resume <session_id>
```

### `s4code -p`

执行一次 prompt 后退出。

```bash
s4code -p "解释这个项目"
s4code --cwd /path/to/repo -p "运行测试并修复失败"
```

### `s4code review`

让 Agent 对当前 diff 或指定目标做 code review。

```bash
s4code review
s4code review src/service.py
```

Review 模式默认按代码审查思路输出：优先列出 bug、风险、行为回归和缺失测试。

### `s4code commit`

根据当前 diff 起草提交说明或提交方案。

```bash
s4code commit
```

### `s4code config`

输出当前解析后的配置。

```bash
s4code config
```

### `s4code doctor`

输出完整诊断信息，包括项目、模型、权限、restore、skills、runtime、工具面等。

```bash
s4code doctor
```

### `s4code session list`

列出 S4Code 保存过的 session。

```bash
s4code session list
```

## Slash Commands

Slash command 可以在 TUI 输入框中使用。输入 `/` 会打开命令面板。

### 基础命令

```text
/help
/status
/config
/doctor
/exit
```

- `/help`：列出所有可用命令。
- `/status`：以 JSON 形式显示当前 session、模型、权限、worktree、skills、context、restore 等状态。
- `/config`：显示解析后的配置。
- `/doctor`：显示完整诊断 payload。
- `/exit`、`/quit`、`/q`：退出 S4Code。

### 模型命令

```text
/model
/model <profile-name>
/model <literal-model>
```

用法示例：

```text
/model
/model default
/model claude
/model gpt-4.1
```

- 不带参数时列出模型 profile。
- 参数匹配 profile 名称时切换到该 profile。
- 参数不匹配 profile 时作为 literal model override 写入当前 session。

### 主题命令

```text
/theme
/theme list
/theme <theme-name>
/theme <theme-json-path>
```

用法示例：

```text
/theme
/theme ember
/theme ./themes/custom.json
```

- `/theme` 或 `/theme list`：列出可用主题，并标记当前主题。
- `/theme <theme-name>`：切换到内置主题，例如 `s4`、`graphite`、`ember`、`forest`、`aurora`。
- `/theme <theme-json-path>`：切换到项目内或绝对路径下的自定义 JSON 主题文件。
- 输入 `/theme ` 后命令面板会展示主题候选，选中后立即应用到当前 TUI，并写入当前 session override。

### Context 和压缩

```text
/context
/compact
/compact <max_tokens>
/compact partial <max_tokens>
/clear
```

- `/context`：显示当前上下文窗口、history token、compaction 状态。
- `/compact`：强制压缩当前 conversation history。
- `/compact 12000`：按目标 token 预算压缩。
- `/compact partial 12000`：等价于目标 token 压缩，用于局部/目标压缩入口。
- `/clear`：清空当前 conversation history。

### 成本、trace、restore

```text
/cost
/trace
/restore
```

- `/cost`：显示观测统计、近期 LLM/tool event 和 token/cost 信息。
- `/trace`：显示最近 turn 级 trace。
- `/restore`：显示当前 session 恢复报告，包括缺失工具、缺失 skill、恢复异常等。

### Session 管理

```text
/session
/session show
/session list
/session load <session_id>
/session resume <session_id>
/session rename <title>
/session fork [title]
/session timeline
/session checkpoints
/session rewind <checkpoint_id|index|last>
/session tree
/resume [session_id]
```

用法示例：

```text
/session list
/session load s4-myrepo-20260423-120000-a1b2c3
/session rename Fix Parser Regression
/session fork Try Alternative Refactor
/session timeline
/session checkpoints
/session rewind last
/session tree
```

行为说明：

- 新启动但没有任何实际对话或状态变更时，不会保存空 session。
- 当有模型执行、checkpoint、权限变更、会话重命名、fork 等状态变化后，会按配置自动保存。
- resume 后 TUI 会清空旧 transcript，并从恢复后的 session history 重建界面内容。
- fork 会生成一个新的 session id，并记录父 session。
- session tree 会显示当前可见 session 的 fork 关系。

### Checkpoint 和 Rewind

```text
/checkpoint
/checkpoint <label>
/checkpoint list
/checkpoints
/rewind [checkpoint_id|index|last]
/timeline
```

用法示例：

```text
/checkpoint before risky refactor
/checkpoints
/rewind cp-003
/rewind 2
/rewind last
/timeline
```

S4Code 会在模型 turn 前后自动生成 checkpoint。手动 checkpoint 可用于在高风险修改前保存恢复点。Rewind 会恢复 Agent conversation history 到指定 checkpoint。

### 权限命令

```text
/permissions
/permissions show
/permissions history
/permissions mode <default|accept_edits|dont_ask|bypass|plan>
/permissions allow <tool|*> [matchers]
/permissions deny <tool|*> [matchers]
/permissions ask <tool|*> [matchers]
/permissions clear [session|source|all]
```

权限模式：

- `default`：默认确认策略。
- `accept_edits`：偏向接受文件编辑，但仍可保留其他确认。
- `dont_ask`：尽量不询问。
- `bypass`：绕过大多数确认，适合受控环境。
- `plan`：计划模式，不直接执行写入类动作。

Matcher 支持：

```text
path=src
paths=src,tests
command=pytest
cmd=npm
host=example.com
hosts=example.com,api.example.com
mcp=server-name
server=server-name
risk=side_effect
equals:key=value
contains:key=value
source=session
desc=human-readable-note
```

用法示例：

```text
/permissions show
/permissions mode accept_edits
/permissions allow FileEdit path=src source=session desc=allow source edits
/permissions deny WebFetch host=unknown.example.com
/permissions ask Bash command=git
/permissions clear session
/permissions history
```

Pending confirmation 时还可以使用：

```text
/confirm
/confirm remember
/deny
/deny remember
```

- `/confirm`：本次确认通过。
- `/deny`：本次拒绝。
- `/confirm remember`：确认本次操作，并根据 pending tool 参数生成 session 级 allow rule。
- `/deny remember`：拒绝本次操作，并根据 pending tool 参数生成 session 级 deny rule。

### Pending Interaction

```text
/pending
/confirm [note|remember]
/deny [reason|remember]
/answer <text>
```

S4Code 支持三类暂停交互：

- 工具执行确认。
- AskUserQuestion 结构化问题。
- plan mode 进入/退出请求。

用法示例：

```text
/pending
/confirm
/confirm remember
/deny too risky
/answer Use Python and keep the public API unchanged.
```

### Plan Mode

```text
/plan
/plan on
/plan off
```

- `/plan` 或 `/plan on`：进入计划模式。
- `/plan off`：退出计划模式并恢复配置中的权限模式。

Plan mode 适合先让模型分析方案、列计划、评估风险，而不直接修改文件。

### 文件和 Diff

```text
/files [path]
/diff [target]
```

用法示例：

```text
/files
/files src
/diff
/diff HEAD~1
```

- `/files`：列出项目文件。
- `/diff`：展示当前 git diff。
- `/diff <target>`：展示相对于指定 git target 的 diff。

### Review 和 Commit 工作流

```text
/review [target]
/commit
```

用法示例：

```text
/review
/review src/parser.py
/commit
```

- `/review`：构造代码审查任务，让模型检查当前 diff 或指定目标。
- `/commit`：根据当前 diff 起草提交方案。

### 工具面

```text
/tools
/mcp
/hooks
```

- `/tools`：列出已注册工具，包括文件、搜索、Bash、任务、Agent、MCP、code intelligence、worktree、skill 等工具。
- `/mcp`：显示 MCP server 状态。
- `/hooks`：显示当前安装的 hook/guardrail。

### Runtime 面板

```text
/runtime
/rt
```

Runtime 面板展示：

- 当前 worktree 状态。
- runtime Agent 列表。
- structured task 列表。
- background task 列表。
- background task 的 stdout/stderr tail。
- context 使用情况。

模型执行过程中，runtime snapshot 会以卡片形式进入 transcript，并随工具结果更新。

### Skill 命令

```text
/skills
/skills list
/skills use <name>
/skills clear
```

Skill 加载来源：

- S4Code 主目录下的 `skills`。
- 全局数据目录下的 `skills`。
- 项目根目录下的 `skills`。
- 项目根目录下的 `.s4code/skills`。

用法示例：

```text
/skills
/skills use reviewer
/skills clear
```

行为说明：

- `/skills` 或 `/skills list`：列出发现的 skills。
- `/skills use <name>`：将 skill 加入下一轮对话的临时启用队列。
- `/skills clear`：清空下一轮 skill 队列。
- 每轮对话启用的 on-demand skill 会在本轮结束后清理。
- S4Code 注册了 `skill_tool`，LLM 可以根据任务自己查询、加载或激活合适的 skill。

### Worktree 命令

```text
/worktree
/worktree show
/worktree enter [name]
/worktree exit [keep|remove] [discard]
```

用法示例：

```text
/worktree
/worktree enter fix-parser
/worktree exit keep
/worktree exit remove
/worktree exit remove discard
```

Worktree 能力用于隔离高风险修改或并行尝试。退出时可以保留 worktree，也可以删除 clean worktree；如果需要强制丢弃改动，需要显式加 `discard`。

### Agent 命令

```text
/agents
/agent
/agent list
/agent show <agent_id>
/agent wait <agent_id> [timeout_ms]
/agent stop <agent_id> [reason]
```

用法示例：

```text
/agents
/agent show agent-123
/agent wait agent-123 5000
/agent stop agent-123 no longer needed
```

Agent runtime 用于多 Agent 协作、后台 Agent、子任务执行和结果跟踪。

### Task 命令

```text
/tasks
/task show <task_id>
/task output <task_id> [timeout_ms]
/task stop <task_id>
```

用法示例：

```text
/tasks
/task show task-123
/task output task-123
/task output task-123 10000
/task stop task-123
```

S4Code 同时支持两类 task：

- Structured Task：由任务服务管理，适合模型维护 TODO、执行计划和子任务状态。
- Background Task：由 Bash 后台进程管理，适合长时间运行的命令，例如测试、服务、构建、监听器。

### Sidebar 和复制

```text
/sidebar
/sidebar show
/sidebar hide
/copy transcript
/copy last
```

- `/sidebar`：切换右侧面板显示状态。
- `/sidebar show`：显示右侧面板。
- `/sidebar hide`：隐藏右侧面板。
- `/copy transcript`：复制完整 transcript。
- `/copy last`：复制最后一个卡片。

## 当前工具能力

S4Code 通过 EasyAgent 注册本地工具面。当前产品能力包括：

### 文件系统

- 读取文件。
- 写入文件。
- 精确替换文件片段。
- 编辑 notebook。
- 搜索文件和内容。
- 列出项目文件。
- 自动捕获 FileEdit/FileWrite 的 diff。

### Shell / Bash

- 执行前台命令。
- 启动后台命令。
- 查询后台命令输出。
- 停止后台命令。
- 展示 return code、stdout、stderr。
- 如果 Bash 导致 working tree 变化，自动展示 git diff。

### Code Intelligence

- 在支持的项目中启用 LSP/code intelligence。
- 提供 symbol-aware 的代码查询能力。
- 比盲目 grep 更适合定位定义、引用和结构化代码信息。

### Web Fetch

- 支持通过工具获取网页内容。
- 可通过权限规则限制 host。

### MCP

- 可以配置多个 MCP server。
- 支持 auto connect。
- 支持 MCP tools 和 resources。
- 支持按 server 名、tool prefix 管理工具面。

### Todo / Task

- 支持模型维护结构化任务列表。
- 支持任务创建、更新、查询、列表。
- 支持任务面板和 task command 操作。

### Multi-Agent Runtime

- 支持创建和管理 runtime Agent。
- 支持 Agent wait、stop、show。
- 支持后台 Agent 和输出文件。
- 支持和 task service 组合形成多 Agent 协作。

### Worktree Runtime

- 支持创建隔离 worktree。
- 支持进入、退出、保留、删除。
- 支持显示 active worktree 和 managed worktrees。

### Skill Runtime

- 自动发现多个目录下的 skill。
- 支持用户通过 `/skills use` 为下一轮启用 skill。
- 支持 LLM 通过 `skill_tool` 自主选择和加载 skill。
- 支持 resident skill 和 on-demand skill。

## 会话和持久化

S4Code 的 session 保存内容包括：

- EasyAgent conversation history。
- 当前 session metadata。
- 项目根目录、标题、分支。
- 模型配置 profile 信息。
- 权限模式和 session-scoped permission rules。
- checkpoints。
- fork 关系。
- restore report。
- skill 恢复信息。
- runtime 可恢复状态。

保存策略：

- 空启动不保存 session。
- 有实际对话、checkpoint、权限变更、session rename/fork 等状态变化后才保存。
- close 时只会保存 dirty session。
- 如果保存失败，会降级关闭 autosave，并在 startup/doctor 信息里显示问题。

恢复策略：

- `s4code --resume <session_id>` 或 `/session load <session_id>` 恢复已有 session。
- 恢复后重建 Agent、工具、权限上下文、skills、history。
- TUI 会重新加载恢复后的 history，而不是继续显示旧 transcript。
- 如果恢复时缺少工具或 skill，会在 restore report 中显示。

## 权限模型

权限由 mode 和 rules 共同决定。

Rule 结构：

```yaml
tool_name: FileEdit
behavior: allow
matcher:
  path_prefixes:
    - src
source: session
description: allow source edits
```

Behavior：

- `allow`：允许。
- `deny`：拒绝。
- `ask`：要求确认。

Matcher 可按路径、命令、host、MCP server、风险类别或参数精确匹配。

适合的使用方式：

- 对可信目录放宽 FileEdit。
- 对危险 Bash 命令保持 ask。
- 对未知 host 的 WebFetch 设为 deny 或 ask。
- 对本轮确认过的 pending operation 使用 `/confirm remember` 固化成 session rule。

## 配置参考

### LLM 配置

`provider` 和 `model` 必填。其他字段可省略，解析时会补为 `null`。

```yaml
active_model_profile: default
model_profiles:
  default:
    provider: openai
    model: gpt-4.1
  local:
    provider: openai
    model: qwen3.5-9b
    base_url: http://127.0.0.1:5124/v1
    api_key: local-key
    temperature: 0.2
    timeout: 120
```

切换模型：

```text
/model default
/model local
```

### Product 配置

```yaml
product:
  permission_mode: accept_edits
  permission_rules: []
  permission_history: []
  enable_codeintel: true
  enable_mcp: true
  enable_worktree: true
  git_binary: git
  shell: bash
  command_timeout_ms: 120000
  max_background_tasks: 4
  session_auto_save: true
  default_review_depth: full
  enable_verifier: true
```

### Context 配置

```yaml
context:
  enabled: true
  max_tokens: 24000
  history_compactor: llm
  recent_turns: 4
```

`history_compactor` 可使用 LLM 压缩，也可以切换为规则压缩实现。`recent_turns` 用于保留最近对话轮次。

### UI 配置

```yaml
ui:
  theme: s4
  show_thinking: true
  right_panel_open: false
```

`theme` 从 JSON 主题文件加载。内置主题包括：

```text
s4
graphite
ember
forest
aurora
```

也可以把 `theme` 设置为一个 JSON 文件路径，S4Code 会直接加载该文件。主题 JSON 可以覆盖 layout、cards、palette 和 diff 颜色；缺失字段会回退到 `s4` 默认主题。运行时可通过 `/theme` 在 TUI 内切换主题。

### MCP 配置

```yaml
mcp_servers:
  - name: docs
    server_source: python
    server_args:
      - /path/to/server.py
    transport_type: null
    tool_prefix: docs_
    auto_connect: true
    include_resources: true
    env: {}
```

## 推荐使用流程

### 日常开发

1. 在项目目录启动 `s4code`。
2. 输入 `/status` 确认模型、权限、项目根目录正确。
3. 输入自然语言任务，例如“修复这个测试失败”。
4. 观察 Cycle、工具调用、diff 和 runtime snapshot。
5. 用 `/diff` 或工具 diff 卡片确认改动。
6. 用 `/review` 让模型审查当前 diff。
7. 用 `/commit` 起草提交说明。

### 高风险修改

1. 输入 `/checkpoint before risky change`。
2. 如需要隔离环境，输入 `/worktree enter risky-refactor`。
3. 让模型执行修改。
4. 如果结果不对，输入 `/rewind last` 恢复对话上下文。
5. 如果 worktree 不需要，输入 `/worktree exit remove discard`。

### 长任务

1. 让模型用 Bash 启动后台任务。
2. 用 `/tasks` 查看 background task。
3. 用 `/task output <task_id>` 查看输出。
4. 用 `/runtime` 查看当前 runtime 状态。
5. 用 `/task stop <task_id>` 停止不需要的后台任务。

### 使用 Skill

1. 把项目专用 skill 放到 `skills` 或 `.s4code/skills`。
2. 输入 `/skills` 查看已发现 skill。
3. 输入 `/skills use <name>` 启用下一轮。
4. 提问或下达任务。
5. 本轮结束后 on-demand skill 自动清理。

### 权限收敛

1. 初期使用 `accept_edits`。
2. 对稳定路径添加 allow rule。
3. 对危险命令或未知 host 添加 ask/deny rule。
4. 遇到 pending confirmation 后，如果规则可复用，用 `/confirm remember` 或 `/deny remember`。

## 数据位置

默认数据位置遵循 XDG 目录：

```text
配置：~/.config/s4code/config.yaml
数据：~/.local/share/s4code
缓存：~/.cache/s4code
Session DB：~/.local/share/s4code/sessions.db
Task DB：~/.local/share/s4code/tasks.db
Agent 存储：~/.local/share/s4code/agents
日志：~/.local/share/s4code/logs
全局 Skills：~/.local/share/s4code/skills
```

项目级数据：

```text
项目配置：<project>/.s4code/config.yaml
项目 Skills：<project>/skills
项目 Skills：<project>/.s4code/skills
```

可以通过 `XDG_CONFIG_HOME`、`XDG_DATA_HOME`、`XDG_CACHE_HOME` 改变默认位置。

## 当前产品能力总览

- 交互式 TUI。
- 一次性 CLI prompt。
- Review workflow。
- Commit workflow。
- 模型 profile 管理。
- YAML 配置解析。
- 必填 LLM 配置，无硬编码模型/API 默认值。
- Session list/load/resume/rename/fork/tree。
- Resume 后 transcript 从恢复 history 重建。
- 空启动不保存 session。
- Checkpoint 自动生成和手动生成。
- Rewind 到 checkpoint。
- Timeline 查看 checkpoint 和 trace。
- Pending confirmation。
- AskUserQuestion。
- Plan mode。
- `/confirm remember` 和 `/deny remember` 权限记忆。
- Permission mode 和 session permission rules。
- 文件读写编辑工具。
- Notebook 编辑工具。
- Search 和文件列表。
- Bash 前台/后台任务。
- Bash 后 working tree diff 展示。
- FileEdit/FileWrite diff 展示。
- Diff hunk 语法高亮。
- Cycle 实时耗时。
- Cycle token/cost/tool/files 指标。
- Runtime snapshot 卡片。
- Sidebar runtime 信息。
- Structured task 管理。
- Background task 输出查看和停止。
- Multi-agent runtime。
- Agent show/wait/stop。
- Worktree enter/exit。
- MCP tool/resource 接入。
- Code intelligence 接入。
- Skill 自动发现。
- Skill next-turn 启用。
- LLM skill_tool 自主加载 skill。
- Context usage 查看。
- History compaction。
- Cost 和 trace 查看。
- Restore report。
- Doctor 诊断。
- Clipboard copy。
- 每次 invoke 后灰色分隔线。

## 常见问题

### 启动时报 LLM 配置缺失

说明没有配置 `model_profiles`，也没有提供 legacy `llm.provider` 和 `llm.model`。写入最小配置后重新启动。

### Resume 后看不到预期内容

确认使用的是正确 session id：

```text
/session list
/session load <session_id>
```

恢复后 TUI 会显示 `Restored Transcript` 卡片，并加载 session history。如果 restore report 显示缺工具或缺 skill，需要补齐运行环境。

### 不想自动保存

配置：

```yaml
product:
  session_auto_save: false
```

关闭后仍可通过会话相关操作显式保存当前状态。

### 命令执行时间太长

调整：

```yaml
product:
  command_timeout_ms: 300000
  max_background_tasks: 8
```

长时间运行的命令建议让模型以后台任务方式启动，然后用 `/task output` 或 `/runtime` 查看输出。

### 不希望模型直接改文件

切换到 plan mode：

```text
/plan
```

或者设置权限模式：

```text
/permissions mode plan
/permissions ask FileEdit path=src
/permissions deny Bash command=rm
```
