"""小红书轮播图工具回归测试，使用临时目录。"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # 被测脚本在 scripts/

import tempfile
import unittest
from pathlib import Path

import generate_xhs_slides as xhs
from PIL import Image

SAMPLE = '''---
series: 测试系列
palette: blue
---

## 封面：「愿我不曾虚度」

副标题一句

## 正文：第谷的临终遗言

1601 年 10 月 24 日夜里，丹麦天文学家第谷·布拉赫在布拉格郊外病倒，高烧中反复念着一句拉丁语。

守在床边的开普勒记下了这句话：==「愿我不曾虚度此生。」==

## 引语

「心神就在不知不觉中蒸发殆尽了。」

— 纳撒尼尔·霍桑，1835 年手记
'''


class XhsSlidesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xhs-slides-test-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, text):
        (self.root/'小红书图片.md').write_text(text, encoding='utf-8')

    def lines(self, text, width=500, size=40):
        rows = xhs.wrap(text, xhs.font(xhs.HEI_REGULAR, size), width)
        return [''.join(t for t, _ in row) for row in rows]

    def test_renders_all_cards_at_3_4(self):
        self.write(SAMPLE)
        xhs.build(self.root)
        files = sorted((self.root/'imgs/xhs').glob('*.png'))
        self.assertEqual([f.name for f in files], ['01.png', '02.png', '03.png'])
        for f in files:
            with Image.open(f) as im:
                self.assertEqual(im.size, (1080, 1440))

    def test_existing_output_needs_replace(self):
        self.write(SAMPLE)
        xhs.build(self.root)
        with self.assertRaises(ValueError):
            xhs.build(self.root)
        xhs.build(self.root, replace=True)

    def test_no_closing_punctuation_at_line_start(self):
        for line in self.lines('守在床边的开普勒记下了这句话，愿我不曾虚度此生。第谷以为自己四十年的观测要白费了，他不知道。')[1:]:
            self.assertNotIn(line[0], xhs.NO_LINE_START)

    def test_consecutive_closing_marks_hang_together(self):
        # 回归用例：「。」」连在行尾时，」曾被单独挤到下一行。
        text = '「作为对他天才（genius）的景仰之证，谨将此书呈献给纳撒尼尔·霍桑。」'
        for size in range(48, 58):
            fnt = xhs.font(xhs.HEI_REGULAR, size)
            lines = self.lines(text, width=872, size=size)
            self.assertEqual(''.join(lines), text)
            for line in lines[1:]:
                self.assertNotIn(line[0], xhs.NO_LINE_START)
            for line in lines:
                # 最多只挂一个标点：去掉最后一个字符后必须排得下。
                self.assertLessEqual(fnt.getlength(line[:-1]), 872)

    def test_no_opening_quote_at_line_end(self):
        for line in self.lines('他在床边写下了这样一句话：「愿我不曾虚度此生」然后又写「再见」。', width=430):
            self.assertNotIn(line[-1], xhs.NO_LINE_END)

    def test_foreign_name_not_split(self):
        rows = self.lines('一二三四五六七八九十丹麦天文学家第谷·布拉赫在布拉格郊外病倒。', width=560)
        self.assertTrue(any('第谷·布拉赫' in r for r in rows))

    def test_wrap_keeps_text(self):
        text = '1601 年 10 月 24 日夜里，丹麦天文学家第谷·布拉赫在布拉格郊外病倒。'
        self.assertEqual(''.join(self.lines(text)), text)

    def test_overflow_is_an_error_not_shrunk(self):
        self.write('## 正文：太长\n\n' + '很长的一段文字，' * 120 + '\n')
        with self.assertRaises(ValueError):
            xhs.build(self.root, check_only=True)

    def test_bad_card_type_and_unpaired_highlight(self):
        self.write('## 图表：不支持\n\n文字\n')
        with self.assertRaises(ValueError):
            xhs.build(self.root, check_only=True)
        self.write('## 正文：标题\n\n==没有闭合\n')
        with self.assertRaises(ValueError):
            xhs.build(self.root, check_only=True)

    def test_cover_art_strip(self):
        art = Image.new('RGB', (1000, 1000), (200, 30, 30))
        (self.root/'imgs').mkdir()
        art.save(self.root/'imgs/master.png')
        self.write(SAMPLE.replace('palette: blue', 'palette: blue\ncover_art: imgs/master.png   # 插画\ncover_focus: 0.5,0.6'))
        xhs.build(self.root)
        with Image.open(self.root/'imgs/xhs/01.png') as im:
            self.assertEqual(im.getpixel((540, 300)), (200, 30, 30))      # 顶部是插画
            self.assertEqual(im.getpixel((20, 1300)), xhs.PAPER)         # 下方是纸色
        with Image.open(self.root/'imgs/xhs/02.png') as im:
            self.assertEqual(im.getpixel((540, 300)), xhs.PAPER)         # 正文卡不受影响

    def test_cover_art_errors(self):
        self.write(SAMPLE.replace('palette: blue', 'palette: blue\ncover_art: imgs/none.png'))
        with self.assertRaises(ValueError):
            xhs.build(self.root, check_only=True)
        (self.root/'imgs').mkdir()
        Image.new('RGB', (10, 10)).save(self.root/'imgs/a.png')
        self.write(SAMPLE.replace('palette: blue', 'palette: blue\ncover_art: imgs/a.png\ncover_focus: 2,0'))
        with self.assertRaises(ValueError):
            xhs.build(self.root, check_only=True)

    def test_cover_art_defaults_to_master(self):
        (self.root/'imgs/cover-source').mkdir(parents=True)
        Image.new('RGB', (1000, 1000), (30, 120, 200)).save(self.root/'imgs/cover-source/master.png')
        self.write(SAMPLE)
        xhs.build(self.root)
        with Image.open(self.root/'imgs/xhs/01.png') as im:
            self.assertEqual(im.getpixel((540, 300)), (30, 120, 200))
        self.write(SAMPLE.replace('palette: blue', 'palette: blue\ncover_art: none'))
        xhs.build(self.root, replace=True)
        with Image.open(self.root/'imgs/xhs/01.png') as im:
            self.assertEqual(im.getpixel((540, 300)), xhs.PAPER)

    def test_cover_with_art_needs_one_line_title(self):
        (self.root/'imgs/cover-source').mkdir(parents=True)
        Image.new('RGB', (1000, 1000)).save(self.root/'imgs/cover-source/master.png')
        self.write(SAMPLE.replace('## 封面：「愿我不曾虚度」', '## 封面：保罗·格雷厄姆的极简生活法则'))
        with self.assertRaises(ValueError):
            xhs.build(self.root, check_only=True)
        self.write(SAMPLE.replace('副标题一句', '保罗·格雷厄姆的极简生活法则：为什么它能救人于虚无'))
        with self.assertRaises(ValueError):
            xhs.build(self.root, check_only=True)

    ARTICLE = '''---
title: "测试"
---

# 测试标题

*斜体副标题，封面卡已有*

第一段正文，**加粗**和[链接](https://example.com)都只留文字。

🪐 一、用 emoji 开头的小标题

| 路径 | 自由度 |
| :-- | :-- |
| 个人轨<br>（牛顿式） | 绝对自由 |

![配图说明 | 1840 年](imgs/pic.png)

> 引用的一段话。

- 列表第一项
- 列表第二项

---

## 参考出处

- 一手文献
'''

    def full_setup(self, article):
        self.write(SAMPLE)
        (self.root/'imgs').mkdir(exist_ok=True)
        Image.new('RGB', (800, 600), (10, 200, 10)).save(self.root/'imgs/pic.png')
        (self.root/'文章_小红书版.md').write_text(article, encoding='utf-8')

    def test_full_article_parse_keeps_everything(self):
        self.full_setup(self.ARTICLE)
        blocks = xhs.parse_article(self.root/'文章_小红书版.md')
        kinds = [b[0] for b in blocks]
        text = ''.join(b[1] for b in blocks if b[0] != 'image')
        self.assertEqual(kinds, ['para', 'head', 'para', 'image', 'quote', 'para', 'para', 'head', 'para'])
        self.assertNotIn('测试标题', text)
        self.assertNotIn('斜体副标题', text)
        self.assertIn('第一段正文，加粗和链接都只留文字。', text)
        self.assertIn('个人轨（牛顿式）。自由度：绝对自由。', text)
        self.assertNotIn('🪐', text)

    def test_full_renders_cover_and_pages(self):
        self.full_setup(self.ARTICLE)
        xhs.build_full(self.root)
        files = sorted((self.root/'imgs/xhs-full').glob('*.png'))
        self.assertGreaterEqual(len(files), 2)
        with Image.open(files[0]) as a:
            self.assertEqual(a.size, (1080, 1440))
        with self.assertRaises(ValueError):          # 已有图片须 --replace
            xhs.build_full(self.root)

    def test_full_cover_same_as_short_carousel(self):
        self.full_setup(self.ARTICLE)
        xhs.build(self.root)
        xhs.build_full(self.root)
        with Image.open(self.root/'imgs/xhs/01.png') as a, Image.open(self.root/'imgs/xhs-full/01.png') as b:
            self.assertEqual(a.crop((0, 0, 1080, 1300)).tobytes(), b.crop((0, 0, 1080, 1300)).tobytes())

    def test_full_long_article_splits_into_notes_with_cover(self):
        long = self.ARTICLE.replace('第一段正文', '很长的一段。' * 4000 + '第一段正文')
        self.full_setup(long)
        xhs.build_full(self.root)
        parts = sorted(p for p in (self.root/'imgs/xhs-full').iterdir() if p.is_dir())
        self.assertGreaterEqual(len(parts), 2)
        for part in parts:
            files = list(part.glob('*.png'))
            self.assertLessEqual(len(files), 18)
            with Image.open(part/'01.png') as im:
                self.assertEqual(im.getpixel((540, 300)), xhs.PAPER)   # 无插画时的封面卡

    def test_full_needs_article(self):
        self.write(SAMPLE)
        with self.assertRaises(ValueError):
            xhs.build_full(self.root, check_only=True)

    def test_quote_needs_source(self):
        self.write('## 引语\n\n「只有原话」\n')
        with self.assertRaises(ValueError):
            xhs.build(self.root, check_only=True)


if __name__ == '__main__':
    unittest.main()
