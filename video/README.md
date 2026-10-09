# MicForYou 宣传片 · 第四版

55 秒 · 1920×1080 · 30 fps · H.264 MP4。

核心文案：**空间共享，表达从容。**

面向开放工位、公共空间里使用 Mac 语音输入的人。所有画面由 React / SVG
编写并通过 Remotion 在本机渲染。配乐和操作音效由 Python 合成，无旁白，
无需用户录屏、出镜或录音，也没有外部视频生成服务或云端音频调用。

## 本版调整

- 开场取消像选中状态的声音 Tag。用绿、紫两种颜色分别标识自己的口述与
  身旁讨论，展示旁人的语句混进语音输入的因果关系。
- 操作章节将菜单和声音链路并排：准备 3 秒、加载 1.5 秒、开启 7.5 秒、
  暂停 6 秒。开启后保留本人波形、减弱旁人波形并显示流向豆包；暂停后
  不再过滤，两种原始波形继续送出，麦克风保持使用。
- 全部章节文案围绕共享空间、交错人声和从容表达重写。
- 结尾采用代码绘制的开放工位：同事项目讨论、线上会议、用户口述方案。
  以「少些人声干扰／豆包输入照旧／过滤、原声由你」收束卖点。
- 页眉、产品介绍、应用菜单、处理模块和结尾改用正式 C01 Logo。
- 产品链路隐藏实现组件，只展示「麦克风 → MicForYou → 豆包输入法」，
  并增加注册声音参考进入 MicForYou 的分支。
- 新导出文件使用 `micforyou-promo-v4`，保留旧成片；第二、三版源码和表格脚本
  备份在 `archive/v2/` 和 `archive/v3/`。

## 运行与导出

```sh
npm ci
npm run sound
npm run lint
npm run dev
```

```sh
bash /Users/deuce/.codex/skills/remotion-demo-export/scripts/export-demo.sh \
  /Users/deuce/claudeproject/productlearning/micforyou/video \
  MicForYouPromo micforyou-promo-v4 945
npm run master
```

`production.json` 保存时长、章节、交互和检查帧的时间位置，供动画、配乐和
检查工具共同读取。最后以 FFmpeg 调整到 -20 LUFS，并让音画时长一致。
本机浏览器路径和字体配置见 `remotion.config.ts`。

## 内容边界

界面依据现有 SwiftUI 源码重建。开场转写是情境演绎，操作旁的波形是效果
示意，都明确标注为非实测结果。本版暂停表现为原音直通，包含本人、旁人
和环境声音；结束才停止输出并释放麦克风。

暂停原音直通已实现并通过自动与真实 ONNX 合成回调检查。操作章节标注
「界面与波形示意 · 非实测」。真实麦克风、豆包与新版 30 分钟验收仍待完成，
见 `../docs/PAUSE_PASSTHROUGH_VALIDATION.md`。中英文 README 通过稳定的
`../docs/media/micforyou-promo-latest.mp4` 与 `promo-preview.png` 链接引用最新成片。

用户指定的 localhost Logo 服务无法连接，因此使用本机品牌目录的同名
正式稿 `brand-20261007/personal-options/C01.png`，原样复制到
`public/brand/C01.png`。两者 SHA-256 均为
`78a96226bcf182497cf1f42696dfde61df0f2a33abab4e84bd4c495929a98080`。

Experimental Alpha 标识始终可见。当前版本能减少部分他人声，不能保证
完全隔离；本人不说话时仍可能放行他人声。MicForYou 在本机处理声音，
豆包负责识别文字，其自身数据处理不受 MicForYou 改变。

## 章节

| 时间 | 文案与场景 |
| --- | --- |
| 0–10 秒 | 同处一间办公室，说的却不止一件事。两句交谈混入一句输入。 |
| 10–16 秒 | 让自己的话，有自己的位置。正式 Logo、注册声音参考。 |
| 16–34 秒 | 开启过滤；过滤暂歇，表达继续。暂停后原音仍送往豆包。 |
| 34–41 秒 | 三节点声音到文字链路，注册声音参考分支。 |
| 41–48 秒 | 协作的热闹，不必都写进你的句子。三个使用收益。 |
| 48–55 秒 | 空间共享，表达从容。开放工位与卖点收束。 |
