# S4Code 架构

## 依赖方向

```text
Python CLI ────────────────────────────────┐
Textual TUI → TerminalController ──────────┤
Python SDK → S4Code / Session ──────────────┤
                                          ▼
                                    S4Code Core
                                          ▲
Ink TUI → InkController ────┐              │
                           ├→ Bridge Client → Bridge Server
TypeScript SDK → S4Code ────┘
                                          │
Core → S4CodeAgent(BasicAgent) → EasyAgent 公共接口
```

Core 是产品主体；S4CodeAgent 只是其中负责 Agent 装配和执行的组件。CLI、Textual、Python SDK 是平级入口，分别使用 Core；Ink 和 TypeScript SDK 共用无 UI 的 Bridge Client，互不依赖。Bridge Server 不导入任何终端控制器、SDK 或 EasyAgent。

EasyAgent 承担推理循环、消息、上下文压缩、权限引擎、工具执行、会话快照和模块扩展机制。S4Code 直接继承 BasicAgent，并通过框架公开的 with_tool/with_context/with_skill/with_mcp 等接口装配代码产品；不建立 Bundle、EasyAgent adapter、QueryEngine 或另一套推理循环。

“产品装配归 Agent”不表示把所有 Core 能力放进一个 Agent 类。S4CodeRuntime 管理产品实例和会话生命周期，CoreSession 是入口层可用的会话边界，Agent 负责框架扩展与执行。通用框架机制应补在 EasyAgent；产品策略留在 Core；UI 策略留在各交互层。

## 当前代码结构

```text
s4code/
├── __init__.py                    # 包版本；不再导出 Agent 作为 SDK
├── core/
│   ├── application.py             # S4CodeRuntime：打开、替换、列出、关闭会话
│   ├── contracts.py               # SessionInfo / RunOptions / RunResult / RunEvent 等
│   ├── errors.py                  # 产品异常，与框架异常隔离
│   ├── agent.py                   # S4CodeAgent(BasicAgent)：产品装配、执行生命周期
│   ├── runs.py                    # RunService：运行、流、取消、交互结果
│   ├── observations.py            # 轮次/压缩等结构化运行事实，不生成 UI 文案
│   ├── inspection.py              # 工具、技能、任务、MCP、用量等结构化只读数据
│   ├── settings.py / configuration.py
│   ├── project.py / paths.py / prompting.py
│   ├── interactions.py / permissions.py / runtime.py / workflows.py
│   └── sessions/
│       ├── session.py             # CoreSession：产品会话及操作边界
│       ├── manager.py             # S4SessionManager：产品元数据、保存/恢复/fork
│       └── catalog.py             # 会话目录、项目过滤
├── sdk/
│   ├── client.py                  # S4Code / AsyncS4Code、会话集合
│   ├── session.py                 # Session / AsyncSession 外部会话对象
│   └── __init__.py                # SDK 公共导出：客户端、数据、异常、配置
└── interfaces/
    ├── cli/app.py                 # 无界面 CLI，直接使用 Core
    ├── terminal/
    │   ├── controller.py          # Textual 回合和交互协调，只访问 Core
    │   ├── commands/ / palette.py # Python 终端命令与补全
    │   ├── checkpoints.py         # 自动取点、标签、保留和回溯策略
    │   ├── transcript.py          # 终端卡片和历史展示
    │   ├── status.py / usage.py / runtime.py / mcp.py
    │   └── settings.py / theme.py / permissions.py / skills.py / ...
    ├── textual/app.py / diff_renderer.py
    └── bridge/
        ├── server.py              # NDJSON 传输、流任务和取消
        └── core_handlers.py       # 验证协议参数，调用 CoreSession / Runtime
ts/
├── packages/
│   ├── bridge-client/src/index.ts # 无 UI 的进程通信、请求关联、错误、协议版本
│   └── sdk/src/index.ts           # 面向外部 TS 应用的 S4Code / Session
└── src/                           # Ink 应用
    ├── controller/
    │   ├── InkController.ts       # UI 状态与命令协调
    │   ├── InkCoreClient.ts       # Ink 的 Core 数据展示与交互操作
    │   └── Checkpoints.ts         # Ink 自己的 checkpoint 策略
    └── commands/ / screens/ / components/ / state/ / ...
```

TerminalController 和 InkCoreClient 是各自 UI 的应用逻辑，不是 EasyAgent 适配层。它们只调用产品操作、处理产品数据，不持有框架管理器。Core 和 Bridge 都不解析 slash command、不返回侧栏/卡片/调色板。

## 会话、运行与 checkpoint

