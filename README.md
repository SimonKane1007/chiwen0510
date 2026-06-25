# chiwen0510

个人分析工具集。

## ETF 多因子分析选股方法

一套系统化、可复用的 ETF 分析选股框架：多因子打分排序 + 组合诊断（仓位/集中度/分散度）+ 每日市场背景更新（风向/政策/美股，先验证后纳入）。

| 文件 | 说明 |
|------|------|
| [`docs/ETF选股方法.md`](docs/ETF选股方法.md) | 方法论：流程、因子体系、市场验证、组合配置、调参与排查 |
| `etf_selection.py` | 主程序：打分排序 + 组合诊断 + 市场简报（终端三段式界面） |
| `data_provider.py` | 量价/估值因子联网抓取层（akshare 优先，东方财富兜底，失败即标记） |
| `market_context.py` | 市场背景更新与真实性验证（白名单+多源交叉+关键词映射） |
| `report_html.py` | 把打分/诊断/简报渲染成手机自适应网页（与终端同源数据） |
| `config.json` | 外置配置：数据源/权重/阈值/硬约束/关键词映射，改这里即可调参 |

```bash
python etf_selection.py                             # 终端三段式界面
python etf_selection.py --html public/index.html    # 生成手机自适应网页
```

可选依赖：`pip install -r requirements.txt`（未安装会自动降级，不影响运行）。

### 在手机上查看

工具内置 GitHub Actions（[`.github/workflows/pages.yml`](.github/workflows/pages.yml)），每天联网重新生成网页并发布到 **GitHub Pages**。手机浏览器收藏下面这个网址即可随时查看，像一个 App：

> **https://chiwen1007.github.io/chiwen0510/**

首次需要两步**一次性设置**：

1. **开启 Pages**：仓库 → **Settings → Pages → Build and deployment → Source** 选 **「GitHub Actions」**。
2. **让每日刷新生效**：GitHub 的定时任务只对**默认分支**上的工作流生效。在功能分支上 `push` 或在 Actions 页面手动「Run workflow」可立即构建出网址先看效果；**要真正每天自动刷新，需把本工作流合并到默认分支（main）**。

> 提示：Actions 运行器有完整外网，发布到 Pages 的页面是**真实联网数据**；本地若无外网，量价因子会显示「⚠待联网」，但版式不受影响。

> ⚠️ 本工具为分析框架/教育用途，输出客观规则信号，**非投资建议**。市场有风险，投资需谨慎。

## 其他

- `personality_model.py` — 文本性格与价值观推理模型。
