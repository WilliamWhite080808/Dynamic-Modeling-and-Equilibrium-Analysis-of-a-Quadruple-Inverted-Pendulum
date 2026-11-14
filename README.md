# 倒立摆实验室

一到五阶自由关节倒立摆：只有小车牵引力，没有关节电机。前四阶310条、五阶992条，共1302条有向稳态转换已通过独立物理积分和实际页面Worker验收；各阶完整连续序列也已通过。不是视频或插值摆角动画，不保证有限轨道和驱动力下任意初值都有解。

## 使用

分享桌面包：`dist/实验/桌面版`，完整解压后双击唯一的“倒立摆.exe”。标准ZIP约97.2 MB，保留现场求解及全部界面功能，无需安装Python/求解器，不联网安装组件。复用已有WebView2或实际安装的浏览器。原 `dist/网页版`、`dist/桌面版` 暂不替换。

进一步裁剪第三方库源码的独立实验：`dist/极简实验/桌面版`，ZIP为88.55 MB。保留现场求解与全部原功能，原实验不变；这是固定版本的应用专用库分支，验收范围及复现方法见[依赖源码裁剪](docs/dependency-pruning.md)。

阶数和醒目的转场矩阵在顶部，起终点方向在仿真/图表下方全展开。切换立即执行，稳态停留5个仿真秒；每次打开/刷新默认1×，0.1×～10×调速。包含手动初值求解、参数/控制分析、路径仓库、角速度、扰动、时间轴和核心区域录制。

开发运行：Python3.11环境安装 `requirements.txt` 后 `python launch.py`。此步骤只供开发，收件人不需执行。测试依赖见 `requirements-dev.txt`。

## 项目结构

| 位置 | 用途 |
|---|---|
| triple_pendulum/ | 被动模型、控制/观测器、规划、验收、插件、服务和构建源码 |
| web/ | 仿真Worker、canvas、图表和操作界面 |
| cluster/、native/ | SSH/PBS四方法任务、Windows启动器、固定数学内核源码 |
| equilibrium_transitions/ | 全部1302条认证方向、状态清单及保留检查点 |
| precomputed_swingups/ | 下垂起摆库及计算记录 |
| trajectory_repository/、recordings/ | 个人成功实验与录制，清理时不删除 |
| results/history/ | 已删除旧构建的独有结果/证明/日志，按SHA独立去重、可恢复 |
| results/acceptance/ | 当前交付的实测报告、图像、数据摘要 |
| results/runtime-build/、desktop-build/、compact-runtime/ | 各自唯一的开发构建资产；不是要发送的运行版本 |
| dist/实验/桌面版/ | 本轮小于100MB的完整桌面分享实验 |
| 项目日志.md、docs/history/ | 完整实施日志、用户要求及对话沿革 |

旧的整套版本、私有浏览器内核、重复缓存、受限单HTML生成器已清理；独有数值结果先校验后归档。不要删results/history对象来缩小分享包：它本来就不进入分享包。

## 重新计算

`python -m triple_pendulum.recompute --orders 1,2,3,4,5 --workers 2 --out results/new-computation`

此命令对已认证输入进行新的受约束IPOPT求解，默认使用原参考暖启动和可行性投影，保留独立输出并重新做真实闭环积分；不是把原文件重放冒充计算。默认每阶抽取下垂到全上的一条。使用 `--all-ready` 覆盖全部1302方向；`--source`/`--target` 选择姿态，`--method` 选择explicit-hs、inverse-hs、residual-continuation或rk4-shooting。用 `--cold` 从冷初猜重新搜索，耗时和成功率不能保证。新结果必须重新经物理和Worker双重认证才能入正式库，重算器不会覆盖原认证库。

从零批量搜索的原算法仍在：`python -m triple_pendulum.precompute_equilibria --orders 1,2,3,4,5 --workers 3 --rounds 3`。已有ready案例会保留并跳过，不应为了重算删除原库；独立实验请使用新目录/仓库。远端实际四方法源码及每方法检查点均保留。

当前源码统一重算抽查1～5阶下垂到全上，5/5通过独立物理回放；没有宣称把全部1302条再优化一遍。全部1302条的现有认证原文件和SHA已核对，五阶完整连续证书覆盖992段、9772.096仿真秒、零触轨、零在线重规划。

## 文档与验证

- [桌面压缩构建、依赖裁剪、实测与限制](docs/compact-desktop.md)
- [轨迹格式和手动更新](docs/motion-plugin-format.md)
- [求解器与实现详解](docs/求解器与实现详解.md)
- [模型推导](docs/model_derivation.md)、[控制与观测器](docs/controls_and_observers.md)
- [五阶计算日志](docs/fifth-order-compute.md)、[完整项目日志](项目日志.md)

`python -m pytest -q`；当前实验另用 `tests/check_compact.py` 验证真实普通EXE冷启动及原生界面，`tests/check_web_entry.py` 验证浏览器回退，`tests/check_compact_solver.py` 在随包解释器中实际求解。数值精度、轨道与力/变化率边界分别验证，不用局部LQR极点证明全局可起摆。

后续方向为小车x/y平移、空间被动摆、仅Fx/Fy的1～3阶双自由度，目前尚未实现；六阶未启动。
