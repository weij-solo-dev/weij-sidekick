# sidekick

一个有身体的桌面家庭管家 agent。sidekick 以单一常驻 Python 服务运行在 Mac mini 或树莓派上，用
[Reachy Mini](https://huggingface.co/docs/reachy_mini/index) 机器人作为眼、耳、嘴和表情，通过机器人本体和
Telegram、微信等远程渠道与家人交流。整体形态类似 OpenClaw：网关、渠道、自研的 agent 运行时（工具 / MCP / skills）、
记忆、自动化、心跳，机器人则是它的具身节点。

状态：**Phase 0–6 已完成，控制台 v3 已落地** —— 机器人听到"Bobby"会醒来聆听，用 MiniMax 以粤语作答，可被打断；自研 agent 具备工具、
从对话本身总结出来的记忆（L0 时间线 → L1 情节 → L2 每个人和全家的事实）、skills、MCP、提醒与心跳；Telegram 与微信（iLink）渠道、在场感知事件已接入；家庭成员可通过声纹与人脸识别；
扩展提供机器人工具、新闻简报、媒体中心与 Home Assistant。本地控制台以 **Live** 页开场，实时监视每个模块（摄像头实时画面、
按真实关节摆姿势的 3D Reachy Mini、交互状态、对话、进行中这一轮及其首字耗时、每个模块一张卡、活动流），**Robot** 页汇总机器人全部实时数据并可
"劫持"机器人测试动作、麦克风、扬声器、拍照与录像，持续录制最近 **24 小时**的视频、音频与遥测（5 分钟一片），并以
"幕后监制"方式回看（视频、多轨道、拖动时间轴、3D 姿态）。部署配置（`lite-mac`、`wireless`、`pi`）、开机服务与备份都在 CLI 中。
状态看板与路线图见 `PLAN.md`。coding agent 从 `AGENTS.md` 开始。English: `README.md`。

## 它要做什么

- 与每位家庭成员对话，通过声纹和人脸知道在和谁说话，记住对每个人重要的事。
- 陪伴孩子：带表情的讲故事、拿东西给它看就讲解、学习小游戏。
- 推送简报：新闻、天气、日程、追剧更新。
- 执行自动化：定时提醒与事件触发规则，当面或远程送达。
- 看护房间：在场、陌生人、警报类声音；向主人手机提供 `/look` 看一眼。
- 通过现成服务编排家庭媒体中心与智能家居（Jellyfin、qBittorrent、Home Assistant），而不是重新实现它们。

## 架构一览

```text
                         ┌─────────────────── sidekick 进程 ──────────────────────────────────────┐
  Telegram ──► channel ─►│   ┌─────── automation ────────────────┐      ┌─── dashboard ──────┐    │
                         │   │ 提醒 · cron · 事件任务            │      │ 每个模块一页       │    │
                         │   │ 心跳 · 自己的工具                 │      │ 看板 · 调用追踪    │    │
                         │   └─────────┬───────────────▲─────────┘      └────────────────────┘    │
                         │             ▼ 到点的任务    │ 调用 schedule（仅 main agent）           │
                         │   ┌─────── agent（蜂群）──────────────┐                                │
  语音 ────► interaction─┼──►│ main agent ──delegate──► subagents│                                │
   ▲  │                  │   │ dialogue · memory · 工具协议      │                                │
   │  ▼                  │   │ MCP · skills · 送达策略           │                                │
  body（Reachy 适配）    │   └───────────────┬───────────────────┘                                │
   ▲  │                  │                   │ llm · asr · tts  ◄── config（服务商 preset）       │
   │  ▼                  │   perception：在场 · 人脸 · 声音 ──► 事件任务   storage · log          │
  Reachy daemon :8000    └────────────────────────────────────────────────────────────────────────┘
  （电机、相机、麦克风、扬声器）                           ▲
                                                         │ API
                                        Jellyfin · qBittorrent · Home Assistant · 订阅源
```

分层与单向依赖规则（完整的允许导入表见 `AGENTS.md`）：

```text
L5  app.py · cli.py · dashboard · doctor
L4  automation                     任务、调度器、事件任务、心跳，以及它自己的调度工具
    extension + extensions/        robot · news · media · home：工具、MCP、skills、subagent、观察者
L3  agent                          main agent + subagents、dialogue、memory、工具协议、MCP、skills
L2  interaction · perception · contact · channel · record
L1  llm · asr · tts · vad · config · body
L0  log · storage · audio
```

所有模块遵守同一条组装规则：`app.py` 只负责创建各模块的会话，按依赖顺序调用 `setup`、`start`、`stop`，
不做别的；模块往别的模块上挂的任何东西（往 agent 登记工具、订阅感知总线、往渠道表注册适配器），都在它自己的
`setup` 里完成、在自己的 `stop` 里撤掉。`tests/test_architecture.py` 会解析 `app.py` 守住这一点。

## 一轮语音对话如何流转

```text
麦克风（16 kHz，硬件回声消除）──► body.AudioPump ──► interaction.frontend（Silero VAD，1 s 前置缓冲，
                                                     流式关键词识别"Bobby"）
        │ 语音片段 + 声源方向
        ▼
interaction.engagement  IDLE：本地 SenseVoice + 关键词识别 ─► 有名字？──否──► 记录追踪后丢弃
                        ENGAGED：同一说话人 / 同一方向？──────────────────► 接受
        │ 被接受的整句（此前绝不上云）
        ▼
interaction.pipeline    asr（本地 SenseVoice 约 0.1 s；MiniMax asr-1.0 作对照约 2.6 s）
                          │ 文本
                          ▼
                        agent.main（MiniMax 快槽位，流式；首 token 约 2.4 s）
                          │ 文本增量 ─► 句段（4 字后遇到第一个逗号即切）
                          ▼
                        tts primary（MiniMax 双向 WebSocket，所有轮次复用同一会话）
                          │ PCM 16 kHz 音频块
                          ▼
body.AudioPlayer（队列不超过 250 ms，实时增益用于压低）──► 机器人扬声器（随语音摆头）
```

2026-10-26 在 Lite 上实测：人说完后 3.0–4.8 s 听到第一个字，其中 LLM 首 token 占 2.1–3.0 s。每个判定
（接受、拒绝、压低、停止、回声）都带分值与音频片段入库，并显示在 dashboard 的"聆听监视"页。

打断：来自对话者方向的人声立刻压低播放；持续说话、停止词（停 / 等一下 / stop）、机器人名字或触碰天线会取消
播放和 LLM 流，打断的那句话成为下一轮；"嗯 / 好"之类的附和只会恢复音量。机器人通过比较麦克风听到的内容与
自己正在说的内容识别自己的声音，并把该方向学习为一个永不触发打断的扇区。注意力：麦克风阵列的声源方向让头
转向说话人，会话中由 daemon 的人脸追踪接管。所有动作都经过 `body` 中唯一的控制所有者。

## 远程对话与蜂群如何工作

```text
Telegram 消息 ──► channel.telegram ──► agent.main
                                            │
                       ┌────────────────────┼─────────────────────┐
                       ▼                    ▼                     ▼
                   直接回答           delegate(sync)        delegate(async)
                                            │                     │
                                            ▼                     ▼
                                      subagent "media"      subagent "news"
                                      工具：qbittorrent、    工具：订阅源、摘要
                                      jellyfin · MCP ·      skills：简报风格
                                      skills                      │
                                            │                     ▼
                                            ▼            结果 ─► 时间线（internal）
                                   结果 ─► main 组织回复        ─► 后续一轮转述
                                            │
                                            ▼
                               回复 ─► 原渠道（Telegram）
```

一份对话时间线存储所有渠道的全部消息。每条消息带 `speaker`、`channel`、`visibility`；LLM 每轮看到的是过滤后的
视图而非原始回放，孩子的聊天与大人的私密远程指令互不泄露。

## 自动化如何运行

```text
“八点提醒我吃药” ──────────► main agent ──► schedule 工具 ──► job {at 08:00, 提示词, 送达方式}
“有陌生人出现就告诉我” ──────────────────────────────────────► job {event: face.unknown}
                                        （automation 的工具，仅 main agent 可用）

perception 事件总线                       automation：调度器 · 事件任务
  在场 · 人脸 · 声音 · 订阅源 ──────────► 匹配触发 ─► 以 job 提示词运行一轮 main agent
  job.done · ha.state                              │
                                                   ▼
                                       agent：送达策略
                                   主人在房间里？──是──► 说出来（语音渠道）
                                           │ 否
                                           └────────────► 发送（Telegram）
```

`automation` 是位于 agent 之上的独立模块：任务库、调度器、事件任务和心跳都在这里；它的 `setup` 把调度工具
登记进 agent，并订阅感知总线。只有 main agent 能创建、取消和执行任务；subagent 是负责某个垂类的专家，看不到这些
工具。`automation.enabled` 是总开关，关掉后调度器、事件任务、心跳和这些工具一起停用，打开后立即恢复。

心跳（`automation/heartbeat.py`）是内置的周期任务：main agent 看看自上次心跳以来有没有家人还没听到的新消息，再决定说话、发送或保持沉默。
它不是供其他模块监听的系统节拍，没有模块依赖它。
提醒由提醒任务自己按时播报，心跳不会重复；心跳的提示里写明上次运行的时间和一天内已经主动说过的话，避免它翻来覆去。

## 服务商框架

每个供应商一个声明式 preset（`src/sidekick/config/provider_<id>.json`），固定的东西都在里面：按区域的端点、模型、
extra body、凭据字段、音色、能力位，覆盖 `llm`、`asr`、`tts`、`vad` 四个服务。本机模型也是一个普通的供应商
（`local`）。用户填凭据、区域和语言，并把每个服务**槽位**绑定到供应商：`llm.fast` 给 main agent，`llm.smart` 给
subagent，`asr.primary` / `asr.local`，`tts.primary` / `tts.fallback`，`vad.primary`。默认全部 MiniMax，换成
ElevenLabs 或本地模型只是改一个槽位。保存时用真实后端逐服务探测，错的 key
或音色当场失败。每次模型调用都写入 SQLite 追踪并在 dashboard 可见。这与 weij-scoop iOS 应用是同一套设计的 Python
实现。

## 扩展

核心之外的一切都是扩展：一个平铺目录加一份 `extension.json` 清单，通过同一套协议贡献工具、MCP 服务、skills、subagent
画像和事件观察者。内置扩展放在 `extensions/`（`robot`、`news`、`media`、`home`），用户安装的放在
`.derived_data/extensions/`。dashboard 负责列出、启用、禁用、配置和删除。

```text
extension.json ──► 加载器 ──► 注册表（启用状态、设置）
      │                           │
      ├── tools.py       ───────► agent 工具表        （origin = extension:<name>）
      ├── mcp.json       ───────► agent MCP 注册表
      ├── skill_*.md     ───────► agent skills 存储
      ├── subagent       ───────► agent 蜂群
      └── watchers.py    ───────► perception 事件总线
```

## 启动与停止 Bobby

命令行只负责启动和关闭 sidekick；Bobby 本身在 dashboard 上开关。

```text
sidekick startup ──► 进程：dashboard · 数据页面 · 就绪检查 · 服务         （sidekick close 结束它）
                          │
     电源控件 ──► 启动：阻塞框逐项打勾，每个模块自己证明能用
     （模块列表底部）    配置（密钥、槽位、磁盘）─ 缺任何一项：不启动，对应 tab 亮红点
                          模型（缺了就下载）
                          机器人   拉起 daemon · 唤醒 · 遥测 · 摄像头 · 麦克风
                          联系人 · 通道
                          语音     VAD · SenseVoice 已加载 · 唤醒词 · TTS 连通
                          agent    每个模型槽位真调用一次
                          自动化   （停止期间错过的提醒：立即补发）
                          感知 · 录像 · 扩展
                 └──► 停止：模块逆序停下；机器人睡下、daemon 退出、模型与连接释放；dashboard 保留
```

有模块证明不了自己（没有麦克风、模型槽位不应答）就中止启动，已经启动的部分会停回去；建议类问题（没配
Telegram、摄像头还在预热）照常运行并标出来。选择会被记住：只有上次是"运行中"，`sidekick startup` 才会把
Bobby 一起带起来；停止期间到点的提醒会在下次启动时补发，并说明是迟到的提醒。

## 控制台：每个 Tab 收拢自己的参数

没有全局的 Settings 页，也没有首次设置向导。参数放在能看到它效果的那一页（摆动滑杆挨着 3D 机身，VAD 阈值挨着判定
列表），由配置的 pydantic schema 生成表单，改完即生效；模块用到的服务（LLM 槽位在 Agent，ASR / TTS / VAD 槽位
在 Voice）也在该模块页配置，key 仍按服务商只存一份。向导由「就绪度」取代：一份「差什么、去哪补」的清单，从运行
状态实时算出，key 过期或机器人没插电都会自己出现在上面。

```text
模块     左侧一列，一个核心模块一项：Live · Voice · Body · Agent · Automation · Contact · Channel · Record ·
         Extension · System；每页是该模块的子模块看板，不再有固定的监视栏；内容多的页面顶部有一排视图，一次只显示
         一个，视图按钮上带关键数字（Agent、Voice、System、Channel）
Live     管"现在"（模块页管深度）：上排摄像头（MJPEG，暗时提亮，框出人脸）· 3D 机身 · 此刻（状态、对象、会话剩余秒数、
         电平、最近的判定）；下面左栏是对话（一屏高，所有渠道，只看不输入）和活动流（每个模块做了什么）；右栏是本轮卡
         （听到 / 说的话、到首字的时间、ASR → 首字 → TTS → 说话、每次工具调用一个标签）和每个模块一张卡：Agent · 服务 ·
         记忆 · 自动化 · 频道 · 系统 · 身体 · 感知 · 联系人 · 录制 · 扩展     ← /api/live：每秒 10 帧，每秒一次 live() + 活动
Body     左：3D 机身（SDK URDF 网格，实测位姿 + 关节），右边并排摄像头；遥测、控制器（"接管"后用滑杆控制头部 / 高度 / 机身偏航 / 天线，手势、表情）与测试（录麦克风、扬声器
         正弦 / 扫频 / 回放、说一句话、拍照、录视频）、表情卡（Bobby 自己的表情库、强度、思考预览）；右：身体参数（表现力、摆动与生动程度、注意力、daemon）  ← /api/robot/*
Voice    视图：Decisions（电平、对话状态、判定列表与音频片段）· Hear（VAD / ASR 服务卡、阈值、唤醒名、触发、
         词表、电视扇区）· Speak（TTS 服务卡、语言、句号后的停顿）· Traces（ASR / TTS 调用追踪）
Agent    视图：Swarm（每个 agent 一张卡片：主 agent 在最前，可看规则、工具并直接改参数；子 agent 自建的可新建 / 编辑 /
         删除，扩展带来的只读；下面是最近的 LLM 调用）· Tools（一个网格，按来源筛选）· MCP · Skills（每项一张
         卡片，点开是详情窗）· Memory（画像：每个人的事实及来源；按天排列的情节 → 原始对话；写入器）· Timeline ·
         Test（以家庭成员身份打字测试主 agent：回复、调用的工具、耗时）·
         Settings（LLM fast / smart 服务卡）
Automation  状态 · 调度器 · 主动开口 · 任务（提醒、周期任务、事件任务、心跳）
System   视图：Readiness（结论、檢查、未通过项、录制 / 服务商 / 运行时长、完整就绪表：本地 · 探测 · 回环）· Logs ·
         Config（控制台地址、备份、脱敏配置）
Channel  视图：Channels（Telegram token 与配对、微信、在场状态）· Events（感知总线事件）
录制     每 5 分钟一片：video.mp4（H.264 720p@10fps）· mic.wav · speaker.wav · telemetry.jsonl.gz · chunk.json
         保留 24 小时 · 磁盘余量下限
Replay   一天的分片条 → 分片视频 + 同步的两路音轨 → 轨道画布（包络、状态色带、对话 / 决策 / 事件标记）→ 拖动 →
         当时的 3D 姿态
```

## 记忆：Bobby 从一段对话里留下什么

```text
L0 时间线    每条消息都属于一段会话：客厅里前后相隔不到 5 分钟算同一段，聊天相隔不到 15 分钟算同一段
   │         —— 每一轮的提示词只看本段会话
   ▼ 会话结束（安静 5 / 15 分钟；很长的会话每 12 轮也写一次）—— 绝不在一轮对话进行中写
记忆写入器    一次 smart 调用 → 一条情节 + 候选事实 → 由代码规则决定留什么：
   │         只记有名字的人 · 私聊的内容只归讲的人、私密 · 全家的事实只来自公开的对话 ·
   │         健康 / 钱 / 感情只记本人亲口说的、私密 · 改变了就取代、不删除 · 测试卡、任务、子 agent 不写
   ▼
L1 情节      标题 · 摘要 · 跟进（第二天问「睇牙順唔順利？」）· 参与者 · 对应的会话
L2 事实      每个人一份、全家一份：类别 · 谁讲的 · 哪个渠道 · 明确要求 / 推断 · 到期日 · 来源；
   │         每晚 03:00：清掉过期的事 · 画像太长时写摘要 · 合并重复（超过四分之一就拒绝）
   ▼ 新一段会话开始
记忆块       从 SQLite 读一次就冻结 —— 一轮对话里不调模型、不检索：说话人的事实（私密的只在他自己的私聊里出现）、
             全家的事实、和他最近的几段对话、到期的跟进   ·   recall → 事实、情节、情节对应的原始对话
```

## 交朋友：陌生人怎样变成有名字的人

```text
未知声音 ──► person:N（声纹中心；声源方向与画面最大人脸吻合时也存人脸）
   听得够多（≥ 6 句跨 ≥ 2 次来访，或单次 ≥ 8 句）──► 事件 person.ready
   ──► automation「befriend」→ 主 agent 按 befriending skill：「你叫咩名？」→ 复述确认 →「想唔想我記住你？」
   ──► 工具 befriend(person_id, name) → 成为联系人，之前收集的声纹人脸全部保留 · 不需要 owner 批准
   7 天没再见 ──► 遗忘                        Contacts 页「見過的人」可手动 Befriend / Forget
   交朋友之前只存声纹和人脸：`remember` 不给 person:N 存记忆；名字和已有成员重名时另建一个联系人
   （爸爸_2），绝不合并（block #63）
```

认识的声音隔天也认得（block #80）：已注册的人只要达到门槛，就优先于更接近的 person:N；略低于门槛
（0.35–0.5）的声音不会被当成新的陌生人，同一段对话里有三句这样的话，就用它们的平均声纹再认一次；不到 1 秒的话
（比如只叫一声「Bobby」）不做识别；每句认出来的话都会继续学习进这个人的声纹；某个 person:N 后来被证明就是某位
联系人的声音（声纹中心相似度 ≥ 0.55）时会合并过去——只凭声音，绝不凭名字。

## 聆听：机器人何时回应？

```text
SLEEPING ──daemon 唤醒机器人──► IDLE ──触发──► ENGAGED ◄──► SPEAKING
   ▲                            ▲               │
   └──────── daemon 让其入睡 ────┴── 超时 / 再见 ─┘

IDLE     仅本地：VAD · 关键词识别 · SenseVoice 名字核对 · 声源方向 · 人脸     （不上云 ASR）
触发     "Bobby"（关键词识别器直接听麦克风流，或 SenseVoice 文本模糊匹配别名）· 触碰天线 ·
         机器人主动说话 ·（注视 + 已注册声纹：Phase 4）
ENGAGED  与某位对话者（声纹或方向）的会话；后续轮次无需再叫名字，直到 Bobby 说完后静默 8 s（Bobby 提问后
         为 15 s；在时限内开口的话一定算数）、"再见"或连续两次 NO_REPLY。只喊名字时 Bobby 立刻出声
         回应（"喺度！咩事呀？"）
SPEAKING 两段式打断：符合条件的人声先压低 −12 dB；说话 ≥ 0.9 s、停止词、机器人名字或触碰天线才真正停下；
         填充音、附和与机器人自己的回声永不打断
```

机器人从不自行唤醒或入睡：两者都由 Reachy daemon 负责——Bobby 的服务启动时拉起 daemon，服务停止时让它带着
睡姿动作退出。每次判定都带分值与
短音频片段写入追踪，dashboard 的"聆听监视"实时展示，阈值与触发方式用真实的家庭数据调，而不是猜。

### 张望与先开口

状态机之上有两层。**注意力层**从不说话：空闲时每 8–15 秒慢慢瞥一眼随机方向（相机只有 90° 视野），听到清晰的
声响就转头看是谁，看到人脸就把它保持在画面中央（我们自己的检测器以 10 fps 驱动一个经运动所有者的伺服，点头
照常叠加；空闲时不再有呼吸起伏）；说话时头会随自己的声音轻轻摆动——这是我们复刻 SDK 的 wobble，Body 页有「生动程度」滑杆（默认是
SDK 的三分之一），各轴幅度与频率都在 `body.sway` 里；**表情是 Bobby 自己的**：51 条偏移曲线（对话小动作、情绪、
表演、思考状态），叠加在注视之上播放，不带任何音效。对话里它听到你说话会轻轻点头，思考时头微微侧一下、天线轮流摆动
（想得久会慢慢换到另一侧，再"嗯"一下），视线始终留在你身上，说话时偶尔在新的一句点头，你说话停顿时轻轻"嗯嗯"点头；
情绪只在 agent 真有感受时才做（`[express:laugh]`，大多数回复没有），`[style:lively]`（讲故事、陪小朋友）或
`[style:calm]`（安慰、坏消息）只放大或收小那一段回复，家里的基准是 `body.expressiveness`；一张居中、正对相机并持续 2.5 秒的脸算作"对视"。Bobby 自己头部
电机转动期间开始并结束的声音会标记为自身动作，永远不会压低播放。**主动行为层**要经过 agent 和预算：认识的
家庭成员离开两小时后第一次对视会产生 `greet.due` 事件，robot 扩展的 `greet` 自动化让 agent 写一句简短的问候
（或回答 `NO_REPLY`）；Automation 页的"话多程度"（quiet / normal / chatty）决定这种事多久允许一次。声响和陌生人
永远不会让 Bobby 先开口。

## 仓库结构

```text
src/sidekick/
  app.py          组装所有模块（运行时）
  cli.py          `sidekick startup | close`（其余都在 dashboard 上）
  <module>/       每个核心模块一个平铺目录
    <module>.py   门面：模块的 Session 与公开 API，组装子模块
    <component>.py
    schemas.py · utils.py
extensions/       内置扩展，每个一个平铺目录
tests/            平铺的 pytest 文件，含强制单向依赖的架构测试
.derived_data/    运行时状态（git 忽略）：config.json、SQLite、日志、音频片段、模型、recordings/（24 小时录制）
AGENTS.md         harness 与模块黄页（给 coding agent）
PLAN.md           带时间戳的计划、决策、预研
```

## 快速开始

```bash
# 要求：Python 3.12、Poetry 2.x、USB 连接的 Reachy Mini Lite
# 所有命令在仓库根目录执行；状态保存在 ./.derived_data/
poetry install
poetry run sidekick startup     # 在后台启动 sidekick；打印 http://127.0.0.1:8787/
poetry run sidekick close       # Bobby 停止（机器人睡下），然后关闭 sidekick
```

全新的 home 会按主机生成第一份配置（macOS：USB 连接的 Lite；Linux ARM 板：树莓派配置）；设置了
`$MINIMAX_API_KEY` 时会顺手填入 key，方便开发。在 dashboard 上，System 列出还缺什么（MiniMax key 填在 Agent
页的服务卡上），模块列表底部的电源控件启动 Bobby；然后说"Bobby，今日天氣點呀？"或轻推天线。Telegram（bot
token、配对码）和微信（扫码登录）在 Channel，扩展在 Extension，备份在 System；没有机器人时，在 Body →
Daemon & connection 把 daemon 设成 mockup 仿真，或把机身设成 `null`。

## 许可

待定。
