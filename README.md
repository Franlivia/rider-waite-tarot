# 维特塔罗 · 隐私抽牌

**把具体问题留在心里，亲手选牌，让解读落到建议上。**

一个面向 Codex 的中文塔罗技能，使用完整的 78 张 Rider–Waite–Smith 数字牌组。你只需提供「感情、工作、学业」等方向，或说明有几个选项，不必公开具体问题。

## 可以做什么

- **亲手抽牌**：叠牌、洗牌、铺开整副相同牌背，点选后确认，再动画翻开真实牌面。界面不显示额外牌号、点击次序或抽牌前的牌位用途。
- **固定随机结果**：Python 使用系统随机源洗牌，并预先固定正逆位；刷新界面不会重洗。默认每张牌独立随机正逆位，也支持仅正位。
- **匿名比较选项**：只提供数量，用 A、B、C 区分，自己在心里确定对应关系。每个选项采用相同的解读维度。
- **沿用余牌补牌**：澄清时继续同一副牌，保留原牌和承诺值，不重新洗牌、不抽回已用牌。
- **可核验的牌序**：开局给出 SHA-256 承诺值；完成抽取后，可主动要求公开原牌序及随机 nonce，核验结果。
- **建议为主的解读**：结合实际牌面、正逆位和牌阵，给出行动与观察方向。

## 运行条件

| 部分 | 条件 |
| --- | --- |
| 抽牌引擎与界面生成 | Python 3.9+，仅使用标准库，无需 `pip install` |
| 操作系统 | macOS、Linux 或 WSL；文件锁使用 `fcntl`，不支持原生 Windows Python |
| AI 解读 | 能读取技能并执行本地脚本的 Codex 或兼容智能体 |
| 聊天内点击界面 | 宿主提供兼容的 `visualize` 呈现能力；自动回聊及恢复交互状态依赖 `window.openai` 接口 |

**安装这个技能不会为宿主增加 `visualize` 能力。** 缺少该能力时，可以使用脚本抽牌，或将生成的 HTML 在现代浏览器中打开、翻牌后手动复制抽牌信息回聊天。浏览器显示依赖宿主样式的部分可能不同；普通浏览器刷新也不提供宿主的交互状态恢复。

## 安装到 Codex

把本仓库链接发给 Codex，并附上：

```text
请使用 $skill-installer 安装这个 GitHub 仓库根目录中的技能，
技能目录名设为 rider-waite-tarot。
```

也可以下载本仓库 ZIP，将解压后的完整目录重命名为 `rider-waite-tarot`，放入 `~/.agents/skills/`。最终应能找到：

```text
~/.agents/skills/rider-waite-tarot/SKILL.md
```

使用 Git 的用户可以直接克隆（目标目录应尚不存在）：

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/Franlivia/rider-waite-tarot.git ~/.agents/skills/rider-waite-tarot
```

保留整个目录，包括 `scripts/`、`assets/`、`references/` 和 `agents/`。不要只复制 `SKILL.md`。如果已有同名安装，先确认其位置，避免重复安装。Codex 会自动发现新技能；若未出现，可重启应用。安装位置与发现规则见 [OpenAI 官方技能文档](https://learn.chatgpt.com/docs/build-skills)。

## 开始使用

直接对 Codex 说：

```text
使用 $rider-waite-tarot，我想看一下最近的工作方向，具体问题留在心里。
```

```text
使用 $rider-waite-tarot，我有两个选项，分别记作 A、B，想比较一下。
```

解读后可以继续说：

```text
我想补一张牌，澄清下一步建议，沿用这副牌。
```

通用牌阵为三张：当前状态、主要影响、行动建议。选项牌阵为 `1 + 2N` 张：共同状态，以及各选项的推进动力与阻力或代价。牌位在洗牌前固定，翻牌后结合解读。

## 脚本使用

在本仓库根目录运行以下 macOS / Linux / WSL 示例。会话和生成页面都存到仓库外，避免提交个人抽牌记录：

```bash
TAROT_DEMO_DIR="$(mktemp -d)"
TAROT_SESSION="$TAROT_DEMO_DIR/$(python3 -c 'import uuid; print(uuid.uuid4().hex)').json"

