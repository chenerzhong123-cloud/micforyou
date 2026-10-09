# 暂停原音直通 · 0.1.1 验证记录

日期：2026-10-08。结论：**软件行为已实现，自动测试和真实 ONNX 合成输入检查通过；真实麦克风、豆包与新版 30 分钟验收尚未完成。**

## 实现行为

- `pause` 在当前 duplex callback 的音频块边界将过滤切为原音直通；保留 PID、输入输出 Stream 与设备选择。原音不经过 TSE、重采样或额外增益，仅做 mono → stereo 声道映射。
- `resume` 复用已加载模型、ORT session 与参考特征，重新构建 resampler、STFT/OLA、recurrent state、worker、输入队列与输出 ring；不重开 Stream。
- 退休 worker 的 ring 独立，队列被丢弃，迟到输出无法进入新模式。恢复前等待上一在途推理完成，避免同一模型同时被两代 worker 调用；若超时，原音保持且操作报错。
- Unix socket 目录权限 0700、端点 0600，校验随机运行 token、PID、请求 ID。跨控制进程用文件锁串行化 start / pause / resume / stop 与配置写入；得到 callback 确认后才写成功状态。
- `PAUSED` 保留采集，只有 `stop` / 菜单“结束”才释放设备。“退出界面”保留原有后台行为，并提示音频继续。
- runtime-state/2 兼容读取旧 state/1。旧 `PAUSED + pid=null` 视为已停止，不显示原音正在输出，不自动开麦。
- 主动原音与故障降级分开。设备异常、模型故障、回调停顿默认静音；故障可覆盖暂停显示，不暗中换用其他麦克风。
- 暂停时 GUI 显示“过滤已暂停 / 原始声音继续输入”，提示含身旁人声。过滤、原音暂停或未完全退出的故障进程都会阻止换麦、重新注册和改配置。
- 修复 `configure` 未保存、`set-policy` 又覆盖回旧配置的问题。新运行报告使用用户自己的 Application Support 路径。

## 已执行检查

| 检查 | 结果与范围 |
| --- | --- |
| Python `uv run pytest -q` | 76 项通过。覆盖原音逐样本一致、模型调用暂停、迟到输出丢弃、恢复失败保留原音、模式确认超时、100 轮切换、pending resume 被结束、两种模式故障静音、socket 认证、同一 PID 启停、旧状态及配置写入回归 |
| Swift debug build | 通过，存在当前 Command Line Tools 搜索路径的 linker warning，无构建错误 |
| `Models.swift + Checks/ModelCheck.swift` | 独立自检通过；覆盖原音暂停活动性、旧暂停、故障优先级与过期健康状态 |
| 真实 ONNX + live main / 原有运行环境 | 5 轮 pause/resume，同一 PID，模拟 Stream 打开 1 次；579 个 callback、49 次模型调用；238 个原音块逐样本一致，0 mismatch，0 runtime fault |
| 真实 ONNX + 新建模型环境 | 按 `requirements-runtime.txt` 重新安装成功，完整 live main 合成输入检查通过；5 轮同 PID，514 个 callback、42 次模型调用；217 个原音块逐样本一致，0 mismatch，Stream 打开 1 次 |
| 合成环境切换确认 | 原有环境暂停约 11.8–14.7 ms，继续约 18.3–28.6 ms；新环境暂停约 10.6–26.2 ms，继续约 16.5–30.1 ms。仅控制确认时间，不是恢复后第一段有效过滤音频或输入法端到端延迟 |
| App release build / codesign | 本机 arm64 构建、ad-hoc 签名、严格签名校验与 BundleCheck 通过（C01 图标 16–1024 px）；已更新并启动 `~/Applications/MicForYou.app` 0.1.1，未开始收音；未做 Developer ID / notarization |
| 最新宣传片 | 第四版 `MicForYouPromo`，1920×1080，30 fps，55 秒；TypeScript、MP4 全音画解码通过，已查看正式预览；已复制到 README 使用的仓库内稳定路径 |

合成输入检查加载既有私有 enrollment 与 ONNX，仅在本机计算，不导出或提交私有音频。实际输入由正弦信号模拟，**没有打开真实麦克风、BlackHole Stream 或输入法**。模型新环境初次导入触发上游 JIT，原先 40 秒测试等待超时；单独完成首次导入后再运行同一检查通过。这属于首次初始化时间，不伪报为实时运行故障。

详细运行 JSON 保存在本机忽略目录 `outputs/pause-validation/` 与 `outputs/pause-validation-fresh-runtime/`，不包含音频。单元及进程控制回归在 `tests/`。可复跑真实 ONNX 检查：`uv run python experiments/verify_pause_passthrough.py --config <本机配置>`，支持 `--runtime-python` 验证新模型环境；不会打开真实设备。仓库内脚本另外执行 2 轮检查通过（284 callbacks、96 原音块、0 mismatch、1 次模拟 Stream）。

## 待执行真机验收

本机当前配置的 `External Microphone` 未连接，`status` 为 `ready=false`，音频已停止；未以其他麦克风替代既定注册设备。

1. 连接日常注册麦克风，验证过滤 → 暂停原音 → 继续过滤 → 结束；PID 保持，输入法设备无需重选。
2. 录音设备与 BlackHole 实际回调检查：暂停输出保持连续、无额外增益，切换无明显爆音、历史片段重复或叠音；报告音频间断与过滤预填充时间。
3. 在豆包完成本人 / 旁人交谈场景检查：暂停时两者原音可进入，结束后本链路无输入。字幕或文字出现延迟与内部音频延迟分别记录。
4. 两种模式分别测试耳机拔插、设备消失、回调故障与恢复；禁止隐式改用内建麦克风，故障状态优先于暂停。
5. 完成新版 30 分钟混合运行，包含多次切换，检查队列、CPU、RSS、模型调用停止和恢复、残留进程。
6. 菜单栏真机确认按钮与设置禁用、麦克风使用指示、退出界面后的原音继续以及“结束”后的释放。

以上未完成项不算通过。此前 M5 30 分钟过滤运行记录不能代替本次新增暂停行为的验收。

## GitHub 交付状态

- 双语入口：`README.md`（中文）、`README.en.md`（英文），完整指南：`docs/INSTALL.md` / `INSTALL.en.md`。
- 本地构建 ZIP 和 checksum：`outputs/releases/MicForYou-0.1.1-alpha-macos-arm64.app.zip` / 对应 `.sha256`。
- ZIP 解压完整性检查通过；包含 28 个条目，只有菜单栏 App 与双语安装提示，不带模型、Python 环境、私有声音或运行报告。双语 README 和安装指南的本地链接检查通过。
- GitHub 仓库仍为 private，尚未提交发布 Release，本轮未改变可见性。发布准备见 `RELEASE.md`。
