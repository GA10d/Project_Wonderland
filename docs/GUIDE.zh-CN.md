# Wonderland 使用与开发指南

[English README](../README.md) · [简体中文 README](../README.zh-CN.md)

在 Mac 本地运行的 Python 像素场景生成器。输入关键词或中文描述，使用 OpenAI 规划场景，复用本地 LimeZu 素材，生成缺失资源，再进入世界走动、碰撞和进出房屋。

## 现在怎么打开

在 Finder 双击 `Launch_Wonderland.command`，或在项目目录运行：

```bash
.venv/bin/python -m wonderland
```

创作台可以输入/粘贴中文描述、选择示例、生成场景、查看进度和打开历史世界。已经生成的世界可离线探索；只有生成新的内容需要网络。

双击入口会自动建立并打开 `build/Wonderland.app`，Dock 中显示为 Wonderland；重复打开复用同一个应用实例。应用运行输出保存在 `logs/desktop.log`。创作台随窗口等比缩放，缩小窗口后所有按钮仍可访问。

- WASD / 方向键：移动。
- 在门前面向门，按 E：进入对应室内；走到室内下方出口，朝下按 E 返回。
- 室内出口覆盖整个门洞，走到最下方仍可按 E 出门；已有世界也适用。
- F1：查看碰撞和门口触发区。
- F2：在游戏或创作台保存当前窗口画面到 `screenshots/`。
- Esc / 右下角「返回创作台」：返回创作台；再次探索会保留本次应用运行期间的房间与位置，关闭应用后重新从出生点开始。
- 点击「开始探索」或场景预览：进入场景；输入框未聚焦时也可按 Enter。Tab 切换输入框焦点，生成完成后 Enter 可直接探索。
- 创作台中 ⌘/Ctrl + Enter：生成；⌘/Ctrl + A：全选描述；⌘/Ctrl + V：粘贴。
- 创作台中 F3 /「查看生成日志」：查看阶段、API 耗时和检查结果；滚轮翻页，Esc / 右上角「关闭」关闭。
- 创作台每两秒检查新保存的场景；F5 /「刷新」可立即更新历史列表。其他窗口生成的新结果会出现在「最近的世界」，不会覆盖正在编辑的描述。
- 历史列表通过左右箭头翻页；同名但不同 seed 的世界分别保留。

原型文本框的光标目前在末尾，支持追加、退格、全选替换和中文 IME；尚未实现鼠标定位光标及完整富文本编辑。

## 第一次安装

需要 Python 3.11 或更新版本。Mac 自带的 Python 3.9 不满足要求。本次已在本地建立 Python 3.12 的 `.venv`。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m wonderland assets --import --scan
.venv/bin/python -m wonderland doctor
```

`requirements.lock` 锁定本次验证使用的依赖版本。也可以使用 `pip install -e '.[dev]'` 按 `pyproject.toml` 安装开发环境。

## 密钥、模型与生成限制

支持项目根目录 `key.env` 中单独一行 API key，或 dotenv 格式：

```dotenv
OPENAI_API_KEY=你的密钥
```

环境变量 `OPENAI_API_KEY` 优先。程序不会执行环境文件，不打印密钥；此文件及全部原始/派生美术、数据库和生成世界均已加入 `.gitignore`。

`config.toml` 当前选择本次账户列出的质量优先模型：

```toml
[models]
llm_model = "gpt-6-astra"
image_model = "gpt-image-2.5-sunburst"
image_quality = "high"