- S4CodeRuntime 可同时持有多个独立 CoreSession。每个会话一次只接受一个运行/修改操作，冲突返回 BusyError；停止或关闭流以后才能保存、切换模型或关闭。
- RunService 调用已有 Agent 执行器，把结果与交互统一为 RunResult；RunEvent 包含 session_id、run_id、sequence。轮次、压缩、文本、工具和用量是产品事实，终端自行渲染。
- 会话恢复拒绝跨项目。替换会话先成功装配新实例，再关闭旧实例；加载失败不会丢弃当前会话。
- fork 创建独立新会话，原会话保持不变。TUI 可选择切换，SDK 返回新的 Session。保留对话和权限，不继承运行中的 Agent、worktree、任务关联或待批准操作；有未解决交互时拒绝 fork。
- 待确认项使用 interaction_id。响应必须引用实际展示的那一项；旧 ID、重复处理、缺失交互会被拒绝。批准仍由真实用户决定。
- Core 提供带版本/会话归属的 ConversationSnapshot 导出、恢复、引用存储和命名空间扩展存储。自动 checkpoint、标签、30 个保留上限、选择时间点、回溯入口分别属于 Textual 和 Ink。
- Textual 数据放在 extensions.terminal；Ink 数据放在 extensions.ink。终端负责旧 checkpoint 格式迁移，Core 不理解扩展含义。
- Ink 通过 `core.conversation.capture` 保存快照，只传回 snapshot_id；`core.conversation.restore_ref` 按引用恢复，`core.conversation.delete_snapshots` 删除该会话的指定引用。快照数据库为数据目录下的 conversation-snapshots.db，需随会话数据一起备份。扩展读取支持字段投影，capture 支持通用 JSON 路径导入旧扩展值，避免迁移时传输大对象。
- Ink 的 CommandMenu 负责分级选择和参数输入，动态候选项只读取 Core 的模型/会话等产品数据。菜单不再经过第二套异步命令匹配覆盖。
- Ink 的 TranscriptPane 直接通过 TranscriptView 渲染完整卡片列表，保留卡片组件的 memo 比较；根布局随内容增长，不做固定高度裁剪、离屏字符串缓存或自管历史翻页。Core 的上下文估算仍按运行/修改边界失效，不在每个流式片段上重复计算。
- 回溯只恢复对话状态，**不撤销文件修改、Git 操作、进程或 MCP 的外部副作用**。fork 默认不复制 UI 扩展。
- 新建但未使用的会话关闭时不自动创建记录。自动保存失败保留脏状态和诊断，显式 save 失败会报告错误。

流必须消费到底，或通过 aclosing 显式关闭。Core 合并运行通知时只预取一个 Agent 流事件，防止慢消费者导致模型流无限堆积。Bridge 断线/关闭会使未完成请求失败，不自动重放可能有副作用的请求；请求超时不代表操作必然未执行。

## 对外与扩展边界

外部 Python 应用导入 `s4code.sdk`，不依赖 `s4code.core.agent`；TS 应用使用 `@s4code/sdk`。SDK 不暴露 Agent、EasyAgent 管理器或终端类，也不需要用户先构造 Agent。详细用法见 [使用指南](usage.md)。

新增产品能力放在 Core 的对应职责类；CLI/TUI/SDK 选择如何暴露它。新增 Textual slash command 放 terminal/commands；新增 Ink 命令放 ts/src/commands。新增通用机制改 EasyAgent 公共接口。简单配置处理和格式化仍可使用纯函数，不为面向对象而添加动态代理或无意义继承。

Bridge 是本地子进程协议，不是带认证的网络服务。协议版本目前为 1；尚未承诺跨版本兼容。TS SDK 的发布包不含 Ink，但需要安装 Python S4Code 运行环境。Python 异步 SDK 的 Agent 执行/流为异步接口；会话装配、保存和审批执行目前仍使用同步 Core 管理操作，大型嵌入式应用应留意这些操作对事件循环的影响。

本次本地 EasyAgent 版本为 0.7.2，补充已装配实例恢复、公共会话 fork 等通用接口；S4Code 依赖 easyagent>=0.7.2。版本更新和可安装构建不代表已发布到 PyPI/npm。旧 s4code.easyagent_adapter、query_engine、bridge、tui 等内部路径不保留转发层。

## 验证约束

架构测试检查 Core 不依赖接口/SDK、入口彼此平级、Bridge 不导入终端、接口不访问框架内部管理器、TS SDK/Bridge Client 不依赖 Ink。行为回归覆盖会话生命周期、fork、快照归属、过期交互、取消清理、流事件、两个 TUI 的命令和真实跨语言会话。

离线测试不等同于真实模型/MCP 的端到端验收；实际 provider、MCP 服务、终端键盘/渲染体验仍需在对应环境验证。
