MicForYou 设备 B 录音采集包

1. 把整个 capture_kit 文件夹复制到最终办公 Mac。
2. 连接耳机 B，并保持今后实际使用的连接方式（Bluetooth/USB/3.5 mm）。
3. 打开 Terminal，把 run.command 拖入窗口后按 Enter。
4. 首次运行可能需要下载约几十 MB Python 依赖；脚本不会安装模型或 BlackHole。
5. macOS 出现麦克风权限提示时，允许当前 Terminal/Python 进程。
6. 在列表中选择耳机 B 的输入设备；不要选择 BlackHole 或 MacBook 内置麦克风。
7. 按提示完成三段录音。脚本会生成一个 zip，不会自动上传。
8. 用 AirDrop、USB 或认可的本地同步方式把 zip 传回原电脑。

脚本不会调用 ASR、不会修改默认输入输出、不会录制提示步骤之外的声音。
