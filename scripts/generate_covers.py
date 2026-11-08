#!/usr/bin/env python3
"""单张母稿双尺寸封面工具（简化版，2026-11-08）。

两步：
1. --prepare：写出母稿提示词 imgs/prompts/cover-prompt.md，交给原生 imagegen 只画一张无字母稿。
2. --master：用这张母稿等比派生小红书 1440 × 2400 与公众号 900 × 383 两张成品，
   生成 封面设计.md，并把缩略图与中心裁切输出到临时目录供看图。

本工具只排版，不画图，也不判断画风。看图结论由人写进 封面设计.md，脚本不会代勾。
"""
import argparse
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from functools import lru_cache
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / '_vendor'  # 随项目附带的 Pillow，系统 Python 没装时使用
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))
from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps

STYLE_VERSION = 'editorial-handdrawn-v1'
XHS_SIZE = (1440, 2400)
WECHAT_SIZE = (900, 383)
SKILL_DIR = Path(__file__).resolve().parents[1]
# 画风样板：每次生成都把它作为画风参考传给生图工具。可用环境变量换成自己的样板。
STYLE_SAMPLE = Path(os.environ.get('ZH_LONGFORM_STYLE_SAMPLE') or SKILL_DIR / 'assets' / 'style-sample' / 'hawthorne-master.png')
PROMPT_REL = 'imgs/prompts/cover-prompt.md'
MASTER_REL = 'imgs/cover-source/master.png'


def usable_font(path):
    try:
        ImageFont.truetype(str(path), 12, index=0)
        return True
    except OSError:
        return False


# 标题字体：环境变量 ZH_LONGFORM_TITLE_FONT 优先，其次京華老宋体，再退回系统宋体。
FONT_CANDIDATES = [
    os.environ.get('ZH_LONGFORM_TITLE_FONT', ''),
    str(Path.home() / 'Library/Fonts/KingHwa_OldSong.ttf'),
    str(Path.home() / '.local/share/fonts/KingHwa_OldSong.ttf'),
    '/System/Library/Fonts/Supplemental/Songti.ttc',
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc',
    '/usr/share/fonts/noto-cjk/NotoSerifCJK-Bold.ttc',
    'C:/Windows/Fonts/simsun.ttc',
]
FONT_PATH = next((Path(p) for p in FONT_CANDIDATES if p and Path(p).is_file() and usable_font(Path(p))),
                 Path('/System/Library/Fonts/Supplemental/Songti.ttc'))

COLOR_PRESETS = {
    'yellow': ('鹅黄与书页蓝', '#FDE696', '#6499CD', 1),
    'gray_green': ('灰绿与蓝红', '#D2D4C9', '#F78F95', 2),
    'cyan': ('青蓝与深墨', '#03CCEA', '#192644', 3),
    'pink': ('玫粉与橙紫', '#E17FA5', '#8970BC', 4),
    'blue_gray': ('蓝灰与珊瑚', '#739DC5', '#F39A99', 5),
    'mint': ('薄荷绿与葡萄紫', '#64D2A1', '#9770BB', 6),
    # 仅作中性底色导出，不是第 7 张用户参考。
    'warm_paper': ('纸色辅助底', '#FCF8F0', '#6499CD', 1),
}


