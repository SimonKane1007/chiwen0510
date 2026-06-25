"""
report_html.py —— 把 ETF 打分 / 组合诊断 / 市场简报渲染成手机自适应网页

与终端三段式界面**同源数据**，只换一种载体：
  ① ETF 多因子打分排序   ② 当前组合诊断   ③ 市场背景简报

设计要点：
  - 自包含：内联 CSS，零外部请求 / CDN，断网也能本地打开；
  - 移动优先：viewport 自适应，打分用卡片堆叠而非宽表格，窄屏不溢出；
  - 深色模式：跟随系统 prefers-color-scheme；
  - 所有外部文本（新闻标题等）一律 HTML 转义，避免破坏页面。

⚠️ 与终端输出一致：内容为客观规则信号 / 教育性框架，非投资建议。
"""

from __future__ import annotations

from html import escape
from typing import List

# 仅用于类型提示；避免与 etf_selection 形成强耦合的循环导入
try:  # pragma: no cover - 类型提示用
    from etf_selection import ETFScore, Holding, PortfolioDiagnosis
    from market_context import MarketContext
except Exception:  # pragma: no cover
    ETFScore = Holding = PortfolioDiagnosis = MarketContext = object  # type: ignore


# ─────────────────────────────────────────────
# 小工具
# ─────────────────────────────────────────────
def _rating_class(rating: str) -> str:
    return {"强": "r-strong", "中": "r-mid", "弱": "r-weak"}.get(rating, "r-na")


def _completeness_flag(completeness: float) -> str:
    if completeness == 0:
        return "⚠数据待联网"
    if completeness < 0.5:
        return "⚠部分缺失"
    return ""


# ─────────────────────────────────────────────
# 各区块
# ─────────────────────────────────────────────
def _score_cards(scores: List["ETFScore"]) -> str:
    cards = []
    for i, s in enumerate(scores, 1):
        flag = _completeness_flag(s.completeness)
        flag_html = f'<span class="flag">{escape(flag)}</span>' if flag else ""
        cards.append(f"""
      <div class="card score">
        <div class="rank">{i}</div>
        <div class="info">
          <div class="name">{escape(s.name)} <span class="code">{escape(s.code)}</span></div>
          <div class="meta">{escape(s.category)}{flag_html}</div>
          <div class="bar"><span style="width:{max(0, min(100, s.completeness * 100)):.0f}%"></span></div>
          <div class="bar-label">数据完整度 {s.completeness:.0%}</div>
        </div>
        <div class="verdict">
          <div class="composite">{s.composite:.1f}</div>
          <div class="rating {_rating_class(s.rating)}">{escape(s.rating)}</div>
        </div>
      </div>""")
    return "\n".join(cards)


def _diag_block(d: "PortfolioDiagnosis", holdings: List["Holding"]) -> str:
    stats = [
        ("总资产", f"¥{d.total_assets:,.0f}"),
        ("仓位", f"{d.position:.1%}"),
        ("现金比例", f"{d.cash_ratio:.1%}"),
        ("集中度 HHI", f"{d.hhi:.3f}"),
        ("单票最大", f"{escape(d.max_weight_name)} {d.max_weight:.0%}"),
        ("现金", f"¥{d.cash:,.0f}"),
    ]
    stat_html = "\n".join(
        f'<div class="stat"><div class="k">{escape(k)}</div><div class="v">{v}</div></div>'
        for k, v in stats
    )

    sectors = "".join(
        f'<div class="sector"><span class="s-name">{escape(k)}</span>'
        f'<span class="s-bar"><span style="width:{max(0, min(100, v * 100)):.0f}%"></span></span>'
        f'<span class="s-pct">{v:.0%}</span></div>'
        for k, v in d.sector_exposure.items()
    )

    rows = "".join(
        f'<div class="hold"><span class="h-name">{escape(h.name)}</span>'
        f'<span class="h-val">¥{h.market_value:,.0f}</span>'
        f'<span class="h-pnl {"up" if h.pnl_pct >= 0 else "down"}">{h.pnl_pct:+.2f}%</span></div>'
        for h in holdings
    )

    alerts = "".join(f"<li>{escape(a)}</li>" for a in d.alerts)
    rebal = "".join(f"<li>{escape(r)}</li>" for r in d.rebalance)
    alerts_html = f'<div class="alerts"><h3>⚠ 触发的风险提示</h3><ul>{alerts}</ul></div>' if alerts else ""
    rebal_html = (
        f'<div class="rebal"><h3>↻ 再平衡方向（客观信号，非买卖建议）</h3><ul>{rebal}</ul></div>'
        if rebal else ""
    )

    return f"""
      <div class="stats">{stat_html}</div>
      <div class="holds">{rows}</div>
      <div class="sectors"><h3>板块暴露</h3>{sectors}</div>
      {alerts_html}
      {rebal_html}"""


