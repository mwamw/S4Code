# S4Code Phase 1 Foundation

## 本阶段完成了什么

这一阶段把 `S4Code` 从空目录推进成了一个可以真实启动的产品骨架，而不是再继续堆在 EasyAgent SDK 内部。

已完成的内容：
- 独立 Python 包：`s4code`
- 打包与入口：`s4code` / `s4`
- 基础配置系统：全局配置、项目配置、session overrides 合并
- 项目与 Git 检测：仓库根目录、分支、diff、文件列表
- EasyAgent 适配层：LLM、TaskService、ToolRegistry、CodeIntel、MCP、session store
- 默认 manager agent：文件工具、写入工具、shell、codeintel、多智能体 runtime、tasks、worktree
- Slash command 系统
- 非交互 CLI
- Textual 全屏 TUI
- 手动调试 example

## 现阶段框架形态的变化

在这一步之前，EasyAgent 只是框架。

在这一步之后，仓库里已经多了一个真正的产品层：
- 用户可以直接进入终端会话，而不是自己写一段 `BasicAgent(...)`
- 会话状态、配置、session resume、slash command 都成为产品概念
- code agent 相关的 runtime、task、codeintel、multi-agent 能力已经被统一收敛到一个 CLI 产品入口里

一句话概括：

`EasyAgent` 现在是内核，`S4Code` 是基于它的首个完整 code agent CLI 外壳。

## 具体例子

一个真实过程可以是：

1. 用户在 EasyAgent 仓库根目录执行 `s4code`
2. TUI 启动后，状态栏会显示当前项目、分支、模型、权限模式和 session id
3. 用户输入 `/review`
4. S4Code 不会把 `/review` 当成普通对话文本，而是把它转成一条结构化 workflow prompt
5. 这条 prompt 再交给 EasyAgent manager agent 执行
6. agent 会优先使用文件工具、git diff、codeintel、task/runtime 工具，而不是只靠聊天
7. 本轮结束后，session 自动保存，下次可以 `/resume <session-id>`

这个例子里，产品层负责：
- slash command 解析
- query routing
- session metadata
- TUI/CLI 展示

框架层负责：
- LLM 调用
- tool loop
- 权限
- task/runtime/team/mailbox
- codeintel
- session snapshot/restore

## 文件结构

关键文件：

- `s4code/config.py`
- `s4code/project.py`
- `s4code/session.py`
- `s4code/easyagent_adapter.py`
- `s4code/query_engine.py`
- `s4code/command_registry.py`
- `s4code/commands/builtin.py`
- `s4code/cli.py`
- `s4code/tui.py`

## 真实 example

手动调试 example：

- `example/example_s4code_foundation.py`

这个 example 使用的是真实 LLM 配置：

```python
EasyLLM(
    provider="openai",
    base_url="http://127.0.0.1:5124/v1",
    api_key="122",
    model="qwen3.5-9b",
)
```

实现步骤没有自动执行它，留给后续手动调试。

## 下一步

后续更适合继续补的是：
- 更完整的 workflow commands：`/review`、`/commit` 的本地 Git 工作流增强
- 更丰富的右侧面板：tasks、agents、mailbox、recent tools、cost
- 非交互命令的参数化能力
- GitHub 可选适配层
- 更强的会话配置编辑命令
