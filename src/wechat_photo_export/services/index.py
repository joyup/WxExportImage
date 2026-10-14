"""静态本地索引，无脚本和远程资源；所有名称转义、URL 编码。"""
import html
from urllib.parse import quote

from ..core.files import atomic_write, child
from ..core.images import EXT


def build_index(output, metadata):
    cards = []
    for full_hash, info in sorted(metadata["sessions"].items()):
        directory = child(output, info["dir"])
        if not directory.is_dir():
            continue
        photos = sorted(p for p in directory.iterdir() if p.suffix.lower() in set(EXT.values())-{".wxgf"}
                        and p.is_file() and child(output, p.relative_to(output)))
        if not photos:
            continue
        images = []
        for path in photos[:4]:
            url = quote(path.relative_to(output).as_posix(), safe="/")
            images.append(f'<a href="{url}"><img src="{url}" loading="lazy" alt="照片"></a>')
        title = html.escape(info.get("name") or "未命名会话")
        folder = quote(info["dir"]+"/", safe="/")
        cards.append(f'<article><h2>{title}</h2><p>{full_hash[:16]} · {len(photos)} 张</p>'
                     +'<div>'+"".join(images)+f'</div><a href="{folder}">打开照片目录</a></article>')
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>微信照片索引</title><style>body{font:15px 'Microsoft YaHei',sans-serif;margin:32px;color:#24292f;background:#f6f7f9}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:16px}
article{background:white;padding:20px;border:1px solid #ddd;border-radius:8px}h2{font-size:17px;margin-top:0}
p{color:#57606a}article div{display:flex;gap:5px;margin:12px 0}img{width:60px;height:60px;object-fit:cover}a{color:#0969da}</style>
<h1>微信照片索引</h1><p>此索引含会话名称及本地照片，保存在你的导出目录中。</p><main>'''
    atomic_write(child(output, "_索引.html"), (document+"".join(cards)+"</main></html>").encode())
