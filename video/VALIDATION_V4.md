# 第四版成片验证

2026-10-08，Composition `MicForYouPromo`，1920×1080，30 fps，55 秒。

- Remotion skill 导出前 TypeScript lint 通过；MP4 / GIF / PNG 导出成功。
- MP4 为 H.264 + AAC 双声道，音画均为 55.000 秒；母带处理完成，最终 FFmpeg 全音画解码通过。
- 已查看第 945 帧正式 PNG：暂停显示原音继续输出，C01 Logo、按钮、波形、文字无可见裁切。
- 去掉“暂停直通待软件更新”，保留“界面与波形示意 · 非实测”，不将动画标为真机效果。
- 成片复制到 `../docs/media/micforyou-promo-latest.mp4`，PNG 复制到 `promo-preview.png`，供双语 README 用稳定相对链接访问。GitHub 尚未发布，本轮只准备仓库内资产。
- 当前软件已实现暂停原音直通并通过自动、真实 ONNX 合成输入检查；真实设备和豆包新行为验收仍待完成。

正式输出：`out/micforyou-promo-v4.mp4`、`out/micforyou-promo-v4.gif`、`out/micforyou-promo-v4-preview.png`。配乐是程序合成，没有真实人声或降噪 A/B 试听。
