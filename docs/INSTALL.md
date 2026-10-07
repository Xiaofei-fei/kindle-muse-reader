# Linux 安装与 Muse 配对

先完成 README 中的资讯模式本地启动。这个项目不会向 Kindle 写文件或要求升级、降级、恢复出厂设置。以下 systemd 操作在**你自己的 Linux 桥接主机**执行，不在 Kindle 执行。

## 1. 阅读服务

需要 Python 3.10+、SQLite 支持与 systemd。Muse 模式另外需要上游支持的 Debian / Ubuntu / Raspberry Pi OS、Bluetooth LE 广播与 BlueZ。Ubuntu 22.04 自带 Python 3.10；较旧发行版需要先确认 Python 版本。

先查看脚本和计划，再执行新安装：

```sh
sh deploy/install-reader.sh --dry-run
sudo sh deploy/install-reader.sh
sudoedit /etc/kindle-muse-bridge.conf
sudo systemctl restart kindle-muse-bridge
sudo cat /var/lib/kindle-muse-bridge/access_code
```

配置中的 `KINDLE_MUSE_HOST` 默认为 `127.0.0.1`。将它换成主机自己的固定局域网 IPv4 地址；建议在路由器给主机做 DHCP 地址保留。访问码只在自己的终端查看，不截图上传。

Kindle 连接同一家庭网络，用自带浏览器打开 `http://主机地址:8766/`，输入访问码并保存书签。只需要资讯时，到这里即可。

```sh
sudo systemctl status kindle-muse-bridge
curl http://127.0.0.1:8766/health
```

若绑定的是局域网地址，健康检查也使用那个地址。`ok: true` 只说明阅读服务可达；未配置 Muse 时 `connected` 和 `paired` 应为 false。

## 2. 安装固定版本官方 SDK（可选）

适配层使用上游私有接口，已测试提交固定为 `b139b45064b4dcecf7bfe97e75bc7f99c10c28b6`。不要未经测试直接替换为最新 main。

在桥接主机取得独立的 SDK 工作副本：

```sh
git clone https://github.com/facebookincubator/muse-gadget-sdk.git ../muse-gadget-sdk
git -C ../muse-gadget-sdk checkout b139b45064b4dcecf7bfe97e75bc7f99c10c28b6
less ../muse-gadget-sdk/linux/install.sh
bash ../muse-gadget-sdk/linux/install.sh --from ../muse-gadget-sdk/linux --run-as kindle-muse --no-pair
sudo systemctl stop musegadget
sudo sh deploy/enable-muse.sh
```

SDK 工作副本应放在本仓库之外，不提交到本项目。上游安装器需要 sudo，配置 BlueZ 并安装 `/opt/musegadget`；`--no-pair` 暂不开配对。本项目先替换默认设备命令为受限适配层，再进行配对。使用专用 `kindle-muse` 账户，不能把有 sudo 权限的个人账户交给设备命令。

若你已有配对的官方 Muse Gadget，请先停止服务、备份其状态并阅读原有配置；不要直接套用新安装流程。这个指南假设一台新桥接主机；现有服务迁移应由你审阅配置后操作。

## 3. 获取令牌并配对

在官方 [SDK 令牌页面](https://gadgets.muse.ai/settings/sdk-tokens) 使用自己的 Muse 账号，阅读并接受 [SDK 服务条款](https://gadgets.muse.ai/sdk-terms)，生成自己的令牌。不要把令牌放到命令参数、Git、issue 或示例配置。

本仓库提供隐藏输入的小工具；它只保存令牌到 SDK 的私密目录：

```sh
sudo /usr/bin/python3 scripts/configure_muse_token.py
sudo systemctl restart musegadget
sudo musegadget pair
```

手机靠近 Linux 主机，打开蓝牙，在 Muse **设置 → 设备** 开启 Developer mode，再添加 `MuseGadget...`。若进入 Wi-Fi 选择页，选 SDK 显示的现有网络并完成最终设置；主机本来已经联网。官方配对窗口约十分钟；仅蓝牙握手不代表最终配置完成。

Kindle 的 `/ask` 页面显示已连接后，发一个无敏感内容的短问题。只有在 Kindle 看到完整回传的回答，才算收发验收通过。Muse 在手机中回复而没有调用 `kindle.publish`，Kindle 不会把它当成已完成。

主机需要能访问 Muse 云端。普通手机聊天可用、蓝牙可发现、SDK 已配对与云端连接可用分别是不同检查；本项目不会配置代理或绕过账号授权。

## 4. 日常维护

```sh
sudo systemctl status kindle-muse-bridge musegadget
sudo journalctl -u kindle-muse-bridge -n 40
sudo journalctl -u musegadget -n 40
```

分享日志前自行检查并移除身份和个人信息。不要公开 SDK 状态文件或阅读数据库。浏览器中断可先回到书签刷新；休眠后需要手动唤醒。不要为了网页问题刷写 Kindle 固件。

## 升级与卸载

安装器只接受新安装，遇到 `/opt/kindle-muse-bridge` 已存在会退出，不覆盖现场。手动升级前停阅读服务（Muse 模式同时停 SDK）、在私密位置备份源码/服务配置和两个 SQLite 数据库，然后只更新 `src/` 与审阅过的服务配置；不要覆盖 `/var/lib` 状态、访问码或配对身份。运行测试后恢复服务，并验证已存回答和摘要能读。

要停止使用，先 `sudo systemctl disable --now kindle-muse-bridge`。若启用了适配层，停止 `musegadget` 并审阅 `kindle.conf` drop-in；删除 drop-in 会恢复上游默认命令，包括 shell 与文件访问，故不能在未审阅账户权限时直接恢复。SDK 卸载按上游说明进行。本项目不提供删除阅读数据库或 Kindle 内容的自动卸载脚本。

## 开发环境完整测试

在独立虚拟环境安装 SDK，**不运行安装器、无需 sudo、蓝牙、账号或令牌**：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'musegadget @ git+https://github.com/facebookincubator/muse-gadget-sdk.git@b139b45064b4dcecf7bfe97e75bc7f99c10c28b6#subdirectory=linux'
.venv/bin/python -m unittest discover -s tests -v
```
