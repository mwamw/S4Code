# Phase 3: Pending Interactions, Confirmation, and AskUserQuestion

本阶段把 `S4Code` 里原本只是“显示一个 warning”的 interruption，补成了真正可操作的产品闭环。

## 本阶段完成了什么

### 1. 需要确认的工具不再只是中断提示

以前当工具返回 `needs_confirmation` 时：

- transcript 里只会出现一张 warning 卡
- `S4Code` 不知道如何继续
- 用户也没有固定入口去确认、拒绝或继续执行

现在已经补齐：

- `/pending`
- `/confirm [note]`
- `/deny [reason]`
- `/answer <text>`

这些命令会消费当前 session 中保存的 pending interaction，然后继续执行，而不是把中断当成终点。

### 2. AskUserQuestion 正式接入产品层

`S4Code` 现在会注册：

- `AskUserQuestion`
- `EnterPlanMode`
- `ExitPlanMode`

它们不再只是 EasyAgent 内核里“有这个工具”，而是已经进入产品实际工具集。

当模型触发这些交互类工具时，TUI transcript 会显示专门的 pending interaction 卡片，而不是一条模糊 warning。

### 3. 批准确认后，执行会从 pending step 继续

这一步的关键不是“确认一下然后重新问模型”，而是：

- 保留原本的 assistant tool call
- 用用户确认后的真实 tool result 替换之前的 `needs_confirmation` 结果
- 把这个 step commit 到历史
- 然后从该 step 后面继续 tool loop

也就是说，继续执行时不会额外插入一条新的用户 query 来污染对话历史。

### 4. EasyAgent 也补了底层能力

为了让 `S4Code` 真正能做“确认后继续”，这次补了两个框架层能力：

- `ToolRegistry.execute_confirmed_tool_result(...)`
  - 跳过 confirmation-only 的短路
  - 但仍保留正常的参数校验和硬性 permission deny
- `BasicAgent.resolve_last_tool_interrupt(...)`
  - 用真实 tool result 替换 pending interrupt 的占位结果
  - commit pending step
  - 清理 last interrupt

此外，tool loop 现在支持 `resume_from_history=True`，这样可以从当前 history 继续，而不是重新 append 一条用户输入。

## 这一步让产品发生了什么变化

变化前：

- interruption 只是一张 warning 卡
- 没有 `/confirm /deny /answer`
- AskUserQuestion 没注册到 S4Code
- 需要确认的工具没有办法继续执行

变化后：

- transcript 里会显示：
  - `Pending Confirmation`
  - `Ask User Question`
  - `Enter Plan Mode Request`
  - `Exit Plan Mode Request`
- 用户可以通过 slash command 解决当前 pending interaction
- 解决后，agent 会从 pending step 后继续执行
- pending interaction 会随 session snapshot 一起恢复

## 一个具体过程例子

假设模型调用了一个写文件工具，但当前模式要求用户确认。

执行链会变成：

1. assistant 先输出本轮分析
2. assistant 发起 `FileWrite(...)`
3. transcript 显示 `Tool · FileWrite`
4. 工具返回 `needs_confirmation`
5. transcript 出现 `Pending Confirmation [PENDING]`
6. 用户输入：

```text
/confirm
```

7. `S4Code` 会：
   - 执行这个已经被用户批准的 tool call
   - 用真实结果替换 pending interrupt 里的占位 tool result
   - 从这个 tool result 之后继续跑 tool loop

如果当前 interruption 是 `AskUserQuestion`，则流程是：

1. transcript 出现 `Ask User Question [PENDING]`
2. 用户输入：

```text
/answer 选择本地 qwen 配置并继续修改 CLI
```

3. `S4Code` 会把这条回答作为该 tool call 的真实 tool result
4. agent 再继续执行下一轮

## 相关文件

- 产品层恢复逻辑：`s4code/query_engine.py`
- 命令入口：`s4code/commands/builtin.py`
- TUI 处理：`s4code/tui.py`
- transcript 展示：`s4code/transcript_state.py`
- 框架层确认执行：`EasyAgent/Tool/ToolRegistry.py`
- 框架层 pending interrupt 解决：`EasyAgent/agent/BasicAgent.py`
- tool loop resume：`EasyAgent/agent/components/tool_loop_engine.py`

## 手动验证入口

真实 example 在：

- `example/example_phase3_pending_interactions.py`

它使用真实的：

```python
EasyLLM(
    provider="openai",
    base_url="http://127.0.0.1:5124/v1",
    api_key="122",
    model="qwen3.5-9b",
)
```

这个 example 不会自动执行，只作为后续手动调试入口。
