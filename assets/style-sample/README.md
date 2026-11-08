# 封面画风样板

[hawthorne-master.png](hawthorne-master.png) 是所有封面母稿的画风参考，1024 × 1024。它是作者为一篇关于霍桑的长文用 AI 生成的原创插画。

画风要点：细铅笔轮廓，密集彩铅排线，低饱和色，自然光，环境细节丰富，人物比例自然、五官简洁。

`generate_covers.py --prepare` 会把这张图的路径写进提示词。生图时要把图片文件本身传给工具，只借画法，不照搬里面的人物、小船和河湾。

想用自己的画风：准备一张样板图，设置环境变量 `ZH_LONGFORM_STYLE_SAMPLE=/path/to/your-sample.png`，再同步修改 `rules/平台与封面.md` 第五节第 2 小节的画风描述。
