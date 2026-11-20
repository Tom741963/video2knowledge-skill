# Video2Knowledge Skill

把视频、字幕和文档转换成带来源定位的结构化知识包，供 AI Agent 后续检索、问答和生成学习资料。

项目包含 GitHub Actions CI，会在 push 和 pull request 时使用 Python 3.10、3.11、3.12 检查工具契约、Skill frontmatter 和测试。

## 当前版本

这是一个可本地运行的 0.2.0 版本：

- 支持 `.txt`、`.md`、`.srt`、`.vtt`、`.csv` 和 `.json`；
- 可选支持 `.pdf`、`.docx`、`.pptx` 和 `.xlsx`；
- 视频文件可以读取媒体信息并抽取关键帧，也可以通过外部转录文本接入完整知识流程；
- 自动生成摘要、关键词、分块内容、时间轴和来源证据；
- Markdown 会按标题拆分章节，并在证据中保留 `section:<标题>` 定位；
- DOCX 会识别 Word 标题样式，并在证据中保留 `section:<标题>` 定位；
- PPTX 会按幻灯片拆分内容，并在证据中保留 `slide:<页码>` 定位；
- CSV 按行保留 `row:<行号>` 定位，XLSX 按工作表和行保留 `sheet:<名称>/row:<行号>` 定位；
- JSON 按嵌套字段保留 `json:<路径>` 定位；
- 提供简单的关键词检索 CLI；
- 不要求云端 API，方便先验证数据流和输出格式。

## 快速开始

```powershell
cd video2knowledge-skill
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

python -m video2knowledge.cli ingest examples\demo.md --output runs\demo
python -m video2knowledge.cli doctor
python -m video2knowledge.cli inspect runs\demo
python -m video2knowledge.cli report runs\demo --output runs\demo\report.md
python -m video2knowledge.cli ask runs\demo "RAG 的主要作用是什么"
```

多个文件可以合并成一个跨来源知识库：

```powershell
python -m video2knowledge.cli ingest-many examples\demo.md examples\another.md --output runs\collection
python -m video2knowledge.cli answer runs\collection "这些资料共同提到了什么？"
```

如果要处理 PDF / DOCX / PPTX / XLSX：

```powershell
pip install -e ".[documents]"
```

如果要在本地对视频做语音转录：

```powershell
pip install -e ".[video]"
python -m video2knowledge.cli ingest demo.mp4 --output runs\demo --transcribe --model-size small --language zh
```

`faster-whisper` 需要本机可用的模型和足够的磁盘/显存；首次运行会下载 Whisper 模型。没有安装时，系统会在 `manifest.json` 中记录 `transcription_unavailable`；如果视频没有音频轨，会记录 `no_audio_track`，不会静默伪造转录结果。

如果视频旁边存在同名的 `.srt` 或 `.vtt` 文件，例如 `lesson.mp4` 和 `lesson.srt`，摄取时会自动读取旁车字幕，并在 manifest 中记录 `subtitle_sidecar`，不需要运行 Whisper。

## 输出结构

```text
runs/demo/
├── manifest.json       # 文件类型、时长、处理状态
├── transcript.md       # 提取或转录后的文本
├── chunks.jsonl        # 可检索分块及来源位置
├── timeline.json       # 章节/时间轴
├── summary.md          # 提取式摘要
├── keywords.json       # 关键词
└── evidence.json       # 结论和来源定位
```

## Agent Skill 用法

把仓库中的 `SKILL.md` 放进目标 Agent 的技能目录，或者将其中的规则合并到已有技能。Skill 负责决定什么时候调用 `ingest` 和 `ask`；解析、分块和证据生成由 Python 包执行。

## Agent 工具契约

仓库根目录的 [tools.json](tools.json) 描述了 Agent 可调用的十个工具：

- `video2knowledge_ingest`：摄取文件并生成知识包；
- `video2knowledge_ingest_many`：把多个文件合并为一个可检索集合；
- `video2knowledge_inspect`：检查模态、索引状态和处理警告；
- `video2knowledge_doctor`：检查本地依赖、二进制和 API 配置；
- `video2knowledge_report`：导出带来源定位的 Markdown 学习报告；
- `video2knowledge_index`：创建或重建本地向量索引；
- `video2knowledge_ask`：只返回检索证据；
- `video2knowledge_answer`：返回带 `citations` 的回答；
- `video2knowledge_describe`：描述已经抽取的关键帧。
- `video2knowledge_evaluate`：回归评估检索覆盖率和引用完整性。

