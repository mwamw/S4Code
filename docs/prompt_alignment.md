# S4Code 的 Claude Code 提示词对齐

## 来源与范围

对照本工作区的 `claude-code-sourcemap/restored-src`，版本为 Claude Code 2.1.88。
这是本地源码还原项目，不是对其官方开源授权状态的声明。S4Code 运行时不读取、导入或依赖这个参考仓库。

本次对齐的对象是完整的**模型指令栈**，不是只追加一段并行工具调用建议：

- Core 主 system prompt。
- 请求时的 `<system-reminder>` 上下文。
- 工具结果、技能加载、计划模式和压缩续接的运行提醒。
- 工具的长说明、简短描述、使用指导和参数 schema 描述。
- 压缩历史时单独调用模型所使用的英文指令。

主提示词以 Claude Code 面向外部用户的默认分支为基准，保留其章节和主要措辞；不合并 Anthropic 内部用户分支、实验模式和互斥功能开关。系统指令使用英文，但默认仍用中文回答用户。用户的 S4.md、技能正文、对话、代码和 MCP 远程说明不做翻译。

## 归属与装配

`s4code/core/prompting.py` 的 `S4_SYSTEM_PROMPT` 是产品主提示词。`S4PromptComposer` 使用 `include_defaults=False`，不调用 EasyAgent 的默认行为规则装配。

EasyAgent 的 `SystemPromptComposer.build_capability_blocks()` 只提供已安装能力的上下文，不添加身份、通用任务规则、安全规则或默认回答风格。S4Code 显式选择英文能力说明。恢复旧会话时，即使保存的 `includeDefaults` 为 true，也不会重新启用框架默认规则。

主 system prompt 与 reminder 分开进入请求编译器。CLI、Textual TUI、Ink bridge 和 SDK 共用 Core 的这条装配路径，不各自维护另一份主提示词，也没有增加 EasyAgent adapter。

## 对应关系

下表中 Claude 源路径相对于参考仓库的 `restored-src/src`，EasyAgent 路径相对于 `../EasyAgent`。

| 指令类别 | Claude Code 来源 | 当前实现与触发条件 |
| --- | --- | --- |
| 身份、安全、工程任务、谨慎执行、工具策略、风格和输出效率 | `constants/prompts.ts`、`constants/cyberRiskInstruction.ts` | S4Code `core/prompting.py`；主 system prompt |
| 项目指令、环境、日期 | `constants/prompts.ts`、`utils/messages.ts` | S4Code 的 `s4_md`、`s4_environment`、`current_date` reminder；使用真实项目、平台、shell、模型配置和日期 |
| 可用技能目录 | `utils/messages.ts` 的 `skill_listing` | EasyAgent `skill/manager.py`；仅在有可用技能时注入目录，不预加载正文 |
| 已调用技能正文 | `utils/messages.ts` 的 `invoked_skills` | EasyAgent `skill/manager.py`；调用后用 reminder 包裹正文，保持当前 invoke 生命周期 |
| 进入计划模式的完整工作流 | `utils/messages.ts` 的 `getPlanModeV2Instructions` | EasyAgent `plan/models.py`、`plan/manager.py`；进入时注入五阶段工作流 |
| 计划模式持续提醒 | `getPlanModeV2SparseInstructions` | EasyAgent prompt composer；每次请求根据当前 plan 状态生成，历史压缩或清空不会丢掉当前只读约束 |
| 退出计划模式 | `utils/messages.ts` 的 `plan_mode_exit` | EasyAgent `plan/models.py`；实际退出后注入，仍受当前权限约束 |
| 自动压缩可用性 | `utils/messages.ts` 的 `compaction_reminder` | 安装 ContextManager 时注入；不承诺无限上下文 |
| 压缩摘要与续接 | `services/compact/prompt.ts` | EasyAgent `context/compressor/history.py`；英文摘要覆盖用户意图、技术、文件、错误、已完成工作、用户消息、待办、当前工作、下一步；生成摘要后注入续接提醒 |
| 文件读取安全提醒 | `tools/FileReadTool/FileReadTool.ts` | EasyAgent `Tool/builtin/filesystem.py`；读取非空文本时附加原文安全提醒 |
| 空文件、越界 offset、输出截断 | `tools/FileReadTool/FileReadTool.ts`、`utils/messages.ts` | EasyAgent FileRead；仅在实际空、越界或截断时提醒，原始文件数据不被提醒文本污染 |
| 延迟工具可见性 | `utils/messages.ts` 的 deferred tools 提醒 | EasyAgent prompt composer、`tool_schema_tool` 和 executor；列出当前工具，展开后通知本轮可用 schema |
| 工具临时上下文与协作消息 | `utils/messages.ts` 中的工具／协作附件机制 | EasyAgent 既有 ephemeral context 和 mailbox 生命周期；用英文 reminder 包裹真实运行信息，不编造完成通知 |
| 文件、搜索、Shell、Web、Agent、Skill、Plan、任务等工具 | `tools/*/prompt.ts` 及相应工具源码 | EasyAgent `Tool/builtin`、`Tool/claude_compat/models.py`、`skill/tool.py`、`plan/tools.py`；模型可见说明与参数描述使用英文 |