def parse_article_meta(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    fm = re.match(r'\A---\s*\n(.*?)\n---(?:\s*\n|$)', text, re.S)
    meta_title = None
    if fm:
        match = re.search(r'^title:\s*(.*?)\s*$', fm[1], re.M)
        if match:
            raw = match[1]
            if raw.startswith('"'):
                meta_title = json.loads(raw)
            elif raw.startswith("'") and raw.endswith("'"):
                meta_title = raw[1:-1].replace("''", "'")
            else:
                meta_title = raw
    body = text[fm.end():] if fm else text
    h1 = re.search(r'^#\s+(.+)$', body, re.M)
    title = h1[1].strip() if h1 else meta_title
    if not title or (meta_title is not None and title != meta_title):
        raise ValueError(f'{path}: 标题缺失或 frontmatter 与正文 H1 不一致')
    return title, text


def titles(root):
    title, _ = parse_article_meta(root / '文章.md')
    xhs_file = root / '文章_小红书版.md'
    xhs = parse_article_meta(xhs_file)[0] if xhs_file.is_file() else title
    return title, xhs


def check_fresh(paths, replace):
    existing = [p for p in paths if p.exists()]
    if existing and not replace:
        raise ValueError('目标已存在；预览请用 --output-dir，确认要覆盖时加 --replace：' + str(existing[0]))


def read_prompt_meta(path):
    text = path.read_text(encoding='utf-8')
    meta = dict(re.findall(r'^- (\S+?)：(.*)$', text.split('\n---\n', 1)[0], re.M))
    for key in ('文章标题', '小红书标题', '画面', '关系', '参考图'):
        if key not in meta:
            raise ValueError(f'{path} 缺少「{key}」，请重新 --prepare')
    return meta


def prepare(root, output, preset, scene, relation, palette_refs=None, replace=False, existing_prompt=None):
    if not scene.strip() or not relation.strip():
        raise ValueError('--prepare 须填写 --scene 和 --relation，不能只用标题或泛化风格词')
    title, xhs_title = titles(root)
    if not STYLE_SAMPLE.is_file():
        raise ValueError(f'画风样板缺失: {STYLE_SAMPLE}')
    refs = []
    for path in palette_refs or []:          # 可选的配色参考图，只借色彩关系
        path = Path(path).resolve()
        if not path.is_file():
            raise ValueError(f'配色参考图不存在: {path}')
        refs.append(path)
    prompt_file = output / PROMPT_REL
    check_fresh([prompt_file], replace)
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    name, primary, accent, _ = COLOR_PRESETS[preset]
    if existing_prompt:
        body = existing_prompt.read_text(encoding='utf-8')
        if not body.strip():
            raise ValueError('历史提示词不能为空')
        origin = f'复用历史母稿，正文为当时的实际提示词，来自 {existing_prompt}'
    else:
        origin = '新母稿，正文为本次交给 imagegen 的完整提示词'
        body = f'''Make ONE original, wordless editorial illustration, roughly 1:1 square and at
least 1800 pixels wide. It will later be scaled, unchanged, into a 1440 x 2400
portrait cover (filling about 60% of the height) and a 900 x 383 landscape cover.
Do not reserve an empty title panel; the whole picture is the scene.

Article context (never written in the image): {title}
Scene and concrete action: {scene}
Why this image belongs to the article: {relation}

STYLE: match the attached STYLE SAMPLE closely; it is the approved look for every
cover in this project:
- {STYLE_SAMPLE}
A detailed storybook pencil illustration: fine, slightly uneven graphite outlines;
dense colored-pencil hatching that builds form, light and texture; muted,
desaturated colors; soft natural light; a lived-in environment full of small
hand-drawn detail such as foliage, wood grain, water, plaster, fabric and paper.
People have natural proportions and calm, simply drawn faces.
Not cartoonish: no big heads, no dot-only eyes, no thick black outlines, no flat
saturated color fills, no vector look. Not photoreal, not an oil painting, not an
antique engraving, no heavy paper texture or vignette.
''' + (('Palette references (color relationships only, NOT drawing style):\n' + '\n'.join(f'- {p}' for p in refs) + '\n') if refs else '') + f'''
Palette: {name}, primary {primary}, accent {accent}, plus near-black and ivory,
rendered as muted pencil tones like the style sample. Low to medium saturation;
no neon and no single-color wash over the whole picture.

One clear action and a few objects the article actually mentions, with the main
figure large in the frame. No generic symbols (gears, coins, globes, glowing dots,
cosmic circles, stock business icons) unless the scene above names them.
Keep the main focus near the center and keep heads, hands and key tools away from
the outer edge. This is conceptual art, not a historical reconstruction.

ABSOLUTELY NO text, Chinese characters, letters, numbers, labels, signature, logo,
watermark or publication branding. Do not copy the style sample's people or scene.
'''
    header = f'''# 封面母稿提示词

- 日期：{date.today().isoformat()}
- 文章标题：{title}
- 小红书标题：{xhs_title}
- 色组：{preset}（{name}）
- 参考图：画风样板 {STYLE_SAMPLE.name}{(' + 配色参考 ' + ', '.join(p.name for p in refs)) if refs else ''}
- 画面：{scene}
- 关系：{relation}
- 来源：{origin}

调用 imagegen 时，把下方提示词和画风样板图片文件一起传入（有配色参考也一并传入），只画一张。

---
'''
    prompt_file.write_text(header + body, encoding='utf-8')
    print(f'已保存提示词: {prompt_file}')
    print(f'下一步：把提示词和画风样板 {STYLE_SAMPLE} 一起交给 imagegen，只画一张母稿；看过母稿再运行 --master。')


def explicit_lines(title, value):
    if not value:
        return None
    lines = json.loads(value) if value.lstrip().startswith('[') else value.split('/')
    if not lines or not all(isinstance(line, str) and line for line in lines) or ''.join(lines) != title:
        raise ValueError('自定义断行必须逐字拼回原标题，不能改标点、删空格或改标题')
    return lines


def wrap_title(title, font, width, max_lines):
    """Partition exact source text, using pixel widths and Chinese punctuation rules."""
    n = len(title)
    opening = '「『（《【(['
    closing = '」』）》】)]，。？！：；、,.!?:;'
    protected = set()
    for match in re.finditer(r'\d+\s*(?:小时|分钟|秒|年|个月|天)|每[周天月年]|小时|分钟|工作|最后|预言|距离|只剩', title):
        protected.update(range(match.start()+1, match.end()))

    @lru_cache(None)
    def measure(start, end):
        return font.getlength(title[start:end])

    def boundary(pos):
        if pos in (0, n):
            return True
        if pos in protected:
            return False
        before, after = title[pos-1], title[pos]
        if before in opening or after in closing or before.isspace() or after.isspace():
            return False
        if before.isascii() and after.isascii() and before.isalnum() and after.isalnum():
            return False
        return True

    @lru_cache(None)
    def solve(start, remaining):
        if start == n:
            return (0.0, ())
        if remaining == 0:
            return None
        best = None
        for end in range(start+1, n+1):
            actual = measure(start, end)
            if actual > width:
                break
            if not boundary(end) or (n-end == 1 and n > 2):
                continue
            rest = solve(end, remaining-1)
            if rest is None:
                continue
            punctuation_bonus = 0 if end == n or title[end-1] in '，：、。？！' else 0.12
            cost = ((width-actual)/width)**2 + punctuation_bonus + 0.65 + rest[0]
            candidate = cost, (title[start:end],) + rest[1]
            if best is None or candidate[0] < best[0]:
                best = candidate
        return best
    result = solve(0, max_lines)
    return list(result[1]) if result else None


def typography(title, custom, box, limits, font_path):
    x, y, width, height = box
    candidates = []
    for size in range(limits[0], limits[1]-1, -2):
        font = ImageFont.truetype(str(font_path), size, index=0)
        lines = custom or wrap_title(title, font, width, limits[2])
        if not lines or len(lines) > limits[2]:
            continue
        spacing = round(size*1.40)
        block_h = size + (len(lines)-1)*spacing
        if block_h <= height and all(font.getlength(line) <= width for line in lines):
            data = {'title': title, 'lines': lines, 'font_size': size, 'font_path': str(font_path),
                    'font_face': font.getname(), 'line_spacing': spacing, 'box': list(box),
                    'block_height': block_h}
            # Prefer a readable, compact title over maximum-size five-line stacks.
            score = size/limits[0] - 0.32*max(0,len(lines)-3)
            candidates.append((score, data, font))
    if candidates:
        _, data, font = max(candidates, key=lambda item:item[0])
        return data, font
    raise ValueError('标题无法自然排入当前区域；请明确断行或调整版式，不得截字或自动改题')


def source_background(art):
    # Lower corner patches should be plain paper in the prepared master.
    w, h = art.size
    d = max(3, min(w, h)//45)
    samples = []
    for x in (0, w-d):
        samples += list(art.crop((x, h-d, x+d, h)).getdata())
    return tuple(sorted(p[c] for p in samples)[len(samples)//2] for c in range(3))


def background_canvas(size, original, box, color):
    if box is None:
        return Image.new('RGB', size, color)
    w, h = original.size
    patch = original.crop(tuple(round(v*s) for v,s in zip(box,(w,h,w,h))))
    if patch.width < 2 or patch.height < 2:
        raise ValueError('背景样本太小')
    # Extend only a caller-reviewed empty paper region; never redraw the subject.
    return ImageOps.fit(patch, size, method=Image.Resampling.LANCZOS)


def paste_complete_scene(canvas, artwork, position, bg):
    # At most 12 final pixels: blend background-like edge pixels only. Dark lines,
    # skin, clothes and other pixels away from the empty-paper color stay opaque.
    w, h = artwork.size
    alpha = Image.new('L', artwork.size, 255)
    pixels = artwork.load()
    mask = alpha.load()
    margin = 12
    for y in range(h):
        for x in range(w):
            edge = min(x,y,w-1-x,h-1-y)
            if edge < margin and max(abs(pixels[x,y][c]-bg[c]) for c in range(3)) <= 42:
                mask[x,y] = round(255*edge/margin)
    canvas.paste(artwork,position,alpha)


def place_text(canvas, data, font, centered):
    draw = ImageDraw.Draw(canvas)
    x, y, width, height = data['box']
    first_y = y + (height-data['block_height'])/2
    for index, line in enumerate(data['lines']):
        line_x = x+(width-font.getlength(line))/2 if centered else x
        draw.text((line_x, first_y+index*data['line_spacing']), line, font=font, fill=(24, 25, 28), anchor='lt')



def render(args):
    root = args.article_dir.resolve()
    output = (args.output_dir or root).resolve()
    prompt_file = output / PROMPT_REL
    if not prompt_file.is_file():
        raise ValueError('须先运行 --prepare 保存提示词；不能出图后再补写')
    meta = read_prompt_meta(prompt_file)
    title, xhs_title = titles(root)
    if (title, xhs_title) != (meta['文章标题'], meta['小红书标题']):
        raise ValueError('文章标题在 --prepare 之后改过，请重新 --prepare（加 --replace）')
    if not args.master or not args.master.is_file():
        raise ValueError('须用 --master 指定本次生成的无字母稿')
    original = Image.open(io.BytesIO(args.master.read_bytes()))
    original.load()
    if original.mode != 'RGB':
        raise ValueError('母稿须为不透明 RGB 图像')
    raw = original.copy()
    if original.info.get('icc_profile'):
        profile = ImageCms.ImageCmsProfile(io.BytesIO(original.info['icc_profile']))
        raw = ImageCms.profileToProfile(raw, profile, ImageCms.createProfile('sRGB'), outputMode='RGB')
    source_w, source_h = raw.size
    art_box = args.art_box or [0, 0, 1, 1]
    if not (0 <= art_box[0] < art_box[2] <= 1 and 0 <= art_box[1] < art_box[3] <= 1):
        raise ValueError('--art-box 须为 0～1 内的 x0,y0,x1,y1，只能排除纯背景')
    if args.art_box and not args.art_box_note.strip():
        raise ValueError('使用 --art-box 须用 --art-box-note 说明被排除的区域为什么是空白')
    art = raw.crop(tuple(round(v*s) for v, s in zip(art_box, (source_w, source_h, source_w, source_h))))
    xhs_w, xhs_h = XHS_SIZE
    art_h = round(xhs_w*art.height/art.width)
    if not round(xhs_h*0.50) <= art_h <= round(xhs_h*0.72):
        raise ValueError('母稿比例不合适：插画会缩成贴图或挤掉标题。请用约 1:1 的完整场景母稿')
    focal = args.focal or [0.5, 0.5]
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in focal):
        raise ValueError('--focal 须为母稿内 0～1 的主体焦点坐标')
    bg = source_background(art)
    background_box = args.background_box
    if background_box:
        if len(background_box) != 4 or not (0 <= background_box[0] < background_box[2] <= 1 and 0 <= background_box[1] < background_box[3] <= 1) or not args.background_note.strip():
            raise ValueError('--background-box 须标出无物件的背景区域，并填写 --background-note')
        bg = source_background(raw.crop(tuple(round(v*s) for v, s in zip(background_box, (source_w, source_h, source_w, source_h)))))
    xhs = background_canvas(XHS_SIZE, raw, background_box, bg)
    paste_complete_scene(xhs, art.resize((xhs_w, art_h), Image.Resampling.LANCZOS), (0, 0), bg)
    wc = background_canvas(WECHAT_SIZE, raw, background_box, bg)
    scale = min(500/art.width, 383/art.height)
    target = (round(art.width*scale), round(art.height*scale))
    # 整幅场景等比排入，不做固定最右侧或居中裁切。
    ox = 400 if args.layout == 'right-art' else 500-target[0]
    oy = (383-target[1])//2
    fx, fy = ox+focal[0]*target[0], oy+focal[1]*target[1]
    if not 258.5 <= fx <= 641.5:
        raise ValueError('主体焦点不在公众号中心正方形安全区，请换 --layout 或核对 --focal')
    paste_complete_scene(wc, art.resize(target, Image.Resampling.LANCZOS), (ox, oy), bg)
    font_path = args.font or FONT_PATH
    if not font_path.is_file() or not usable_font(font_path):
        raise ValueError(f'字体不可用：{font_path}；请用 --font 指定可用的粗宋体')
    data_x, font_x = typography(xhs_title, explicit_lines(xhs_title, args.lines_xhs or args.lines),
        (88, art_h+40, xhs_w-176, xhs_h-art_h-124), (108, 74, 4), font_path)
    text_x = 38 if args.layout == 'right-art' else 538
    data_w, font_w = typography(title, explicit_lines(title, args.lines_wechat or args.lines),
        (text_x, 34, 324, 315), (40, 28, 5), font_path)

    imgs = output / 'imgs'
    master_out = output / MASTER_REL
    targets = [imgs/'cover-xhs.png', imgs/'cover-wechat.png', imgs/'cover.png', output/'封面设计.md']
    if master_out.resolve() != args.master.resolve():
        targets.append(master_out)
    check_fresh(targets, args.replace)
    master_out.parent.mkdir(parents=True, exist_ok=True)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    if master_out.resolve() != args.master.resolve():
        raw.save(master_out, icc_profile=icc)
    place_text(xhs, data_x, font_x, True)
    place_text(wc, data_w, font_w, False)
    xhs.save(imgs/'cover-xhs.png', icc_profile=icc)
    wc.save(imgs/'cover-wechat.png', icc_profile=icc)
    shutil.copyfile(imgs/'cover-wechat.png', imgs/'cover.png')

    preview = Path(tempfile.mkdtemp(prefix='cover-preview-'))
    xhs.resize((360, 600), Image.Resampling.LANCZOS).save(preview/'thumbnail-xhs.png')
    wc.resize((360, 153), Image.Resampling.LANCZOS).save(preview/'thumbnail-wechat.png')
    wc.crop((259, 0, 642, 383)).save(preview/'wechat-center-crop.png')

    doc = f'''# 封面设计

规范：`{STYLE_VERSION}`，见 zh-longform Skill 的 `rules/平台与封面.md` 第五节。生成日期：{date.today().isoformat()}。

- 公众号标题：{title}
- 小红书标题：{xhs_title}
- 画面：{meta['画面']}
- 与文章的关系：{meta['关系']}
- 参考图：{meta['参考图']}
- 提示词：`{PROMPT_REL}`
- 母稿：`{MASTER_REL}`
- 小红书：1440 × 2400，标题 {data_x['font_size']} px，断行 {json.dumps(data_x['lines'], ensure_ascii=False)}
- 公众号：900 × 383，{args.layout}，标题 {data_w['font_size']} px，断行 {json.dumps(data_w['lines'], ensure_ascii=False)}，主体焦点 {fx:.0f},{fy:.0f}
- 字体：`{font_path}`

[小红书封面](imgs/cover-xhs.png) · [公众号封面](imgs/cover-wechat.png)

## 看图记录

对照画风样板（`{STYLE_SAMPLE.name}`），打开两张成品、两张缩略图和公众号中心裁切。全部打勾、写下记录后，把结论改为「通过」。

- [ ] 画风和画风样板同类：细铅笔线、密集彩铅排线、低饱和色、环境细节丰富、人物比例自然；不是卡通大头、粗黑描边、饱和平涂或矢量感，也没有缩成小贴图。
- [ ] 整幅场景都在，主体没有被裁断。
- [ ] 图中标题与对应正文逐字一致，断行自然，没有孤字或溢出。
- [ ] 缩略图下标题可读，公众号中心裁切里主体可辨认。
- [ ] 没有文字、品牌、媒体名、英文副标题或水印，也没有照搬样板里的人物和场景。

记录：待填写

看图结论：待看图

用户采用：待确认。发布：未发布。
'''
    (output/'封面设计.md').write_text(doc, encoding='utf-8')
    print(f'双尺寸封面已生成: {imgs}')
    print(f'缩略图与中心裁切（临时，不入库）: {preview}')
    print('看图后在 封面设计.md 里打勾、写记录，把「看图结论」改为「通过」。')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('article_dir', type=Path)
    parser.add_argument('--output-dir', type=Path, help='预览输出到独立目录，不动文章里的成品')
    parser.add_argument('--prepare', action='store_true', help='第 1 步：保存母稿提示词')
    parser.add_argument('--preset', choices=COLOR_PRESETS, default='yellow')
    parser.add_argument('--palette-ref', type=Path, action='append', help='可选的配色参考图路径，可重复；画风一律以画风样板为准')
    parser.add_argument('--scene', default='', help='画面里的具体动作')
    parser.add_argument('--relation', default='', help='这幅画和文章的关系')
    parser.add_argument('--existing-prompt', type=Path, help='复用历史母稿时，导入当时的实际提示词')
    parser.add_argument('--master', type=Path, help='第 2 步：本次生成的无字母稿')
    parser.add_argument('--focal', type=lambda s: [float(v) for v in s.split(',')], help='母稿主体焦点 x,y（0～1）')
    parser.add_argument('--layout', choices=('right-art', 'left-art'), default='right-art')
    parser.add_argument('--lines', help='两版共用的手动断行，用 / 分隔，须逐字拼回标题')
    parser.add_argument('--lines-xhs')
    parser.add_argument('--lines-wechat')
    parser.add_argument('--font', type=Path)
    parser.add_argument('--art-box', type=lambda s: [float(v) for v in s.split(',')], help='旧母稿去掉纯背景区域 x0,y0,x1,y1')
    parser.add_argument('--art-box-note', default='')
    parser.add_argument('--background-box', type=lambda s: [float(v) for v in s.split(',')], help='无物件的背景样本，用于延续纸色')
    parser.add_argument('--background-note', default='')
    parser.add_argument('--replace', action='store_true', help='覆盖已有文件')
    args = parser.parse_args()
    output = (args.output_dir or args.article_dir).resolve()
    if args.prepare:
        prepare(args.article_dir.resolve(), output, args.preset, args.scene, args.relation,
                args.palette_ref, args.replace, args.existing_prompt)
    else:
        if args.art_box and len(args.art_box) != 4:
            parser.error('--art-box 需要四个坐标')
        if args.focal and len(args.focal) != 2:
            parser.error('--focal 需要两个坐标')
        render(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f'封面流程未完成：{exc}', file=sys.stderr)
        sys.exit(1)