工具契约使用接近 JSON Schema 的结构，包含输入参数、CLI 命令模板和结果字段。接入其他 Agent 框架时，可以把 `input_schema` 映射为函数工具参数，把 `result` 映射为工具返回值。每次回答都应优先保留 `citations.location`、`source` 和 `modality`。

## 设计原则

1. **知识摄取而不是模型训练**：先把资料变成可检索知识。
2. **证据优先**：回答尽量返回页码、时间戳或原文片段。
3. **本地优先**：没有 API Key 也能跑通数据管线。
4. **可扩展**：后续可接 Whisper、视觉模型、Embedding、向量数据库和 Agent 工具调用。

## 当前边界

项目已经覆盖视频、字幕、文本、Markdown、PDF、DOCX、PPTX、CSV、XLSX 和 JSON 的摄取、检索、证据问答、报告生成、评测和 MCP 接入。视频画面描述、语音转录和本地向量检索属于可选能力；未配置对应依赖或 API 时，知识包会明确记录不可用状态，不会伪造内容。

### 关键帧视觉描述

配置 OpenAI 兼容视觉模型后，可以在关键帧抽取时生成描述：

```powershell
$env:VISION_API_KEY = "your-api-key"
python -m video2knowledge.cli ingest demo.mp4 --output runs\demo --describe-frames
```

也可以单独描述已经抽取的图片：

```powershell
python -m video2knowledge.cli describe runs\demo\frames --output runs\demo\frame_descriptions.json
```

视觉模型未配置时，会在 `frame_descriptions.json` 记录 `unavailable`，不会伪造画面内容。

音频转录和关键帧描述会统一进入 `timeline.json`、`source_timeline.json`、`chunks.jsonl` 和 `evidence.json`，并通过 `modality` 区分 `audio`、`vision` 和 `text`。

### 向量检索

安装检索依赖后，`ingest` 会自动构建本地向量索引：

```powershell
pip install -e ".[retrieval]"
python -m video2knowledge.cli ask runs\demo "视频里讲了什么" --mode vector
```

也可以单独重建索引：

```powershell
python -m video2knowledge.cli index runs\demo
```

### 带证据问答

不配置大模型时，项目会返回检索片段整理，并附带来源、位置和模态信息：

```powershell
python -m video2knowledge.cli answer runs\demo "视频主要讲了什么" --mode vector
```

需要同时兼顾语义相似度和专有词命中时，可以使用混合检索：

```powershell
python -m video2knowledge.cli answer runs\demo "视频主要讲了什么" --mode hybrid
```

问答默认使用 `--min-score 0.05` 过滤弱相关检索结果。若没有达到阈值，结果会标记为 `evidence_status: insufficient`，并返回“暂时无法回答”；可以按资料质量调整阈值。

配置 `QA_API_KEY` 后，可以让兼容 Chat Completions 的模型基于检索片段生成自然语言回答：

```powershell
$env:QA_API_KEY = "your-api-key"
python -m video2knowledge.cli answer runs\demo "视频主要讲了什么" --mode vector --llm --output runs\demo\answer.json
```

### MCP Server

需要让支持 MCP 的 Agent 直接调用这些能力时，安装可选依赖并启动 stdio server：

```powershell
pip install -e ".[mcp]"
python -m video2knowledge.mcp_server
```

Server 提供单文件摄取、多文件摄取、证据检索、带引用问答、评测和关键帧描述工具。已有 CLI 和 `tools.json` 不受影响。

### 评测检索和引用

仓库提供了一个最小评测集 `evals/demo_cases.jsonl`，可以检查检索结果是否包含预期关键词，以及回答是否返回来源和位置：

```powershell
python -m video2knowledge.cli evaluate runs\demo evals\demo_cases.jsonl --mode vector --min-score 0 --output runs\demo\evaluation.json
```

评测结果中的 `retrieval_pass_rate` 衡量预期关键词是否出现在检索片段中，`citation_pass_rate` 衡量每个用例是否返回带 `source` 和 `location` 的引用。它们用于回归检查，不等同于人工评估答案质量。
