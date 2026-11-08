"""封面流程回归测试，使用临时目录，不碰真实文章。"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # 被测脚本在 scripts/

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import generate_covers as covers
from PIL import Image, ImageDraw, ImageFont


class CoverWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cover-workflow-test-')
        self.root = Path(self.temp.name)
        self.title = '距离凯恩斯预言的「每周工作 15 小时」，只剩最后 4 年了'
        self.write_article(self.title)
        master = Image.new('RGB', (1200, 1000), (253, 230, 150))
        draw = ImageDraw.Draw(master)
        draw.rectangle((30, 300, 130, 400), fill=(230, 20, 20))
        draw.rectangle((1070, 650, 1170, 750), fill=(20, 30, 230))
        self.master = self.root/'fixture-master.png'
        master.save(self.master)
        self.args = SimpleNamespace(article_dir=self.root, output_dir=None, master=self.master,
            art_box=None, art_box_note='', background_box=None, background_note='', focal=[.45, .5],
            layout='right-art', font=None, lines=None, lines_xhs=None, lines_wechat=None, replace=False)
        self.quiet(covers.prepare, self.root, self.root, 'yellow', 'Test fixture only.',
                   'Test geometry, not a publication cover.')

    def tearDown(self):
        self.temp.cleanup()

    def write_article(self, title):
        (self.root/'文章.md').write_text(
            '---\ntitle: '+json.dumps(title, ensure_ascii=False)+'\n'
            'cover_style: "editorial-handdrawn-v1"\ncover_text: "title-only"\n'
            'cover_image: "imgs/cover.png"\ncover_xhs: "imgs/cover-xhs.png"\n'
            'cover_wechat: "imgs/cover-wechat.png"\n---\n\n# '+title+'\n', encoding='utf-8')

    def quiet(self, fn, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*args)

    def render(self):
        self.quiet(covers.render, self.args)

    def verify(self, *extra):
        script = Path(covers.__file__).with_name('verify_covers.py')
        return subprocess.run([sys.executable, str(script), str(self.root), *extra], capture_output=True, text=True)

    def approve(self, note='实际看过两张成品与缩略图。'):
        path = self.root/'封面设计.md'
        text = path.read_text(encoding='utf-8').replace('- [ ]', '- [x]')
        text = text.replace('记录：待填写', '记录：'+note).replace('看图结论：待看图', '看图结论：通过')
        path.write_text(text, encoding='utf-8')

    def test_explicit_lines_preserve_source_text(self):
        lines = ['距离凯恩斯预言的', '「每周工作 15 小时」，', '只剩最后 4 年了']
        self.assertEqual(covers.explicit_lines(self.title, json.dumps(lines)), lines)

    def test_explicit_lines_cannot_silently_change_spaces_or_punctuation(self):
        for bad in [self.title.replace(' 15 ', '15'), self.title.replace('，', ',')]:
            with self.assertRaises(ValueError):
                covers.explicit_lines(self.title, json.dumps([bad]))

    def test_wrapping_protects_temporal_units(self):
        font = ImageFont.truetype(str(covers.FONT_PATH), 32, index=0)
        lines = covers.wrap_title(self.title, font, 324, 5)
        self.assertEqual(''.join(lines), self.title)
        split_positions = {sum(len(line) for line in lines[:i]) for i in range(1, len(lines))}
        for phrase in ['每周', '小时', '工作', '最后']:
            self.assertNotIn(self.title.index(phrase)+1, split_positions)

    def test_missing_palette_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            covers.prepare(self.root, self.root, 'yellow', 'fixture', 'fixture', [self.root/'none.png'], True)

    def test_prompt_attaches_style_sample(self):
        text = (self.root/'imgs/prompts/cover-prompt.md').read_text(encoding='utf-8')
        self.assertIn(str(covers.STYLE_SAMPLE), text)
        self.assertTrue(covers.STYLE_SAMPLE.is_file())

    def test_prepare_requires_scene_and_relation(self):
        with self.assertRaises(ValueError):
            covers.prepare(self.root, self.root, 'yellow', '', '', None, True)

    def test_render_requires_prompt_first(self):
        (self.root/covers.PROMPT_REL).unlink()
        with self.assertRaises(ValueError):
            self.render()
        self.assertFalse((self.root/'imgs/cover-xhs.png').exists())

    def test_whole_scene_keeps_both_edges_in_landscape(self):
        self.render()
        im = Image.open(self.root/'imgs/cover-wechat.png')
        # 两侧标记都在；固定截取最右侧会丢掉红块。
        self.assertEqual(im.getpixel((431, 134)), (230, 20, 20))
        self.assertEqual(im.getpixel((829, 268)), (20, 30, 230))

    def test_outputs_sizes_and_minimal_assets(self):
        self.render()
        with Image.open(self.root/'imgs/cover-xhs.png') as im:
            self.assertEqual(im.size, (1440, 2400))
        with Image.open(self.root/'imgs/cover-wechat.png') as im:
            self.assertEqual(im.size, (900, 383))
        self.assertEqual(covers.Path(self.root/'imgs/cover.png').read_bytes(),
                         (self.root/'imgs/cover-wechat.png').read_bytes())
        source = sorted(p.name for p in (self.root/'imgs/cover-source').iterdir())
        self.assertEqual(source, ['master.png'])

    def test_new_cover_is_pending_until_reviewed(self):
        self.render()
        self.assertNotIn('- [x]', (self.root/'封面设计.md').read_text(encoding='utf-8'))
        self.assertEqual(self.verify('--files-only').returncode, 0)
        self.assertNotEqual(self.verify().returncode, 0)
        self.approve()
        self.assertEqual(self.verify().returncode, 0)

    def test_pass_without_ticks_or_notes_is_rejected(self):
        self.render()
        path = self.root/'封面设计.md'
        path.write_text(path.read_text(encoding='utf-8').replace('看图结论：待看图', '看图结论：通过'), encoding='utf-8')
        self.assertNotEqual(self.verify().returncode, 0)
        self.approve(note='')
        path.write_text(path.read_text(encoding='utf-8').replace('记录：', '记录：待填写', 1), encoding='utf-8')
        self.assertNotEqual(self.verify().returncode, 0)

    def test_title_change_after_cover_is_detected(self):
        self.render()
        self.approve()
        self.write_article('换了一个新标题')
        self.assertNotEqual(self.verify('--files-only').returncode, 0)

    def test_existing_outputs_are_protected_unless_replace(self):
        self.render()
        before = (self.root/'imgs/cover-xhs.png').read_bytes()
        with self.assertRaises(ValueError):
            self.render()
        self.assertEqual(before, (self.root/'imgs/cover-xhs.png').read_bytes())
        self.args.replace = True
        self.render()

    def test_focal_outside_safe_area_is_rejected(self):
        self.args.focal = [1, .5]
        with self.assertRaises(ValueError):
            self.render()


if __name__ == '__main__':
    unittest.main()
