# 四阶 240 条转场的远程求解

四阶共有 16 种上下组合，包含全下垂基态。任意两个不同姿态的有向转场共 16×15=240 条；与前三阶合计 310 条。

## 计算位置和运行方式

- SSH 主机：`wqm`。
- 独立目录：`/data/wangqm/hmy/pendulum4_20261112`。没有改动同级的化学算例。
- PBS：三个 8 核作业、每个 32 GB 内存，使用 `medium` 队列。分片各覆盖 80 个固定任务，已完成任务不会改变分片归属。
- Python 3.12 独立环境；NumPy 2.2.6、SciPy 1.15.3、Numba 0.61.2、CasADi 3.6.7。每个求解进程的 BLAS 线程数为 1。
- 作业记录在远端 `job.json`，各分片日志为 `solver-0.log`、`solver-1.log`、`solver-2.log`，候选检查点在 `equilibrium_transitions/candidates`。

本机后台同步进程的 PID、当前输出分别记录在 `results/fourth-order-sync.pid`、`results/fourth-order-sync-staged.log`，此前补齐和直接替换阶段日志分别为 `fourth-order-sync-cases.log`、`fourth-order-sync-refine.log`。它每轮接收新结果，独立验收后发布到本机仓库，并把本机已验收直达结果共享回远端，跳过重复求解。若一个完整批次结束后仍有缺项且有新增进展，会自动以新搜索轮次再提交剩余分片，最多续提两轮；没有新进展时明确标记需要进一步搜索。

## 数值求解与验收

对象仍为均匀刚性杆、被动关节阻尼，唯一主动输入为小车水平力。默认轨道 ±2.4 m、推力上限 120 N，转场限制推力变化率 500 N/s。

1. 采用受限配点优化，约束全部被动关节的控制力矩为零，搜索转圈方向、额外绕圈和不同时间范围。
2. 已完成的反向路径可提供几何初值，随后重新优化以满足真实阻尼。直接反转一段动画不会自动成为成功解。
3. 每个远端成功候选经过非线性闭环积分；传回本机后，再做 1 ms RK4 独立回放和页面同一份 `sim-worker.js` 的真实积分。
4. 通过稳态误差、速度、推力、变化率、跟踪误差与轨道余量检查后，才写入 `equilibrium_transitions` 并保存仓库回放。
5. 240 条单独验收全部完成后，再执行完整有向欧拉巡游验收；通过前四阶的巡游按钮保持关闭，已验收的单条路径始终可以点播。

## 完整可播放覆盖与直达优化

对于尚未取得直达解的组合，`python -m triple_pendulum.complete_fourth_order` 从已验收直达轨迹构建候选，通过一个或多个明确的中间稳态连续转换。参考角度按绕圈次数对齐，参考位置、速度、驱动力在接点连续；全程使用同一个连续参考轨迹和 TVLQR，不重置积分状态。每个候选仍需从头通过 Python 1 ms 回放及真实网页 Worker 验收，首选路径失败后尝试不同中间姿态。除端点外不会绕经全下垂。

这些条目在索引和文件中保存 `route_waypoints`，界面显示“经中间姿态连续衔接”，与直达条目分开计数。最初补齐至 240 条时为 184 条直达、56 条连续衔接。远端继续搜索原缺项的直达解，同步器不会将衔接解发布为远端直达成功；新直达解通过双重复验后可替换对应衔接条目。索引摘要变化后必须重新验收巡游，旧巡游证书不能冒用。

新直达解先在 `results/fourth-order-upgrades/批次` 的独立副本里验收，随后对拟发布的完整 240 条路径做单条和连续巡游验证。通过后以不可变的摘要文件名保存新轨迹，先写入按索引摘要保存的巡游证书，再原子发布索引。旧索引引用的文件和证书继续保留。失败时保留当前可玩版本，后台升级不再临时关闭巡游。

`python -m triple_pendulum.refine_direct --workers 2` 是针对剩余衔接条目的额外直达搜索。它使用全程自由配点，不固定中间稳态，搜索反向轨迹、时间压缩后的已验收参考和悬垂起摆参考。候选参考的推力余量可放宽至执行器上限的 92%，物理执行器仍为 120 N，小车边界和 500 N/s 变化率不变；每条新解都重新做 1 ms 积分及真实 Worker 验收。另检查是否在非起终点的其他稳态停留超过 0.25 秒（角度 3°、角速度 0.15 rad/s、小车速度 0.08 m/s 的联合阈值），防止把中途停靠的轨迹当成直达解。额外搜索只发布候选到本任务远端证书目录，页面仍须经过独立副本整套巡游验收才切换。

本机搜索 PID 为 `results/fourth-order-direct-search.pid`，当前日志为 `results/fourth-order-direct-rounds.log`，最初一批日志为 `fourth-order-direct-search.log`。每轮每个组合最多尝试两个新的求解配置，记录已试过的配置并继续其他缺项，避免只占用在同一组合上。单条进度和已验收文件在 `results/direct-refinement`。四阶完全下垂静止至全直立已得到并发布 7.2 秒的直达解，物理落稳时间约 5.448 秒，峰值力约 20.154 N，最大小车位移约 1.466 m；这些数值绑定该具体轨迹及默认参数。

四阶完成率显示在页面的“转场矩阵”与提示行。绿色按钮可跳到起点并立即播放；未通过的条目不会冒充可用路径。实时状态见 `results/fourth-order-remote.json`，完整串联验收结果将写入 `results/fourth-order-worker-audit.json`。

## 共享存储和恢复

集群启用 `PENDULUM_CLUSTER_MODE=1`。每个固定分片独立写入对应算例的 `progress/键.json`；成功解按 SHA-256 命名为不可变文件，再原子发布 `certificates/键.json`。本机同步协调器是全局 `status.json` 索引的唯一写入者，求解进程不再获取跨节点共享锁，也不写远端回放仓库。失败复验通过 `rejections/键.json` 指定被拒绝的文件摘要，新解的不同摘要可正常覆盖旧证书。

本次发现共享存储上的 `flock` 不可靠，后续目录锁仍可能阻塞，因此最终去掉了求解阶段的全局共享写入。原索引保存在远端 `status-before-recovery.json` 与 `repository-index-before-recovery.json`，恢复时未发现损坏的已验收路径文件。

`python -m triple_pendulum.route_seeds` 可利用已验收边生成剩余组合的图路径初值，文件在 `results/fourth-order-route-seeds`。中间姿态避免绕经全下垂；仅作整段配点优化的初始猜测，不直接发布或计为成功。绕圈角度按连续转角对齐，关节没有额外力矩。此次生成 129 条初值，远端继续重新优化和双重积分验收。

本机恢复同步命令：`python -m triple_pendulum.remote_transitions --watch`。PBS 提交脚本源文件为 `cluster/fourth-order.pbs`，批处理入口为 `triple_pendulum.precompute_equilibria --orders 4 --shards 3 --shard-index 0`，其余分片对应 1、2。