Bash 的说明还包含原有的提交与 PR 工作流、Git 安全规范、独立信息收集的并行指令和依赖操作的先后顺序，而不只是一个通用的“请并行”句子。

## 必须保留的实现差异

这些是能力或协议差异，不是重新设计一套系统行为规范：

- `Read/Edit/Write/Skill/ToolSearch` 对应现有的 `FileRead/FileEdit/FileWrite/skill_tool/tool_schema_tool`，参数以真实 schema 为准。
- FileRead 当前支持文本和 PDF 文本，不宣称可向模型传递视觉图片。行号分隔符是 ` | `，Notebook 按 JSON 读取。PDF 按现有实现使用 20 页限制。
- 计划模式没有独立的可写 plan 文件，也没有固定注册的 Explore/Plan agent 类型；计划在对话中呈现，通过 ExitPlanMode 请求调用方批准。
- 技能正文与临时工具只在当前 invoke 有效，不能照搬 Claude 的整段会话持续激活语义。
- 后台 Bash 任务用 TaskOutput 获取状态；后台 Agent 用 AgentGet/AgentWait/AgentList。不能照搬“自动收到完成通知，因此绝不检查结果”。SendMessage 不会自动恢复已结束的 agent。
- 文件修改保留 EasyAgent 既有的读前置与版本检查，不能用提示词取消权限检查。
- 压缩器保留现有 JSON 字符串数组协议，不改为 Claude 的 analysis/summary XML 输出格式；不添加无限上下文承诺或不存在的 transcript 文件路径。
- Git 的 stage、commit、status，以及 branch、push、PR create 有先后依赖；没有照抄参考源码中这些步骤也写作 parallel 的矛盾措辞。
- SDK 不保证终端渲染、弹窗或 slash command，因此主提示词不承诺特定 TUI 行为。配置的 hooks 和审批仍由真实 Core／调用方协议决定。
- 可选 MemoryManage 使用 EasyAgent 实际启用的 working/episodic/semantic/perceptual 类型，不宣称存在 Claude 的文件式 auto-memory 目录。

## 没有伪造的条件提醒

“完整”不表示把参考仓库里的所有条件分支同时发给模型。以下内容需要对应的运行能力和触发状态，本次没有通过文字冒充实现：

- IDE 的选区／打开文件、浏览器、语音、远程会话等专属附件。
- writable plan 文件引用、Claude 专属 auto-memory 文件及记忆整理 agent。
- Anthropic 内部用户、undercover、KAIROS／proactive、实验输出模式等分支。
- 未实际生成的后台完成通知、团队配置路径、MCP server instructions 增量、token/effort 预算通知。
- “最近没有使用任务工具”、外部文件被用户或 linter 修改等需要专门状态追踪的提醒。当前保留任务工具使用规范及真实文件版本检查，不编造其触发历史。

本次不修改模型 provider、不修改工具参数协议、不修改并发调度器。因此，英文提示词明确允许一次返回多个独立工具调用，但不把这一改动视为工具已实现真正并发的证明。

## 验证

离线测试覆盖 Core 主提示词完全替换、旧会话恢复、reminder 状态、内置工具 schema 英文检查、MCP 原文保留、文件结果提醒，以及同步／异步压缩的 JSON 协议。不需要启动 Claude Code 或调用真实模型。

主要回归测试：S4Code 的 `tests/test_system_prompt.py`、`tests/test_core_agent.py`，以及 EasyAgent 的 `test/test_english_prompts.py` 和既有工具、技能、计划模式、请求编译与缓存测试。
