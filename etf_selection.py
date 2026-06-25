"""
etf_selection.py —— ETF 多因子打分 / 组合诊断 主程序

一套系统化、可复用的 ETF 分析选股方法，回答两个问题：
  (1) 选哪只 —— 多因子打分对自选 ETF 排序；
  (2) 配多少 —— 组合层面诊断仓位、集中度、分散度，对照「核心-卫星」基准。

数据：默认联网取量价/估值因子(data_provider) + 市场情绪因子(market_context)；
      任一因子取数失败 → 打 ⚠ 标记、取中性、按剩余权重重新归一，绝不静默污染分数。

界面：终端三段式 —— ① 打分排序表  ② 组合诊断  ③ 市场背景简报（底部纯文字）。

⚠️ 免责声明：本工具为分析框架 / 教育用途，输出的是客观规则信号，
   不构成任何投资建议或买卖推荐。阈值与权重均为可调参数（见 config.json），
   请结合自身风险承受能力独立决策，市场有风险，投资需谨慎。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from data_provider import (FactorBundle, OK, fetch_benchmark_closes,
                           fetch_factor_bundle, load_config)
from market_context import MarketContext, build_market_context

NEUTRAL = 50.0  # 中性分


# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────
@dataclass
class FactorScore:
    name: str
    raw: Optional[float]
    score: float          # 标准化 0~100
    weight: float
    ok: bool              # 数据是否有效
    note: str = ""


@dataclass
class ETFScore:
    code: str
    name: str
    category: str
    composite: float
    rating: str
    completeness: float
    factors: List[FactorScore] = field(default_factory=list)


@dataclass
class Holding:
    code: str
    name: str
    category: str
    qty: float
    cost: float
    price: float

    @property
    def market_value(self) -> float:
        return self.qty * self.price

    @property
    def pnl(self) -> float:
        return (self.price - self.cost) * self.qty

    @property
    def pnl_pct(self) -> float:
        return (self.price / self.cost - 1) * 100 if self.cost else 0.0


@dataclass
class PortfolioDiagnosis:
    total_assets: float
    stock_value: float
    cash: float
    position: float          # 仓位
    cash_ratio: float
    hhi: float               # 集中度
    max_weight: float        # 单票最大权重
    max_weight_name: str
    sector_exposure: Dict[str, float]
    alerts: List[str] = field(default_factory=list)        # 触发的风险提示
    rebalance: List[str] = field(default_factory=list)      # 再平衡方向


# ─────────────────────────────────────────────
# 因子标准化（横截面排名，稳健于异常值）
# ─────────────────────────────────────────────
def _rank_scores(values: Dict[str, float], invert: bool = False) -> Dict[str, float]:
    """把一组原始值映射到 0~100（百分位排名）。invert=True 表示越小越好。"""
    if not values:
        return {}
    if len(values) == 1:
        return {k: NEUTRAL for k in values}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    out = {}
    for i, (code, _) in enumerate(ordered):
        pct = i / (n - 1) * 100
        out[code] = (100 - pct) if invert else pct
    return out


def _turnover_score(turnover: float, good_range: List[float]) -> float:
    """换手率：落在健康区间得高分，过低(流动性差)或过高(过热)都扣分。"""
    lo, hi = good_range
    if lo <= turnover <= hi:
        return 100.0
    if turnover < lo:
        return max(0.0, 100 - (lo - turnover) / lo * 100)
    return max(0.0, 100 - (turnover - hi) / hi * 80)


# ─────────────────────────────────────────────
# 打分（横截面）
# ─────────────────────────────────────────────
def score_universe(cfg: dict, bundles: Dict[str, FactorBundle],
                   ctx: MarketContext) -> List[ETFScore]:
    w = cfg["weights"]
    th = cfg["rating_thresholds"]
    good_range = cfg["factor_params"]["turnover_good_range"]
    floor = cfg["validation"]["sentiment_confidence_floor"]
    name_map = {e["code"]: e for e in cfg["universe"]}

    # 1) 收集各因子原始值（仅 OK 的）
    def collect(attr):
        return {c: getattr(b, attr).value for c, b in bundles.items()
                if getattr(b, attr).status == OK and getattr(b, attr).value is not None}

    rank_mom = _rank_scores(collect("momentum"))
    rank_rs = _rank_scores(collect("relative_strength"))
    rank_ff = _rank_scores(collect("fund_flow"))
    rank_vol = _rank_scores(collect("volatility"), invert=True)  # 低波动得高分

    results: List[ETFScore] = []
    for code, b in bundles.items():
        cat = name_map[code]["category"]
        factors: List[FactorScore] = []

        def add(name, wkey, score, raw, ok, note=""):
            factors.append(FactorScore(name, raw, score if ok else NEUTRAL,
                                       w[wkey], ok, note))

        # 趋势动量
        ok = code in rank_mom
        add("趋势动量", "trend_momentum", rank_mom.get(code, NEUTRAL),
            b.momentum.value, ok, "" if ok else b.momentum.note)
        # 相对强弱
        ok = code in rank_rs
        add("相对强弱", "relative_strength", rank_rs.get(code, NEUTRAL),
            b.relative_strength.value, ok, "" if ok else b.relative_strength.note)
        # 估值分位（低分位=便宜=高分）
        ok = b.valuation_pct.status == OK and b.valuation_pct.value is not None
        vscore = (100 - b.valuation_pct.value) if ok else NEUTRAL
        add("估值分位", "valuation", vscore, b.valuation_pct.value, ok,
            "" if ok else b.valuation_pct.note)
        # 资金流/规模
        ok = code in rank_ff
        add("资金流", "fund_flow", rank_ff.get(code, NEUTRAL),
            b.fund_flow.value, ok, "" if ok else b.fund_flow.note)
        # 流动性（换手率健康区间）
        ok = b.turnover.status == OK and b.turnover.value is not None
        tscore = _turnover_score(b.turnover.value, good_range) if ok else NEUTRAL
        add("流动性", "liquidity", tscore, b.turnover.value, ok,
            "" if ok else b.turnover.note)
        # 波动/风险（低波动得高分）
        ok = code in rank_vol
        add("风险(低波动)", "risk", rank_vol.get(code, NEUTRAL),
            b.volatility.value, ok, "" if ok else b.volatility.note)
        # 市场情绪（验证达标才生效）
        sval, snote = ctx.sentiment_factor(code, floor)
        ok = sval is not None
        sscore = (sval + 1) * 50 if ok else NEUTRAL
        add("市场情绪", "market_sentiment", sscore, sval, ok, "" if ok else snote)

        # 2) 综合分：仅用有效因子，按其权重重新归一
        present = [f for f in factors if f.ok]
        if present:
            tw = sum(f.weight for f in present)
            composite = sum(f.weight * f.score for f in present) / tw if tw else NEUTRAL
        else:
            composite = NEUTRAL
        completeness = len(present) / len(factors)
        rating = ("强" if composite >= th["strong"]
                  else "中" if composite >= th["neutral"] else "弱")
        # 数据太少不给出可信评级，避免单因子产生过度自信的「强/弱」标签
        if completeness < 0.3:
            rating = "数据不足"

        results.append(ETFScore(code, name_map[code]["name"], cat,
                                round(composite, 1), rating,
                                round(completeness, 2), factors))

    results.sort(key=lambda r: r.composite, reverse=True)
    return results


# ─────────────────────────────────────────────
# 组合诊断
# ─────────────────────────────────────────────
def diagnose_portfolio(holdings: List[Holding], cash: float, cfg: dict) -> PortfolioDiagnosis:
    lim = cfg["portfolio_limits"]
    cs = cfg["core_satellite_template"]
    stock_value = sum(h.market_value for h in holdings)
    total = stock_value + cash
    position = stock_value / total if total else 0.0
    cash_ratio = cash / total if total else 0.0

    weights = {h.name: h.market_value / stock_value for h in holdings} if stock_value else {}
    hhi = sum(wt ** 2 for wt in weights.values())
    max_name, max_wt = (max(weights.items(), key=lambda kv: kv[1]) if weights else ("-", 0.0))

    sector: Dict[str, float] = {}
    for h in holdings:
        sector[h.category] = sector.get(h.category, 0.0) + (h.market_value / stock_value if stock_value else 0)

    alerts, rebalance = [], []

    if max_wt > lim["single_etf_max"]:
        alerts.append(f"单票集中度过高：{max_name} 占 {max_wt:.1%}，超过上限 {lim['single_etf_max']:.0%}")
        rebalance.append(f"降低 {max_name} 至 ≤{lim['single_etf_max']:.0%}，分散个券风险")
    for sec, exp in sector.items():
        if exp > lim["single_sector_max"]:
            alerts.append(f"单板块过度暴露：{sec} 占 {exp:.1%}，超过上限 {lim['single_sector_max']:.0%}")
    if position > lim["position_range"][1]:
        alerts.append(f"总仓位偏高：{position:.1%}，超过建议上限 {lim['position_range'][1]:.0%}")
        rebalance.append(f"降低总仓位至 {lim['position_range'][0]:.0%}~{lim['position_range'][1]:.0%} 区间，留出缓冲")
    elif position < lim["position_range"][0]:
        alerts.append(f"总仓位偏低：{position:.1%}，低于建议下限 {lim['position_range'][0]:.0%}")
    if cash_ratio < lim["min_cash_buffer"]:
        alerts.append(f"现金缓冲不足：{cash_ratio:.1%}，低于建议 {lim['min_cash_buffer']:.0%}")
        rebalance.append(f"将现金提升至 ≥{lim['min_cash_buffer']:.0%}，应对回撤与再平衡")

    broad = sum(exp for sec, exp in sector.items() if sec == "宽基")
    core_lo = cs["core_broad_base"][0]
    if broad < core_lo:
        alerts.append(f"缺少核心仓：宽基占比 {broad:.1%}，低于核心基准 {core_lo:.0%}")
        rebalance.append(f"增配宽基(沪深300/上证50等)作为核心，目标 {core_lo:.0%}~{cs['core_broad_base'][1]:.0%}")

    if len(sector) < 3:
        rebalance.append("品类过窄，建议跨「宽基/跨境/行业/商品」分散，降低相关性")

    return PortfolioDiagnosis(
        total_assets=round(total, 2), stock_value=round(stock_value, 2), cash=round(cash, 2),
        position=position, cash_ratio=cash_ratio, hhi=round(hhi, 3),
        max_weight=max_wt, max_weight_name=max_name, sector_exposure=sector,
        alerts=alerts, rebalance=rebalance,
    )


# ─────────────────────────────────────────────
# 终端界面（三段式，简洁优美）
# ─────────────────────────────────────────────
def _w(s: str) -> int:
    """字符串显示宽度（CJK 全角算 2）。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def _pad(s: str, width: int, align: str = "left") -> str:
    """按显示宽度对齐（兼容中英文混排）。"""
    s = str(s)
    gap = max(0, width - _w(s))
    return (s + " " * gap) if align == "left" else (" " * gap + s)


