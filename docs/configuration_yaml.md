# S4Code YAML Configuration

`S4Code` 现在只认 YAML 配置，默认会按下面的顺序合并：

1. 全局配置：`~/.config/s4code/config.yaml`
2. 项目配置：`<repo>/.s4code/config.yaml`
3. session overrides：由命令或调用方临时传入，不会反写到 YAML

后面的层会覆盖前面的层。

## 最小可用示例

```yaml
active_model_profile: local-qwen

model_profiles:
  local-qwen:
    provider: openai
    base_url: http://127.0.0.1:5124/v1
    api_key: "122"
    model: qwen3.5-9b
    temperature: 0.2
    timeout: 120
    reasoning_effort: high
    reasoning_summary: auto

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
  session_auto_save: true

ui:
  theme: s4
  show_thinking: true
  right_panel_open: false
```

## 多模型 profile

推荐把不同来源的模型都写到 `model_profiles` 里，然后用：

- `/model`：查看当前 profile 和全部 profile
- `/model <profile-name>`：切换 profile
- `/model <literal-model-name>`：只临时覆盖当前 profile 的 `model`

例如：

```yaml
active_model_profile: local-qwen

model_profiles:
  local-qwen:
    provider: openai
    base_url: http://127.0.0.1:5124/v1
    api_key: "122"
    model: qwen3.5-9b

  claude-local:
    provider: anthropic_native
    base_url: http://127.0.0.1:5124/v1
    api_key: "122"
    model: claude-sonnet-4

  gemini-local:
    provider: google_native
    base_url: http://127.0.0.1:5124/v1
    api_key: "122"
    model: gemini-2.5-pro
```

## ContextManager 与历史压缩

如果你希望 `S4Code` 自动管理上下文并在超预算时使用当前模型压缩历史，需要：

```yaml
context:
  enabled: true
  max_tokens: 24000
  history_compactor: llm
  recent_turns: 4
```

含义：

- `enabled`: 是否启用 `ContextManager`
- `max_tokens`: 历史预算上限
- `history_compactor`: `llm` 或其他后备压缩器
- `recent_turns`: 压缩时保留的最近轮次数

当前产品行为：

- 只有真正超出历史预算时，才会显示 `Context Compaction`
- 压缩器使用当前 active profile 对应的 `EasyLLM`
- 切换 `/model <profile>` 后，后续压缩会自动改用新的 profile

你可以用 `/context` 查看当前：

- `max_tokens`
- `used_tokens`
- `remaining_tokens`
- `history_tokens`
- `last_history_compaction`

## 常用 product 配置

```yaml
product:
  permission_mode: accept_edits
  enable_codeintel: true
  enable_mcp: true
  enable_worktree: true
  command_timeout_ms: 120000
  max_background_tasks: 4
  session_auto_save: true
  default_review_depth: full
  enable_verifier: true
```

其中最常改的是：

- `permission_mode`
- `enable_codeintel`
- `enable_mcp`
- `session_auto_save`

## UI 配置

```yaml
ui:
  theme: s4
  show_thinking: true
  right_panel_open: false
```

当前版本里：

- `show_thinking` 决定是否展示模型思考相关信息
- `right_panel_open` 只是默认值；运行时仍可以通过命令控制

## MCP Server 配置

```yaml
mcp_servers:
  - name: docs
    server_source: python
    server_args:
      - -m
      - my_mcp_server
    transport_type: stdio
    tool_prefix: docs_
    auto_connect: true
    include_resources: true
    env:
      API_KEY: example
```

## 推荐做法

- 全局配置里放通用模型 profile 和默认权限模式
- 项目配置里放项目专用的 MCP、context budget、默认 review 风格
- 不要把临时 session 变更手写回 YAML；这类改动让 `S4Code` 自己保存在 session 里

## 相关命令

- `/config`: 查看当前生效配置
- `/model`: 查看或切换模型 profile
- `/context`: 查看当前上下文使用情况
- `/permissions`: 查看或切换权限模式
