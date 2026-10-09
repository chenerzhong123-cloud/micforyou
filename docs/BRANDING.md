# MicForYou 正式 Logo

定稿日期：2026-10-08。用户明确选定 **C01 · M 声路**，不再使用其他候选替换此稿。

## 图形与含义

米白底、黑色麦克风、灰色干扰声线、白色双峰 M 声路及金色输出声线。M 对应 MicForYou 的 Mic；不同声音进入，突出一道被保留的声音。它是品牌寓意，不是绝对隔离或声纹认证能力的承诺。

## 单一源文件与使用位置

- 正式 1024×1024 PNG：`app/MicForYouMenuBar/Resources/AppIcon.png`。
- 文件来自用户选定的 C01，保持原始构图与配色，不重新生成或自动美化。
- `build_app.sh` 从该 PNG 生成 16–1024 px 的图标并封装为 `Contents/Resources/AppIcon.icns`；Info.plist 通过 `CFBundleIconFile` 引用。
- 菜单面板头部读取同一应用图标，并保留状态色点与状态文字。
- 顶部菜单栏继续使用启停状态图标；其用途是状态提示，不作为另一套品牌 Logo。

候选和生成提示词位于本机 `/Users/deuce/claudeproject/codexworks/micforyou/brand-20261007/personal-options/`；正式构建不依赖该目录或绝对路径。生成方式为内置 image_gen，C01 基于 B06 编辑，选中之后仅进行复制、尺寸派生和 ICNS 封装。

## 验证

```bash
cd app/MicForYouMenuBar
./build_app.sh
swiftc -parse-as-library Checks/BundleCheck.swift -o .build/bundle-check
.build/bundle-check .build/MicForYou.app
```

本次定稿不表示商标/图形相似性清查已通过，不是 App Store 上架许可。正式提交仍需完成图形清查、分层/外观资源准备和应用合规检查；当前应用仍是 Experimental Alpha。
