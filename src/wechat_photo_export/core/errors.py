"""错误码可以分享；原始异常、账号、路径和图片头不进入诊断。"""
MESSAGES = {
    "account_invalid": "请选择包含 msg/attach 的微信 4.x 账号目录。",
    "source_changed": "源图片已变化或被清理，请重新预览。",
    "unsafe_path": "目录含链接、越界路径或与微信数据重叠，请选择其他目录。",
    "output_owned": "此目录已有其他账号或旧脚本的数据，请选择新的输出目录。",
    "output_busy": "另一个任务正在使用此输出目录。",
    "target_conflict": "目标文件已有不同内容，已保留原文件。请选择新的输出目录。",
    "wechat_not_running": "请登录 Windows 微信，打开几张原图后重试。",
    "image_key_unavailable": "未找到有效图片密钥，请在微信打开 2–3 张原图后重试。",
    "contact_key_unavailable": "暂时无法读取会话名称，可以按编号导出或稍后刷新名称。",
    "cache_invalid": "本地状态无法验证，未改写原记录。",
    "decoder_unavailable": "未找到本机微信图片转换组件，特殊格式原文件已保存。",
    "decode_failed": "图片转换失败，特殊格式原文件已保存，可重试。",
    "image_invalid": "图片格式或内容验证失败，未作为成功图片导出。",
    "image_too_large": "图片超过本版处理上限。",
    "disk_full": "保存位置空间不足，释放空间后可以继续。",
    "permission_denied": "无法访问目录，请检查当前用户的权限。",
    "platform_unsupported": "当前发行版仅支持 Windows x64。",
    "cancelled": "任务已取消，已完成的文件保留，再次导出可以继续。",
    "unexpected": "操作失败。可导出不含个人信息的诊断报告。",
}


class AppError(Exception):
    def __init__(self, code):
        self.code = code if code in MESSAGES else "unexpected"
        super().__init__(MESSAGES[self.code])


def error_code(exc):
    if isinstance(exc, AppError):
        return exc.code
    if isinstance(exc, InterruptedError):
        return "cancelled"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, FileNotFoundError):
        return "source_changed"
    if isinstance(exc, OSError) and (exc.errno == 28 or getattr(exc, "winerror", 0) == 112):
        return "disk_full"
    return "unexpected"
