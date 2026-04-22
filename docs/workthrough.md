# S4Code 整体执行计划

  ## Summary

  S4Code 定位为一个独立包、纯 Python、本地优先、以全屏 TUI 为主的 code
  agent CLI，底层全面复用 EasyAgent，产品层对齐 Claude Code 的核心能力而
  不是一次性追全量产品面。
  第一版目标是做到：能作为真实日常 coding agent 使用，具备 Claude Code
  风格的会话模式、slash commands、权限控制、session/resume、多智能体协
  作、code intelligence、MCP、review/commit/worktree 等核心能力。
  明确不纳入第一版主线的内容：remote session、voice、vim mode、buddy/
  mobile、plugin marketplace、云端账号体系。

  ## Key Changes

  ### 1. 产品形态与仓库边界

  - 新建独立产品包 s4code，不继续堆在 EasyAgent SDK 目录里；S4Code 只依
    赖 easyagent 公共 API，不依赖 EasyAgent 内部私有路径作为稳定边界。
  - 发布两个入口：
      - s4code：主命令
      - s4：短别名
  - 产品形态分两层：
      - interactive TUI：默认入口，Claude Code 风格全屏终端交互
      - non-interactive CLI：脚本/流水线/单次调用模式
  - 技术栈固定：
      - CLI 参数与入口：typer
      - TUI：textual
      - 终端富文本/表格/状态输出：rich
  - 每个实现阶段结束后都补：
      - docs/ 阶段文档
      - example/ 下真实 example
      - example 固定使用真实 EasyLLM(provider="openai",
        base_url="http://127.0.0.1:5124/v1", api_key="122",
        model="qwen3.5-9b")
      - example 不执行，只作为手动验证入口

  ### 2. 核心运行时适配层

  - 在 S4Code 产品层建立一层显式适配，而不是直接把 EasyAgent 的
    BasicAgent 暴露为产品对象。
  - 固定产品核心对象：
      - S4App：CLI/TUI 顶层应用
      - S4Session：当前对话会话和恢复语义
      - S4QueryEngine：单次用户输入到 agent 执行结果的总调度器
      - S4CommandRegistry：slash command 注册与分发
      - S4AgentFactory：构造 manager agent / subagent / verifier agent
      - S4ProjectContext：仓库根目录、worktree、git 状态、可见文件范围
  - S4QueryEngine 统一封装：
      - EasyAgent BasicAgent
      - ToolRegistry
      - PermissionContext
      - TaskService
      - ExecutionContext
      - AgentRuntimeManager
      - TeamManager
      - CodeIntelManager
      - MCP runtime
      - observability recorder
  - 统一会话状态：
      - 当前模型
      - thinking/effort 模式
      - permission mode
      - 当前 project/worktree
      - slash command 修改后的会话设置
      - session title / id / resume metadata
  - Session 持久化使用 EasyAgent 的：
      - SessionStore
      - ConversationStore
      - SessionRestoreReport
  - S4Code 额外持久化产品态：
      - 当前命令栏输入历史
      - UI 偏好
      - command-local state
      - 项目级配置与全局配置快照

  ### 3. 命令系统与交互契约

  - S4Code 同时支持两类“命令”：
      - 顶层 CLI 子命令：s4code ...
      - 会话内 slash command：/review、/commit 等
  - 命令兼容策略固定为：核心命令尽量沿用 Claude Code 同名和近似语义。
  - 第一版必须内建的 slash command 集合：
      - /help
      - /model
      - /config
      - /permissions
      - /plan
      - /resume
      - /session
      - /clear
      - /compact
      - /status
      - /cost
      - /files
      - /diff
      - /review
      - /commit
      - /tasks
      - /agents
      - /mcp
      - /memory
      - /hooks
      - /theme
      - /exit
  - 命令类型固定为三类：
      - local：只改本地产品状态，不发模型
      - workflow：执行一段固定工作流，可选触发模型
      - prompt-command：展开为结构化 prompt 进入主会话
  - 命令结果契约固定：
      - 可返回用户可见文本
      - 可返回“应继续发模型”的后续动作
      - 可返回对会话配置的更新
      - 可返回要追加到 transcript 的 meta message
  - 顶层 CLI 第一版必须支持：
      - s4code：进入 TUI
      - s4code -p "..."：单次 prompt
      - s4code --resume <session-id>
      - s4code review [path|commit|pr-ref]
      - s4code commit
      - s4code session list
      - s4code config
      - s4code doctor
  - TUI 交互契约固定：
      - 顶部：当前项目、分支、模型、permission mode、session id
      - 中部：消息流、tool 活动、agent/team 活动、diff/review 结果面板
      - 底部：输入框、slash command 提示、状态栏
      - 右侧可折叠面板：tasks、agents、mailbox、recent tools、context/
        cost

  ### 4. Code agent 能力面

  - 文件/代码工作流必须优先走 EasyAgent 的 builtin tooling 和
    codeintel，而不是让模型自己盲用 shell。
  - 第一版 coding 核心工作流固定支持：
      - 读文件、搜索、编辑、写入、notebook 编辑
      - shell 命令
      - worktree 进入/退出
      - codeintel：definition / references / symbols / diagnostics
      - task 创建/更新/列表
      - subagent 启动/等待/停止
      - team 创建/删除/发消息
      - mailbox read/ack
      - MCP tools/resources
  - review 工作流固定为本地 Git 优先：
      - 支持 review 当前未提交改动
      - 支持 review 指定 diff / commit range
      - GitHub PR review 作为可选适配层，不绑定第一版主链
  - commit 工作流固定支持：
      - 生成 commit message
      - 展示 staged/unstaged diff 摘要
      - 用户确认后执行 git commit
      - 可选继续 push/创建 PR 作为后续扩展，不纳入第一版强制验收
  - 多智能体固定采用 EasyAgent runtime，不额外造第二套协作引擎。
  - 角色最少包括：
      - manager
      - worker
      - verifier
  - verifier 是第一版正式角色，不是以后再补；当单轮工作涉及非平凡改动
    时，支持显式验证工作流。

  ### 5. 权限、配置、Git 与产品边界

  - 权限体系直接建立在 EasyAgent 之上，但产品层要补完整用户入口：
      - session permission mode 切换
      - 项目级 allow/deny 规则
      - 常用 shell / path / MCP server 白名单
      - TUI 权限弹窗与命令 /permissions
  - 配置体系固定分三层：
      - global config
      - project config
      - session overrides
  - 配置项第一版必须覆盖：
      - default model
      - thinking/effort
      - default permission mode
      - theme
      - GitHub integration toggles
      - MCP server presets
      - default reviewer/verifier behavior
  - Git 集成策略固定：
      - 本地 git 为一等能力
      - GitHub 为可选集成层
      - 无 GitHub 时，所有核心 coding workflow 仍可运行
  - 明确第一版不做：
      - 云端 remote session
      - 语音
      - vim mode
      - 插件市场
      - 手机/伴侣 UI
  - 但包结构预留这些扩展目录，不让后续重构命令系统或会话层。

  ## Delivery Plan

  ### Phase 1: 产品骨架与单会话 CLI

  - 建立 s4code 独立包、入口命令、基础配置、session 持久化、全屏 TUI 骨
    架。
  - 接通 BasicAgent + ToolRegistry + PermissionContext + SessionStore 的
    单会话闭环。
  - 做最小可用 slash command：/help /model /config /resume /status /
    exit。
  - 验收：能进入 TUI，发起一次真实 query，保存并恢复 session。

  ### Phase 2: 核心 coding workflow

  - 接文件工具、shell、diff、review、commit、worktree、codeintel。
  - 完成 /files /diff /review /commit /plan /compact。
  - 加本地 git 状态栏和 review 面板。
  - 验收：在真实代码仓库完成“读代码 -> 编辑 -> review -> commit”闭环。

  ### Phase 3: 多智能体与任务系统

  - 接 EasyAgent 的 task/runtime/team/mailbox。
  - 完成 /tasks /agents，并把 subagent 生命周期、mailbox 和 completion
    records 接进 UI。
  - 增加 verifier 角色与等待/停止逻辑。
  - 验收：manager 能起两个 worker，再等待汇总，并能在 UI 中看到 agent/
    task 状态。

  ### Phase 4: MCP、权限与配置产品化

  - 接 /mcp /permissions /hooks 和完整配置面板。
  - 加项目级和 session 级权限编辑入口。
  - MCP server 配置、连接状态、资源浏览进入 TUI。
  - 验收：用户能在 TUI 和命令层完成 MCP 接入、权限切换、规则查看。

  ### Phase 5: 非交互命令、GitHub 可选层与打磨

  - 做 s4code -p、s4code review、s4code commit、s4code session list、
    s4code doctor。
  - GitHub 集成只做可选层：PR reference 解析、可选 GitHub review/push/PR
    workflow。
  - 做文档、examples、安装与发布脚本、用户 README。
  - 验收：S4Code 可作为独立 CLI 安装、运行，并完成核心非交互工作流。

  ## Test Plan

  - CLI 入口
      - s4code 进入 TUI
      - s4code -p 正常返回
      - s4code --resume 可恢复历史会话
  - 命令系统
      - 核心 slash commands 可发现、可执行、结果显示正确
      - local/workflow/prompt-command 三类命令都覆盖测试
  - Session 与配置
      - 全局、项目、会话配置优先级正确
      - session 保存后恢复模型、权限模式、任务上下文
  - Coding workflow
      - 文件读写、搜索、编辑、shell、diff、review、commit 全链路可运行
      - codeintel 不可用时 fallback 行为稳定
  - 多智能体
      - subagent 启动、等待、停止
      - team 创建和 mailbox 读取/确认
      - verifier 工作流可执行
  - MCP
      - server 注册、工具可见、资源读取、连接关闭、恢复
  - 权限
      - plan / accept_edits / dont_ask / bypass 行为符合预期
      - 高风险工具会触发 ask/deny
  - UI
      - TUI 主界面、状态栏、command palette、task/agent 面板都有黄金路径
        测试
  - 文档与 examples
      - 每阶段文档存在
      - 每阶段 example 存在且只做语法/导入校验，不自动执行

  ## Assumptions

  - S4Code 是独立包，不直接并入 EasyAgent SDK 主包。
  - 第一版目标是 Claude Code 核心能力对齐，不是全量产品复制。
  - 主交互是全屏 TUI，非交互 CLI 是正式支持但不是主体验。
  - 命令命名尽量兼容 Claude Code 核心 slash commands。
  - 产品本地优先，不依赖云后端。
  - Git 本地工作流是一等能力；GitHub 是可选适配层。
  - 技术栈固定为纯 Python：typer + textual + rich + easyagent。