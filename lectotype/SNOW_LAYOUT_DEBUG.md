# 雪山布局失败与恢复

日期：2026-09-10（America/New_York）。

用户描述：雪山场景，有一个巨大的房屋，里面有壁炉和床。

任务 `6e13d0d2b1e619e7` 于 21:52:58 在 compiling 阶段失败。雪地 `generated.829949c6a1b38c1d`、山峰 `generated.6c23b312d7f998da` 均已完成生图、通过检查并入库。错误为五座北侧山峰放置了 0/5，seed 42、43、44 三次均失败。

## 根因

`house.country` 的视觉尺寸为 576×512，放在 (1024,768) 时覆盖矩形 (736,268,576,512)。旧版「north」只在 x=768…1280、y≈270…590 之间随机采样；山峰的候选轮廓全部与这栋房屋重叠，因此随机重试不能找到合法位置。地图北侧其他空地实际上足够容纳山峰。

## 修复

- 保留原来的优先采样；采样耗尽后，依据素材尺寸、锚点与目标方向，在更大的有效区域内进行有限网格搜索。
- 北侧仍限制在地图北侧；继续检查越界、入口预留、房屋轮廓、实体碰撞、道路水面，完整保留要求的物件数量。
- compiler 版本升级到 0.1.3；正常生成缓存区分新旧编译器。
- 摆放失败事件新增 asset_name、asset_id、zone、placed、requested、rejections，以便区分空间不足和选址问题。
- 增加 `retry <job_id>`，明确恢复原任务，不重新规划，不丢失旧失败记录；可直接复用已入库素材。

## 本次恢复结果

执行 `.venv/bin/python -m wonderland retry 6e13d0d2b1e619e7` 后，任务状态已变为 complete，旧失败记录保留在 JSONL，当前错误字段已清除。

输出：`worlds/76621d0b42b2/world.json`，标题「雪山大木屋」，seed 42。室外包含一栋大房屋、五座山峰、十棵松树；室内包含壁炉、床和四件起居家具。通路与入口检查通过。本次恢复追加的 API 调用为 0，两份生成素材均记录为 asset_reused。

已检查室外全图、正常游戏视角与室内渲染；真实 Mac 窗口也已打开该世界并显示「壁炉暖居」。山峰位于房屋后方，初始镜头主要展示大房屋，向北探索才能接近山峰。

截图：`screenshots/snow_recovered_map.png`、`screenshots/snow_recovered_outdoor.png`、`screenshots/snow_recovered_indoor.png`。任务日志：`logs/6e13d0d2b1e619e7.jsonl`。

## 回归测试

`.venv/bin/python -m pytest -q`：41 passed，1 skipped（需单独开启的 Cocoa 原生显示测试）。

新增五项覆盖：原故障布局在 seed 42/43/44 均保留五座山峰并保持入口可达；确实无法放置时仍报错并保留拒绝原因；跨编译器版本恢复失败任务时复用计划和素材，禁止任何 API 调用。
