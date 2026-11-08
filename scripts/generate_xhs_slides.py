#!/usr/bin/env python3
"""小红书轮播图生成工具（B 版式，2026-11-08）。

读取文章目录下的 `小红书图片.md`，输出 1080 × 1440 的 PNG 到 `imgs/xhs/`。
版式：一种纸色底，一种强调色。左上角章节号和短色条，底部系列名和页码。没有框、标签和装饰。

三种卡片，在 `小红书图片.md` 里用二级标题区分：
  ## 封面：标题文字      下一行可写一句副标题
封面卡默认在顶部放封面母稿插画 `imgs/cover-source/master.png`：
标题和副标题各须一行排下，排不下就改短，比如标题只留核心短语，其余挪到副标题。
`cover_art` 可另指插画，写 none 表示不放；`cover_focus` 调裁切焦点。
  ## 正文：小标题        下面写 1～3 段短文字，==文字== 会染成强调色
  ## 引语                下面第一段是原话，以 — 开头的一行是出处

用法：
  python3 generate_xhs_slides.py "05_待发表/<主题>"            # 出图
  python3 generate_xhs_slides.py "05_待发表/<主题>" --check    # 只检查能否排下，不出图
  python3 generate_xhs_slides.py "05_待发表/<主题>" --full     # 全文轮播图：文章_小红书版.md 全文不删减，输出到 imgs/xhs-full/

全文轮播图的封面卡和精简版完全相同（取自 小红书图片.md 的封面卡和插画），之后按正文顺序连续排版：
二级标题、段落、列表、引用、表格和正文配图都保留，段落排不下时接到下一张。
"""
import argparse
import os
import re
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / '_vendor'  # 随项目附带的 Pillow，系统 Python 没装时使用
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))
from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1080, 1440
MARGIN_X = 104
TOP, BOTTOM = 120, 96
PAPER = (246, 243, 238)
INK = (31, 31, 31)
MUTED = (107, 101, 93)
MUTED_ON_TINT = (95, 90, 82)
SONG = '/System/Library/Fonts/Supplemental/Songti.ttc'
HEI = '/System/Library/Fonts/Hiragino Sans GB.ttc'


def font_spec(env, default):
    """字体可用环境变量覆盖，格式为「路径」或「路径#字面索引」，例如 /usr/share/fonts/NotoSerifCJK.ttc#1。"""
    value = os.environ.get(env, '')
    if not value:
        return default
    path, _, index = value.partition('#')
    return (path, int(index or 0))


SONG_BOLD = font_spec('ZH_LONGFORM_SERIF_BOLD', (SONG, 1))
SONG_REGULAR = font_spec('ZH_LONGFORM_SERIF_REGULAR', (SONG, 6))
HEI_REGULAR = font_spec('ZH_LONGFORM_SANS_REGULAR', (HEI, 0))
HEI_BOLD = font_spec('ZH_LONGFORM_SANS_BOLD', (HEI, 2))

# 强调色与配套的引语底色，和画布上 Tweaks 的四组一致。
PALETTES = {
    'green': ('#3F5F52', '#E6EAE3'),
    'blue': ('#3E5C7A', '#E4EAF1'),
    'red': ('#9A4A3C', '#F3E6E1'),
    'ochre': ('#7A5A1E', '#F3ECDD'),
}

NO_LINE_START = set('，。、：；？！」』）》…%,.;:?!)')
NO_LINE_END = set('「『（《(')
CJK = re.compile(r'[一-鿿]')


def hex_rgb(value):
    value = value.strip().lstrip('#')
    if not re.fullmatch(r'[0-9A-Fa-f]{6}', value):
        raise ValueError(f'颜色须为 #RRGGBB：{value}')
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def font(spec, size):
    path, index = spec
    try:
        return ImageFont.truetype(path, size, index=index)
    except OSError:
        raise ValueError(f'找不到字体 {path}（索引 {index}）。非 macOS 系统请用环境变量 ZH_LONGFORM_SERIF_BOLD、'
                         'ZH_LONGFORM_SERIF_REGULAR、ZH_LONGFORM_SANS_REGULAR、ZH_LONGFORM_SANS_BOLD 指定中文字体，见 README') from None


