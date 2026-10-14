# 参与开发

使用 Windows x64、Python 3.13。不要向仓库或 issue 添加本人或他人的微信数据。
测试使用临时目录及人工构造的图片和数据库；真实客户端验证只在本人或获授权环境本地进行。
文档使用占位路径和名称，不记录真实会话 ID、聊天内容、密钥或个人数据统计。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-desktop.lock
.venv/Scripts/python.exe -m pip install --no-build-isolation -e .
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe -m wechat_photo_export
```

公共核心放在 `src/wechat_photo_export/core`，不要导入 Qt 或 Windows 专属 API。
平台访问放在 `platforms`，GUI 通过 `services` 调用后台任务，不解析旧脚本输出。
修改文件身份、密钥验证、路径边界、原子发布或恢复逻辑时，补充对应失败场景的人工夹具测试。
日志和异常文本不得携带真实密钥或用户内容；新诊断字段需明确允许公开的数据类型。

使用 `tools/build_windows.py` 构建并验证冻结程序。源码包使用 `tools/prepare_public_source.py`。
依赖更新同时修改 `pyproject.toml` 和构建锁，运行图片、数据库、界面和冻结进程检查。
新增依赖核对许可证，发行包须保留相应原文和版本。测试没有覆盖的客户端版本不得标为支持。

公开源码包含桌面应用、公共 CLI、项目技能及发布所需资源，本地运行数据不进入仓库。
公开前按[发布指南](docs/开源发布指南.md)创建新仓库，文档清理不能移除旧 Git 历史。
Windows 是当前实施范围；macOS 改动应通过平台接口接入，不得以可启动界面代替导出验证。
