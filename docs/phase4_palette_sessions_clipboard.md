# Phase 4: Command Palette, Session Rename/Fork, and Clipboard Support

这一阶段收口的是 `S4Code` 的产品层交互问题，而不是 EasyAgent 内核。

## 本阶段完成了什么

### 1. Command palette 支持 Enter 选入

现在输入 `/` 后：

- `↑ / ↓` 用来移动当前选择
- `Tab` 用来把当前项插入输入框
- `Enter` 会按上下文执行两类行为

行为规则：

- 普通命令项：`Enter` 会把命令插入输入框
- 动态选项项：`Enter` 会直接接受当前选项

例如：

- 输入 `/re`，选中 `/review`，按 `Enter` 会把 `/review` 放进输入框
- 输入 `/model`，选中某个 model profile，按 `Enter` 会直接切换到该 profile
- 输入 `/resume`，选中某个 session，按 `Enter` 会直接加载该 session

### 2. `/model` 现在有真正的可选模型列表

palette 不再只列 slash commands。

当输入：

- `/model`
- `/model <prefix>`

会直接展示当前 YAML 里定义的 `model_profiles`。每一项会显示：

- profile 名
- provider
- model
- 当前 active profile 标记

然后可以直接：

- `↑ / ↓` 选择
- `Enter` 切换

### 3. Session 支持 rename / fork / load

新增并完善：

- `/session show`
- `/session list`
- `/session load <session_id>`
- `/session rename <title>`
- `/session fork [title]`

其中：

- `rename` 会更新当前 session 的 title，并立即持久化
- `fork` 会把当前 session 状态分叉保存成一个新的 session id，然后把当前 TUI 切到这个新 session 上继续工作

metadata 里现在也会保留：

- `forked_from_session_id`

### 4. Session 可以通过 Enter 直接选择加载

当输入：

- `/resume`
- `/resume <prefix>`
- `/session load`
- `/session load <prefix>`

palette 会展示保存过的 sessions，并带：

- session id
- title
- provider/model
- project root

当前活跃 session 会有 `*` 标记。  
选中后按 `Enter` 会直接加载，不需要再手敲完整 session id。

### 5. Transcript 支持复制

现在支持两种方式：

- `/copy transcript`
- `/copy last`

以及两组快捷键：

- `Ctrl+Shift+C`：复制完整 transcript
- `Ctrl+Alt+C`：复制最新一张 card

实现上优先使用 Textual clipboard API；如果环境不支持，会尝试：

1. `pyperclip`
2. OSC52

### 6. System 消息视觉收敛

system message 不再用高亮蓝色强调，而是改成更克制的 slate 风格，避免和真正的 assistant/user 内容抢视觉优先级。

### 7. 翻页时的 palette 选中态修复

palette 现在不再只依赖箭头字符提示，而是对整行做反色高亮。  
即使结果集翻页，当前选中项也不会“看起来消失”。

## 这一步让产品发生了什么变化

变化前：

- `/` 只能补命令名，不能稳定用 `Enter` 选入
- `/model` 看不到 profile 列表
- session 只能手打 id
- 没有 rename/fork
- transcript 不能稳定复制
- system card 颜色太抢眼

变化后：

- command palette 变成真正的选择式交互
- model/session 都支持动态项和 Enter 选择
- session lifecycle 具备 show/list/load/rename/fork
- transcript 可以复制
- system 通知退回到更克制的视觉层级

## 一个具体过程例子

1. 在 TUI 输入 `/model`
2. palette 直接列出：
   - `* local-qwen`
   - `claude-local`
   - `gemini-local`
3. 用 `↓` 选到 `claude-local`，按 `Enter`
4. TUI 会直接执行 `/model claude-local`
5. 然后输入 `/session fork review-branch`
6. 当前 session 会被分叉成新的 session id，并把 title 设成 `review-branch`
7. 再输入 `/resume`
8. palette 会列出最近 sessions
9. 选中某个旧 session，按 `Enter`
10. 当前 TUI 直接加载那个 session
11. 之后执行 `/copy transcript` 或 `Ctrl+Shift+C`，把完整 transcript 复制出去

## 相关文件

- `s4code/tui.py`
- `s4code/query_engine.py`
- `s4code/session.py`
- `s4code/commands/builtin.py`

## 手动验证入口

真实 example 在：

- `example/example_phase4_palette_sessions_clipboard.py`

本阶段没有执行 example，只负责把真实入口文件和产品代码落到仓库里。