# ---------- 解析 ----------

def parse(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    meta = {}
    fm = re.match(r'\A---\s*\n(.*?)\n---\s*\n', text, re.S)
    if fm:
        for line in fm[1].splitlines():
            m = re.match(r'''^(\w+):\s*("[^"]*"|'[^']*'|[^#]*?)\s*(?:#.*)?$''', line)
            if m:
                meta[m[1]] = m[2].strip().strip('"\'')
        text = text[fm.end():]
    text = re.sub(r'%%.*?%%', '', text, flags=re.S)
    cards = []
    for block in re.split(r'^##\s+', text, flags=re.M)[1:]:
        head, _, body = block.partition('\n')
        head = head.strip()
        paras = [re.sub(r'\s*\n\s*', '', p).strip() for p in re.split(r'\n\s*\n', body) if p.strip()]
        kind, _, title = head.partition('：')
        kind = kind.strip()
        if kind == '封面':
            cards.append({'kind': 'cover', 'title': title.strip(), 'subtitle': paras[0] if paras else ''})
        elif kind == '正文':
            if not title.strip() or not paras:
                raise ValueError(f'正文卡须有小标题和至少一段文字：{head}')
            cards.append({'kind': 'body', 'title': title.strip(), 'paras': paras})
        elif kind == '引语':
            source = next((p for p in paras if p.startswith(('—', '——'))), '')
            quote = [p for p in paras if p != source]
            if len(quote) != 1 or not source:
                raise ValueError('引语卡须有一段原话和一行以 — 开头的出处')
            cards.append({'kind': 'quote', 'quote': quote[0], 'source': source.lstrip('—').strip()})
        else:
            raise ValueError(f'未知卡片类型「{kind}」，只能是 封面、正文、引语')
    if not cards:
        raise ValueError('没有读到任何卡片，二级标题须写成「## 正文：……」等形式')
    if len(cards) > 18:
        raise ValueError(f'共 {len(cards)} 张，超过小红书 18 张上限')
    return meta, cards


# ---------- 断行 ----------

def runs(text):
    """把 ==高亮== 拆成 (文字, 是否高亮) 的片段。"""
    out = []
    for i, part in enumerate(re.split(r'==', text)):
        if part:
            out.append((part, i % 2 == 1))
    if text.count('==') % 2:
        raise ValueError(f'高亮标记 == 没有成对：{text}')
    return out


def tokens(text):
    """断行单位：英文单词和数字不拆；外文人名中点两侧各最多 4 个汉字粘在一起，不在名字中间换行。"""
    toks = re.findall(r'[A-Za-z0-9]+|.', text)
    out, i = [], 0
    while i < len(toks):
        if toks[i] == '·' and out:
            head = out.pop()
            while out and len(head) < 4 and len(out[-1]) == 1 and CJK.match(out[-1]):
                head = out.pop() + head
            tail, j = '', i + 1
            while j < len(toks) and len(tail) < 4 and len(toks[j]) == 1 and CJK.match(toks[j]):
                tail += toks[j]
                j += 1
            out.append(head + '·' + tail)
            i = j
            continue
        out.append(toks[i])
        i += 1
    return out


def wrap(text, fnt, width):
    """返回行列表，每行是 [(文字, 是否高亮)]。遵守避头尾，避免末行孤字。"""
    units = []
    for part, hl in runs(text):
        units += [(t, hl) for t in tokens(part)]
    lines, line = [], []
    measure = lambda ln: fnt.getlength(''.join(t for t, _ in ln))
    for unit in units:
        if not line or measure(line + [unit]) <= width:
            line.append(unit)
            continue
        if unit[0] in NO_LINE_START:
            if measure(line) <= width:
                line.append(unit)      # 允许一个收尾标点挂在行尾
                continue
            # 已经挂了一个，再挂就太长：把这些标点连同前一个字一起移到下一行。
            carry = []
            while line and line[-1][0] in NO_LINE_START:
                carry.insert(0, line.pop())
            if line:
                carry.insert(0, line.pop())
            lines.append(line)
            line = carry + [unit]
            continue
        carry = []
        while line and line[-1][0] in NO_LINE_END:
            carry.insert(0, line.pop())
        lines.append(line)
        line = carry + [unit]
    if line:
        lines.append(line)
    if len(lines) > 1:
        last = ''.join(t for t, _ in lines[-1]).rstrip('，。、：；？！」』）》')
        prev = lines[-2]
        if len(last) <= 2 and len(prev) > 2:
            move = prev[-1]
            if len(move[0]) == 1 and move[0] not in NO_LINE_START | NO_LINE_END and prev[-2][0] not in NO_LINE_END:
                lines[-2], lines[-1] = prev[:-1], [move] + lines[-1]
    return lines


def draw_lines(d, lines, fnt, x, y, leading, color, accent):
    for line in lines:
        cx = x
        if line and line[0][0][:1] in '「『《（':
            cx -= fnt.getlength(line[0][0][0]) / 2   # 行首的开引号、书名号、括号悬挂半个字
        for text, hl in line:
            d.text((cx, y), text, font=fnt, fill=accent if hl else color, anchor='la')
            cx += fnt.getlength(text)
        y += leading
    return y


# ---------- 版式 ----------

def frame(bg, number, accent, series, page, muted):
    im = Image.new('RGB', (W, H), bg)
    d = ImageDraw.Draw(im)
    if number:
        d.text((MARGIN_X, TOP), number, font=font(SONG_BOLD, 44), fill=accent, anchor='lt')
        d.rectangle((MARGIN_X, TOP + 68, MARGIN_X + 64, TOP + 73), fill=accent)
    small = font(HEI_REGULAR, 28)
    if series:
        d.text((MARGIN_X, H - BOTTOM), series, font=small, fill=muted, anchor='ls')
    d.text((W - MARGIN_X, H - BOTTOM), page, font=small, fill=muted, anchor='rs')
    return im, d


CONTENT_TOP, CONTENT_BOTTOM = TOP + 120, H - BOTTOM - 80   # 章节号下方到页脚上方


def place(blocks, gap_after, top=CONTENT_TOP, bottom=CONTENT_BOTTOM):
    total = sum(len(lines)*lead for lines, _, lead, _ in blocks) + sum(gap_after[:len(blocks)-1])
    room = bottom - top
    if total > room:
        raise ValueError(f'文字超出版面 {total - room} px，请删减或拆成两张')
    return top + (room - total)//2


ART_H = 760   # 封面插画条高度
DEFAULT_COVER_ART = 'imgs/cover-source/master.png'   # 没写 cover_art 时自动使用


def cover_with_art(card, page, accent, series, art, focus):
    """封面卡：顶部整幅宽的封面插画条，下方标题。插画只裁不改色。"""
    im, d = frame(PAPER, '', accent, series, page, MUTED)
    strip = ImageOps.fit(art.convert('RGB'), (W, ART_H), method=Image.Resampling.LANCZOS, centering=focus)
    im.paste(strip, (0, 0))
    width = W - 2*MARGIN_X
    tf, sf = font(SONG_BOLD, 76), font(HEI_REGULAR, 38)
    blocks = [(wrap(card['title'], tf, width), tf, 106, INK)]
    if card['subtitle']:
        blocks.append((wrap(card['subtitle'], sf, width), sf, 64, MUTED))
    for (lines, *_), name in zip(blocks, ('标题', '副标题')):
        if len(lines) > 1:
            raise ValueError(f'有插画的封面卡{name}须一行排下，现在是 {len(lines)} 行，请改短；'
                             '标题只留核心短语，比如「愿我不曾虚度」，其余挪到副标题')
    y = place(blocks, [48, 0], top=ART_H + 130, bottom=CONTENT_BOTTOM)
    d.rectangle((MARGIN_X, y - 56, MARGIN_X + 64, y - 51), fill=accent)
    for i, (lines, fnt, lead, color) in enumerate(blocks):
        y = draw_lines(d, lines, fnt, MARGIN_X, y, lead, color, accent) + (48 if i == 0 else 0)
    return im


def render_card(card, n, total, number, accent, tint, series, art=None, focus=(0.5, 0.5)):
    width = W - 2*MARGIN_X
    page = f'{n} / {total}'
    if card['kind'] == 'quote':
        im, d = frame(tint, number, accent, series, page, MUTED_ON_TINT)
        qf, sf = font(SONG_REGULAR, 54), font(HEI_BOLD, 32)
        blocks = [(wrap(card['quote'], qf, width), qf, 94, INK), (wrap(card['source'], sf, width), sf, 46, accent)]
        y = place(blocks, [56, 0])
        y = draw_lines(d, blocks[0][0], qf, MARGIN_X, y, 94, INK, accent)
        draw_lines(d, blocks[1][0], sf, MARGIN_X, y + 56, 46, accent, accent)
        return im
    if card['kind'] == 'cover' and art is not None:
        return cover_with_art(card, page, accent, series, art, focus)
    if card['kind'] == 'cover':
        im, d = frame(PAPER, '', accent, series, page, MUTED)
        tf, sf = font(SONG_BOLD, 84), font(HEI_REGULAR, 40)
        blocks = [(wrap(card['title'], tf, width), tf, 118, INK)]
        if card['subtitle']:
            blocks.append((wrap(card['subtitle'], sf, width), sf, 70, MUTED))
        y = place(blocks, [72, 0])
        d.rectangle((MARGIN_X, y - 64, MARGIN_X + 64, y - 59), fill=accent)
        for i, (lines, fnt, lead, color) in enumerate(blocks):
            y = draw_lines(d, lines, fnt, MARGIN_X, y, lead, color, accent) + (72 if i == 0 else 0)
        return im
    im, d = frame(PAPER, number, accent, series, page, MUTED)
    tf, bf = font(SONG_BOLD, 66), font(HEI_REGULAR, 40)
    blocks = [(wrap(card['title'], tf, width), tf, 90, INK)]
    blocks += [(wrap(p, bf, width), bf, 72, INK) for p in card['paras']]
    gaps = [52] + [40]*(len(card['paras'])-1) + [0]
    y = place(blocks, gaps)
    for (lines, fnt, lead, color), gap in zip(blocks, gaps):
        y = draw_lines(d, lines, fnt, MARGIN_X, y, lead, color, accent) + gap
    return im


def load_setup(root):
    """读取 小红书图片.md，返回卡片和两种轮播图共用的样式设置。"""
    source = root / '小红书图片.md'
    if not source.is_file():
        raise ValueError(f'缺少 {source}，可复制 Skill 的 templates/小红书图片模板.md')
    meta, cards = parse(source)
    palette = meta.get('palette', 'green')
    if palette not in PALETTES:
        raise ValueError(f'palette 只能是 {"、".join(PALETTES)}')
    accent_hex, tint_hex = PALETTES[palette]
    accent = hex_rgb(meta.get('accent', accent_hex))
    tint = hex_rgb(meta.get('tint', tint_hex))
    series = meta.get('series', '')
    art, focus = None, (0.5, 0.5)
    art_rel = meta.get('cover_art') or (DEFAULT_COVER_ART if (root / DEFAULT_COVER_ART).is_file() else '')
    if art_rel.lower() == 'none':
        art_rel = ''
    elif not art_rel and any(c['kind'] == 'cover' for c in cards):
        print(f'提示：没有 {DEFAULT_COVER_ART}，封面卡暂时不放插画；封面母稿做好后重新出图', file=sys.stderr)
    if art_rel:
        art_path = root / art_rel
        if not art_path.is_file():
            raise ValueError(f'找不到封面插画 {art_path}')
        art = Image.open(art_path)
        if meta.get('cover_focus'):
            try:
                focus = tuple(float(v) for v in meta['cover_focus'].split(','))
                assert len(focus) == 2 and all(0 <= v <= 1 for v in focus)
            except (ValueError, AssertionError):
                raise ValueError('cover_focus 须为 0～1 的 x,y，例如 0.5,0.6') from None
    return cards, dict(accent=accent, tint=tint, series=series, art=art, focus=focus)


def save_images(images, out, replace):
    if out.exists() and any(out.glob('*.png')) and not replace:
        raise ValueError(f'{out} 已有图片；确认覆盖请加 --replace')
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob('*.png'):
        old.unlink()
    for i, im in enumerate(images, 1):
        im.save(out / f'{i:02}.png')
    print(f'已输出 {len(images)} 张到 {out}')


def build(article_dir, check_only=False, replace=False):
    root = Path(article_dir)
    cards, st = load_setup(root)
    accent, tint, series, art, focus = st['accent'], st['tint'], st['series'], st['art'], st['focus']
    out = root / 'imgs' / 'xhs'
    images, number = [], 0
    for i, card in enumerate(cards, 1):
        if card['kind'] != 'cover':
            number += 1
        try:
            images.append(render_card(card, i, len(cards), f'{number:02}' if card['kind'] != 'cover' else '', accent, tint, series, art, focus))
        except ValueError as exc:
            raise ValueError(f'第 {i} 张：{exc}') from None
    if check_only:
        print(f'共 {len(cards)} 张，全部排得下。')
        return
    save_images(images, out, replace)


# ---------- 全文轮播图 ----------

FULL_MAX = 18                 # 小红书一篇笔记最多 18 张图
FULL_BODY = (HEI_REGULAR, 36, 62)    # 全文正文：字号、行距
FULL_HEAD = (SONG_BOLD, 52, 74)      # 二级标题
FULL_QUOTE = (SONG_REGULAR, 40, 68)  # 引用段
FULL_CAPTION = (HEI_REGULAR, 26, 40) # 配图说明
PARA_GAP, HEAD_BEFORE, HEAD_AFTER = 30, 44, 26
IMG_MAX_H = 600
EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u20E3]')


