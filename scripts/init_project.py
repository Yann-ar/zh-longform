#!/usr/bin/env python3
"""在一个目录里初始化 zh-longform 写作项目。

用法：
  python3 init_project.py <项目目录>      # 目录不存在会新建；已有文件一律不覆盖
"""
import argparse
import shutil
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL_DIR / 'templates'
FOLDERS = ['01_选题', '02_调研', '03_写作/进行中', '05_待发表']
FILES = {
    'AGENTS.md': '项目AGENTS.md',
    '01_选题/选题池.md': '选题池.md',
    '02_调研/资料索引.md': '资料索引.md',
}


def init(root):
    root = Path(root).resolve()
    created, kept = [], []
    for folder in FOLDERS:
        path = root / folder
        if not path.exists():
            path.mkdir(parents=True)
            created.append(folder + '/')
    for target, template in FILES.items():
        path = root / target
        if path.exists():
            kept.append(target)
            continue
        shutil.copyfile(TEMPLATES / template, path)
        created.append(target)
    return root, created, kept


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('project_dir', type=Path)
    args = parser.parse_args()
    root, created, kept = init(args.project_dir)
    print(f'项目目录：{root}')
    for item in created:
        print(f'  新建 {item}')
    for item in kept:
        print(f'  已存在，未改动 {item}')
    print(f'模板在 {TEMPLATES}，写新文章时复制 X长文模板.md 和 X长文Caption模板.md。')


if __name__ == '__main__':
    main()