[generation]
max_new_assets = 3
max_image_attempts = 2
```

每个缺失资源最多尝试两次；每次图片还会由文本/视觉模型检查。这里是调用数量上限，不是美元费用硬上限。`data/jobs/<id>.json` 保存最新状态、计划和结果路径，`logs/<id>.jsonl` 追加记录每次运行的阶段、API 模型、耗时、usage、request ID、素材检查与异常位置。日志不保存请求头、密钥或图片 base64；重试保留事件历史并清除旧错误。同一任务有进程锁，避免重复启动覆盖状态。

生成失败会显示「本次生成失败，未产生新场景」；保留的旧预览明确标注为「历史场景」。修改描述后，预览也会标注为历史场景，直到新请求成功。旧版本任务只有 JSON 状态快照，不能追溯未记录的事件。

`logs/studio.jsonl` 记录创作台实例启动、历史列表刷新、场景加载成功或失败、鼠标点击与坐标换算、探索开始/返回、房门切换和异常，便于区分「没有生成」「界面没显示」和「探索入口失败」。选中历史场景后，F3 会关联该场景的生成日志，不再被上一次生成任务覆盖。

摆放失败日志包含素材名称、目标区域、已放/请求数量，以及越界、建筑遮挡、碰撞、入口预留和道路水面等拒绝原因计数。区域中心放不下时，程序会搜索该方向的其余可用空间，仍然保留完整数量和通路检查。

修复程序后，可指定原任务 ID 重试，保留原计划、已验证素材和日志历史：

```bash
.venv/bin/python -m wonderland retry 6e13d0d2b1e619e7
```

所需素材已经入库时不会重新生图；任务仍缺计划或素材时会继续相应 API 步骤。

素材处理 v2 保留小面积的醒目颜色（如收银机绿屏），仍使用 16 像素/格、64 色物件调色板、二值透明和最近邻 2 倍显示。已接受的素材不重做；失败候选可复用原图，写入独立版本文件。视觉检查按最终像素尺寸评估，必须保留物件、视角、主要部件及用户明确要求；模型自行增加的小字、价签和购物袋精确数量可简化。

视觉检查缓存包含最终图片、参考图、检查指令与模型的指纹。未改变的失败候选重试时会复用检查结果，避免重复调用；图片或规则改变后才重新检查。连续失败仍会报错，不会把被拒绝的候选强制入库。

```bash
.venv/bin/python -m wonderland doctor --api
```

会使用密钥读取可见模型列表，不生成内容。模型在列表中不代表每次内容请求必然成功；正式调用还受账户配额等条件影响。

## 场景生成与离线游玩

完全不调用 API 的本地样板：

```bash
.venv/bin/python -m wonderland demo --play
```

使用 OpenAI：

```bash
.venv/bin/python -m wonderland generate \
  --prompt '松林里有一间小屋，门前有水井，屋内有床、桌椅和壁炉。' \
  --seed 91 --play
