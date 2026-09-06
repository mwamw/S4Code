# S4Code TypeScript

Ink 应用与外部 TypeScript SDK 是平级入口，共用无 UI 的 Bridge Client：

```text
Ink (src/) ────────────────────┐
                              ├→ packages/bridge-client → Python Bridge → Core
外部应用 → packages/sdk ───────┘
```

Ink 命令、卡片、checkpoint 属于 src/；SDK 和 Bridge Client 不依赖 React、Ink 或 Python terminal 层。

## Ink

```bash
bun install
S4CODE_PYTHON=/path/to/python bun run src/main.tsx --cwd /path/to/project
bun run src/main.tsx --cwd /path/to/project --prompt /status
```

Python 必须已安装 EasyAgent 和 S4Code。选择顺序：显式 python 选项、S4CODE_PYTHON、PATH 中的 python。不会自动搜索仓库内的虚拟环境或修改 PYTHONPATH。

--prompt 且未 --resume 时使用 transient session，普通只读 smoke 命令不自动保存空会话；显式保存和 checkpoint 命令仍有自己的持久化语义。

交互命令使用逐级菜单：输入 `/model` 后按 Enter，选择已配置的模型，再按 Enter 切换；
`/session` → Enter → 选择子命令，`load` 会继续列出会话，`rename` 会进入标题输入。
只有 Enter 确认才展开下一层；输入空格或 Tab 补全不会提前列出模型、会话等选项。
菜单不显示完整参数语法，每项最多一行，超出可用宽度以 `…` 省略。
↑/↓ 选择，Enter 确认，Tab 仅补全文本，Esc 或 Shift+Tab 返回上一级；完整命令也可以直接输入。

聊天记录由 Ink 直接渲染完整卡片列表，界面随内容增长，不使用固定高度视口、离屏字符串缓存或 TUI 自管翻页。
Esc 在运行时取消整条提交流程（包括准备阶段），Ctrl+C 关闭 bridge 后退出。

Ink checkpoint 的标签和引用保存在 `extensions.ink`，对话快照保存在 S4Code 数据目录的
`conversation-snapshots.db`，不再把整份历史反复传过 bridge。旧内嵌快照在加载时迁移，
自动保留最近 30 个；备份会话时也应备份该数据库。回溯仍只恢复对话，不撤销工作区文件或外部副作用。

## SDK 构建与使用

```bash
bun run build:sdk
# 在外部应用目录执行：
npm install /absolute/path/to/S4Code/ts/packages/sdk
```

构建输出包含 Node ESM 和 TypeScript 类型声明，不含 Ink；需要独立的 Python 运行环境。包尚未发布到 npm。完整用例见 [使用指南](../docs/usage.md)。

## 检查

```bash
bun run typecheck
bun test
bun run build:sdk
bun run smoke
```

Python 的 tests/test_cross_language.py 在隔离配置下测试 Bun SDK、构建后的 Node SDK 和 Ink 到真实 Python Bridge 的调用，不请求模型。

可使用 [bin/s4code-ts](bin/s4code-ts) 从其他目录启动，或设置 S4CODE_BUN 指定 Bun。架构和扩展规则见 [架构文档](../docs/architecture.md)。
