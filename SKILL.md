---
name: video2knowledge
description: 将视频、字幕、PDF、DOCX、PPTX、XLSX、CSV、JSON、Markdown 或文本资料转换为可检索的知识包，并用带来源定位的证据回答问题。
---

# Video2Knowledge

当用户要求 AI Agent 学习或分析视频、字幕、PDF、DOCX、PPTX、XLSX、CSV、JSON、Markdown、TXT 等资料时，先把资料转换为知识包，再基于知识包检索和回答。知识包用于资料摄取与问答，不代表对模型进行训练。

## Agent 工作流

1. 识别输入文件类型，并为每个输入选择独立的输出目录，例如 `runs/<文件名>`。
2. 必要时先调用 `doctor`，确认所需的可选依赖和 API 配置可用。
3. 单个文件调用 `ingest`；多个文件调用 `ingest-many`，生成一个跨来源知识包。
4. 调用 `inspect` 或查看 `manifest.json`，确认摄取状态、分块数量和可用模态。
5. 如果向量索引缺失或需要重建，调用 `index`；否则直接使用 `answer`。
6. 需要给用户整理完整学习材料时调用 `report`；需要单个问题回答时调用 `answer`。
7. 回答问题前调用 `answer`，优先使用 `--mode auto`，默认保留 `--min-score 0.05`；当问题包含专有词、时间码或精确术语时可使用 `--mode hybrid`。需要检查原始检索片段时，再调用 `ask`。
8. 从 `answer` 返回的 `citations` 或报告中的来源位置保留证据；没有足够匹配时明确说明资料不足，不要补写资料中没有的结论。

## 按文件类型选择处理方式

- `.txt`：直接摄取文本并引用 `document`。
- `.md`、`.markdown`：按 Markdown 标题拆分章节，优先引用 `section:<标题>`。
- `.srt`、`.vtt`：解析字幕时间段，回答时引用对应时间范围。
- `.pdf`：先安装 `documents` 可选依赖，再摄取；优先引用 `page:<页码>`。
- `.docx`：先安装 `documents` 可选依赖，再摄取；有 Word 标题样式时引用 `section:<标题>`，没有标题时引用 `document`。
- `.pptx`：先安装 `documents` 可选依赖，再摄取；按幻灯片引用 `slide:<页码>`。
- `.csv`：直接摄取并按行引用 `row:<行号>`。
- `.xlsx`：先安装 `documents` 可选依赖，再按工作表和行引用 `sheet:<名称>/row:<行号>`。
- `.json`：直接摄取并按嵌套字段引用 `json:<路径>`。
- `.mp4`、`.mov`、`.mkv`、`.avi`、`.webm`、`.m4v`：摄取时会尝试读取媒体信息并抽取关键帧。
  - 如果视频旁边有同名的 `.srt` 或 `.vtt`，优先自动读取旁车字幕；
  - 需要语音内容时使用 `--transcribe`，并确保已安装 `video` 可选依赖。
  - 需要画面内容时设置视觉模型环境变量并使用 `--describe-frames`。
  - 只有视频元数据或关键帧而没有可用文本时，必须说明当前结论的证据范围。

## 常用命令

在仓库根目录执行：

```powershell
$env:PYTHONPATH="src"

# 文本、字幕、PDF、DOCX 或普通视频摄取
python -m video2knowledge.cli ingest <input> --output <knowledge_dir>

# 视频语音转录
python -m video2knowledge.cli ingest <video> --output <knowledge_dir> --transcribe --language zh

# 视频关键帧视觉描述
$env:VISION_API_KEY = "your-api-key"
python -m video2knowledge.cli ingest <video> --output <knowledge_dir> --describe-frames

# 重建本地向量索引
python -m video2knowledge.cli index <knowledge_dir>

# 查看检索证据
python -m video2knowledge.cli ask <knowledge_dir> "<问题>" --mode auto

# 生成带证据的回答
python -m video2knowledge.cli answer <knowledge_dir> "<问题>" --mode auto --output <answer.json>
```

