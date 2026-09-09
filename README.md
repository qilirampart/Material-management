# 抖音素材下载与片头文字/logo检测

优化工作跟踪：[软件优化任务板](docs/优化任务板.md)。

导入需求方 Excel，下载抖音视频，抽取 0、1、2 秒三帧（含解码首帧），使用现有 `qwen3-vl-flash` 图片模型检测，并导出带证据的结果表。已提供原生 Windows 桌面界面，命令行入口仍保留，不执行内部平台上传。

桌面入口：`release/素材投放助手/素材投放助手.exe`，或源码目录双击 `启动素材投放助手.bat`。安装及使用见 [桌面软件使用说明](docs/桌面软件使用说明.md)。

## 已验证结果

2026-09-05：需求表共 200 条有效记录。已实际处理前 3 条，下载、完整解码、音轨检查、三帧提取、模型识别与 Excel 导出均完成，三条均为“片头抽检未发现”；其余 197 条为待处理，尚未执行全量。

- 样本视频：`output/pilot/videos/`。
- 样本证据：`output/pilot/frames/`。
- 结果表：`output/pilot/检测结果.xlsx`（包含全部输入行，未执行行明确标注待处理）。
- 完整结果及模型响应：`output/pilot/results.json`。
- 模型专项验证：`output/model_acceptance/`，三种指定文字阳性、logo 阳性和无命中阴性均通过。
- 本地行为验证：`python -m unittest discover -s tests -v`，18 项通过；`python scripts/smoke_desktop.py` 已验证真实Qt控件、视频播放、200行批次、备注导出与后台暂停。另覆盖跨盘保存，避免更换保存目录后下载失败。

专项 logo 测试使用用户提供的清晰原图，不代表已经验证所有小尺寸、透明、遮挡或变形水印的识别率。结果属于片头抽检，不代表全片合格。

## 当前规则

- 文字：`0元免费看`、`免费观看`、`免费看`、`一分钱不花`，另覆盖 `0元观看`。忽略空白换行、兼容常见繁体字。
- 图标：红果 logo，参考原图保存在 `assets/references/hongguo_logo.png`。模型只比对图片上部的图标，忽略下部截图说明；参考图片自身不算命中。
- 任一帧命中即“命中拦截”；缺帧、模糊、模型失败或响应不完整则“待复核”。
- 三帧无命中且判断完整才是“片头抽检未发现”；无音轨的视频仍进入待复核。
- “免费停车”“点击下方链接观看全集”等不在已确认的禁用表达中，目前不会仅因这些文字被拦截。
- 命中视频仍保留本地文件，不删除或自动剪辑。所有记录均为“未上传”。

## 环境与模型

已在 Python 3.9、FFmpeg 8.0.1、requests 2.32.5、openpyxl 3.1.2、PySide6 6.9.3 下验证。FFmpeg/ffprobe 需要在 PATH 中。图片模型验收脚本额外使用 Pillow（当前环境已有）。

```powershell
python -m pip install -r requirements.txt
python -m src.cli inspect --input "懂小剧素材_婚房门后的秘密.xlsx"
```

默认读取 `config.example.json`。模型配置从用户指定的 YouTube 项目 `runtime/api_config.json` 中只读选择第一个启用且完整的 `llm.profiles`；也可设置 `model_profile_id` 指定配置。当前使用 `qwen3-vl-flash`。密钥只在内存中读取并发给配置的模型端点，不复制到本项目。

下载采用侵权巡检助手的分享页解析、备用解析服务和 PySide6 WebEngine 浏览器兜底逻辑。必要源码迁移到 `src/vendor/`，调用适配见 `src/download_support.py`。解析配置也只读引用原项目。不会写入两个参考项目。

换电脑时将配置路径改成可访问的位置；自定义设置可保存为 `config.local.json`，并使用 `--config config.local.json`。该文件已排除版本管理。

## 运行

先验证前三条（已存在批次使用恢复参数）：

```powershell
python -m src.cli run --input "懂小剧素材_婚房门后的秘密.xlsx" --limit 3 --output output/pilot --resume
```

继续同一批次的全部 200 条，复用前三条结果：

```powershell
python -m src.cli run --input "懂小剧素材_婚房门后的秘密.xlsx" --output output/pilot --resume
```

只下载（不调用图片模型，结果标记为未检测）：

```powershell
python -m src.cli run --input "懂小剧素材_婚房门后的秘密.xlsx" --output output/download_only --download-only
```

Excel 被打开占用时，JSON 仍保存进度。关闭结果表后重新导出：

```powershell
python -m src.cli export --output output/pilot
```

Ctrl+C 停止后用相同输入、输出及 `--resume` 继续。已完成视频重新检查完整解码；损坏文件改名保留后重新下载。恢复时同时核对输入、视频哈希、证据帧哈希及规则/模型指纹，规则更新自动重检。`--limit 3` 始终限定输入中的前三个唯一视频，并非每次增加三条。

## 验证命令

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src
python scripts/check_model.py
```

最后一条会联网调用配置的图片模型，并生成固定文字和 logo 验收样本。普通本地单元测试不联网。

## 目录

- `src/batch.py`：表格导入、批次恢复、状态和结果导出。
- `src/media.py`：视频校验和带实际时间的首帧/后续帧提取。
- `src/vision.py`：模型配置、参考图比对、文字规则和严格结果校验。
- `src/vendor/`：参考下载代码；迁移来源见 `docs/下载源码迁移记录.md`。
- `assets/references/`：用户提供的红果 logo 原图。
- `docs/抖音素材下载与片头文字检测规格.md`：业务规格。

下一阶段需对齐内部平台的剧目映射、认证、上传格式及去重；不能把本期“片头抽检未发现”直接等同于全片审核通过。