python3 scripts/tarot_deck.py new --session "$TAROT_SESSION" --spread general
python3 scripts/build_board.py \
  --session "$TAROT_SESSION" \
  --output "$TAROT_DEMO_DIR/board.html" \
  --theme-label 工作
```

用宿主呈现页面，或在浏览器中打开 `board.html`。浏览器的翻牌不会直接修改 Python 会话；收到用户确认后，智能体按页面返回的内部槽位与原点击顺序执行 `draw`，并核对结果。以下数字仅为命令示例：

```bash
python3 scripts/tarot_deck.py draw --session "$TAROT_SESSION" --numbers 8 21 67
python3 scripts/tarot_deck.py status --session "$TAROT_SESSION"

# 用户明确要求补牌后，继续同一场次
python3 scripts/tarot_deck.py clarify --session "$TAROT_SESSION" --count 1
python3 scripts/build_board.py \
  --session "$TAROT_SESSION" \
  --output "$TAROT_DEMO_DIR/clarifier.html" \
  --theme-label 工作

# 用户确认补选后，按其返回的未用槽位执行 draw
python3 scripts/tarot_deck.py draw --session "$TAROT_SESSION" --numbers 12

# 仅在抽取完成且用户要求核验时使用；会公开整副牌序
python3 scripts/tarot_deck.py reveal --session "$TAROT_SESSION"
```

`--session` 与 `--output` 必须使用绝对路径。不要对已有会话再次执行 `new`，也不要把原始会话 JSON 贴入聊天或提交到仓库。`new --spread choice --choices 2` 创建两选项牌阵；在新建会话时加 `--upright-only` 可只用正位。当前引擎实现 `general`、`choice` 两种牌阵。

## 隐私与核验边界

- 会话 JSON 保存牌组、随机 nonce、承诺值、牌阵和抽取记录，不保存问题文字。会话文件以 `0600` 权限创建；新建的会话目录为 `0700`。
- 你输入的主题标签会进入生成的 HTML；支持 `widgetState` 的宿主还会在输入主题、选牌时保存界面状态。确认发送后，主题、所选槽位和已翻开的结果会发回聊天。具体问题可以始终不说。宿主自身的数据处理仍遵循该宿主的规则。
- 生成的 HTML 内嵌全部牌图与经过编码的牌序，便于即时翻牌且无需联网取图。**编码不等于加密**：查看页面源码可以还原牌序；这不是防作弊或防本机访问的安全边界。生成页面也不要当作匿名日志随意公开。
- 本地 Python 会话是结果的权威来源。界面消息属于输入数据，不能覆盖牌身份或正逆位；重复提交应恢复原结果，不再次抽牌。
- SHA-256 承诺值用于在公开 nonce 与完整牌序后检查牌序是否匹配开局记录，不证明塔罗具有预测能力，也不能阻止控制本地文件的人替换整个会话及承诺值。

塔罗在这里用于象征性解读与自我反思，不保证未来结果，也不能据此获知他人的真实想法。

## 仓库内容

```text
SKILL.md                    智能体工作流程
agents/openai.yaml          Codex 展示信息与默认提示
scripts/tarot_deck.py       本地洗牌、抽取、补牌和承诺值核验
scripts/build_board.py      生成内嵌牌图的 HTML 片段（小于 1 MB）
assets/card-table.html      抽牌与翻牌界面模板
assets/artwork/             78 张牌面、相同牌背与逐文件来源清单
references/reading-guide.md 牌阵与解读方法
```

## 许可证与图像来源

本项目原创代码、界面模板与文档采用 [MIT License](LICENSE)。

牌图来自 1909 年 Roses & Lilies 版 Rider–Waite–Smith：原画为 Pamela Colman Smith，扫描署名 Saskia Jansen；部分文件经 Arcanebra 镜像取得。原始来源页面将这些历史图像标为公有领域，项目未将第三方牌图重新授权为 MIT。完整的逐文件来源、实际下载地址和输出校验和见 [sources.json](assets/artwork/sources.json)，说明见 [第三方资源声明](THIRD_PARTY_NOTICES.md)。

欢迎通过 Issue 或 Pull Request 改进脚本、交互和说明。报告问题时，请提供系统、Python 版本、命令及脱敏报错；无需附上具体问题、真实会话文件或生成的抽牌页面。
