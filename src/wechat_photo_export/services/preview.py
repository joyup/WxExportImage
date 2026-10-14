"""所选会话的少量高清预览只留在内存，不生成缩略图文件。"""
from ..core.errors import AppError, error_code
from ..core.files import child
from ..core.images import decrypt_any, pick_best
from ..platforms.decoder import Decoder
from ..platforms.windows import decoder_path, image_keys
from .catalog import dat_files
from .jobs import MAX_INPUT, validate_image


def preview_images(account, state, full_hash, cancelled=lambda: False, progress=lambda _: None):
    keys = image_keys(account, state, cancelled, progress)
    files = sorted(pick_best(dat_files(child(account.attach, full_hash), cancelled)), key=lambda row: row[1])
    if not files:
        return []
    decoder = Decoder(decoder_path())
    images = []
    try:
        for path, _, _ in files[:12]:
            if cancelled():
                raise AppError("cancelled")
            try:
                if path.stat().st_size > MAX_INPUT:
                    continue
                data, fmt = decrypt_any(path, *keys)
                if data is None:
                    continue
                if fmt == "wxgf":
                    data = decoder.decode(data, cancelled)
                validate_image(data)
                # 只把小尺寸 PNG 交给界面，避免多个原图占用大量内存。
                import io
                from PIL import Image
                stream = io.BytesIO()
                with Image.open(io.BytesIO(data)) as image:
                    image.thumbnail((480, 360))
                    image.convert("RGB").save(stream, "PNG")
                images.append(stream.getvalue())
                if len(images) == 3:
                    break
            except Exception as exc:
                if error_code(exc) == "cancelled":
                    raise AppError("cancelled") from None
        if not images:
            raise AppError("image_invalid")
        return images
    finally:
        decoder.close()