def _print_scores(scores: List[ETFScore]) -> None:
    print("①  ETF 多因子打分排序")
    print("─" * 64)
    print(_pad("排名", 6) + _pad("名称", 16) + _pad("类别", 12)
          + _pad("综合分", 8, "right") + _pad("评级", 10, "right") + _pad("完整度", 9, "right"))
    print("─" * 64)
    for i, s in enumerate(scores, 1):
        flag = "  ⚠数据待联网" if s.completeness == 0 else ("  ⚠部分缺失" if s.completeness < 0.5 else "")
        print(_pad(i, 6) + _pad(s.name, 16) + _pad(s.category, 12)
              + _pad(f"{s.composite:.1f}", 8, "right") + _pad(s.rating, 10, "right")
              + _pad(f"{s.completeness:.0%}", 9, "right") + flag)
    print("─" * 64)
    print("注：综合分基于横截面排名；取数失败的因子取中性并按剩余权重归一，完整度反映可信度。\n")


def _print_diagnosis(d: PortfolioDiagnosis) -> None:
    print("②  当前组合诊断")
    print("─" * 64)
    print(f"  总资产 ¥{d.total_assets:,.2f}   股票 ¥{d.stock_value:,.2f}   现金 ¥{d.cash:,.2f}")
    print(f"  仓位 {d.position:.2%}   现金比例 {d.cash_ratio:.2%}   "
          f"集中度HHI {d.hhi:.3f}   单票最大 {d.max_weight_name} {d.max_weight:.1%}")
    print(f"  板块暴露：" + "  ".join(f"{k} {v:.1%}" for k, v in d.sector_exposure.items()))
    print()
    if d.alerts:
        print("  ⚠ 触发的风险提示：")
        for a in d.alerts:
            print(f"    • {a}")
    if d.rebalance:
        print("  ↻ 再平衡方向（客观信号，非买卖建议）：")
        for r in d.rebalance:
            print(f"    • {r}")
    print("─" * 64 + "\n")


