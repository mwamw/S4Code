# 外部如何使用 S4Code

## 安装

本工作区使用已经配置好的 conda 环境 S4Code：

```bash
conda activate S4Code
cd /home/wxd/LLM/FakeCC/S4Code
python -m pip install -e ../EasyAgent -e '.[tui]'
```

只有 CLI/SDK 时可安装 `-e .`，不需要 Textual。仓库位置不参与运行时模块查找；安装好后可从任意工作目录导入。下面的模型示例会调用配置的服务，可能产生费用；无模型的会话示例见 [example/sdk_usage.py](../example/sdk_usage.py)。

## Python SDK：客户端与会话

外部应用的入口是 SDK，**不是 S4CodeAgent**：

```python
from s4code.sdk import S4Code, RunOptions

with S4Code(cwd="/path/to/project") as client:
    session = client.sessions.create()
    result = session.run("解释这个项目的主要模块", options=RunOptions(max_iter=20))
    print(result.status, result.text)
    session.save(title="仓库分析")
    print(session.id)
```

不传 settings 时按项目/全局配置加载模型。也可由应用明确提供配置：

```python
import os
from s4code.sdk import S4Code, S4AgentSettings, LLMSettings

settings = S4AgentSettings(
    llm=LLMSettings(
        provider="openai", model="your-model",
        api_key=os.environ["OPENAI_API_KEY"],
    ),
    product={"permission_mode": "default", "enable_mcp": False},
)
with S4Code(cwd=".", settings=settings) as client:
    result = client.sessions.create().run("解释测试组织方式，不修改文件")
    print(result.text)
```

S4Code 有文件和命令执行能力，不是只读聊天 API。根据应用场景配置权限，不能用 bypass 替代用户批准。

### 恢复、列出、fork

```python
from s4code.sdk import S4Code

with S4Code(cwd="/path/to/project") as client:
    for info in client.sessions.list(limit=20):
        print(info.session_id, info.title)

    original = client.sessions.resume("EXISTING_SESSION_ID")
    branch = original.fork(title="另一个方案")
    print(original.id, branch.id)  # 两个独立会话，原对象不切换
    branch.save()
```

恢复拒绝其他项目的会话。保存的会话级 overrides 会参与配置合并；检查项目配置和保存的模型选择后再继续运行。未解决交互必须先处理才能 fork。close 关闭运行资源，不删除保存的记录。

### 结果、交互和异常

RunResult.status 为 completed、interaction_required、cancelled 或 failed。正常文本在 text；有待处理交互时在 interaction。执行异常也可能抛出 SDK 的 S4CodeError；不要只检查 text 非空来判断成功。

```python
from s4code.sdk import S4CodeError

try:
    result = session.run("运行相关测试")
    pending = result.interaction
    if pending:
        print(pending.interaction_id, pending.kind, pending.tool_name)
        print(pending.arguments, pending.details)
        # 将上述信息展示给用户，再收集 approve / deny / answer。
        # 这里演示用户已经选择拒绝，不自动批准任何工具。
        session.respond(
            pending.interaction_id,
            action="deny",
            answer="用户取消此操作",
        )
        # 如需继续：session.run("根据刚才的交互结果继续")
except S4CodeError as exc:
    print(exc.code, str(exc))
```

上例应在仍打开的 client/session 生命周期内使用。answer 用于回答提问；remember=True 可保存本次工具决定对应的会话规则。stale interaction_id 和重复响应会失败。BusyError、ClosedError、SessionNotFoundError、InvalidRequestError 均从 s4code.sdk 导出。

### 异步执行与事件流

```python
import asyncio
from contextlib import aclosing
from s4code.sdk import AsyncS4Code

async def main():
    async with AsyncS4Code(cwd="/path/to/project") as client:
        session = await client.sessions.create()
        async with aclosing(session.stream("解释当前模块")) as events:
            async for event in events:
                if event.type == "text_delta":
                    print(event.content, end="", flush=True)
                elif event.type == "run_finished":
                    print("\nResult:", event.data["status"])
        await session.save()

asyncio.run(main())
```

每个 RunEvent 都有 session_id、run_id、sequence、type、content、data。事件包括 round_start、reasoning_delta、text_delta、tool_call、tool_result、compaction_start/result、usage 和 run_finished；final 是 Agent 最终文本事实，run_finished 才是产品运行结果。不要将两者重复追加到 transcript。

