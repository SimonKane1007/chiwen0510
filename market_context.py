"""
market_context.py —— 市场背景更新与真实性验证

职责（与计划一致）：
  每日 / 启动时更新「市场风向 / 政策变化 / 美股动向」，但**只关注与自选 ETF 相关**的信息，
  且必须先经「筛选 → 过滤 → 真实性验证」后才纳入分析。

数据流：
  fetch_news()  →  validate_and_filter()  →  build_market_context()
   (联网/本地)        (白名单/时效/去重/        (按ETF归类的简报 +
                       多源交叉/关键词映射)        每板块情绪因子 market_sentiment)

关键纪律：
  • 默认联网抓取；联网失败回退本地 market_feed.json（**仅供简报展示，不参与打分**）。
  • 「已验证」= 被 ≥N 个独立可信源交叉报道；未达标只进简报、不影响分数。
  • 这是**启发式可信度评估，非事实核查**。⚠️ 非投资建议。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from data_provider import _http_get, load_config

_HERE = os.path.dirname(os.path.abspath(__file__))
_FEED_FILE = os.path.join(_HERE, "market_feed.json")

# 方向判定词典（粗粒度，用于从标题推断利多/利空）
_POS_WORDS = ["利好", "提振", "超预期", "回暖", "增持", "降准", "降息", "宽松", "补贴",
              "复苏", "新高", "上涨", "提速", "扩张", "改善", "支持", "放量", "突破"]
_NEG_WORDS = ["利空", "回落", "不及预期", "下滑", "减持", "加息", "收紧", "承压",
              "下跌", "新低", "暴跌", "违约", "退坡", "降温", "风险", "调查", "处罚"]


# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────
@dataclass
class NewsItem:
    source: str          # 来源域名
    title: str
    summary: str = ""
    url: str = ""
    timestamp: str = ""  # ISO 时间

    def dt(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self.timestamp)
        except Exception:
            return None


@dataclass
class MarketSignal:
    """映射到某只 ETF 的、经验证的市场信号"""
    etf_code: str
    direction: str            # 利多 / 利空 / 中性
    strength: float           # 0~1
    confidence: float         # 0~1（由交叉验证源数量决定）
    validated: bool           # 是否达到多源交叉阈值
    evidence: List[NewsItem] = field(default_factory=list)


@dataclass
class MarketContext:
    updated_at: str
    signals_by_etf: Dict[str, MarketSignal] = field(default_factory=dict)
    overall_risk_mood: str = "中性"   # 整体风险情绪
    briefing: str = ""                # 纯文字简报（界面底部展示）
    online: bool = False              # 本次是否联网成功
    freshness: str = ""               # 数据新鲜度说明

    def sentiment_factor(self, etf_code: str, floor: float) -> Tuple[Optional[float], str]:
        """
        返回 (情绪因子 -1~1, 状态说明)。
        未验证 / 置信度不足 → 返回 (None, 原因)，由打分模块取中性并打标记。
        """
        sig = self.signals_by_etf.get(etf_code)
        if sig is None:
            return None, "无相关市场信号"
        if not sig.validated or sig.confidence < floor:
            return None, "未充分验证(仅进简报)"
        sign = {"利多": 1, "利空": -1}.get(sig.direction, 0)
        return round(sign * sig.strength * sig.confidence, 3), "已验证"


# ─────────────────────────────────────────────
# 采集
# ─────────────────────────────────────────────
def fetch_news(cfg: dict) -> Tuple[List[NewsItem], bool]:
    """
    尝试联网抓取新闻 RSS（白名单源）；失败回退本地 market_feed.json。
    返回 (新闻列表, 是否联网成功)。
    """
    items: List[NewsItem] = []
    online = False
    timeout = cfg["data_sources"].get("request_timeout_sec", 8)

    # 联网通道：此处给出 RSS 抓取骨架（不同源字段不同，解析失败即跳过）。
    # 公开 RSS/接口随时可能变动，故全部 try/except 兜底。
    for url in cfg["data_sources"].get("news_rss", []):
        raw = _http_get(url, timeout)
        if not raw:
            continue
        parsed = _parse_rss(raw)
        if parsed:
            items.extend(parsed)
            online = True

    if not items:
        items = _load_local_feed()  # 兜底：本地/示例数据，仅供简报
    return items, online


def _parse_rss(raw: str) -> List[NewsItem]:
    """极简 RSS 解析（标准库，无 feedparser 依赖）。失败返回空。"""
    out: List[NewsItem] = []
    try:
        for m in re.finditer(r"<item>(.*?)</item>", raw, re.S):
            block = m.group(1)
            title = _tag(block, "title")
            link = _tag(block, "link")
            desc = _tag(block, "description")
            pub = _tag(block, "pubDate")
            domain = re.sub(r"^https?://(www\.)?", "", link).split("/")[0] if link else ""
            out.append(NewsItem(source=domain, title=title, summary=desc,
                                url=link, timestamp=_to_iso(pub)))
    except Exception:
        return []
    return out


def _tag(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", block, re.S)
    return (m.group(1).strip() if m else "")


def _to_iso(pub: str) -> str:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S"):
        try:
            return datetime.strptime(pub.strip(), fmt).isoformat()
        except Exception:
            continue
    return datetime.now().isoformat()


def _load_local_feed() -> List[NewsItem]:
    """读取本地 market_feed.json；不存在则写一份示例供用户编辑。"""
    if not os.path.exists(_FEED_FILE):
        _write_sample_feed()
    try:
        with open(_FEED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [NewsItem(**it) for it in data.get("items", [])]
    except Exception:
        return []


def _write_sample_feed() -> None:
    """生成示例 feed（时间戳取当前，确保落在时效窗口内）。⚠️ 仅为演示，请替换为真实数据。"""
    now = datetime.now()
    def ts(hrs):
        return (now - timedelta(hours=hrs)).isoformat()
    sample = {
        "_说明": "市场新闻兜底/手动数据。items 为示例，请替换为真实抓取或手动录入的内容。仅供简报展示，不直接参与打分（需多源交叉验证后才进情绪因子）。",
        "items": [
            {"source": "csrc.gov.cn", "title": "监管表态活跃资本市场，支持券商并购重组",
             "summary": "活跃资本市场政策持续发力", "url": "https://csrc.gov.cn/x1", "timestamp": ts(6)},
            {"source": "cnstock.com", "title": "活跃资本市场再加码，券商板块获提振",
             "summary": "资本市场改革预期升温", "url": "https://cnstock.com/x2", "timestamp": ts(5)},
            {"source": "eastmoney.com", "title": "美联储降息预期升温，纳指创新高",
             "summary": "美股科技股走强，利好成长与跨境资产", "url": "https://eastmoney.com/x3", "timestamp": ts(10)},
            {"source": "wallstreetcn.com", "title": "纳指再创新高，降息预期支撑风险偏好",
             "summary": "美股延续涨势", "url": "https://wallstreetcn.com/x4", "timestamp": ts(9)},
            {"source": "people.com.cn", "title": "发改委部署特高压电网建设提速",
             "summary": "电网投资加码，电力设备需求提升", "url": "https://people.com.cn/x5", "timestamp": ts(20)},
            {"source": "unknownblog.xyz", "title": "传某地产政策将大幅放松",
             "summary": "未经证实的小道消息", "url": "https://unknownblog.xyz/x6", "timestamp": ts(3)},
        ],
    }
    try:
        with open(_FEED_FILE, "w", encoding="utf-8") as f:
            json.dump(sample, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────
# 筛选 / 过滤 / 真实性验证
# ─────────────────────────────────────────────
def validate_and_filter(items: List[NewsItem], cfg: dict) -> Dict[str, MarketSignal]:
    v = cfg["validation"]
    whitelist = cfg["data_sources"]["news_whitelist"]
    kw_map = cfg["keyword_etf_map"]

    # 1) 时效窗口
    now = datetime.now()
    fresh = []
    for it in items:
        d = it.dt()
        if d is None:
            continue
        # 兼容带/不带时区
        d = d.replace(tzinfo=None)
        if now - d <= timedelta(hours=v["recency_hours"]):
            fresh.append(it)

    # 2) 去重（标题相似度）
    deduped = _dedup(fresh, v["title_dedup_similarity"])

    # 3) 关键词 → ETF 映射；同时按 (etf, 方向) 聚合证据，统计独立可信源数量
    buckets: Dict[Tuple[str, str], List[NewsItem]] = {}
    for it in deduped:
        etfs = _map_to_etfs(it, kw_map)
        if not etfs:
            continue  # 与自选无关，丢弃
        direction = _infer_direction(it)
        for code in etfs:
            buckets.setdefault((code, direction), []).append(it)

    # 4) 多源交叉验证 → 生成 MarketSignal
    signals: Dict[str, MarketSignal] = {}
    for (code, direction), evid in buckets.items():
        trusted_sources = {e.source for e in evid if _trusted(e.source, whitelist)}
        n_trusted = len(trusted_sources)
        validated = n_trusted >= v["min_corroboration_sources"]
        confidence = min(1.0, n_trusted / max(v["min_corroboration_sources"], 1)) if validated \
            else n_trusted / (v["min_corroboration_sources"] + 1)
        strength = min(1.0, 0.4 + 0.2 * len(evid))
        sig = MarketSignal(etf_code=code, direction=direction, strength=round(strength, 2),
                           confidence=round(confidence, 2), validated=validated, evidence=evid)
        # 同一 ETF 若多方向，保留置信度更高者
        if code not in signals or confidence > signals[code].confidence:
            signals[code] = sig
    return signals


def _dedup(items: List[NewsItem], thresh: float) -> List[NewsItem]:
    kept: List[NewsItem] = []
    for it in items:
        if any(_similar(it.title, k.title) >= thresh and it.source == k.source for k in kept):
            continue
        kept.append(it)
    return kept


def _similar(a: str, b: str) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _map_to_etfs(it: NewsItem, kw_map: Dict[str, List[str]]) -> List[str]:
    text = it.title + " " + it.summary
    hit: List[str] = []
    for kws, codes in kw_map.items():
        if any(k and k in text for k in kws.split("|")):
            hit.extend(codes)
    return list(dict.fromkeys(hit))


def _infer_direction(it: NewsItem) -> str:
    text = it.title + " " + it.summary
    pos = sum(1 for w in _POS_WORDS if w in text)
    neg = sum(1 for w in _NEG_WORDS if w in text)
    if pos > neg:
        return "利多"
    if neg > pos:
        return "利空"
    return "中性"


def _trusted(domain: str, whitelist: List[str]) -> bool:
    return any(domain == w or domain.endswith("." + w) for w in whitelist)


# ─────────────────────────────────────────────
# 组装市场背景
# ─────────────────────────────────────────────
def build_market_context(cfg: dict) -> MarketContext:
    items, online = fetch_news(cfg)
    signals = validate_and_filter(items, cfg)

    name_map = {e["code"]: e["name"] for e in cfg["universe"]}
    validated = [s for s in signals.values() if s.validated]
    pos = sum(1 for s in validated if s.direction == "利多")
    neg = sum(1 for s in validated if s.direction == "利空")
    mood = "偏多" if pos > neg else ("偏空" if neg > pos else "中性")

    lines: List[str] = []
    if signals:
        for code, sig in sorted(signals.items(), key=lambda kv: -kv[1].confidence):
            nm = name_map.get(code, code)
            tag = "✅已验证" if sig.validated else "⚠未充分验证(仅参考)"
            src = "、".join(sorted({e.source for e in sig.evidence}))
            lines.append(f"• {nm}({code})  {sig.direction}  置信{sig.confidence:.0%}  {tag}")
            lines.append(f"    依据[{len(sig.evidence)}条/{src}]：{sig.evidence[0].title}")
    else:
        lines.append("• 暂无与自选 ETF 相关、且通过验证的市场信息。")

    src_note = "联网抓取" if online else "本地/示例数据（未联网，仅供参考、不进打分）"
    briefing = "\n".join(lines)

    return MarketContext(
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        signals_by_etf=signals,
        overall_risk_mood=mood,
        briefing=briefing,
        online=online,
        freshness=src_note,
    )


if __name__ == "__main__":
    cfg = load_config()
    ctx = build_market_context(cfg)
    print(f"市场背景更新于 {ctx.updated_at}  来源：{ctx.freshness}  整体情绪：{ctx.overall_risk_mood}")
    print("=" * 60)
    print(ctx.briefing)
    print("=" * 60)
    print("参与打分的情绪因子（已验证且置信度达标者）：")
    floor = cfg["validation"]["sentiment_confidence_floor"]
    for e in cfg["universe"]:
        val, note = ctx.sentiment_factor(e["code"], floor)
        if val is not None:
            print(f"  {e['name']}({e['code']}): market_sentiment={val:+.3f}  [{note}]")