`ingest` 会自动尝试创建本地 TF-IDF 向量索引；没有安装检索可选依赖时，`answer` 和 `ask` 会回退到关键词检索。`answer --llm` 只在需要自然语言整理且已配置 `QA_API_KEY` 或 `OPENAI_API_KEY` 时使用；模型必须只根据返回的检索片段回答，并保留证据编号。

## 证据引用规则

每个重要结论都要能回到 `citations` 中的条目：

- `location` 为 `page:3`：引用来源文件和第 3 页；
- `location` 为 `00:01:12 --> 00:01:18` 或带 `start_seconds` / `end_seconds`：引用视频时间段；
- `location` 为 `frame:12.5s`：引用视频帧时间点；
- `modality` 为 `audio`、`vision`、`text`：在答案中按需要说明证据来自语音、画面或文字。

不要只引用 `summary.md` 中的摘要而省略原始来源。若 `evidence_status` 为 `insufficient`、`citations` 为空、检索分数低于 `min_score`，或资料状态显示 `no_audio_track`、`transcription_unavailable`、`unavailable`，应回答“当前资料不足以确认”，并指出用户需要补充的资料或回看位置。

## 完整 Agent 示例

用户提供 `lesson.mp4` 并询问“视频中解释了哪三个步骤？”时，Agent 可以按以下顺序执行：

```text
1. 运行：
   python -m video2knowledge.cli ingest lesson.mp4 --output runs/lesson --transcribe --describe-frames

2. 读取 runs/lesson/manifest.json：
   - 确认转录和关键帧描述是否成功；
   - 如果某一模态不可用，只使用成功生成的模态回答。

3. 运行：
   python -m video2knowledge.cli answer runs/lesson "视频中解释了哪三个步骤？" --mode auto

4. 使用返回的 answer 和 citations 组织答案，例如：
   - 步骤一……（lesson.mp4，00:01:12–00:01:18）
   - 步骤二……（lesson.mp4，00:02:04–00:02:16）
   - 步骤三……（lesson.mp4，frame:148.0s）

5. 如果没有能支持“三个步骤”的证据，明确说无法从当前资料确认，不要根据常识补全。
```

对文档资料使用相同流程，只需把视频位置替换为页码或文档位置。回答应区分资料原文、基于多个片段的归纳和不确定推断；对低置信度结论建议用户回看对应原始资料。

## Agent 工具契约

仓库根目录的 [tools.json](tools.json) 是工具调用契约。需要接入函数调用或其他 Agent 框架时，先读取其中对应工具的 `input_schema` 和 `result`：

- 摄取资料使用 `video2knowledge_ingest`；
- 多个资料合并摄取使用 `video2knowledge_ingest_many`；
- 检查知识包状态使用 `video2knowledge_inspect`；
- 检查运行环境使用 `video2knowledge_doctor`；
- 导出学习报告使用 `video2knowledge_report`；
- 需要重建索引使用 `video2knowledge_index`；
- 只检查证据使用 `video2knowledge_ask`；
- 需要回答并引用来源使用 `video2knowledge_answer`；
- 需要补充关键帧画面描述使用 `video2knowledge_describe`。
- 需要回归检查检索和引用使用 `video2knowledge_evaluate`。

工具返回的 `citations` 是回答的证据边界。不要把 `matches` 中没有对应来源定位的内容扩展成确定性结论。

如果目标 Agent 支持 MCP，可以安装 `.[mcp]` 并启动 `python -m video2knowledge.mcp_server`，直接使用同一套摄取、检索、问答、评测和关键帧描述能力。MCP 调用仍需遵守本文件中的证据门槛和引用规则。

仓库中的 `evals/demo_cases.jsonl` 可作为最小回归集。评测通过表示预期关键词被检索到且返回了来源定位；它不能替代对答案事实性的人工复核。

