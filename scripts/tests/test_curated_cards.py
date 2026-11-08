"""策展卡片流回归测试，使用临时目录。"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # 被测脚本在 scripts/

import tempfile
import unittest
from pathlib import Path

import generate_curated_cards as cc
from PIL import Image

CARD = '''<!-- card
index: 01
title_zh: 《示例书名》
title_en: Sample Book Title
author_zh: 示例作者
author_en: Sample Author
badge: 某位作家说
quote_zh: 「这里放一句查得到出处的一手原话。」
{image}
-->
'''


class CuratedCardsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='curated-test-')
        self.root = Path(self.temp.name)
        Image.new('RGB', (380, 580), (140, 60, 50)).save(self.root/'book.png')

    def tearDown(self):
        self.temp.cleanup()

    def test_both_sizes_and_old_image_field(self):
        (self.root/'文章.md').write_text(CARD.format(image='cover_image: book.png'), encoding='utf-8')
        cc.build(self.root, palette='warm_paper')      # 旧配色名仍可用
        with Image.open(self.root/'imgs/cards/card_01_xhs.png') as im:
            self.assertEqual(im.size, (1080, 1440))
        with Image.open(self.root/'imgs/cards/card_01_wechat.png') as im:
            self.assertEqual(im.size, (1080, 810))

    def test_missing_image_is_an_error(self):
        (self.root/'文章.md').write_text(CARD.format(image='image: none.png'), encoding='utf-8')
        with self.assertRaises(ValueError):
            cc.build(self.root)

    def test_unknown_palette_and_no_cards(self):
        (self.root/'文章.md').write_text(CARD.format(image=''), encoding='utf-8')
        with self.assertRaises(ValueError):
            cc.build(self.root, palette='purple')
        (self.root/'文章.md').write_text('没有卡片', encoding='utf-8')
        with self.assertRaises(ValueError):
            cc.build(self.root)


if __name__ == '__main__':
    unittest.main()
