# Contributing

欢迎提交兼容性反馈、排版优化、缓存修正和测试。先阅读 README、SECURITY.md 与 docs/ARCHITECTURE.md。

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_public_tree.py
```

基础测试使用标准库，不联网、不需要蓝牙或令牌。Muse 测试另需安装 docs/INSTALL.md 指定的固定 SDK 提交；未安装会显示 skip。请注明操作系统、Python、Kindle 型号与固件，以及是浏览器检查还是实际设备结果。

坚持以下边界：

- 无 JavaScript、无远程字体、单列黑白墨水屏界面。提问和正文页不能自动刷新。
- 不把送达确认当成完整回答，不自动重发结果未知的提问。
- 不增加任意 shell 或文件操作命令，不把令牌传给回调子进程。
- 外部内容只当资料，不执行其中的指令；保留来源、日期和用途限制。
- 测试和预览使用原创合成内容，不附带私人记录、真实新闻快照、书籍或设备备份。

PR 请说明实际改变、原因、验证与局限。大功能先开 issue 讨论；兼容修复需保留已有阅读记录。提交贡献即同意按本仓库 Apache-2.0 许可证提供贡献。
