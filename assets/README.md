# 美术资源与标记

`raw/` 是用户提供的原始素材，保持原样。所有图片、派生图、候选图和预览均被 Git 忽略。此目录中只将我们编写的说明与 manifest 加入版本管理。

## 添加一个可用素材

在 `manifests/limezu.json` 的 `definitions` 中新增条目，然后运行：

```bash
.venv/bin/python -m wonderland assets --import
```

条目示例（字段含义示例，不代表存在此文件）：

```json
{
  "id": "furniture.example",
  "name": "示例木椅",
  "category": "furniture",
  "source": "素材包/16x16/椅子.png",
  "tags": ["chair", "seat", "椅子"],
  "anchor": [8, 30],
  "collision": [-6, -7, 12, 9],
  "door": null,
  "crop": null
}
```

- `source` 相对于 `assets/raw/`。
- 标注坐标统一是原生 **16 像素美术坐标**，导入时全部乘 2。
- `anchor`：图片左上角为原点，指向物体接地位置。渲染按这个点排序。
- `collision`：相对于 anchor 的 `[左, 上, 宽, 高]`；`null` 表示不阻挡角色。
- `door`：相对于 anchor 的入口接地点，只用于 `building`。
- `crop`：从图集中裁切的 `[x, y, width, height]`；单张物件图片用 `null`。
- `fill_from_pixel`：可选，从原图指定像素采色并铺满单格，用于同风格纯色底层。
- 可放置的类别是 `building / nature / prop / furniture`；`tile` 用于地面；`character` 是角色帧。

像素大小、透明范围、建造占地、物理碰撞和图片锚点不能相互代替。添加后查看 `assets/previews/catalog.png`，并在游戏中按 F1 核对碰撞和入口。

## 原始索引

`assets --scan` 对原生单图目录建立 `inventory` 表，保留文件路径、宽高和文件名关键词。`assets --search tree --raw` 查询的是未必完成标注的原始记录；不意味着所有查到的图片都能直接用于游戏。

## 地形连接

道路和水面的原始地形图来自 Modern Farm。程序用已确认的外角、直边和内凹角象限组合 47 种 Blob 形态，位序为 `N=1, E=2, S=4, W=8, NE=16, SE=32, SW=64, NW=128`。

`normalized_mask` 去掉无效对角关系；`build_autotile` 负责素材象限匹配。它只适用于当前素材布局，不是所有图集通用的坐标表。

## 生成素材

`generated/<signature>/` 保存原图、处理结果、检查结果和 `asset.json`。接受后数据库记录稳定 ID、图片 hash、锚点、碰撞模板和生成来源；agent 的目录摘要会包含它。`candidate` 失败文件不会自动入库。

本地素材使用 LimeZu 系列。请保留原包的许可证与署名；不要将原始或规范化图片提交到公开仓库。