```

也支持 `--prompt-file /absolute/path/prompt.txt`。生成命令打印具体 `worlds/<id>/world.json` 路径。随后用该路径运行：

```bash
.venv/bin/python -m wonderland play worlds/<id>/world.json
.venv/bin/python -m wonderland render worlds/<id>/world.json --scene interior_0 --out screenshots/room.png
```

重复同一输入、seed 和流程版本会读取已保存结果。已经接受的生成素材进入全局素材库，新的描述也能引用它。正在进行的请求无法通过关闭窗口撤销计费；取消会在 API 返回后的检查点停止后续步骤。

场景保存时复制所用图片并固定元数据，因此以后更新素材库不会改变旧世界。播放不依赖原始素材目录或 API，但需要保留整个对应世界文件夹，并保持在本项目 `worlds/` 下。

## 素材库

本地原始包包括 Modern Exteriors、Modern Interiors、Modern Farm、Modern Office 和 RPG Maker 导出。运行时采用 **32×32 格子、16 像素美术密度、最近邻 2 倍放大**；房屋和树木可以跨多格。

`assets/manifests/limezu.json` 保存首批人工核对的资源定义。`assets/normalized/` 保存规范化图片，`data/assets.sqlite` 提供检索，`assets/previews/catalog.png` 是可用素材联系表。

首次扫描索引了约 1.3 万个原生资源；首批 142 个可用资源条目包含 28 个角色帧、20 个基础/物件资源及 94 个道路/水面边角图。生图资源会继续增加。

已补充 11 个办公室定义：两种含电脑、桌椅的完整工位，以及打印机、咖啡台、饮水机、服务器、白板、办公椅、盆栽、垃圾桶和地板。工位通过 manifest 的 `canvas` / `layers` 组合原始像素素材。素材标注文件变动后会自动更新目录，并使旧计划缓存失效。办公室采用四个工位区与中央通道；都市使用灰色铺装。

**原始索引和可用素材有区别。** 原始图片没有自动获得可靠的语义、占地与碰撞。未标注条目可以搜索、检查，但不会直接交给 agent 放置。当前 agent 从已验证目录挑选，缺少可直接使用的资源时进入生图流程。后续可逐步扩大人工标注目录，减少生图次数。

```bash
.venv/bin/python -m wonderland assets --search 木屋
.venv/bin/python -m wonderland assets --search tree --raw
.venv/bin/python -m wonderland assets --import
```

新增本地素材的方法见 `assets/README.md`。原始文件不移动、不覆盖；Git 只保存程序和我们编写的标注数据。美术作者：**LimeZu**（https://limezu.itch.io/），具体使用范围以本地素材包许可为准。

## Agent 与程序分工

1. Responses API + Pydantic 将描述转成 `SceneSpec`，包含建筑、家具、数量、区域及缺失资源。
2. 模型只能选择可用资源 ID；道路、草地、池塘、室内墙地板由编译器提供。
3. 缺失物件由 Images API 生成，转换到标准画布、透明与像素密度，再做技术和视觉检查。
4. Python 根据 seed 放置建筑、连接道路、布置家具与装饰，计算边角图块。
5. Python 检查实际角色碰撞体能否从出生点到门口，以及出口目标是否安全。
6. 验证通过才保存场景快照；pygame-ce 负责之后的移动、碰撞、排序和 E 键进出。

生成素材原图、规格化结果、模型检查和请求来源保存在 `assets/generated/<id>/`。失败候选不会变为可用资源。首版的生成建筑采用固定的正面中央入口模板；生成地形支持平面材质，暂不产生高差与特殊玩法。

## 测试与当前边界

```bash
.venv/bin/python -m pytest -q
```

Mac 原生显示回归测试（会短暂打开窗口）：

```bash
WONDERLAND_NATIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_render_alpha.py
```

该测试覆盖 Cocoa 窗口的 alpha 合成、窗口高度受限后的预览，以及加载预览时保留原窗口。普通测试使用 dummy 显示驱动，另覆盖窗口缩放后的实际点击、Retina 坐标映射和返回后继续探索，无法单独验证 Mac 窗口像素格式问题。

测试覆盖多个 seed、真实素材的碰撞与通路、进出往返、按键去重、低帧率移动、三栋小屋的独立室内、场景快照、素材复用、透明处理和尺寸规范。另已调用真实 API 验证场景规划和缺失素材生成。

第一版范围：64×48 格室外、最多三栋建筑、每栋一个 18×16 格室内；移动、实体碰撞、室内外进出、保存与重新打开。地图生成使用区域约束和模板，不支持任意精确空间关系、多层楼/楼梯、桥梁、高差、NPC 行为或无限地图。需要的物件放不下会报错，不悄悄删除。

当前视觉检查能筛除明显错误，不能保证所有生成素材都达到手绘美术质量。家具碰撞用矩形模板，房屋结构与室内大小是游戏抽象，不保证建筑学意义上的内外一致。

架构设计：`lectotype/SCENE_GENERATOR_PLAN.md`；Tilemap 原理：`lectotype/README.md`。

Office 生成失败的定位、修复与复验记录：`lectotype/OFFICE_GENERATION_DEBUG.md`。

创作台探索入口与实机试玩修复记录：`lectotype/PLAYTEST_FIXES.md`。

雪山布局失败与任务恢复记录：`lectotype/SNOW_LAYOUT_DEBUG.md`。

Joja 超市素材检查失败与处理方案：`lectotype/JOJA_ASSET_DEBUG.md`。

API 参考：[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) · [Image generation](https://developers.openai.com/api/docs/guides/image-generation)。
