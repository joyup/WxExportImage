# 第三方组件

本项目自有代码采用 MIT；第三方组件各自的许可证保持有效，不由 MIT 替代。
目录版保留 Qt 的动态库，`licenses/` 包含构建环境 wheel 附带的许可证和 notice 原文，
`build-info.json` 记录实际版本。正式发布时应审阅这些文件及组件分发要求。

Qt 6.12.0 的 wheel 在本次构建中只附商业许可选项原文，因此另行收集了官方固定提交中的
Qt Base、Qt Image Formats 与 PySide/ Shiboken 许可及第三方 attribution。
`licenses/UPSTREAM_MANIFEST.json` 记录版本、不可变提交、原文 URL 和逐文件 SHA-256，
构建时核对版本和摘要。资源目录是第三方原文，分别遵循其自身许可，不属于项目的 MIT 自有代码。
采用 Qt/PySide 的开源 LGPLv3 选项，并保留 GNU GPL 等可选许可原文；
未使用文档列出的 GPL 专属 Qt 模块。wheel 的开源选项见
[上游 PyPI 发布说明](https://pypi.org/project/PySide6-Essentials/6.12.0/)。

| 组件 | 用途 | 上游与许可证信息 |
|---|---|---|
| Python | 运行时 | [Python 许可证](https://docs.python.org/3/license.html) |
| PySide6 Essentials / Qt | 桌面界面 | [Qt for Python](https://doc.qt.io/qtforpython-6/)；含 LGPL/GPL 等原文，以实际组件为准 |
| shiboken6 | Qt 绑定运行时 | 同 Qt for Python 发行说明及 wheel 许可证 |
| PyCryptodome | AES | [上游许可](https://www.pycryptodome.org/src/license) |
| Pillow | 图片解析与校验 | [上游许可](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| PyInstaller | 冻结应用 | [上游许可及分发例外](https://pyinstaller.org/en/stable/license.html) |

本项目未修改这些组件的源码。可替换的动态库与源码构建步骤保留在发行目录及公开仓库中。
对应源码可从清单所列的 Qt 官方仓库固定提交取得；第三方 copyright/notice 与其原许可证一并保留。
Python 运行时许可由构建脚本从当前 Python 安装目录收集；缺少原文时构建应停止。

WXGF 转换调用用户本机微信安装目录的 `VoipEngine.dll`，不复制到安装包或公开仓库。
本项目不拥有微信组件的分发授权，也不将其纳入 MIT 许可。无法发现组件时保留 WXGF 原文件。

数据库处理采用 SQLCipher 与 SQLite 公开格式文档；Windows 取钥布局参考已注明的公开研究，
每个候选都需对用户所选数据库验证 HMAC，不依赖未验证的名字猜测：

- [SQLCipher 设计](https://www.zetetic.net/sqlcipher/design/)
- [SQLite WAL 文件格式](https://www.sqlite.org/fileformat2.html#wal_file_format)
- [Config.Cipher 布局参考，固定版本](https://github.com/fanyuantaier/wechatauto-replica/blob/d6e61bea7f9c75906faa8b71d37ef3572fba2454/wechatauto/db.py)