def inline_md(text):
    """去掉行内 Markdown，只保留 ==高亮==。"""
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<br\s*/?>\s*(?=[（(])', '', text)
    text = re.sub(r'<br\s*/?>', '，', text)
    text = re.sub(r'\*\*(.+?)\*\*|__(.+?)__', lambda m: m[1] or m[2], text)
    text = re.sub(r'(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return EMOJI.sub('', text).strip()     # 字体没有 emoji，去掉


def parse_article(path):
    """把 文章_小红书版.md 拆成按顺序的块：('head', 文字) ('para', 文字) ('quote', 文字) ('image', 路径, 说明)。
    跳过 frontmatter、一级标题、紧跟其后的斜体副标题、分隔线和注释，其余全部保留。"""
    text = Path(path).read_text(encoding='utf-8-sig')
    text = re.sub(r'\A---\s*\n.*?\n---\s*\n', '', text, flags=re.S)
    text = re.sub(r'%%.*?%%', '', text, flags=re.S)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    blocks, after_h1 = [], False
    for chunk in re.split(r'\n\s*\n', text):
        lines = [ln.rstrip() for ln in chunk.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        first = lines[0]
        if re.match(r'^#\s', first):
            after_h1 = True
            continue
        if after_h1 and re.fullmatch(r'\*[^*].*\*|_[^_].*_', first) and len(lines) == 1:
            after_h1 = False
            continue          # 一级标题下的斜体副标题，封面卡已有
        after_h1 = False
        if re.fullmatch(r'(-{3,}|\*{3,}|_{3,})', first):
            continue
        m = re.match(r'^#{2,6}\s+(.*)', first)
        if m:
            blocks.append(('head', inline_md(m[1])))
            lines = lines[1:]
            if not lines:
                continue
        if len(lines) == 1 and EMOJI.match(first) and len(first) <= 40 and not first.rstrip().endswith(tuple('。！？；：:')):
            blocks.append(('head', inline_md(first)))   # 小红书版用 emoji 开头的短行代替二级标题
            continue
        if all(ln.lstrip().startswith('|') for ln in lines):
            rows = [[c.strip() for c in ln.strip().strip('|').split('|')] for ln in lines]
            rows = [r for r in rows if not all(re.fullmatch(r':?-{2,}:?', c) for c in r)]
            header, body = rows[0], rows[1:]
            for row in body:
                label = inline_md(row[0])
                parts = [f'{inline_md(h)}：{inline_md(c)}' for h, c in zip(header[1:], row[1:]) if inline_md(c)]
                blocks.append(('para', f'{label}。' + '；'.join(parts) + '。'))
            continue
        for ln in lines:
            img = re.fullmatch(r'!\[([^\]]*)\]\(([^)\s]+)[^)]*\)', ln.strip())
            if img:
                blocks.append(('image', img[2], img[1].replace(' | ', '，')))
        lines = [ln for ln in lines if not re.fullmatch(r'!\[[^\]]*\]\([^)]*\)', ln.strip())]
        if not lines:
            continue
        if all(ln.startswith('>') for ln in lines):
            blocks.append(('quote', inline_md(''.join(re.sub(r'^>\s?', '', ln) for ln in lines))))
        elif all(re.match(r'^\s*([-*+]|\d+[.、])\s', ln) for ln in lines):
            for ln in lines:
                m = re.match(r'^\s*([-*+]|\d+[.、])\s+(.*)', ln)
                mark = '·' if m[1] in '-*+' else m[1]
                blocks.append(('para', f'{mark} {inline_md(m[2])}'))
        else:
            blocks.append(('para', inline_md(''.join(lines))))
    return [b for b in blocks if b[0] == 'image' or b[1]]


def build_full(article_dir, check_only=False, replace=False):
    root = Path(article_dir)
    article = root / '文章_小红书版.md'
    if not article.is_file():
        raise ValueError(f'缺少 {article}；全文轮播图按小红书版正文排版')
    cards, st = load_setup(root)
    covers = [c for c in cards if c['kind'] == 'cover']
    if not covers:
        raise ValueError('小红书图片.md 里没有封面卡；全文轮播图沿用同一张封面卡')
    width = W - 2*MARGIN_X
    body_f, head_f, quote_f, cap_f = (font(spec, size) for spec, size, _ in (FULL_BODY, FULL_HEAD, FULL_QUOTE, FULL_CAPTION))

    # 先把每一块变成「行」或「图」，再按页面高度连续分页。
    pages, page, y = [], [], CONTENT_TOP
    def new_page():
        nonlocal page, y
        if page:
            pages.append(page)
        page, y = [], CONTENT_TOP
    def room():
        return CONTENT_BOTTOM - y

    blocks = parse_article(article)
    for i, block in enumerate(blocks):
        kind = block[0]
        if kind == 'head':
            lines = wrap(block[1], head_f, width)
            gap = HEAD_BEFORE if page else 0
            nxt = blocks[i+1] if i+1 < len(blocks) else None
            need = gap + len(lines)*FULL_HEAD[2] + HEAD_AFTER + (2*FULL_BODY[2] if nxt and nxt[0] != 'image' else 0)
            if need > room():
                new_page()
                gap = 0
            y += gap
            page.append(('text', lines, head_f, FULL_HEAD[2], 'ink', y))
            y += len(lines)*FULL_HEAD[2] + HEAD_AFTER
        elif kind == 'image':
            path = (root / block[1])
            if not path.is_file():
                raise ValueError(f'找不到正文配图 {path}')
            with Image.open(path) as im:
                pic = im.convert('RGB')
            scale = min(width / pic.width, IMG_MAX_H / pic.height)
            size = (round(pic.width*scale), round(pic.height*scale))
            cap = wrap(block[2], cap_f, width) if block[2] else []
            need = size[1] + (16 + len(cap)*FULL_CAPTION[2] if cap else 0)
            if page and need + PARA_GAP > room():
                new_page()
            if page:
                y += PARA_GAP // 2
            page.append(('image', pic.resize(size, Image.Resampling.LANCZOS), y))
            y += size[1] + 16
            if cap:
                page.append(('text', cap, cap_f, FULL_CAPTION[2], 'muted', y))
                y += len(cap)*FULL_CAPTION[2]
            y += PARA_GAP
        else:
            fnt, _, lead = (quote_f, *FULL_QUOTE[1:]) if kind == 'quote' else (body_f, *FULL_BODY[1:])
            indent = 28 if kind == 'quote' else 0
            lines = wrap(block[1], fnt, width - indent)
            while lines:
                fit = max(0, room() // lead)
                if fit < min(2, len(lines)) and page:   # 页底只剩一行时整段挪到下一张，不留孤行
                    new_page()
                    continue
                take, lines = lines[:fit], lines[fit:]
                if len(lines) == 1 and len(take) > 2:  # 避免下一张只剩一行
                    lines = [take.pop()] + lines
                page.append(('text', take, fnt, lead, kind, y))
                y += len(take)*lead
                if lines:
                    new_page()
            y += PARA_GAP
    new_page()

    # 超过 18 张时拆成几篇笔记，每篇开头放同一张封面卡，正文页尽量平均分。
    parts = -(-len(pages) // (FULL_MAX - 1))
    size = -(-len(pages) // parts)
    groups = [pages[i:i+size] for i in range(0, len(pages), size)]
    if check_only:
        note = f'，超过单篇 {FULL_MAX} 张上限，会拆成 {parts} 篇笔记，每篇开头都放封面卡' if parts > 1 else ''
        print(f'全文轮播图共 {len(pages) + parts} 张（封面卡 {parts} 张，正文 {len(pages)} 张）{note}。')
        return
    out = root / 'imgs' / 'xhs-full'
    if out.exists() and any(out.rglob('*.png')) and not replace:
        raise ValueError(f'{out} 已有图片；确认覆盖请加 --replace')
    for old in out.rglob('*.png') if out.exists() else []:
        old.unlink()
    n = 0
    for g, group in enumerate(groups, 1):
        total = len(group) + 1
        images = [render_card(covers[0], 1, total, '', st['accent'], st['tint'], st['series'], st['art'], st['focus'])]
        for k, items in enumerate(group, 2):
            n += 1
            im, d = frame(PAPER, f'{n:02}', st['accent'], st['series'], f'{k} / {total}', MUTED)
            for item in items:
                if item[0] == 'image':
                    _, pic, top = item
                    im.paste(pic, (MARGIN_X + (width - pic.width)//2, top))
                    continue
                _, lines, fnt, lead, kind, top = item
                color = MUTED if kind == 'muted' else INK
                x = MARGIN_X + (28 if kind == 'quote' else 0)
                if kind == 'quote':
                    d.rectangle((MARGIN_X, top + 8, MARGIN_X + 5, top + len(lines)*lead - 18), fill=st['accent'])
                draw_lines(d, lines, fnt, x, top, lead, color, st['accent'])
            images.append(im)
        save_images(images, out / f'第{g}篇' if parts > 1 else out, True)
    if parts > 1:
        print(f'超过单篇 {FULL_MAX} 张上限，已拆成 {parts} 篇笔记，分别在 {out}/第1篇 … 第{parts}篇')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('article_dir', type=Path)
    parser.add_argument('--check', action='store_true', help='只检查能否排下，不出图')
    parser.add_argument('--replace', action='store_true', help='覆盖已有的图片')
    parser.add_argument('--full', action='store_true', help='全文轮播图：文章_小红书版.md 全文不删减，输出到 imgs/xhs-full/')
    args = parser.parse_args()
    (build_full if args.full else build)(args.article_dir, args.check, args.replace)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f'轮播图未生成：{exc}', file=sys.stderr)
        sys.exit(1)
