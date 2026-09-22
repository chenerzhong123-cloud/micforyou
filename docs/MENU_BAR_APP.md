# MicForYou 菜单栏应用

状态：`BUILD + AD-HOC SIGN + USER INSTALL + PROCESS LAUNCH PASS / VISUAL UI SMOKE PENDING`。这是 Stage-D Python 控制层的原生 SwiftUI 外壳，不包含、复制或修改 TSE 模型。

## 功能

- 常驻显示 `STARTING / RUNNING / RECOVERING / PAUSED / STOPPED / FAULT`；
- 开始、暂停、继续和停止隐私优先后台桥；
- 选择已存在的实体麦克风；原设备消失时不会自动改用其他麦克风；
- 在停止状态发起 45 秒重新注册；只有 ONNX correctness PASS 才替换旧注册；
- 固定显示 Experimental Alpha 的质量边界，以及豆包必须选择 `BlackHole 2ch` 的提示；
- 打开当前运行日志；日志不包含音频、embedding 或豆包文字。

菜单栏应用只允许通过后台控制器启动 `fault_policy=silence`。连续优先的 raw passthrough 仍需在可见 Terminal 中运行，直到 UI 能保证 degraded 警告在应用退出后仍持续可见。

## 构建

无需完整 Xcode；本机 Command Line Tools 的 Swift 6.4 已验证可编译：

```bash
cd app/MicForYouMenuBar
swift build
swiftc Sources/MicForYouMenuBar/Models.swift Checks/ModelCheck.swift \
  -o .build/model-check
.build/model-check
./build_app.sh
```

最后一个命令生成并 ad-hoc 签名：

```text
app/MicForYouMenuBar/.build/MicForYou.app
```

当前用户的一键安装入口为：

```bash
./install_app.sh
```

它安装到 `~/Applications/MicForYou.app` 并打开应用，不添加开机启动项。重复执行会更新应用文件；配置、模型、注册音频和运行报告仍保留在原位置。完全移除界面时只需退出后将该 `.app` 移到废纸篓；不要同时删除 `Application Support/MicForYou`，除非确认不再需要配置与注册信息。

应用读取现有 `~/Library/Application Support/MicForYou/config.json`，再调用该配置 `project_root/.venv/bin/micforyou`。因此首次使用前仍须完成 Python 环境、模型、BlackHole 和 `configure`；应用不会下载许可不明确的模型，也不会更改系统默认输入。

## 当前验收边界

- SwiftUI executable：编译通过；
- 固定 controller JSON 解码、health/status 优先级及危险状态映射：独立自检通过；
- Python controller：自动生命周期测试通过；
- 已安装到 `~/Applications/MicForYou.app`，ad-hoc 签名校验通过，安装版本进程稳定启动；没有添加开机启动项，也没有启动音频 bridge；
- 当前 Mac A 保存的输入设备 `External Microphone` 未连接，因此应用应显示“尚未就绪”，开始按钮禁用。这是预期安全行为。
- 连接已配置耳机后的点击、菜单栏状态、重新注册确认框与真实 TSE 启停仍需一次本机 UI smoke，不能提前标记通过。