不用流时可 `await session.run(...)`，直接获得 RunResult。另一个协程可 `await session.cancel(reason)` 请求停止，再等待流结束；提前 break 必须关闭生成器后再保存/关闭。取消当前消费任务会传播 CancelledError，同时清理运行资源。

异步 SDK 的运行与流是异步的，装配/持久化/审批仍调用同步 Core 操作；它不是保证所有管理操作都无阻塞的远程客户端。同步 Session 当前不提供同步 stream；需要流使用 AsyncSession。

## TypeScript SDK

仓库已有独立 SDK 构建包，尚未发布到 npm。先在 S4Code/ts 构建：

```bash
bun install
bun run build:sdk
```

然后在外部应用中安装本地包：

```bash
npm install /absolute/path/to/S4Code/ts/packages/sdk
```

Node ESM / Bun 应用：

```typescript
import { S4Code } from '@s4code/sdk'

const client = new S4Code({
  cwd: '/path/to/project',
  python: '/home/wxd/miniconda3/envs/S4Code/bin/python',
})
try {
  const session = await client.createSession()
  const result = await session.run('解释项目结构', {
    maxIter: 20,
    onEvent(event) {
      if (event.type === 'text_delta') process.stdout.write(event.content)
    },
  })
  console.log(result.status)
  await session.save('仓库分析')
  const branch = await session.fork('另一种方案')
  console.log(branch.id)
} finally {
  await client.close()
}
```

另有 resumeSession(id)、listSessions()；会话提供 pending()、respond(interactionId, action, answer)、cancel() 和 close()。TS SDK 通过共享 Bridge Client 启动 Python Core 服务，不加载 Ink，不要求导入 React，也不内嵌 Python。Python 选择顺序是显式 python 选项、S4CODE_PYTHON、PATH 中的 python；激活 conda 后 PATH 自然指向该环境。

请求超时/断线意味着结果可能未知，尤其不能自动重试已经开始执行的有副作用操作。S4CodeError 是 TS SDK 导出的产品通信错误。

## CLI 与两个 TUI

```bash
# Python CLI 直接使用 Core
s4code --cwd /path/to/project --prompt '解释这个项目'
s4code review src/parser.py --cwd /path/to/project
s4code session list --cwd /path/to/project
s4code doctor --cwd /path/to/project

# Textual 也直接使用 Core，不经过 Python SDK
s4code --cwd /path/to/project
s4code --cwd /path/to/project --resume SESSION_ID

# Ink：本地交互逻辑 → Bridge Client → Bridge Server → Core
cd /path/to/S4Code/ts
S4CODE_PYTHON=/path/to/python bun run src/main.tsx --cwd /path/to/project
```

Python CLI 的 --prompt 是自然语言，不解析 /status。Ink 的 --prompt /status 是无界面执行 Ink 本地命令。CLI 遇到待确认项会保存会话，输出 interaction_required JSON 并返回退出码 2；可由 Textual 恢复后继续处理。

checkpoint 自动取点、标签和回溯选择属于各 TUI，SDK 不被迫承担这些 UI 策略。回溯**不恢复文件、Git 或其他外部副作用**。

## 无界面 Bridge

```bash
python -m s4code.interfaces.bridge.server --cwd /path/to/project
```

stdin/stdout 每行一个 JSON。诊断写 stderr。先协商版本：

```json
{"request_id":"init","method":"initialize","params":{"protocol_version":1}}
{"request_id":"run","method":"core.stream","params":{"prompt":"解释测试结构","max_iter":20}}
```

可用初始化响应中的 session_id 操作默认会话，也可 core.session.create/open 管理其他会话。事件与最终响应的形状：

```json
{"request_id":"run","type":"event","event":{"run_id":"r","session_id":"s","sequence":1,"type":"text_delta","content":"...","data":{}}}
{"request_id":"run","type":"response","ok":true,"result":{"run_id":"r","session_id":"s","status":"completed","text":"..."}}
```

错误响应是 ok:false 和 error:{code,message}。方法参数严格校验；core.interaction.respond 必须指定 interaction_id。core.inspect 返回数据，不返回终端卡片。Bridge 没有 submit_prompt、execute_command、render_view、command_palette 等终端协议。

这是本地进程协议，不是经过认证的网络服务。协议版本目前是 1；有跨版本兼容要求的应用应固定 SDK 和 Python Core 版本。
