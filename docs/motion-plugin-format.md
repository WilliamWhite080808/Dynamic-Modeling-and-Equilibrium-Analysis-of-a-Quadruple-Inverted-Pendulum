# 轨迹插件格式

当前实验桌面包使用 **TOML v4**，兼容读取v1/v2/v3及旧JSON。每对姿态一个文件 `motions/N_A_B.toml`，共享模型 `models/standard.toml`。例如 `3_DDD_UUU.toml` 的ab和ba是分别真实求解、分别验收的两个方向，不能把带阻尼的轨迹倒序当逆解。

头部：v、n、ends、model、recipe、kernel。每个方向保存时长T、间隔h、节点数nodes、原控制hash、origin源文件SHA、proof/worker/direct证明，以及forces/states/corrections三个96字符换行的压缩块。非默认初值、绕转目标才另写；默认角度由U/D推导。

参考仍是 **state-hermite-v1**：q/v/a为广义坐标、速度和加速度节点，u为唯一小车牵引力，K为反馈增益。三次Hermite参考及分段线性u/K不变，真实摆角由被动方程积分产生。

v4用固定的隐式Hermite–Simpson预测器和TVLQR基线，再保存与原IEEE754值的XOR修正；力也无损差分编码。字节重排、LZMA和Base64只改变表示。全部原始节点、低位、数值类型及元数据均可精确还原，不舍入、不拟合、不按视频帧记录。kernel/state/baseline/hash各层摘要均核对；kernel或数值环境不匹配明确失败。配方为hs12-fdlibm-tvlqr-nehalem-v2，内核/固定运行库随包提供。

格式v3将完整q/v/a/u/K进行XOR、字节重排和deflate，独立于预测基线，仍可加载；v2是逐节点展开矩阵。格式沿革及早期未发布的省略系数草案移至[历史文档](history/轨迹格式沿革.md)，不当作有效插件。

随包预建索引，只核对源SHA并复制不可变快照。首次缺索引/损坏可重建；已有索引后新增或修改必须点击“检查轨迹更新”激活。快照丢失且源已改变时不可假造旧解。阶数由实际有效文件发现；完整序列还必须绑定当前全量控制摘要，不能仅凭数量开放。

1～5阶共有651对、1302条方向，五阶992条及完整连续序列已通过。v4全量逐位对比报告在results/acceptance/compact，构建和实测见[桌面分享包说明](compact-desktop.md)。原始认证JSON保留在项目数据目录，不受压缩构建修改。