def _market_block(ctx: "MarketContext") -> str:
    briefing = escape(ctx.briefing).replace("\n", "<br>")
    return f"""
      <div class="market-meta">更新于 {escape(ctx.updated_at)} ｜ 来源：{escape(ctx.freshness)} ｜ 整体情绪：<b>{escape(ctx.overall_risk_mood)}</b></div>
      <div class="briefing">{briefing}</div>"""


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────
def render(scores, diag, holdings, cash, ctx, cfg, generated_at: str) -> str:
    """渲染完整 HTML 页面字符串（自包含、移动端自适应）。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ETF 多因子选股与组合诊断</title>
<style>
:root {{
  --bg:#f4f5f7; --card:#ffffff; --fg:#1c1e21; --sub:#6b7280; --line:#e5e7eb;
  --accent:#2563eb; --green:#16a34a; --amber:#d97706; --red:#dc2626; --gray:#9ca3af;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg:#0f1115; --card:#1a1d23; --fg:#e7e9ee; --sub:#9aa1ad; --line:#2a2e37;
    --accent:#60a5fa; --green:#4ade80; --amber:#fbbf24; --red:#f87171; --gray:#6b7280;
  }}
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--bg); color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",
    "Helvetica Neue",Arial,"Noto Sans CJK SC",sans-serif;
  line-height:1.5; -webkit-text-size-adjust:100%;
}}
.wrap {{ max-width:680px; margin:0 auto; padding:16px 14px 40px; }}
header {{ text-align:center; padding:8px 0 14px; }}
header h1 {{ font-size:19px; margin:0 0 6px; }}
header .gen {{ color:var(--sub); font-size:12px; }}
.mood {{ display:inline-block; margin-top:8px; padding:3px 12px; border-radius:999px;
  background:var(--card); border:1px solid var(--line); font-size:13px; }}
section {{ margin-top:22px; }}
section > h2 {{ font-size:15px; margin:0 0 10px; padding-left:10px;
  border-left:3px solid var(--accent); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:12px 14px; margin-bottom:10px; }}
/* 打分卡片 */
.score {{ display:flex; align-items:center; gap:12px; }}
.score .rank {{ flex:0 0 28px; width:28px; height:28px; border-radius:8px;
  background:var(--bg); display:flex; align-items:center; justify-content:center;
  font-weight:700; font-size:14px; color:var(--sub); }}
.score .info {{ flex:1 1 auto; min-width:0; }}
.score .name {{ font-weight:600; font-size:15px; }}
.score .name .code {{ color:var(--sub); font-weight:400; font-size:12px; }}
.score .meta {{ color:var(--sub); font-size:12px; margin:2px 0 6px; }}
.score .flag {{ color:var(--amber); margin-left:8px; }}
.bar {{ height:5px; background:var(--bg); border-radius:99px; overflow:hidden; }}
.bar > span {{ display:block; height:100%; background:var(--accent); }}
.bar-label {{ color:var(--sub); font-size:11px; margin-top:3px; }}
.verdict {{ flex:0 0 auto; text-align:center; min-width:56px; }}
.verdict .composite {{ font-size:26px; font-weight:800; line-height:1; }}
.rating {{ display:inline-block; margin-top:6px; padding:1px 9px; border-radius:99px;
  font-size:12px; color:#fff; }}
.r-strong {{ background:var(--green); }}
.r-mid {{ background:var(--amber); }}
.r-weak {{ background:var(--red); }}
.r-na {{ background:var(--gray); }}
.note {{ color:var(--sub); font-size:11px; margin-top:4px; }}
/* 诊断 */
.stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:10px 8px; text-align:center; }}
.stat .k {{ color:var(--sub); font-size:11px; }}
.stat .v {{ font-size:15px; font-weight:700; margin-top:3px; }}
.holds {{ margin-top:10px; }}
.hold {{ display:flex; align-items:center; padding:8px 12px; background:var(--card);
  border:1px solid var(--line); border-radius:10px; margin-bottom:6px; font-size:13px; }}
.hold .h-name {{ flex:1 1 auto; }}
.hold .h-val {{ color:var(--sub); margin-right:12px; }}
.hold .h-pnl {{ font-weight:700; }}
.up {{ color:var(--red); }}   /* A股惯例：红涨 */
.down {{ color:var(--green); }}
.sectors {{ margin-top:14px; }}
.sectors h3, .alerts h3, .rebal h3 {{ font-size:13px; margin:14px 0 8px; }}
.sector {{ display:flex; align-items:center; gap:8px; font-size:12px; margin-bottom:6px; }}
.sector .s-name {{ flex:0 0 64px; }}
.sector .s-bar {{ flex:1 1 auto; height:8px; background:var(--bg); border-radius:99px; overflow:hidden; }}
.sector .s-bar > span {{ display:block; height:100%; background:var(--accent); }}
.sector .s-pct {{ flex:0 0 40px; text-align:right; color:var(--sub); }}
.alerts ul, .rebal ul {{ margin:0; padding-left:18px; }}
.alerts li {{ color:var(--red); margin-bottom:5px; font-size:13px; }}
.rebal li {{ color:var(--accent); margin-bottom:5px; font-size:13px; }}
/* 市场简报 */
.market-meta {{ color:var(--sub); font-size:12px; margin-bottom:10px; }}
.briefing {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:14px; font-size:13px; }}
footer {{ margin-top:26px; color:var(--sub); font-size:11px; text-align:center;
  border-top:1px dashed var(--line); padding-top:14px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>ETF 多因子选股与组合诊断</h1>
    <div class="gen">生成于 {escape(generated_at)}</div>
    <div class="mood">整体情绪：{escape(ctx.overall_risk_mood)}</div>
  </header>

  <section>
    <h2>① ETF 多因子打分排序</h2>
{_score_cards(scores)}
    <div class="note">综合分基于横截面排名；取数失败的因子取中性并按剩余权重归一，完整度反映可信度。</div>
  </section>

  <section>
    <h2>② 当前组合诊断</h2>
{_diag_block(diag, holdings)}
  </section>

  <section>
    <h2>③ 市场背景简报</h2>
{_market_block(ctx)}
  </section>

  <footer>
    ⚠ 免责声明：本页输出为分析框架与客观规则信号，非投资建议；市场有风险，决策需独立判断。
  </footer>
</div>
</body>
</html>
"""
