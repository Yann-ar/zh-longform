#!/usr/bin/env python3
"""策展卡片流：书单、人物思想档案的书目卡片（B 版式，2026-11-08）。

和小红书轮播图共用一套视觉：纸色底、一种强调色、宋体标题加冬青黑体正文，
没有胶囊标签、阴影卡片和装饰。字体、颜色、断行规则都取自 generate_xhs_slides.py。

输出：
  imgs/cards/card_XX_xhs.png     1080 × 1440，小红书轮播
  imgs/cards/card_XX_wechat.png  1080 × 810，公众号正文内嵌

卡片数据写在 文章.md 的 <!-- card ... --> 注释块里，或文章目录下的 cards.json，字段：
  index, title_zh, title_en, author_zh, author_en, badge, quote_zh, quote_en, image

用法：
  python3 generate_curated_cards.py --article "05_待发表/<主题>" [--palette green] [--series 系列名]
  python3 generate_curated_cards.py --article "05_待发表/<主题>" --mode xhs
  python3 generate_curated_cards.py --demo
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import generate_xhs_slides as xs
from PIL import Image, ImageDraw

# 旧配色名兼容到新的四组强调色。
OLD_PRESETS = {'warm_paper': 'red', 'cream': 'ochre', 'sage': 'green', 'ink_blue': 'blue'}
BORDER = (217, 211, 202)


def palette_colors(name):
    name = OLD_PRESETS.get(name, name)
    if name not in xs.PALETTES:
        raise ValueError(f'配色只能是 {"、".join(xs.PALETTES)}')
    return xs.hex_rgb(xs.PALETTES[name][0])


def load_book(path, max_w, max_h):
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise ValueError(f'找不到书影图片 {p}')
    im = Image.open(p).convert('RGB')
    im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    return im


def paste_book(canvas, book, x, y):
    canvas.paste(book, (x, y))
    ImageDraw.Draw(canvas).rectangle((x, y, x + book.width - 1, y + book.height - 1), outline=BORDER, width=1)


def author_line(item):
    author = item.get('author_zh', '')
    if item.get('author_en'):
        author = f"{author}（{item['author_en']}）" if author else item['author_en']
    return author


def text_blocks(item, width, sizes, accent):
    """按顺序生成文字块：书名、英文书名、作者、引语标签、中文引语、英文原文。"""
    title_size, meta_size, badge_size, quote_size, en_size = sizes
    blocks = []
    if item.get('title_zh'):
        f = xs.font(xs.SONG_BOLD, title_size)
        blocks.append((xs.wrap(item['title_zh'], f, width), f, round(title_size * 1.35), xs.INK, 20))
    meta = [m for m in (item.get('title_en', ''), author_line(item)) if m]
    for i, m in enumerate(meta):
        f = xs.font(xs.HEI_REGULAR, meta_size)
        blocks.append((xs.wrap(m, f, width), f, round(meta_size * 1.6), xs.MUTED, 44 if i == len(meta) - 1 else 0))
    if item.get('badge'):
        f = xs.font(xs.HEI_BOLD, badge_size)
        blocks.append((xs.wrap(item['badge'], f, width), f, round(badge_size * 1.6), accent, 16))
    if item.get('quote_zh'):
        f = xs.font(xs.SONG_REGULAR, quote_size)
        blocks.append((xs.wrap(item['quote_zh'], f, width), f, round(quote_size * 1.7), xs.INK, 20))
    if item.get('quote_en'):
        f = xs.font(xs.HEI_REGULAR, en_size)
        blocks.append((xs.wrap(item['quote_en'], f, width), f, round(en_size * 1.6), xs.MUTED, 0))
    return blocks


def blocks_height(blocks):
    return sum(len(lines) * lead + gap for lines, _, lead, _, gap in blocks) - (blocks[-1][4] if blocks else 0)


def draw_blocks(d, blocks, x, y, accent):
    for lines, f, lead, color, gap in blocks:
        y = xs.draw_lines(d, lines, f, x, y, lead, color, accent) + gap
    return y


def render_xhs_card(item, out, page, total, accent, series, base=Path('.')):
    im, d = xs.frame(xs.PAPER, item['index'], accent, series, f'{page} / {total}', xs.MUTED)
    width = xs.W - 2 * xs.MARGIN_X
    book = load_book(base / item['image'] if item.get('image') else None, 420, 420)
    blocks = text_blocks(item, width, (60, 30, 30, 44, 28), accent)
    top, bottom = xs.CONTENT_TOP, xs.CONTENT_BOTTOM
    need = blocks_height(blocks) + (book.height + 72 if book else 0)
    if need > bottom - top:
        raise ValueError(f'第 {item["index"]} 张文字超出版面 {need - (bottom - top)} px，请删减')
    y = top + (bottom - top - need) // 2
    if book:
        paste_book(im, book, xs.MARGIN_X, y)
        y += book.height + 72
    draw_blocks(d, blocks, xs.MARGIN_X, y, accent)
    im.save(out)


def render_wechat_card(item, out, accent, base=Path('.')):
    w, h, margin = 1080, 810, 88
    im = Image.new('RGB', (w, h), xs.PAPER)
    d = ImageDraw.Draw(im)
    book = load_book(base / item['image'] if item.get('image') else None, 380, 600)
    text_x = margin + (book.width + 72 if book else 0)
    width = w - text_x - margin
    blocks = text_blocks(item, width, (44, 24, 24, 34, 22), accent)
    head = 34 + 24 + 5 + 40    # 章节号、间距、色条、间距
    need = head + blocks_height(blocks)
    if need > h - 2 * margin:
        raise ValueError(f'第 {item["index"]} 张公众号卡片文字超出版面 {need - (h - 2 * margin)} px，请删减')
    if book:
        paste_book(im, book, margin, (h - book.height) // 2)
    y = (h - need) // 2
    d.text((text_x, y), item['index'], font=xs.font(xs.SONG_BOLD, 34), fill=accent, anchor='lt')
    d.rectangle((text_x, y + 58, text_x + 48, y + 62), fill=accent)
    draw_blocks(d, blocks, text_x, y + head, accent)
    im.save(out)


def parse_cards_from_markdown(md_text):
    cards = []
    for block in re.findall(r'<!--\s*card\s*\n(.*?)\n\s*-->', md_text, re.S | re.I):
        item = {}
        for line in block.strip().splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                item[k.strip()] = v.strip()
        if item:
            cards.append(item)
    return cards


def load_items(art_dir):
    spec = art_dir / 'cards.json'
    if spec.is_file():
        items = json.loads(spec.read_text(encoding='utf-8'))
    else:
        items = parse_cards_from_markdown((art_dir / '文章.md').read_text(encoding='utf-8'))
    for i, it in enumerate(items, 1):
        it['index'] = str(it.get('index') or f'{i:02}')
        if not it.get('image') and it.get('cover_image'):
            it['image'] = it['cover_image']      # 旧字段名
    return items


def build(art_dir, mode='all', palette='green', series='', output_dir=None):
    art_dir = Path(art_dir)
    items = load_items(art_dir)
    if not items:
        raise ValueError('没有找到卡片数据：文章.md 里没有 <!-- card --> 块，也没有 cards.json')
    if len(items) > 18:
        raise ValueError(f'共 {len(items)} 张，超过小红书 18 张上限')
    accent = palette_colors(palette)
    out = Path(output_dir) if output_dir else art_dir / 'imgs' / 'cards'
    out.mkdir(parents=True, exist_ok=True)
    for i, it in enumerate(items, 1):
        if mode in ('all', 'xhs'):
            render_xhs_card(it, out / f'card_{it["index"]}_xhs.png', i, len(items), accent, series, art_dir)
        if mode in ('all', 'wechat'):
            render_wechat_card(it, out / f'card_{it["index"]}_wechat.png', accent, art_dir)
    print(f'已输出 {len(items)} 组卡片到 {out}')


def run_demo():
    demo = Path(tempfile.mkdtemp(prefix='curated-cards-demo-'))
    Image.new('RGB', (380, 580), (140, 60, 50)).save(demo / 'book.png')
    (demo / '文章.md').write_text('''<!-- card
index: 01
title_zh: 《示例书名》
title_en: Sample Book Title
author_zh: 示例作者
author_en: Sample Author
badge: 某位作家说
quote_zh: 「这里放一句查得到出处的一手原话。」
quote_en: A verifiable first-hand quotation goes here.
image: book.png
-->
''', encoding='utf-8')
    build(demo, series='演示书单')
    print(f'演示卡片在 {demo / "imgs" / "cards"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--article', help='文章目录，读取 文章.md 的 card 块或 cards.json')
    parser.add_argument('--output-dir', help='输出目录，默认 imgs/cards')
    parser.add_argument('--mode', choices=['all', 'wechat', 'xhs'], default='all')
    parser.add_argument('--palette', '--preset', dest='palette', default='green',
                        help='green、blue、red、ochre；旧名 warm_paper、cream、sage、ink_blue 仍可用')
    parser.add_argument('--series', default='', help='小红书卡片底部左侧的系列名')
    parser.add_argument('--demo', action='store_true', help='生成一组演示卡片到临时目录')
    args = parser.parse_args()
    if args.demo:
        run_demo()
    elif args.article:
        build(args.article, args.mode, args.palette, args.series, args.output_dir)
    else:
        parser.print_help()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f'卡片未生成：{exc}', file=sys.stderr)
        sys.exit(1)
