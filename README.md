# S4Code

S4Code 是一个面向真实代码仓库的本地优先代码智能体。它可以读取和编辑文件、运行 shell 命令、管理权限、恢复会话、加载技能、检查差异、跟踪后台任务，并在终端中展示完整的执行流程。

本仓库目前提供两个面向用户的前端：

- `s4code` / `s4`：Python 命令行工具 + Textual 终端用户界面 (TUI)
- `s4code-ts` / `s4ts`：基于 Ink 构建的 TypeScript 终端 UI，使用 Python 后端桥接

## 屏幕截图
### python
- ![1](./s4code/figure/1.png)
- ![2](./s4code/figure/2.png)
- ![3](./s4code/figure/3.png)
### ts
- ![1](./s4code/figure/33.png)

## S4Code 的适用场景

当您需要一个在实际代码库上工作而不是仅仅作为聊天外壳的智能体时，请使用 S4Code。

典型用例：

- 在编辑代码仓库前解释其结构
- 修复 bug 或失败的测试
- 审查差异代码以寻找回退（regressions）缺陷
- 运行命令并检查输出
- 利用检查点和会话恢复来管理多步骤的编码工作
- 处理高风险工具的审批工作流

## 前端

### Python 前端

Python 前端是稳定的默认用户入口点。

命令：

- `s4code`
- `s4`

这两者是等价的。

### TypeScript 前端

TypeScript 前端使用相同的 Python 后端和会话模型，但通过 Ink 渲染 UI。

命令：

- `s4code-ts`
- `s4ts`

这两者是等价的。

## 环境要求

### Python

- Python `>= 3.10`
- 已正确安装的 `EasyAgent`
- 有效的 S4Code 模型配置

### TypeScript 前端

- `bun >= 1.1`
- 包含上述的 Python 后端依赖

## 安装

### 1. 安装 EasyAgent

