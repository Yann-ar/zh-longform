#!/usr/bin/env bash
# ==============================================================================
# X 长文交付检查与发布辅助一体化脚本 (verify_article.sh)
# 用法:
#   1. 检查单篇文章: ./verify_article.sh "05_待发表/deepseek-v4-flash-codex"
#   2. 扫描待发表区全部文章: ./verify_article.sh --all
#   3. 指定目录全量扫描: ./verify_article.sh --all "05_待发表"
# ==============================================================================

set -uo pipefail

# 统一按 UTF-8 处理中文。终端语言环境为 C 时，grep 会把中文和弯引号拆成字节匹配，产生大量误报。
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# 颜色输出定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# 统计变量
TOTAL_ERRORS=0
TOTAL_WARNINGS=0
XHS_MODE=0
WECHAT_MODE=0
COVERS_MODE=0
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------------------------
# 单篇检查函数
# ------------------------------------------------------------------------------
check_single_article() {
    local target_dir="$1"
    # 去除末尾斜杠
    target_dir="${target_dir%/}"

    if [ ! -d "$target_dir" ]; then
        echo -e "${RED}[ERROR] 目录不存在: ${target_dir}${NC}"
        TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
        return 1
    fi

    local article_file="${target_dir}/文章.md"
    if [ "$XHS_MODE" -eq 1 ] && [ -f "${target_dir}/文章_小红书版.md" ]; then
        article_file="${target_dir}/文章_小红书版.md"
    fi
    local caption_file="${target_dir}/caption.md"
    if [ "$XHS_MODE" -eq 1 ] && [ -f "${target_dir}/caption_小红书版.md" ]; then
        caption_file="${target_dir}/caption_小红书版.md"
    fi
    local review_file="${target_dir}/审读.md"

    echo -e "\n${BOLD}${CYAN}================================================================${NC}"
    echo -e "${BOLD}${CYAN} 正在质检: ${target_dir}${NC}"
    echo -e "${BOLD}${CYAN}================================================================${NC}"

    local dir_errors=0
    local dir_warnings=0

    # 0. 发布平台：frontmatter 的 platforms 字段，如 platforms: [x, xhs, wechat]。
    #    未声明时按旧行为检查；声明后只检查列出的平台，列出的平台按严格模式检查。
    local platforms=""
    if [ -f "${target_dir}/文章.md" ]; then
        platforms=$(python3 - "${target_dir}/文章.md" << 'EOF'
import re, sys
text = open(sys.argv[1], encoding='utf-8-sig').read()
fm = re.match(r'\A---\s*\n(.*?)\n---', text, re.S)
if fm:
    m = re.search(r'^platforms:\s*\[(.*?)\]\s*$', fm[1], re.M)
    items = re.findall(r'[a-z]+', m[1]) if m else []
    if not m:
        block = re.search(r'^platforms:\s*\n((?:\s+-\s*\S+\s*\n?)+)', fm[1], re.M)
        items = re.findall(r'-\s*([a-z]+)', block[1]) if block else []
    print(' '.join(items))
EOF
)
    fi
    local pf_declared=0 pf_xhs=0 pf_wechat=0
    if [ -n "$platforms" ]; then
        pf_declared=1
        [[ " $platforms " == *" xhs "* ]] && pf_xhs=1
        [[ " $platforms " == *" wechat "* ]] && pf_wechat=1
        echo -e "  ${BLUE}ℹ [发布平台] ${platforms}${NC}"
        for pf in $platforms; do
            if [[ "$pf" != "x" && "$pf" != "xhs" && "$pf" != "wechat" ]]; then
                echo -e "  ${RED}✗ [发布平台] 未知平台 ${pf}，只能是 x、xhs、wechat${NC}"
                dir_errors=$((dir_errors + 1))
            fi
        done
        if [ "$pf_xhs" -eq 1 ]; then
            for f in 文章_小红书版.md caption_小红书版.md; do
                if [ ! -f "${target_dir}/${f}" ]; then
                    echo -e "  ${RED}✗ [发布平台] 声明了 xhs，但缺少 ${f}${NC}"
                    dir_errors=$((dir_errors + 1))
                fi
            done
        fi
        if [ "$pf_wechat" -eq 1 ] && [ ! -f "${target_dir}/文章.html" ]; then
            echo -e "  ${RED}✗ [发布平台] 声明了 wechat，但缺少 文章.html${NC}"
            dir_errors=$((dir_errors + 1))
        fi
    fi

    # 1. 检查基础文件存在性
    if [ ! -f "$article_file" ]; then
        echo -e "  ${RED}✗ [文件缺失] 未找到 文章.md${NC}"
        dir_errors=$((dir_errors + 1))
        return 1
    else
        echo -e "  ${GREEN}✓ [基础文件] 找到 文章.md${NC}"
    fi

    # 2. 检查审读.md (独立审读门禁)
    if [ ! -f "$review_file" ]; then
        echo -e "  ${RED}✗ [审读门禁] 缺失 审读.md，未执行物理隔离的独立审读${NC}"
        dir_errors=$((dir_errors + 1))
    else
        # 智能分析审读结论部分
        local review_status
        review_status=$(python3 - << 'EOF' "$review_file"
import sys, re

filepath = sys.argv[1]
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

# 新格式（见 Skill 的 templates/审读模板.md）：一行「结论：通过」或「结论：退回」
verdict = re.search(r'^结论[：:]\s*(通过|退回)\s*$', text, re.M)
if verdict:
    if verdict.group(1) == '退回':
        print("REJECTED")
    elif re.search(r'^\s*- \[ \]', text, re.M):
        print("INCONSISTENT:阻断清单仍有未打勾项")
    elif re.search(r'\|\s*未改\s*\|\s*$', text, re.M):
        print("INCONSISTENT:修改表仍有「未改」条目")
    else:
        print("PASSED")
    sys.exit(0)

# 旧格式兼容
match = re.search(r'#+\s*(?:三[、.]\s*)?审读结论[\s\S]*', text)
conclusion_text = match.group(0) if match else text

if re.search(r'(?:判定|结果|结论)[：:\s]*(?:不合格|退回|打回|需重写|未通过)', conclusion_text) and not re.search(r'(?:复审|重新审读|修正后)?通过', conclusion_text):
    print("REJECTED")
elif "通过" in conclusion_text:
    print("LEGACY_PASSED")
else:
    print("UNKNOWN")
EOF
)
        if [ "$review_status" == "REJECTED" ]; then
            echo -e "  ${RED}✗ [审读门禁] 审读.md 中仍有未解决的打回/不合格判定${NC}"
            dir_errors=$((dir_errors + 1))
        elif [[ "$review_status" == INCONSISTENT:* ]]; then
            echo -e "  ${RED}✗ [审读门禁] 结论写了「通过」，但${review_status#INCONSISTENT:}${NC}"
            dir_errors=$((dir_errors + 1))
        elif [ "$review_status" == "PASSED" ]; then
            echo -e "  ${GREEN}✓ [审读门禁] 独立《审读.md》存在且通过${NC}"
        else
            echo -e "  ${GREEN}✓ [审读门禁] 独立《审读.md》存在且通过（旧格式审读，未检查阻断清单）${NC}"
        fi
    fi

    # 3. 检查 caption.md
    if [ ! -f "$caption_file" ]; then
        echo -e "  ${RED}✗ [配文缺失] 未找到 caption.md${NC}"
        dir_errors=$((dir_errors + 1))
    else
        echo -e "  ${GREEN}✓ [配文文件] 找到 caption.md${NC}"
    fi

    # 4. 标题三者一致性检查
    local fm_title=""
    local h1_title=""
    local caption_title=""

    # 提取 frontmatter title (兼容双引号、单引号或无引号)
    fm_title=$(grep -m1 '^title:' "$article_file" | sed -E 's/^title:[[:space:]]*["'"'"']?([^"'"'"']+)["'"'"']?/\1/' | tr -d '\r')
    # 提取正文 H1
    h1_title=$(grep -m1 '^# ' "$article_file" | sed -E 's/^#[[:space:]]+//' | tr -d '\r')

    if [ -f "$caption_file" ]; then
        # 优先从 caption 的 frontmatter 提取 title
        caption_title=$(grep -m1 '^title:' "$caption_file" | sed -E 's/^title:[[:space:]]*["'"'"']?([^"'"'"']+)["'"'"']?/\1/' | tr -d '\r' || true)
        # 若 caption frontmatter 里的 title 是默认的 "文章配文" 或 "Caption"，则尝试提取书名号
        if [ "$caption_title" == "文章配文" ] || [ "$caption_title" == "Caption" ] || [ -z "$caption_title" ]; then
            caption_title=$(grep -oE '《[^》]+》' "$caption_file" | head -n 1 | tr -d '《》\r' || true)
        fi
    fi

    if [ -z "$fm_title" ] || [ -z "$h1_title" ]; then
        echo -e "  ${RED}✗ [标题比对] 无法提取 frontmatter title 或 正文 H1${NC}"
        dir_errors=$((dir_errors + 1))
    elif [ "$fm_title" != "$h1_title" ]; then
        echo -e "  ${RED}✗ [标题比对] frontmatter 与 H1 不一致:${NC}"
        echo -e "      frontmatter: \"${fm_title}\""
        echo -e "      正文 H1:     \"${h1_title}\""
        dir_errors=$((dir_errors + 1))
    else
        if [ -n "$caption_title" ] && [ "$caption_title" != "$h1_title" ]; then
            echo -e "  ${YELLOW}⚠ [标题比对] 正文标题与 caption 中提取的标题可能有差异:${NC}"
            echo -e "      正文 H1: \"${h1_title}\""
            echo -e "      Caption: \"${caption_title}\""
            dir_warnings=$((dir_warnings + 1))
        else
            echo -e "  ${GREEN}✓ [标题比对] frontmatter / H1 / Caption 标题一致 (\"${h1_title}\")${NC}"
        fi
    fi

    # 5. 图片路径与绝对路径/外链检查 (Python 精准解析)
    local img_check_res
    img_check_res=$(python3 - << 'EOF' "$article_file" "$target_dir"
import sys, re, os, urllib.parse

article_file = sys.argv[1]
target_dir = sys.argv[2]

with open(article_file, 'r', encoding='utf-8') as f:
    content = f.read()

img_matches = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', content)

abs_or_url_imgs = []
missing_imgs = []

for alt, raw_src in img_matches:
    src = raw_src.strip().strip('<>').strip('"').strip("'")
    src = urllib.parse.unquote(src)

    if src.startswith(('http://', 'https://', '/')):
        abs_or_url_imgs.append(src)
        continue

    full_path = os.path.join(target_dir, src)
    if not os.path.isfile(full_path):
        missing_imgs.append(src)

if abs_or_url_imgs:
    for item in abs_or_url_imgs:
        print(f"ABS_OR_URL:{item}")
if missing_imgs:
    for item in missing_imgs:
        print(f"MISSING:{item}")
EOF
)

    local img_issues=0
    if [ -n "$img_check_res" ]; then
        while read -r line; do
            if [[ "$line" =~ ^ABS_OR_URL:(.*) ]]; then
                echo -e "  ${RED}✗ [图片路径] 发现绝对路径或外链图片: ${BASH_REMATCH[1]}${NC}"
                dir_errors=$((dir_errors + 1))
                img_issues=$((img_issues + 1))
            elif [[ "$line" =~ ^MISSING:(.*) ]]; then
                echo -e "  ${RED}✗ [图片丢失] 正文引用了不存在的图片: ${BASH_REMATCH[1]}${NC}"
                dir_errors=$((dir_errors + 1))
                img_issues=$((img_issues + 1))
            fi
        done <<< "$img_check_res"
    fi

    if [ "$img_issues" -eq 0 ]; then
        echo -e "  ${GREEN}✓ [图片路径] 全部图片引用均为有效相对路径${NC}"
    fi

    # 6. 已知错字与赘字模式扫描 (精确短距离匹配，避免跨句误报)
    local typo_patterns='在在|的的|是是|了了|会[一-龥]{0,4}会[滚发出来]|看的(很|得)|映到|填色|信稿|擦枪拉锯'
    local typo_hits
    typo_hits=$(grep -nE "$typo_patterns" "$article_file" || true)
    if [ -f "$caption_file" ]; then
        local cap_typo_hits
        cap_typo_hits=$(grep -nE "$typo_patterns" "$caption_file" || true)
        if [ -n "$cap_typo_hits" ]; then
            typo_hits="${typo_hits}
[caption] ${cap_typo_hits}"
        fi
    fi

    if [ -n "$typo_hits" ] && [ "$typo_hits" != "
[caption] " ]; then
        echo -e "  ${RED}✗ [错字赘字] 命中已知病句/错字模式:${NC}"
        echo "$typo_hits" | while read -r line; do
            [ -n "$line" ] && echo -e "      $line"
        done
        dir_errors=$((dir_errors + 1))
    else
        echo -e "  ${GREEN}✓ [错字赘字] 未命中已知病句/错字模式${NC}"
    fi

    # 7. 引号体例检查 (正文严禁使用全角弯引号 “”)
    local quote_hits
    quote_hits=$(python3 - "$article_file" << 'EOF'
import re, sys
text = open(sys.argv[1], encoding='utf-8-sig').read()
in_code = False
for no, line in enumerate(text.splitlines(), 1):
    if line.lstrip().startswith('```'):
        in_code = not in_code
        continue
    if in_code:
        continue
    if '\u201c' in line or '\u201d' in line:
        print(f'{no}:{line}')
EOF
)
    if [ -n "$quote_hits" ]; then
        echo -e "  ${RED}✗ [引号体例] 发现非标弯引号（正文应统一直角引号「」）:${NC}"
        echo "$quote_hits" | head -n 5 | while read -r line; do
            echo -e "      $line"
        done
        dir_errors=$((dir_errors + 1))
    else
        echo -e "  ${GREEN}✓ [引号体例] 引号体例统一为直角引号「」${NC}"
    fi

    # 8. 智能盘古之白检测 (过滤代码块、行内代码、URL、Markdown链接)
    local pangu_hits
    pangu_hits=$(python3 - << 'EOF' "$article_file"
import sys, re

filepath = sys.argv[1]
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_code_block = False
errors = []

for idx, raw_line in enumerate(lines, 1):
    line = raw_line.strip()
    if line.startswith('```'):
        in_code_block = not in_code_block
        continue
    if in_code_block or not line:
        continue
    if line.startswith('%') or line.startswith('<!--'):
        continue

    # 清除行内代码 `...`
    clean = re.sub(r'`[^`]+`', ' ', raw_line)
    # 清除 Markdown 图片与链接 ![...](...) / [...](...)
    clean = re.sub(r'!\[[^\]]*\]\([^\)]+\)', ' ', clean)
    clean = re.sub(r'\[[^\]]+\]\([^\)]+\)', ' ', clean)
    # 清除 URL
    clean = re.sub(r'https?://[^\s]+', ' ', clean)
    # 清除 Obsidian 嵌入语法 [[...]]
    clean = re.sub(r'\[\[[^\]]+\]\]', ' ', clean)
    # 忽略表格对齐符和纯符号行
    if clean.strip().startswith('|') and '---' in clean:
        continue

    # 检测 中文 + 英文/数字 或 英文/数字 + 中文
    matches = re.findall(r'([\u4e00-\u9fa5][A-Za-z0-9]|[A-Za-z0-9][\u4e00-\u9fa5])', clean)
    valid_matches = []
    for m in matches:
        valid_matches.append(m)

    if valid_matches:
        snippet = raw_line.strip()
        if len(snippet) > 80:
            snippet = snippet[:80] + '...'
        errors.append(f"第 {idx} 行 [{', '.join(valid_matches[:3])}]: {snippet}")

if errors:
    for e in errors[:5]:
        print(e)
    if len(errors) > 5:
        print(f"... 共发现 {len(errors)} 处未加空格")
EOF
)
    if [ -n "$pangu_hits" ]; then
        echo -e "  ${YELLOW}⚠ [盘古之白] 发现中英文/数字之间可能缺失半角空格:${NC}"
        echo "$pangu_hits" | while read -r line; do
            echo -e "      $line"
        done
        dir_warnings=$((dir_warnings + 1))
    else
        echo -e "  ${GREEN}✓ [盘古之白] 中英文及数字之间空格规范${NC}"
    fi

    # 9. 时效陈述与数字自洽检测
    local time_hits
    time_hits=$(grep -nE '预计|截至[[:space:]]*[0-9]{4}' "$article_file" || true)
    if [ -n "$time_hits" ]; then
        echo -e "  ${BLUE}ℹ [时效提示] 正文包含时效陈述，请在发表前确认最新状态:${NC}"
        echo "$time_hits" | while read -r line; do
            echo -e "      $line"
        done
    fi

    # 10. 小红书与国内多平台合规脱敏扫描 (基于《平台与封面.md》第三节)
    local xhs_target="$article_file" xhs_strict=$XHS_MODE run_xhs=1
    if [ "$pf_declared" -eq 1 ]; then
        if [ "$pf_xhs" -eq 1 ]; then
            xhs_strict=1
            [ -f "${target_dir}/文章_小红书版.md" ] && xhs_target="${target_dir}/文章_小红书版.md"
        elif [ "$XHS_MODE" -eq 0 ]; then
            run_xhs=0
            echo -e "  ${BLUE}ℹ [小红书] 未声明 xhs 平台，跳过脱敏扫描${NC}"
        fi
    fi
    local xhs_scan_res=""
    [ "$run_xhs" -eq 1 ] && xhs_scan_res=$(python3 - << 'EOF' "$xhs_target"
import sys, re

article_file = sys.argv[1]

sensitive_rules = [
    {
        "category": "刑事暴力侵权",
        "pattern": r'(强奸|强奸罪|家暴|死亡威胁|偷拍|性侵|性侵犯|侵犯受害者)',
        "suggestion": "建议改为中性法律表达：面临刑事指控、多起伤害行为成立、严重违法诉讼"
    },
    {
        "category": "违禁药物不良",
        "pattern": r'(毒品|贩毒|吸毒|毒贩|可卡因|海洛因|冰毒|大麻)',
        "suggestion": "建议改为中性表述：违禁物品、不良社交圈子、涉足违禁物质"
    },
    {
        "category": "名流特定丑闻",
        "pattern": r'(爱泼斯坦|萝莉岛|招募未成年|裸体壁纸)',
        "suggestion": "建议隐去高敏人名：深陷争议的已故富商、名流社交风波、名流丑闻"
    },
    {
        "category": "民俗迷信医疗",
        "pattern": r'(萨满|通灵|巫术|辟邪吊坠|改变原子结构|预防新冠病毒)',
        "suggestion": "建议改为中性表述：神秘学人士、心灵疗愈争议、非传统疗法风波"
    },
    {
        "category": "生命心理危机",
        "pattern": r'(自杀|自杀身亡|自残|恐惧得剧烈颤抖|绝望的痛哭)',
        "suggestion": "建议改为中性表述：遗憾离世、骤然辞世、因抑郁症离开人世、深切的无力与悲凉"
    },
    {
        "category": "重大时政更迭",
        "pattern": r'(降半旗|特别国务委员会|内阁通报|宣布依宪法登基)',
        "suggestion": "建议淡化元首更迭：权力平稳过渡、王室成员完成交接、家族长辈辞世"
    },
    {
        "category": "时政军事涉密 (薯条P0)",
        "pattern": r'(五角大楼|军方|原子能委员会|战略机密|国防科研|核武器|核战略|洲际导弹|荷枪实弹)',
        "suggestion": "建议改为学术中性表达：前沿官方机构、尖端科学项目、重大科研课题、核心学术底牌"
    },
    {
        "category": "重症医疗病理 (薯条高危)",
        "pattern": r'(骨癌|癌细胞|恶性肿瘤|骨转移)',
        "suggestion": "建议改为生活与健康中性表述：突如其来的重病、不可逆的身体衰竭、健康骤受冲击"
    },
    {
        "category": "宗教神职活动 (薯条敏感)",
        "pattern": r'(罗马天主教|神父|临终圣事|忏悔仪式)',
        "suggestion": "建议改为人文哲学对话：有深厚学养的学者、哲学家、精神层面的思想长谈"
    }
]

with open(article_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_code = False
found_sensitive = []
found_urls = []

for idx, raw_line in enumerate(lines, 1):
    line = raw_line.strip()
    if line.startswith('```'):
        in_code = not in_code
        continue
    if in_code or not line or line.startswith('%'):
        continue

    urls = re.findall(r'https?://[^\s\)]+', line)
    if urls:
        found_urls.append((idx, urls))

    for rule in sensitive_rules:
        matches = re.findall(rule["pattern"], line)
        if matches:
            found_sensitive.append((idx, rule["category"], list(set(matches)), rule["suggestion"]))

if found_sensitive:
    for item in found_sensitive:
        print(f"SENSITIVE:{item[0]}:{item[1]}:{','.join(item[2])}:{item[3]}")
else:
    print("NO_SENSITIVE")

if found_urls:
    print(f"URL_COUNT:{len(found_urls)}")
    for idx, urls in found_urls[:3]:
        print(f"URL:{idx}:{','.join(urls)}")
else:
    print("NO_URL")
EOF
)

    local sens_count=0
    local url_count=0
    if [ -n "$xhs_scan_res" ]; then
        sens_count=$(echo "$xhs_scan_res" | grep -c '^SENSITIVE:' || true)
        if echo "$xhs_scan_res" | grep -q '^URL_COUNT:'; then
            url_count=$(echo "$xhs_scan_res" | grep '^URL_COUNT:' | cut -d':' -f2)
        fi
    fi

    if [ "$run_xhs" -eq 0 ]; then
        :
    elif [ "$sens_count" -gt 0 ]; then
        if [ "$xhs_strict" -eq 1 ]; then
            echo -e "  ${RED}✗ [小红书阻断] 命中 ${sens_count} 处国内平台机审红线词汇 (Ghost-ban 风险):${NC}"
            dir_errors=$((dir_errors + sens_count))
        else
            echo -e "  ${YELLOW}⚠ [小红书合规提示] 发现 ${sens_count} 处国内分发潜在敏感词 (发布至国内需脱敏):${NC}"
            dir_warnings=$((dir_warnings + sens_count))
        fi
        echo "$xhs_scan_res" | grep '^SENSITIVE:' | while IFS=':' read -r _ line_no cat terms sugg; do
            echo -e "      第 ${line_no} 行 【${cat}】: 命中 \"${terms}\" -> ${sugg}"
        done
    else
        echo -e "  ${GREEN}✓ [小红书脱敏] 正文未命中任何涉敏违法/迷信/丑闻词汇${NC}"
    fi

    if [ "$run_xhs" -eq 0 ]; then
        :
    elif [ "$url_count" -gt 0 ]; then
        if [ "$xhs_strict" -eq 1 ]; then
            echo -e "  ${RED}✗ [小红书阻断] 发现 ${url_count} 处外部超链接（小红书严禁外部跳转外链，会导致单向屏蔽）${NC}"
            dir_errors=$((dir_errors + 1))
        else
            echo -e "  ${BLUE}ℹ [小红书提示] 正文包含 ${url_count} 处外部超链接（若同步国内平台，请转为纯文本书名/机构引用）${NC}"
        fi
    else
        echo -e "  ${GREEN}✓ [小红书外链] 正文无外部 URL 超链接（符合小红书零外链规范）${NC}"
    fi

    # 11. 微信公众平台推荐合规与防低创作度专项检测
    local wechat_scan_res
    wechat_scan_res=$(python3 - << 'EOF' "$article_file"
import sys, re

article_file = sys.argv[1]
with open(article_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_code = False
found_leads = []
has_table = False
list_count = 0
non_empty_lines = 0
caption_issues = []

for idx, raw_line in enumerate(lines, 1):
    line = raw_line.strip()
    if line.startswith('```'):
        in_code = not in_code
        continue
    if in_code or not line or line.startswith('%'):
        continue
    
    non_empty_lines += 1

    # 1. 检测导流词汇
    lead_matches = re.findall(r'(长按扫码|长按识别二维码|扫码关注|回复关键词|私信回复|点击阅读原文|领取资料|进群交流|加微信|添加客服)', line)
    if lead_matches:
        found_leads.append((idx, list(set(lead_matches))))

    # 2. 检测结构化表格
    if re.search(r'\|(?:\s*[-:]+[-|\s:]*)\|', line):
        has_table = True

    # 3. 统计列表项
    if re.match(r'^(?:-|\*|\d+\.)\s+', line):
        list_count += 1

    # 4. 检测图片图注（检查是否交代物证出处与年份：包含 | 分隔符或来源/现藏/图源关键字）
    img_matches = re.findall(r'!\[(.*?)\]\((.*?)\)', line)
    for cap, src in img_matches:
        has_source = ('|' in cap) or any(k in cap for k in ['来源', '图源', '现藏于', '档案', '藏品', '摄于', '引自'])
        if 'cover' not in src.lower() and not has_source:
            caption_issues.append((idx, cap if cap else "空图注", src))

# 输出结果
if found_leads:
    for idx, terms in found_leads:
        print(f"WECHAT_LEAD:{idx}:{','.join(terms)}")
else:
    print("NO_WECHAT_LEAD")

if has_table:
    print("WECHAT_TABLE:FOUND")
else:
    print("WECHAT_TABLE:NONE")

if non_empty_lines > 20 and (list_count / non_empty_lines) > 0.45:
    print(f"WECHAT_DICT_RISK:{list_count}:{non_empty_lines}")
else:
    print("NO_WECHAT_DICT_RISK")

if caption_issues:
    for idx, cap, src in caption_issues:
        print(f"CAPTION_MISSING_SOURCE:{idx}:{cap}:{src}")
else:
    print("NO_CAPTION_ISSUES")
EOF
)

    local wechat_strict=$WECHAT_MODE run_wechat=1
    if [ "$pf_declared" -eq 1 ]; then
        if [ "$pf_wechat" -eq 1 ]; then
            wechat_strict=1
        elif [ "$WECHAT_MODE" -eq 0 ]; then
            run_wechat=0
            echo -e "  ${BLUE}ℹ [公众号] 未声明 wechat 平台，跳过导流与低创作度检查${NC}"
        fi
    fi
    local lead_count=0
    if [ -n "$wechat_scan_res" ]; then
        lead_count=$(echo "$wechat_scan_res" | grep -c '^WECHAT_LEAD:' || true)
    fi

    if [ "$run_wechat" -eq 0 ]; then
        :
    elif [ "$lead_count" -gt 0 ]; then
        if [ "$wechat_strict" -eq 1 ]; then
            echo -e "  ${RED}✗ [微信公域阻断] 命中 ${lead_count} 处破坏推荐的导流违规词汇（会被移出公域推荐）:${NC}"
            dir_errors=$((dir_errors + lead_count))
        else
            echo -e "  ${YELLOW}⚠ [微信推荐提示] 发现 ${lead_count} 处潜在导流词汇（微信严禁导流，影响推荐）:${NC}"
            dir_warnings=$((dir_warnings + lead_count))
        fi
        echo "$wechat_scan_res" | grep '^WECHAT_LEAD:' | while IFS=':' read -r _ line_no terms; do
            echo -e "      第 ${line_no} 行: 命中 \"${terms}\""
        done
    else
        echo -e "  ${GREEN}✓ [微信推荐合规] 无违规导流/扫码/诱导互动话术（符合公域推荐规范）${NC}"
    fi

    if [ "$run_wechat" -eq 0 ]; then
        :
    elif echo "$wechat_scan_res" | grep -q '^WECHAT_TABLE:FOUND'; then
        echo -e "  ${GREEN}✓ [信息增量-结构化] 正文包含结构化 Markdown 数据表格（高信息密度物证）${NC}"
    else
        echo -e "  ${BLUE}ℹ [信息增量提示] 未检测到 Markdown 数据表格（建议在参数对比或算账时补充原生表格）${NC}"
    fi

    if [ "$run_wechat" -eq 1 ] && echo "$wechat_scan_res" | grep -q '^WECHAT_DICT_RISK:'; then
        echo -e "  ${YELLOW}⚠ [低创作度风险] 列表占比超过 45%，存在词典式罗列风险（建议加强连贯叙事与实测）${NC}"
        dir_warnings=$((dir_warnings + 1))
    fi

    local caption_issue_count=0
    caption_issue_count=$(echo "$wechat_scan_res" | grep -c '^CAPTION_MISSING_SOURCE:' || true)
    if [ "$caption_issue_count" -gt 0 ]; then
        echo -e "  ${YELLOW}⚠ [物证图注规范] 发现 ${caption_issue_count} 处插图未采用「物证对象 | 年份 | 出处」三要素格式:${NC}"
        echo "$wechat_scan_res" | grep '^CAPTION_MISSING_SOURCE:' | while IFS=':' read -r _ line_no cap src; do
            echo -e "      第 ${line_no} 行: \"${cap}\" (${src}) -> 建议增加年份与馆藏/文献出处"
        done
        dir_warnings=$((dir_warnings + caption_issue_count))
    else
        echo -e "  ${GREEN}✓ [物证图注规范] 正文插图均规范标注物证、年份与出处${NC}"
    fi

    # 12. X Article 发布图文映射辅助清单
    echo -e "\n  ${BOLD}${BLUE}📋 [X Article 发布辅助] 配图插入对照表:${NC}"
    python3 - << 'EOF' "$article_file" "$target_dir"
import sys, re, os, urllib.parse

article_file = sys.argv[1]
target_dir = sys.argv[2]

with open(article_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

current_section = "顶部 (H1 开场)"
img_count = 0

for line in lines:
    line_s = line.strip()
    if line_s.startswith('# '):
        current_section = f"H1: {line_s[2:]}"
    elif line_s.startswith('## '):
        current_section = f"H2: {line_s[3:]}"
    elif line_s.startswith('### '):
        current_section = f"H3: {line_s[4:]}"
    
    img_match = re.search(r'!\[([^\]]*)\]\(([^)]+)\)', line_s)
    if img_match:
        img_count += 1
        alt = img_match.group(1) or "(无说明)"
        raw_src = img_match.group(2)
        rel_path = raw_src.strip().strip('<>').strip('"').strip("'")
        rel_path = urllib.parse.unquote(rel_path)
        full_path = os.path.join(target_dir, rel_path)
        exists_mark = "✓ 存在" if os.path.exists(full_path) else "✗ 缺失"
        print(f"      [{img_count}] 位置: [{current_section}]")
        print(f"          文件: {rel_path} ({exists_mark})")
        print(f"          图注: {alt}")

if img_count == 0:
    print("      (本篇为纯文字稿，无配图)")
EOF

    # 13. 双平台封面：新文章自动检查，--covers 强制旧文章检查。
    local cover_args=("$target_dir")
    if [ "$COVERS_MODE" -eq 0 ]; then
        cover_args+=(--if-enabled)
    fi
    if ! python3 "$SCRIPT_DIR/verify_covers.py" "${cover_args[@]}"; then
        dir_errors=$((dir_errors + 1))
    fi

    # 单篇总结
    TOTAL_ERRORS=$((TOTAL_ERRORS + dir_errors))
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + dir_warnings))

    if [ "$dir_errors" -eq 0 ]; then
        echo -e "\n  ${BOLD}${GREEN}✔ 该文章已通过全部质检项，具备交付条件！${NC}"
        return 0
    else
        echo -e "\n  ${BOLD}${RED}✘ 发现 ${dir_errors} 处阻断性错误，请修复后再交付。${NC}"
        return 1
    fi
}

# ------------------------------------------------------------------------------
# 主入口
# ------------------------------------------------------------------------------
main() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --xhs|--redbook)
                XHS_MODE=1
                shift
                ;;
            --wechat|--wx)
                WECHAT_MODE=1
                shift
                ;;
            --covers)
                COVERS_MODE=1
                shift
                ;;
            *)
                break
                ;;
        esac
    done

    local target="${1:-}"

    if [ -z "$target" ]; then
        echo -e "${YELLOW}用法:${NC}"
        echo -e "  $0 <文章目录路径>             (单篇标准检查，自动附带小红书与微信合规提示)"
        echo -e "  $0 --xhs <文章目录路径>       (小红书分发严格模式，外链与敏感词一票阻断)"
        echo -e "  $0 --wechat <文章目录路径>    (微信公域推荐严格模式，导流违规一票阻断)"
        echo -e "  $0 --covers <文章目录路径>    (强制检查双尺寸封面，可与 --xhs/--wechat 组合)"
        echo -e "  $0 --all [父级目录]           (全量扫描，默认 05_待发表)"
        echo -e "  $0 --xhs --all [父级目录]     (小红书严格模式全量扫描)"
        echo -e "  $0 --wechat --all [父级目录]  (微信推荐严格模式全量扫描)"
        exit 1
    fi

    if [ "$target" == "--all" ]; then
        local parent_dir="${2:-05_待发表}"
        if [ ! -d "$parent_dir" ]; then
            echo -e "${RED}[ERROR] 目录不存在: ${parent_dir}${NC}"
            exit 1
        fi

        echo -e "${BOLD}${CYAN}================================================================${NC}"
        echo -e "${BOLD}${CYAN} 开始全量扫描目录: ${parent_dir}${NC}"
        echo -e "${BOLD}${CYAN}================================================================${NC}"

        for sub_dir in "$parent_dir"/*; do
            if [ -d "$sub_dir" ]; then
                check_single_article "$sub_dir" || true
            fi
        done

        echo -e "\n${BOLD}${CYAN}================================================================${NC}"
        echo -e "${BOLD}全量扫描汇总:${NC}"
        echo -e "  总阻断性错误 (Errors):   ${RED}${TOTAL_ERRORS}${NC}"
        echo -e "  总警告/提示 (Warnings): ${YELLOW}${TOTAL_WARNINGS}${NC}"
        echo -e "${BOLD}${CYAN}================================================================${NC}"

        if [ "$TOTAL_ERRORS" -gt 0 ]; then
            exit 1
        else
            exit 0
        fi
    else
        check_single_article "$target"
        exit $?
    fi
}

main "$@"
