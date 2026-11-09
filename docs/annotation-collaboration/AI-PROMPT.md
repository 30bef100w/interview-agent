# 给协作AI的自助下载与连续标注指令

以下整段复制给华为云码道等能访问网络、读写文件并运行Python的AI。只需把第一行的M01换成分配编号；仓库、题库地址和执行方法已包含在提示词里。M01–M07各5,000题，M08为1,033题。不要给不同协作者分配重叠宏批次。

```text
本次分配给你的是深问题库宏批次 M01，请自行拉取仓库和题库，连续完成这个宏批次的5,000条逐题语义初标。若分配M08则为1,033条。不要只输出计划或示例，不要每100题停下来询问是否继续。

【地址】
仓库：https://github.com/30bef100w/interview-agent
代码分支：main
完整题库包：https://github.com/30bef100w/interview-agent/raw/refs/heads/main/docs/annotation-collaboration/interview-agent-annotation-remaining-36033.zip
执行规则：https://github.com/30bef100w/interview-agent/blob/main/skills/annotate-interview-questions/SKILL.md
宏批范围：https://github.com/30bef100w/interview-agent/blob/main/docs/annotation-collaboration/macro-plan.json

【1. 自行取得文件】
在可写工作目录执行：
git clone --depth 1 --branch main https://github.com/30bef100w/interview-agent.git
cd interview-agent

克隆后题库ZIP已经位于docs/annotation-collaboration/，不需要另找我要数据。如果已有此仓库，检查工作区后使用现有副本；正常拉取main更新，保留已有标注，禁止reset或覆盖未提交改动。如果缺少ZIP，可以从上述完整题库地址下载到同名位置。

选择Python 3.10以上可用解释器，下文以python3为例。从仓库根目录执行下面的Python脚本，先验哈希再解压。若已有解压目录，保留原目录，运行后续inspect校验；不要覆盖已完成结果或已更新场景。

python3 - <<'PY'
from pathlib import Path
import hashlib, zipfile
p = Path('docs/annotation-collaboration/interview-agent-annotation-remaining-36033.zip')
expected = '249a442be03af796b720588345cd3a612b53ffc09d593c2ef3f565c42ff0e120'
if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
    raise SystemExit('数据包哈希不符，请重新下载，不要修改校验值')
root = Path('data/annotation_collaboration/2026-11-06-remaining-36033')
if not root.exists():
    with zipfile.ZipFile(p) as z:
        z.extractall('.')
print('数据目录：', root.resolve())
PY

【2. 读取规则和任务范围】
读取以下仓库文件，不依赖AI软件是否识别skill安装机制，直接遵守文件内容：
- skills/annotate-interview-questions/SKILL.md
- skills/annotate-interview-questions/references/collaboration.md
- skills/annotate-interview-questions/references/annotation-contract.md
- skills/annotate-interview-questions/references/scene-labeling.md
- skills/annotate-interview-questions/references/semantic-examples.md
- docs/annotation-collaboration/macro-plan.json

读取macro-plan.json中本次宏批次的task_ids。例如M01覆盖B0001–B0050。内部100题分片是存储和校验单元，不是需要人再次确认的任务边界。不要改动原plan.json、task.json、源数据或共享知识索引。

先运行，后续按本次分配编号替换M01：
python3 skills/annotate-interview-questions/scripts/macro_progress.py --macro M01 --stage initial

从next_task定位的任务开始，完成部分已有输出优先，已通过相同阶段完整校验的单元可以跳过。若文件缺失或输入哈希不符先恢复匹配文件，不能删除检查或修改哈希蒙混过关。

【3. 连续逐题初标】
对task_ids按顺序自动循环执行：
- 运行check_collaboration.py inspect --task <本单元目录>/task.json。
- 读取本单元source.jsonl、场景MD/注册表，以及共享catalog/concept-registry.json。每次展示并实际阅读25–50题，必要时缩小，读取截断必须补读。
- 每道题都由你做语义判断。脚本只负责读写、查索引和校验，禁止关键词批量生成标签、照抄底稿或补全空壳记录。
- 先查知识索引的中文定义、父级、同层、别名及本宏批之前的提案；已有概念复用同一ID，tests与requires分别判断。允许题目挂非叶节点，不机械补全祖先。
- 按业务场景定义判断：同一项目不按订单、日志等模块拆场景；黑马点评归本地生活，苍穹外卖归外卖；无场景依据就留空。
- 新知识点按协议写本单元node_proposals.jsonl；新增场景需去重、中文介绍及适用/排除范围，并同步本单元场景MD和JSON版本。跨单元先查已产生的提案，防止同义重复；本批引用仍须有本批真实证据。
- 能确定到宽知识点就正常标宽主题。确实缺失必要对象且查原答案、准确上下文仍不可恢复时才needs_context，不臆造项目、企业或技术。
- 按源顺序把实际判断结果写入本单元annotations.jsonl。review_stage=initial，不冒充二次复核。短中文理由和真实原文引用即可，无需输出逐题长篇推理。

每完成一个100题单元执行（<单元目录>替换为实际路径）：
python3 skills/annotate-interview-questions/scripts/check_collaboration.py manifest --task <单元目录>/task.json --annotations <单元目录>/annotations.jsonl --out <单元目录>/manifest.initial.json
python3 skills/annotate-interview-questions/scripts/check_collaboration.py check --task <单元目录>/task.json --annotations <单元目录>/annotations.jsonl --manifest <单元目录>/manifest.initial.json --out <单元目录>/validation.initial.json

存在node_proposals.jsonl时，上述两条都加--proposals <单元目录>/node_proposals.jsonl。失败先修正；最终校验不得使用--allow-partial。

然后更新进度并自动继续下一个单元：
python3 skills/annotate-interview-questions/scripts/macro_progress.py --macro M01 --stage initial --out data/annotation_collaboration/2026-11-06-remaining-36033/macro-progress/M01.initial.json

持续执行到本宏批所有单元完成。不要把脚本校验通过说成语义复核通过。需要复核时另按skills/review-interview-annotations/SKILL.md执行，使用--stage reviewed跟踪独立复核进度。

【4. 中断和交付】
每完成25–50题就保存文件，每100题校验，进度不只放在聊天记忆里。若平台有上下文、工具或回合硬限制，在触限前保存实际完成前缀、当前任务、已用/新增索引提案位置和待解决事项，并给出同宏批恢复命令；不要伪报5,000条完成，也不要声称能绕过平台硬限制。普通内部单元结束不构成停止理由。

宏批完成后报告计划数、实际初标数、labeled/needs_context/not_question数、新节点/场景提案数、校验通过数和实际复核数（未复核就为0）。将本宏批task_ids对应的各任务目录（含源题、输出、提案和本批场景库）与宏进度文件打包为annotation-M01-results.zip，保留原始输入便于复核，提供本机完整路径交付；不要混入其他人的输出或宣称已生成生产图。
```

如平台中断，下一回合只需发送：

```text
继续宏批次M01。读取docs/annotation-collaboration/AI-PROMPT.md和标注skill，先运行macro_progress.py --macro M01 --stage initial，从next_task按真实文件续做，不重跑已完成单元，也不要每100题停下来询问继续。
```
