"""项目初始化测试。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init_project


class InitProjectTests(unittest.TestCase):
    def test_creates_layout_and_keeps_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'writing'
            init_project.init(root)
            for p in ['01_选题/选题池.md', '02_调研/资料索引.md', 'AGENTS.md']:
                self.assertTrue((root / p).is_file(), p)
            for p in ['03_写作/进行中', '05_待发表']:
                self.assertTrue((root / p).is_dir(), p)
            (root / 'AGENTS.md').write_text('mine', encoding='utf-8')
            _, created, kept = init_project.init(root)
            self.assertEqual(created, [])
            self.assertIn('AGENTS.md', kept)
            self.assertEqual((root / 'AGENTS.md').read_text(encoding='utf-8'), 'mine')


if __name__ == '__main__':
    unittest.main()
