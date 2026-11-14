# 第三方库源码裁剪实验

本轮是与 `dist/实验` 并列的独立实验：`dist/极简实验/桌面版`。只修改构建副本，原实验的716个文件逐SHA核对未变；不修改开发机安装的库，不替换当前应用或个人记录。

## 实际结果

| 项目 | 原实验 | 源码裁剪实验 |
|---|---:|---:|
| 数值引擎 runtime.7z | 39,569,611 字节 | 30,932,317 字节 |
| 完整标准ZIP | 97,185,619 字节 | 88,546,072 字节 |

完整包减少8,639,547字节（8.89%）。压缩包为 `dist/极简实验/桌面分享包.zip`，SHA256：`6cb7d6fcb301da63ef964b9d415f2159940dd5f87eb00ec78f08ca49a5cadf9d`。完整解压，双击桌面版唯一的EXE；`程序文件/runtime.7z` 仍是必需的随包引擎。

## 裁剪方法

`triple_pendulum/prune_dependencies.py` 将SciPy 1.11.4变成应用专用修改版，不能拿来替换通用SciPy。版本不符拒绝编辑。运行树限定在 `results/dependency-prune`，明确拒绝其中的baseline；不会原地修改dist或系统环境。

先精简SciPy导出层，避免只需最小二乘或Riccati方程就导入所有优化器。OptimizeResult、OptimizeWarning和Bounds及其辅助函数直接从原源码提取，保留原类体；最小二乘改为导入这个私有共享模块。没有空实现、假返回值或替代数值算法。

然后以应用实际导入及属性引用为根，递归收集函数体、默认参数、装饰器及类体引用的本模块定义。未执行分支也参与静态分析；不能因测试没走到就删除。结合原版/修改版运行时的模块、函数和DLL加载记录取并集，保留相对导入父包和原生扩展。使用globals/locals/eval/exec等动态命名空间的模块整体保护。FastAPI/Pydantic等动态框架、CPython标准库压缩包没有按函数激进裁剪。

最终删除102个模块级函数/类定义、785个闭包外文件（含无用扩展和字节码，共45,639,493字节）。151个保留定义的AST与原版一致。NumPy只裁剪闭包外文件；保留的NumPy/SciPy/CasADi原生数值二进制没有改写。原许可证、NOTICE和包元数据保留，SciPy内加PENDULUM_VARIANT.json标明修改版和报告摘要。

这不是对所有Python动态调用的形式化证明；更换应用功能、输入类型、第三方库版本时必须重建并重新验收，不能复用旧调用覆盖率当作保证。

## 复现流程

开发构建使用原实验引擎 `results/compact-runtime/runtime-minimal.7z` 和官方7zr，展开到新的 `results/dependency-prune/runtime`。不可在已经删除文件的树上重新进行源码裁剪；重新实验先从固定原引擎建立干净树，保留旧证据。

1. 用原引擎解释器运行 `tests/probe_dependency_runtime.py <应用程序文件绝对路径> <新的原版证据目录> --profile`，固定环境使用 `triple_pendulum.build_compact.pinned_environment()`。
2. `python -m triple_pendulum.prune_dependencies results/dependency-prune/runtime --evidence results/dependency-prune --app dist/实验/桌面版/程序文件`，先做明确的导出层及函数根裁剪。
3. 用修改后的引擎再次运行同一probe到新目录，带 `--profile`；比较values及numeric_sha256。任何导入/数值失败先恢复，不计成功。
4. 再运行裁剪命令，添加 `--coverage <上一步coverage.json>`。它将静态调用及动态记录合并，进一步收集所需定义；再profile、比较数值。
5. 添加 `--coverage <最终函数裁剪后的coverage.json> --trim-files`，只删除联合闭包外的NumPy/SciPy代码文件和明确未用的Python SQLite/MSI/声音扩展。运行最后probe并比对原版。
6. 以裁剪后解释器运行 `tests/check_pruned_bank.py <应用目录> <新报告.json> --workers 4`；全651对必须还原到索引中原始1302方向的SHA。
7. 保留修改说明和许可证，将runtime按固定7z参数压缩；重新计算runtime SHA，使用 `build_compact.assemble` 的新assets构建到独立目录。不可覆盖已运行实例。轨迹可复用已逐位认证的v4编码，不能重新舍入。
8. 独立解压新ZIP，执行 `tests/check_compact.py`、`tests/check_web_entry.py` 和包内解释器的 `tests/check_compact_solver.py`；入口、浏览器回退、物理、现场求解、录制和手动更新分别验证。生命周期测试各用独立应用目录，不能互相关闭服务。

源码备份、逐文件SHA清单、静态图、动态覆盖率、删除清单、数值输出和图像在 `results/dependency-prune`。可提交的摘要为 `results/dependency-prune-acceptance.json`；运行库和ZIP不进Git。

## 实测范围

原版与三个裁剪阶段的确定性结果摘要全部为 `a8d30d3ed2f938bcf29005699432f81fb8c0d1e37f022aff7af043197636e8e2`。覆盖1～5阶、两种质量模型的124个平衡点设计，36组观测器情形，实际稀疏最小二乘规划及新IPOPT下垂起摆。全651对/1302方向解码后原控制SHA均不变，物理模型、Worker、反馈参考与已认证序列未被修改。

实际ZIP在中文空格路径、隔离PATH/PYTHONHOME/代理后，经普通EXE自行进入可见WebView2窗口，冷启动8.42秒；强制浏览器分支自行打开实际Firefox，约7.67秒，默认1×及刷新恢复通过。原生界面1～5阶起摆、停止/继续、时间轴、仓库、手动更新、非空且实际可解码录制通过，截图已视觉检查。矩阵仍在顶部、完整阶数文字、起终点方向仍在下方。

包内引擎新解单摆完全下垂起摆，求解和独立回放约1.97秒，最大力26.4549N、变化率287.1826N/s、位移0.90110m，稳定；不是读取旧轨迹。120个随机状态的动力学与原Numba实现最大差7.82e-14。HTTP人工初值求解并存仓库通过。首次缺索引、损坏重建和手动激活新插件通过。普通关闭及启动期立即关闭均无自己的孤儿后台。

这些是当前Windows机器上的实测，不代表所有Windows/浏览器或任意初值均通过；也没有重新搜索全部1302条路径。原认证参考逐位不变，所以沿用原始物理/Worker及精确整库序列证明，而非把函数测试当成全局物理证明。

## 为什么不再直接删DLL函数

原生二进制通过PE导入表和Cython C-API连接。实际保留的cython_lapack扩展就导入约1500个BLAS/LAPACK符号，即使Python层只调用很少函数，DLL加载时仍需解析这些符号。NumPy、SciPy、CasADi的三份BLAS分别有不同版本/整数ABI，不能简单合并。

进一步压缩需要从源码重编译扩展和数学库，控制导出、整数ABI、CPU派发和链接，再检查数值与v4预测基线。当前没有实施这一层重编译，没有把原生库中“看起来没用”的字节直接删除，也不声称已达到理论最小体积。