def _print_market(ctx: MarketContext) -> None:
    print("③  市场背景简报")
    print("─" * 64)
    print(f"  更新于 {ctx.updated_at} ｜ 来源：{ctx.freshness} ｜ 整体情绪：{ctx.overall_risk_mood}")
    print()
    for line in ctx.briefing.splitlines():
        print("  " + line)
    print("─" * 64)


# ─────────────────────────────────────────────
# 示例数据：用户真实自选 + 持仓（来自截图）
# ─────────────────────────────────────────────
def demo_holdings(cfg: dict) -> Tuple[List[Holding], float]:
    name_map = {e["code"]: e for e in cfg["universe"]}

    def mk(code, qty, cost, price):
        e = name_map[code]
        return Holding(code, e["name"], e["category"], qty, cost, price)

    holdings = [
        mk("513180", 110200, 0.6205, 0.5620),  # 恒生科技ETF
        mk("159611", 11500, 0.8744, 0.9560),   # 电网设备ETF（UC电网设备）
        mk("561560", 9100, 1.3200, 1.2720),    # 电力ETF华泰柏瑞
    ]
    cash = 7400.42
    return holdings, cash


def main() -> None:
    cfg = load_config()

    print("\n" + "=" * 64)
    print("           ETF 多因子选股与组合诊断  ·  分析框架")
    print("=" * 64 + "\n")

    # 市场背景（联网+验证，失败回退本地）
    ctx = build_market_context(cfg)

    # 量价/估值因子（默认联网；失败打标记）
    bench = fetch_benchmark_closes(cfg["factor_params"]["relative_benchmark"], cfg)
    bundles = {e["code"]: fetch_factor_bundle(e, bench, cfg) for e in cfg["universe"]}

    # 打分排序
    scores = score_universe(cfg, bundles, ctx)
    _print_scores(scores)

    # 组合诊断
    holdings, cash = demo_holdings(cfg)
    diag = diagnose_portfolio(holdings, cash, cfg)
    _print_diagnosis(diag)

    # 市场简报（界面底部）
    _print_market(ctx)

    print("\n⚠ 免责声明：本输出为分析框架与客观规则信号，非投资建议；"
          "市场有风险，决策需独立判断。\n")


if __name__ == "__main__":
    main()
