# WxExportImage

一个在本机运行的 Windows 桌面工具，将微信 4.x 已下载的高清照片按群聊、联系人分目录保存。
使用 Python + Qt，项目自有代码采用 MIT。当前为 Windows x64 预览版，macOS 后端尚未实现。

## 使用

获取 Windows 目录版 ZIP，完整解压后运行 `WeChatPhotoExport.exe`，无需安装 Python。
也可按下方步骤自行构建。当前为未签名预览版；支持范围见[兼容性](docs/兼容性.md)。

1. 登录微信，在工具中明确选择账号。
2. 刷新群名 / 用户名，搜索并勾选会话，或点击“勾选全部会话”。
3. 选择保存位置，预览照片数和源文件容量，再开始导出。
4. 可以取消；重新预览后继续会校验并跳过已完成文件。完成后打开照片目录或索引。

群名来自通过数据库校验的会话身份，人工确认名称优先。同名群使用不同会话编号。
只导出 `_h` 高清版和 `_W` 大图版，同一完整 fileId 优先 `_h`；普通版和缩略图不导出。
未识别会话按编号保存。不能恢复已被微信清理、且本机没有下载的原图。

WXGF 私有格式保留原文件，调用本机微信组件尝试生成静态图片；动画、透明效果尚不保证完整恢复。
转换失败会显示待转换数量，原文件保留，可再次导出重试。应用不附带微信 DLL。

详细步骤和错误处理见[桌面工具使用](docs/桌面工具使用.md)。
开发者可阅读[桌面架构](docs/桌面架构.md)，依赖与发布步骤见下文。

## 目录

```text
src/wechat_photo_export/
  core/          解密、图片策略、身份、数据库格式、文件安全
  platforms/     Windows 只读进程访问、DPAPI、原生转换
  services/      账号、名称、SQLite 状态、计划、导出、索引
  gui/           Qt 桌面界面和后台线程
packaging/       Windows 构建入口及配置
licenses/        固定版本的 Qt 许可原文、第三方声明及来源清单
tests/           人工构造的图片、数据库及界面回归测试
tools/           构建及干净源码快照
.github/         CI、依赖更新、故障反馈模板
docs/            使用、架构、兼容性与开源发布
.agents/skills/  调用公共 CLI 的项目技能入口
```

## 开发与构建

推荐 Windows x64 + Python 3.13。使用独立虚拟环境，避免把日常 Python 环境的额外组件打进包。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-desktop.lock
.venv/Scripts/python.exe -m pip install --no-build-isolation -e .
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe -m wechat_photo_export
.venv/Scripts/python.exe tools/build_windows.py
```

构建产物：`dist/WeChatPhotoExport/` 和 `dist/WeChatPhotoExport-windows-x64.zip`。
同时生成依赖版本、许可证原文和 SHA-256 文件，冻结程序自检通过后才生成 ZIP。
桌面版用 PySide6 Essentials 与 PyInstaller 目录包；第三方组件见[许可说明](THIRD_PARTY_NOTICES.md)。

安装核心包后也可使用公共 CLI，必须明确账号和范围，默认只预览。
以下账号路径、输出路径和群名均为占位示例，使用时替换为自己的值：

```powershell
wechat-photo-cli accounts
wechat-photo-cli sessions --account "X:/xwechat_files/示例账号" --refresh
wechat-photo-cli export --account "X:/xwechat_files/示例账号" --output "X:/Photos" --group "示例群"
wechat-photo-cli export --account "X:/xwechat_files/示例账号" --output "X:/Photos" --all --apply
```

项目技能入口见 [wechat-photo-export](.agents/skills/wechat-photo-export/SKILL.md)，用于通过公共 CLI
预览、导出和重试照片备份，依赖已安装的应用核心包。它采用 Codex 的[仓库技能目录](https://learn.chatgpt.com/docs/build-skills)，
在本项目中可用 `$wechat-photo-export` 调用；如果新技能没有出现在列表中，重启 Codex。

## 隐私与开源发布

图片、名称和任务记录只在本机处理，没有遥测或上传。图片密钥缓存用 Windows DPAPI 保护，
数据库密钥只留在内存。微信源数据只读；不同账号分开存储状态，输出目录绑定账号。
新增照片采用不可覆盖的原子写入，已有不同内容的文件保留并报告冲突。

本地状态位于 `%LOCALAPPDATA%/WeChatPhotoExport`。照片、索引、名称表和状态库都属于个人数据。
反馈问题时仅主动导出脱敏诊断，报告只含版本、计数和错误码。详见[SECURITY](SECURITY.md)。

```powershell
.venv/Scripts/python.exe tools/prepare_public_source.py --directory dist/github-source
```

产物为独立源码目录 `dist/github-source/`、`dist/wechat-photo-export-source.zip` 及 ZIP 的 `.sha256` 校验文件。
源码目录须不存在或为空，工具保留已有目录内容并拒绝写入。产物不含旧 `.git`、个人数据、编号脚本和实验记录。
公开快照只包含桌面应用、公共 CLI、项目技能入口、人工构造的测试及发布所需文档。
具体步骤见[开源发布指南](docs/开源发布指南.md)，贡献约定见[CONTRIBUTING](CONTRIBUTING.md)。
