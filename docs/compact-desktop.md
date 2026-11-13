# 完整桌面分享包：小于100 MB

唯一分享入口是 `dist/实验/桌面版/倒立摆.exe`。完整转发桌面版文件夹；外层只有此EXE和“程序文件”。本轮不替换原 `dist/网页版`、`dist/桌面版`，不改用户自己生成的压缩文件。

标准ZIP为97,185,619字节，约97.19 MB（十进制，必须小于100,000,000字节）；实际文件大小及SHA见 `results/acceptance/compact/final-report.json`。完整功能包括新初值现场求解、被动动力学积分、参数/分析/观测器、图表、矩阵、仓库、扰动、变速、时间轴和核心录制。前四阶310方向、五阶992方向，总651个双向插件、1302方向，1～5阶完整连续序列均有精确证书。

## 为什么原包大，新包如何缩小

原包主要体积来自科学计算二进制运行库、Numba/LLVM编译环境及完整参考轨迹，并非项目自己的Python脚本。现在只打入从服务入口实际导入的17个项目模块，约110 KB。开发/批算/旧构建入口不混进分享包。

动力学和耗散恢复控制用相同算法提前编译为通用x64原生核，因此收件人不需要Numba、LLVM或C编译器。仍保留CPython、NumPy、SciPy、CasADi及IPOPT；没有用视频或删掉现场求解换体积。CasADi保留真实IPOPT依赖链和QR等动态插件，移除其他求解后端、头文件和静态开发库。SciPy只移除界面和现场规划不使用的子模块；主项目开发环境完整保留。

运行库作为约39.57 MB的 `runtime.7z` 随包分发。首次启动自动展开到当前用户缓存，不联网、不安装组件、不要求管理员；后续按内容摘要复用。界面显示准备进度。运行时的轨迹快照和浏览器窗口缓存也在用户缓存，不在分享文件夹里再复制一整套轨迹或运行库。个人新实验和录制仍在应用自己的目录，须保留。

界面复用已有WebView2，失败时自动尝试实际存在的Firefox/Chrome等浏览器，跳过卸载Edge留下的坏关联。目标平台为Windows10/11 x64；实测为当前Windows机器上的WebView2和Firefox，不声称测过所有Windows发行版或一台完全没有可用浏览器内核的系统。

## 无损轨迹

公开格式v4仍然一对姿态一个TOML，正反分别真实验收。头部和证明可读，压缩块96字符换行。对每个参考节点预测，再保存**原始64位数值与预测值的XOR修正**；加速度和TVLQR增益也保留逐位修正。不删节点，不舍入，不拟合。全部651对的原始展开控制参考与还原结果已逐位比较，1302条原控制摘要全部不变。

预测器用随包固定fdlibm三角函数、通用CPU核、单线程NEHALEM OpenBLAS及固定NumPy CPU派发，避免依赖不同Windows系统数学库的末位行为。文件记录内核SHA、状态SHA、预测基线SHA和完整控制SHA。数值运行库不匹配会明确拒绝，不能悄悄近似还原。旧v1/v2/v3仍兼容；原始认证JSON数据独立完整保留在项目中。

随包预建小索引，首次只核对源SHA并复制不可变快照，不解码全部651个文件。缺索引或损坏时可重建；已存在索引后的新增、修改只在用户点击“检查轨迹更新”时激活。删除缓存且源已修改，不能冒充原快照，会要求手动检查。

## 可复现构建

在项目开发环境执行；收件人不需要执行这些命令。构建必须使用新目录，拒绝覆盖已运行实例。

1. `python -m triple_pendulum.build_native results/native-portable`：从被动动力学、恢复控制及 `native/fdlibm` 源码编译AOT核（开发机需要Numba/LLVM及MSVC）。
2. `python -c "from triple_pendulum.motion_export import export; export('results/compact-runtime/final-source',compact=True)"`：只导出真实状态清单里的已认证原文件，逐条核对SHA。
3. 如需从完整运行库重新裁剪：`python -m triple_pendulum.build_compact prepare-runtime dist/桌面版/程序文件/runtime results/runtime-rebuild --extractor results/compact-runtime/7zr.exe`。原目录不变，输出逐文件清单并验证7z。实际构建资产的摘要在 `results/compact-runtime/assets.json`；固定CPython3.11.9、NumPy1.26.4、SciPy1.11.4、CasADi3.7.2。
4. 用随包解释器运行 `cluster/encode_motions.py --kernel results/native-portable/_native.cp311-win_amd64.pyd --source results/compact-runtime/final-source --output 新编码目录 --workers 4`。此入口对子进程固定相同数值环境，每个文件编码后立即完整解码，比较原始IEEE754值、元数据、证明和两方向控制SHA。第一次可用7zr将引擎展开到构建缓存。
5. `python -m triple_pendulum.build_compact assemble 新输出目录 --source results/compact-runtime/final-source --encoded 新编码目录 --assets results/compact-runtime/assets.json --zip 新验证压缩包.zip`。资产SHA、输入SHA和逐位报告必须匹配，创建预建索引、许可证和真实EXE；标准ZIP达到100,000,000字节即失败。

`prepare-runtime`只裁剪新的构建树。不要指向原实例的runtime或个人目录。没有使用pickle作为交付解码格式。

## 实际验收

证据在 `results/acceptance/compact`。独立解压到中文和空格路径，隔离PATH、PYTHONHOME和外网代理，普通EXE自行打开可见窗口，驱动没有先导航页面；原型冷启动约9.27秒；最终真实页面导航完成约12.86秒。原生窗口1～5阶下垂起摆、停止/继续和拖动时间轴、仓库、手动更新、非空且实际可解码的核心录制通过。另强制浏览器回退，经真实EXE自动打开Firefox，默认1×和刷新恢复、顶部醒目矩阵、完整阶数文字和底部真实指针选择通过；截图已实际查看。

在无短路径的中文缓存内，发现并修复CasADi窄字符DLL加载失败；改为Unicode预载依赖，随后同一失败环境重新求解通过。用收件人解释器新做单摆完全下垂静止IPOPT优化（不是取旧路径），独立物理积分收敛，约2.31秒完成求解及回放，力26.45 N、变化率287.18 N/s、位移0.9011 m。1～5阶两种质量模型共120个随机状态与原Numba动力学比较，最大绝对差7.82e-14；各阶控制分析通过，无Numba导入。HTTP新初值 `[0,0.05,0,0]` 实际求解并存入仓库，最大力5.53 N、零越轨。

这些验收不证明任意初值都可在有限轨道/有限驱动力下稳定，也不宣称全局最短时间。原992条方向的物理与Worker双重证明和完整连续序列证书保留，编码后的控制参考摘要完全一致。

最终ZIP还验证了普通窗口关闭及启动期间立即关闭，自己的后台均退出。修复与完整范围见项目日志。原始结果未被压缩版覆盖。
