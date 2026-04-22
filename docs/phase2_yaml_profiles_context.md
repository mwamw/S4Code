# Phase 2: YAML Profiles + Context Management

本阶段完成了 `S4Code` 的第一组产品化能力收口，重点是把“配置层”和“上下文层”真正接进产品主路径，而不是停留在 EasyAgent 内核可用、产品层未接线的状态。

## 本阶段完成了什么

### 1. YAML 配置替代 JSON

`S4Code` 现在默认使用：

- 全局配置：`~/.config/s4code/config.yaml`
- 项目配置：`<repo>/.s4code/config.yaml`

为了平滑迁移，解析阶段仍兼容旧的 `config.json`，但新的写入路径和约定都已经切到 YAML。

### 2. 多模型 profile

配置现在支持：

- `active_model_profile`
- `model_profiles`

也就是说，用户可以在同一个 YAML 里放多个模型来源，然后通过 `/model <profile-name>` 在会话里切换。

当前 `/model` 的行为：

- 不带参数：显示当前 profile、当前 provider/model、所有可用 profile
- 传入 profile 名：切换整套 provider/base_url/api_key/model 配置
- 传入非 profile 名：作为当前 profile 上的临时 `model` override

### 3. ContextManager 接入产品层

`S4Code` 现在不再只是裸 `BasicAgent`。构造 agent 时会同时挂上：

- `ContextManager`
- `history_via_context_manager=True`
- `LLMHistoryCompactor` 或 `RuleBasedHistoryCompactor`

默认策略是：

- 开启上下文管理
- 历史压缩器使用 `LLMHistoryCompactor`
- 压缩器用的就是当前 active model profile 对应的 `EasyLLM`

这意味着：

- 正常对话时，历史预算会按 `ContextManager` 逻辑管理
- 触发压缩时，不再是规则压缩优先，而是优先使用当前模型做历史总结
- 当用户通过 `/model` 切换 profile 时，history compactor 也会同步切换到新的 LLM

### 4. 上下文使用情况显示

新增 `/context` 命令，直接输出 `agent.get_context_usage()` 的结构化结果。

当前可以看到的核心字段包括：

- `max_tokens`
- `used_tokens`
- `remaining_tokens`
- `history_tokens`
- `stable_context_tokens`
- `compaction`

侧栏如果被打开，也会显示当前上下文用量摘要。

### 5. 压缩阶段显式展示

以前历史压缩是静默发生的。现在 `S4Code` 在产品层增加了 compaction runtime notice：

- 压缩开始时，会出现 `Context Compaction [RUNNING]`
- 压缩结束后，会更新成 `Context Compaction [DONE]`
- 文案里会带上 `before / after / budget / changed`

这部分不是硬编码在 TUI 里“猜测”出来的，而是通过产品层 hook 在 `before_compaction` 阶段发出 notice，再在下一次 agent 流事件到达时补充 compaction result。

## 这一步让框架发生了什么变化

变化前：

- `S4Code` 的模型配置只有一个 `llm`
- 只能改模型名，不能切 provider profile
- 没有真正接 `ContextManager`
- 没有上下文用量视图
- 压缩即使发生，UI 里也看不到

变化后：

- `S4Code` 已经具备 YAML 配置 + 多 profile 的真实产品层配置体系
- agent 运行时走 `ContextManager`
- 历史压缩默认用当前 profile 对应的 LLM
- `/context` 和 sidebar 都能看到上下文预算情况
- 压缩开始/结束会进入 transcript

## 一个具体过程例子

假设你的 `config.yaml` 是：

```yaml
active_model_profile: local-qwen
model_profiles:
  local-qwen:
    provider: openai
    base_url: http://127.0.0.1:5124/v1
    api_key: "122"
    model: qwen3.5-9b
  claude:
    provider: anthropic_native
    base_url: http://127.0.0.1:5124/v1
    api_key: "122"
    model: claude-sonnet-4

context:
  enabled: true
  max_tokens: 24000
  history_compactor: llm
  recent_turns: 4
```

然后在 TUI 里执行：

1. `/model`
2. `/context`
3. 连续做多轮代码任务，直到历史逼近预算
4. 当压缩触发时，transcript 会先出现 `Context Compaction [RUNNING]`
5. 压缩完成后，同一张卡会更新成 `Context Compaction [DONE]`
6. 再次执行 `/context`，可以看到 `compaction` 字段已经更新
7. 如果此时执行 `/model claude`，后续 history compaction 就会改用 `claude` profile 对应的 LLM

## 相关文件

- 配置模型与 YAML 解析：`s4code/config.py`
- context 接线与 compactor 构造：`s4code/easyagent_adapter.py`
- model/profile/context 命令逻辑：`s4code/query_engine.py`
- compaction notice hook：`s4code/runtime_hooks.py`
- transcript 压缩事件显示：`s4code/transcript_state.py`

## 手动验证入口

真实 example 在：

- `example/example_phase2_yaml_profiles_context.py`

这个 example 使用真实的：

```python
EasyLLM(
    provider="openai",
    base_url="http://127.0.0.1:5124/v1",
    api_key="122",
    model="qwen3.5-9b",
)
```

但本阶段实现没有执行它，只负责把例子落到仓库里，供后续手动调试。
