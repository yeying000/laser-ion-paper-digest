# 激光离子加速每日论文进展

这个项目每天自动检索与激光离子加速相关的论文，覆盖 arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC，以及按 ISSN 定向扫描的重点期刊 watchlist，做跨源去重、关键词相关性排序，并生成中文 Markdown 日报。配置 `OPENAI_API_KEY` 后会调用 OpenAI 生成结构化摘要；未配置时会使用保守的本地摘要，不会编造摘要中没有的参数。

## 功能

- 从 arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC 抓取最近论文和更新
- 按 ISSN 定向扫描 APS、Nature、AIP/Physics of Plasmas、IOP、Cambridge、Elsevier、Wiley、Optica 等重点期刊
- 用关键词、学科分类和排除词进行相关性过滤
- SQLite 保存论文和摘要，避免重复处理
- 生成 `reports/YYYY/YYYY-MM-DD.md` 日报
- GitHub Actions 每天自动运行，也支持手动触发

## 本地运行

```bash
python -m pip install -e .
paper-digest --no-openai
```

如果你想调用 OpenAI 生成更高质量的结构化摘要：

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-5.5"
paper-digest
```

可选地设置数据源联系信息和 API key，以获得更稳定的限流额度：

```bash
export CONTACT_EMAIL="your.email@example.com"
export OPENALEX_API_KEY="..."
export S2_API_KEY="..."
```

调试时可以只打印报告，不写入文件：

```bash
paper-digest --no-openai --dry-run --max-papers 5
```

如果只是做本地 smoke test，也可以临时跳过多关键词请求之间的等待：

```bash
paper-digest --no-openai --dry-run --max-papers 5 --lookback-days 90 --pause-seconds 0
```

## GitHub 自动化

1. 创建一个新的 GitHub 仓库，并把本项目推送上去。
2. 在仓库的 `Settings -> Secrets and variables -> Actions` 中添加：
   - `OPENAI_API_KEY`：可选；不配置也能生成保守摘要
   - `OPENAI_MODEL`：可选变量，默认 `gpt-5.5`
3. `.github/workflows/daily.yml` 已配置每日 `00:30 UTC` 运行，即北京时间 `08:30`。
4. 也可以在 GitHub Actions 页面点击 `Run workflow` 手动运行。

## 调整检索范围

编辑 `configs/queries.json`：

- `queries`：检索词
- `sources.enabled`：启用的数据源，当前支持 `arxiv`、`openalex`、`crossref`、`semantic_scholar`、`europe_pmc`、`journal_watchlist`
- `sources.external_queries`：OpenAlex、Crossref、Semantic Scholar、Europe PMC 使用的通用检索词
- `sources.journal_watchlist.journals`：重点期刊列表，按 ISSN 从 Crossref 定向抓取近期文章，再交给相关性排序过滤
- `sources.journal_watchlist.max_results_per_journal`：每本期刊每天最多取回的近期论文数
- `sources.request_pause_seconds`：外部数据源请求之间的等待时间
- `arxiv.categories`：arXiv 分类
- `arxiv.lookback_days`：回看天数；命令行 `--lookback-days` 会覆盖所有数据源
- `ranking.strong_terms`：强相关词
- `ranking.support_terms`：辅助相关词
- `ranking.exclude_terms`：排除无关方向
- `ranking.minimum_score`：入选阈值

建议先运行几天，人工抽查漏报和误报，再微调关键词。激光离子加速这个方向术语密集，关键词质量比模型本身更决定日报质量。

当前 watchlist 已覆盖几类重点来源：

- 综合高影响力期刊：Science、Science Advances、PNAS
- Nature 系列：Nature、Nature Physics、Nature Photonics、Nature Communications、Communications Physics、Scientific Reports、Nature Reviews Physics、Nature Materials、Nature Nanotechnology、Nature Electronics、Nature Reviews Materials、Communications Materials、npj Materials Degradation 等
- APS 系列：Physical Review Letters、Reviews of Modern Physics、Physical Review X、Physical Review Research、Physical Review E、Physical Review Accelerators and Beams 等
- AIP 系列：Physics of Plasmas、Physics of Fluids、Review of Scientific Instruments、Applied Physics Letters、Journal of Applied Physics、AIP Advances、Applied Physics Reviews、APL Photonics
- 等离子体和强场激光核心期刊：Plasma Physics and Controlled Fusion、Nuclear Fusion、Plasma Sources Science and Technology、Journal of Plasma Physics、High Energy Density Physics、Matter and Radiation at Extremes、High Power Laser Science and Engineering、Laser and Particle Beams
- 材料与器件辐照交叉：IEEE Transactions on Nuclear Science、IEEE Transactions on Device and Materials Reliability、IEEE Transactions on Electron Devices、IEEE Electron Device Letters、IEEE Journal of the Electron Devices Society、IEEE Transactions on Semiconductor Manufacturing、IEEE Transactions on Radiation and Plasma Medical Sciences、IEEE Transactions on Reliability
- 其他交叉方向：Nuclear Instruments and Methods in Physics Research A、Physics in Medicine & Biology、Medical Physics、Optica、Optics Express、Optics Letters、Light: Science & Applications、Laser & Photonics Reviews

## 报告字段

每篇论文会尽量整理：

- 一句话结论
- 加速机制
- 研究类型
- 激光参数
- 靶材
- 离子种类
- 最高能量或关键结果
- 主要贡献
- 局限或注意点
- 为什么重要

如果摘要中没有对应信息，报告会写“摘要中未明确说明”。

## 注意事项

- 各论文数据源通常按日更新，不需要高频请求。
- 连续检索多个关键词时，外部数据源默认每次请求间隔 2 秒，arXiv 默认 3 秒；遇到 429/5xx 会自动短暂重试，单个查询失败不会中断整个日报。
- 当前版本只解析标题、摘要和元数据；如果要做全文级总结，可以后续增加 PDF 下载与解析模块。
