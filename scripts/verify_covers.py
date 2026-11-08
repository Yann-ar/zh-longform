#!/usr/bin/env python3
"""Read-only checks for editorial-handdrawn-v1 cover deliverables.

只查文件与看图记录，不做 OCR，不判断画风，不从文件存在推断看图已通过。
"""

import argparse
import hashlib
import io
import json
import re
import sys
from pathlib import Path

# 随项目附带的 Pillow，系统 Python 没装时使用
_vendor = Path(__file__).resolve().parent / "_vendor"
if _vendor.is_dir() and str(_vendor) not in sys.path:
    sys.path.insert(0, str(_vendor))


STYLE = "editorial-handdrawn-v1"
OUTPUTS = {
    "cover_xhs": ("imgs/cover-xhs.png", (1440, 2400)),
    "cover_wechat": ("imgs/cover-wechat.png", (900, 383)),
}


def frontmatter(path):
    text = path.read_text(encoding="utf-8-sig")
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.S)
    if not match:
        return {}
    fields = {}
    for line in match[1].splitlines():
        field = re.match(r"^([a-z_]+):\s*(.*?)\s*$", line)
        if field:
            fields[field[1]] = field[2].strip().strip("\"'")
    return fields


PROMPT_REL = "imgs/prompts/cover-prompt.md"
MASTER_REL = "imgs/cover-source/master.png"


def record_line(text, label):
    match = re.search(rf"^-?\s*{label}：(.*)$", text, re.M)
    return match[1].strip() if match else None