\`\`\`bash
pip install -e /path/to/EasyAgent
\`\`\`

### 2. 安装 S4Code

\`\`\`bash
pip install -e /path/to/S4Code
\`\`\`

这为您提供了以下命令：

\`\`\`bash
s4code
s4
\`\`\`

### 3. 安装 TypeScript 前端依赖

\`\`\`bash
cd /path/to/S4Code/ts
bun install
\`\`\`

如果您需要全局 TS 启动器，请为 `ts/bin/s4code-ts` 创建符号链接：

\`\`\`bash
ln -sf /path/to/S4Code/ts/bin/s4code-ts ~/.local/bin/s4code-ts
ln -sf /path/to/S4Code/ts/bin/s4code-ts ~/.local/bin/s4ts
\`\`\`

## 配置

S4Code 没有内置模型。在首次使用前，您必须配置至少一个模型配置文件。

全局配置目录：

\`\`\`text
~/.config/s4code/
\`\`\`

项目配置目录：

\`\`\`text
<project>/.s4code/
\`\`\`

支持的文件结构：

\`\`\`text
~/.config/s4code/config.yaml
~/.config/s4code/models.yaml
~/.config/s4code/context.yaml
~/.config/s4code/product.yaml
~/.config/s4code/ui.yaml
~/.config/s4code/mcp.json
\`\`\`

项目级文件使用相同的名称：

\`\`\`text
<project>/.s4code/config.yaml
<project>/.s4code/models.yaml
<project>/.s4code/context.yaml
<project>/.s4code/product.yaml
<project>/.s4code/ui.yaml
<project>/.s4code/mcp.json
\`\`\`

加载顺序：

1. 全局 `config.yaml`
2. 全局拆分配置文件
3. 项目 `config.yaml`
4. 项目拆分配置文件
5. 会话级覆盖设置

项目配置会覆盖全局配置。同一目录下，拆分的配置文件会覆盖 `config.yaml` 中的对应设置。

### 最小有效配置

`models.yaml`

\`\`\`yaml
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
\`\`\`

`context.yaml`

\`\`\`yaml
enabled: true
max_tokens: 24000
history_compactor: llm
recent_turns: 4
\`\`\`

`product.yaml`

\`\`\`yaml
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
\`\`\`

`ui.yaml`

\`\`\`yaml
theme: s4
show_thinking: true
right_panel_open: false
\`\`\`

`mcp.json`

\`\`\`json
{
  "servers": []
}
\`\`\`

如果 `api_key` 或 `base_url` 为 `null`，底层提供商可能仍会读取以下环境变量：

\`\`\`bash
export LLM_API_KEY="your-key"
export LLM_BASE_URL="https://api.example.com/v1"
export LLM_MODEL_ID="gpt-4.1"
\`\`\`

## 快速开始

### Python TUI

在代码仓库内运行：

\`\`\`bash
s4code
\`\`\`

或者指定一个代码仓库路径：

\`\`\`bash
s4code --cwd /path/to/repo
\`\`\`

### Python 一次性执行模式 (one-shot mode)

\`\`\`bash
s4code --prompt "Summarize this repository"
s4code --cwd /path/to/repo --prompt "Review the current diff"
\`\`\`

### TypeScript 交互式 UI

在任意位置运行：

\`\`\`bash
s4code-ts
\`\`\`

或者指定目标仓库：

\`\`\`bash
s4code-ts --cwd /path/to/repo
\`\`\`

该封装器默认将 `--cwd` 指向您当前的 shell 目录。

### TypeScript 一次性执行模式

\`\`\`bash
s4code-ts --prompt "/status"
s4code-ts --cwd /path/to/repo --prompt "Review the current diff"
\`\`\`

当使用 `--prompt` 但不跟 `--resume` 时，TS 前端会创建一个瞬态会话，以确保脚本化的一次性运行不会污染 `/session list` 列表。

## 常见工作流

### 探索代码仓库

\`\`\`bash
s4code --cwd /path/to/repo --prompt "Read this repository and explain the main flow"
\`\`\`

### 审查 Diff

Python CLI 快捷方式：

\`\`\`bash
s4code review
s4code review src/parser.py
\`\`\`

在交互式 UI 内部：

\`\`\`text
/diff
/review
/review src/parser.py
\`\`\`

### 恢复以前的会话

Python：

\`\`\`bash
s4code session list
s4code --resume <session-id>
\`\`\`

TypeScript：

\`\`\`text
/session list
/session load <session-id>
\`\`\`

### 诊断运行时问题

Python：

\`\`\`bash
s4code doctor
\`\`\`

TypeScript：

\`\`\`text
/doctor
/runtime
\`\`\`

## 交互式斜杠命令

TypeScript 前端目前暴露了最广泛的应用内命令。常用的高频命令包括：

### 核心命令

- `/help`
- `/status`
- `/quit`

### 会话管理

- `/session`
- `/session list`
- `/session load <session-id>`
- `/session checkpoints`
- `/session timeline`
- `/session tree`
- `/session rewind <checkpoint-id|index|last>`
- `/session fork [title]`
- `/session rename <title>`
- `/restore`

### 运行时和任务

- `/context`
- `/cost`
- `/trace`
- `/tasks`
- `/task <task-id>`
- `/task output <task-id>`
- `/task stop <task-id>`
- `/tools`
- `/runtime`
- `/doctor`

### 模型和权限

- `/model <profile-or-model>`
- `/models`
- `/permissions`
- `/permissions mode <mode>`
- `/permissions allow <tool> ...`
- `/permissions deny <tool> ...`
- `/permissions ask <tool> ...`
- `/permissions clear [session|all]`
- `/pending`
- `/confirm`
- `/deny [reason]`
- `/answer <text>`

### 技能

- `/skills`
- `/skills queue <skill-name>`
- `/skills clear`

### 工作区树和 diff

- `/worktree`
- `/worktree enter [name]`
- `/worktree exit [keep|remove] [discard]`
- `/diff [target]`
- `/review [target]`

### MCP 和代理

- `/mcp`
- `/mcp server <server-name>`
- `/mcp tools <server-name>`
- `/mcp resources <server-name>`
- `/mcp refresh [server-name]`
- `/mcp connect [server-name]`
- `/mcp disconnect [server-name]`
- `/agents`
- `/agent <agent-id>`

## Python CLI 命令

Python CLI 也直接暴露了少量直达命令：

\`\`\`bash
s4code review [target]
s4code commit
s4code config
s4code doctor
s4code session list
\`\`\`

## 用户界面说明

### Python TUI

Python TUI 是目前功能更丰富的终端产品。它包含：

- 用于展示对话轮次、工具、警告、错误、代码差异、检查点和运行时更新的历史记录卡片 (transcript cards)
- 用于项目、模型、权限、会话、还原状态、上下文、任务和代理的侧边栏面板
- 较旧记录卡片的紧凑渲染模式
- 修改文件的工具结果的结构化 diff 面板

### TypeScript 终端 UI

TypeScript UI 使用 Python 桥接协议，目前支持：

- 使用 Ink 进行标准的终端渲染
- 交互式提示词输入
- 斜杠命令和命令面板
- 用于对话交互、助手输出、推理思考和工具的实时对话历史卡片
- 简化版的工具卡片
- 后台任务摘要
- 工具卡片内的受限 diff 预览功能

## 环境变量

有用的覆盖项：

- `S4CODE_PYTHON`: TS 桥接所使用的 Python 可执行程序路径
- `S4CODE_BUN`: `s4code-ts` 包装器使用的 Bun 可执行程序路径
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL_ID`

TS 桥接解析 Python 路径的顺序：

1. `S4CODE_PYTHON`
2. `<project>/.venv/bin/python`
3. `<project>/venv/bin/python`
4. `python`

## 故障排除 (Troubleshooting)

### \`S4Code LLM configuration missing\`

您在全局或项目配置中没有可用的模型配置。请先添加 `models.yaml`。

### TypeScript interactive mode says it needs a TTY

交互模式下请使用真实的终端。若要进行非交互式调用，请使用 `--prompt`。

示例：

\`\`\`bash
s4code-ts --prompt "/status"
\`\`\`

### \`bun not found\`

安装 Bun，或者设置：

\`\`\`bash
export S4CODE_BUN=/path/to/bun
\`\`\`

### Session list is empty or sessions do not restore

请检查以下内容：

- 您是否使用了与之前相同的 config/data 主目录
- 会话自动保存是否已启用
- 您是否混淆了瞬态的 TS 单次运行会话与正常的已保存会话

### MCP shows no servers

如果 `mcp.json` 中没有配置任何服务器或者配置中禁用了 MCP，这是符合预期的。

## 开发者代码检查

Python 安装：

\`\`\`bash
pip install -e /path/to/S4Code
\`\`\`

TypeScript 检查：

\`\`\`bash
cd /path/to/S4Code/ts
bun install
bun run typecheck
bun test
bun run smoke
\`\`\`

## 当前状态

- 如果您希望拥有目前最完整的终端产品体验，请使用 `s4code`。
- 如果您想体验基于 Ink 开发的新前端，同时具有相同的后端和会话模型，请使用 `s4code-ts`。
- 上述两种前端都依赖同一套模型配置和代码仓库权限控制模型。