def workflow_checks(root, article_title, xhs_title, files_only):
    """新流程看 封面设计.md；2026-11-08 前的旧流程只认 visual-review.json 的通过记录。"""
    errors, notes = [], []
    design = root / "封面设计.md"
    if not design.is_file() or not design.read_text(encoding="utf-8").strip():
        return ["缺少 封面设计.md"], notes
    text = design.read_text(encoding="utf-8")
    if "看图结论：" not in text:
        notes.append("旧流程封面（2026-11-08 前），未按新格式检查")
        if not files_only:
            review_file = root / "imgs/cover-source/visual-review.json"
            try:
                review = json.loads(review_file.read_text(encoding="utf-8")) if review_file.is_file() else {}
            except (OSError, ValueError):
                review = {}
            if review.get("status") != "passed":
                errors.append("旧流程封面没有通过的看图记录；重做时请用新流程，只查文件可加 --files-only")
        return errors, notes
    for relative in (PROMPT_REL, MASTER_REL):
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"缺少 {relative}")
    for label, expected in (("公众号标题", article_title), ("小红书标题", xhs_title)):
        recorded = record_line(text, label)
        if recorded != expected:
            errors.append(f"封面设计.md 记录的{label}与正文不一致，标题改过后须重新生成封面")
    if not files_only:
        section = text.split("## 看图记录", 1)[1] if "## 看图记录" in text else ""
        if record_line(text, "看图结论") != "通过":
            errors.append("看图结论不是「通过」；只查文件可加 --files-only")
        elif re.search(r"^\s*- \[ \]", section, re.M):
            errors.append("看图结论写了「通过」，但看图清单还有未打勾项")
        elif record_line(text, "记录") in (None, "", "待填写"):
            errors.append("看图结论写了「通过」，但没有写看图记录")
    return errors, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article_dir", type=Path)
    parser.add_argument(
        "--if-enabled", action="store_true",
        help="Skip legacy articles without a cover_style frontmatter field.",
    )
    parser.add_argument("--files-only", action="store_true", help="只查文件，不检查看图结论")
    parser.add_argument("--assets-dir", type=Path, help="检查独立预览目录，文章标题仍从 article_dir 读取")
    args = parser.parse_args()
    root = args.assets_dir or args.article_dir
    article = args.article_dir / "文章.md"
    if not article.is_file():
        print(f"  ✗ [双封面] 未找到母稿: {article}")
        return 1
    try:
        fields = frontmatter(article)
    except (OSError, UnicodeError) as exc:
        print(f"  ✗ [双封面] 母稿无法读取: {exc}")
        return 1
    if args.if_enabled and not args.assets_dir and "cover_style" not in fields:
        print("  ℹ [双封面] 旧文章未声明新封面规范，未执行双尺寸检查")
        return 0

    errors = []
    if not args.assets_dir and fields.get("cover_style") != STYLE:
        errors.append(f"母稿须声明 cover_style: \"{STYLE}\"")
    if not args.assets_dir and fields.get("cover_text") not in {"title-only", "none"}:
        errors.append("cover_text 须为 title-only 或 none")
    if not args.assets_dir and fields.get("cover_image") != "imgs/cover.png":
        errors.append("cover_image 须为 imgs/cover.png")

    for key, (relative, _) in OUTPUTS.items():
        if not args.assets_dir and fields.get(key) != relative:
            errors.append(f"{key} 须为 {relative}")

    try:
        from PIL import Image, ImageCms
    except ImportError:
        errors.append("图像检查需要 Pillow，请在可用的 Python 环境中安装后重试")
        Image = ImageCms = None

    for relative, expected_size in OUTPUTS.values():
        path = root / relative
        if not path.is_file():
            errors.append(f"缺少成品: {relative}")
            continue
        if Image is None:
            continue
        try:
            with Image.open(path) as im:
                if im.format != "PNG":
                    errors.append(f"{relative}: 必须为真实 PNG，当前为 {im.format}")
                if im.size != expected_size:
                    errors.append(f"{relative}: 尺寸为 {im.size}，应为 {expected_size}")
                if im.mode != "RGB" or "transparency" in im.info:
                    errors.append(f"{relative}: 必须为无透明通道的 RGB，当前为 {im.mode}")
                if im.format == "PNG" and path.read_bytes()[24] != 8:
                    errors.append(f"{relative}: 必须为 8 位 PNG")
                profile = im.info.get("icc_profile")
                if profile:
                    description = ImageCms.getProfileDescription(
                        ImageCms.ImageCmsProfile(io.BytesIO(profile))
                    )
                    if "srgb" not in description.lower().replace(" ", ""):
                        errors.append(f"{relative}: ICC 配置不是 sRGB: {description.strip()}")
                elif "srgb" not in im.info:
                    errors.append(f"{relative}: 缺少明确的 sRGB 标记或 ICC 配置")
                im.verify()
            # verify() checks PNG structure; load() also checks the pixel stream.
            with Image.open(path) as im:
                im.load()
        except Exception as exc:
            errors.append(f"{relative}: 图像解码或色彩配置检查失败: {exc}")

    alias = root / "imgs/cover.png"
    wechat = root / OUTPUTS["cover_wechat"][0]
    if not alias.is_file():
        errors.append("缺少兼容副本: imgs/cover.png")
    elif wechat.is_file():
        if hashlib.sha256(alias.read_bytes()).digest() != hashlib.sha256(wechat.read_bytes()).digest():
            errors.append("imgs/cover.png 与 cover-wechat.png 不是相同副本")

    article_text = article.read_text(encoding="utf-8-sig")
    h1 = re.search(r"^# (.+)$", article_text, re.M)
    article_title = h1[1].strip() if h1 else ""
    xhs_file = args.article_dir / "文章_小红书版.md"
    xhs_h1 = re.search(r"^# (.+)$", xhs_file.read_text(encoding="utf-8-sig"), re.M) if xhs_file.is_file() else None
    xhs_title = xhs_h1[1].strip() if xhs_h1 else article_title
    workflow_errors, notes = workflow_checks(root, article_title, xhs_title, args.files_only)
    errors.extend(workflow_errors)
    for error in errors:
        print(f"  ✗ [双封面] {error}")
    if errors:
        return 1
    print("  ✓ [双封面文件] 1440 × 2400 / 900 × 383，PNG、8 位 RGB、sRGB，兼容副本一致")
    for note in notes:
        print(f"  ℹ [双封面] {note}")
    if args.files_only:
        print("  ℹ [仅文件检查] 不代表画风合格、用户采用或已发布")
    else:
        print("  ✓ [看图记录] 已有看图通过记录；用户采用与发布另计")
    for relative, _ in OUTPUTS.values():
        print(f"      交付: {root / relative}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, UnicodeError) as exc:
        print(f"  ✗ [双封面] 文件读取失败: {exc}")
        sys.exit(1)
