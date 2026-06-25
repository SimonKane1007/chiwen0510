"""
data_provider.py —— ETF 量价 / 估值因子的联网抓取层

设计原则（与计划一致）：
  1. 默认联网取数；优先用 akshare，未安装则退回东方财富公开接口（标准库 urllib，尊重 HTTPS_PROXY）。
  2. 当日缓存，避免重复请求被限频。
  3. 任何超时 / 异常 / 接口变动，统一兜底为「该因子取数失败」并带原因，绝不抛错崩溃。
  4. 统一返回 FactorBundle：各因子原始值 + 取数状态，供上层（etf_selection）打标记。

⚠️ 本模块仅做数据采集，不构成投资建议。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

# ─────────────────────────────────────────────
# 取数状态
# ─────────────────────────────────────────────
OK = "ok"            # 取数成功
FAILED = "failed"    # 联网/解析失败
MISSING = "missing"  # 数据源不支持该因子


@dataclass
class FactorValue:
    """单个因子的原始值 + 状态"""
    value: Optional[float] = None
    status: str = MISSING
    note: str = ""


@dataclass
class FactorBundle:
    """单只 ETF 的全部因子原始数据"""
    code: str
    name: str = ""
    price: FactorValue = field(default_factory=FactorValue)            # 现价
    change_pct: FactorValue = field(default_factory=FactorValue)       # 当日涨跌幅 %
    momentum: FactorValue = field(default_factory=FactorValue)         # N日动量收益 %
    relative_strength: FactorValue = field(default_factory=FactorValue)  # 相对基准超额 %
    valuation_pct: FactorValue = field(default_factory=FactorValue)    # 估值历史分位 0~100
    fund_flow: FactorValue = field(default_factory=FactorValue)        # 规模/份额变化 %
    turnover: FactorValue = field(default_factory=FactorValue)         # 换手率 %
    volatility: FactorValue = field(default_factory=FactorValue)       # 年化波动率 %
    source: str = ""                                                   # 实际取数来源

    def completeness(self) -> float:
        """数据完整度 0~1：成功取到的因子占比"""
        fields = [self.momentum, self.relative_strength, self.valuation_pct,
                  self.fund_flow, self.turnover, self.volatility]
        ok = sum(1 for f in fields if f.status == OK)
        return ok / len(fields)


# ─────────────────────────────────────────────
# 工具：配置、缓存、HTTP
# ─────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "etf_cache")


def load_config(path: Optional[str] = None) -> dict:
    path = path or os.path.join(_HERE, "config.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _cache_path(key: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    safe = key.replace("/", "_")
    return os.path.join(_CACHE_DIR, f"{date.today().isoformat()}_{safe}.json")


def _cache_get(key: str, ttl_hours: int) -> Optional[dict]:
    p = _cache_path(key)
    if not os.path.exists(p):
        return None
    if time.time() - os.path.getmtime(p) > ttl_hours * 3600:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_put(key: str, data: dict) -> None:
    try:
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass  # 缓存失败不影响主流程


def _http_get(url: str, timeout: int) -> Optional[str]:
    """标准库 GET，自动走 HTTPS_PROXY/HTTP_PROXY 环境变量；失败返回 None。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ETFSelector/1.0)",
            "Referer": "https://quote.eastmoney.com/",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def _secid(code: str) -> str:
    """东方财富 secid：沪市(5x/6x)=1.code，深市(15/0/3)=0.code。"""
    return ("1." if code[0] in ("5", "6") else "0.") + code


# ─────────────────────────────────────────────
# 因子计算工具
# ─────────────────────────────────────────────
def _pct_return(closes: List[float], lookback: int) -> Optional[float]:
    if len(closes) <= lookback or closes[-1 - lookback] == 0:
        return None
    return (closes[-1] / closes[-1 - lookback] - 1) * 100


def _annualized_vol(closes: List[float], window: int) -> Optional[float]:
    seg = closes[-window:]
    if len(seg) < 5:
        return None
    rets = [seg[i] / seg[i - 1] - 1 for i in range(1, len(seg)) if seg[i - 1]]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100


# ─────────────────────────────────────────────
# 东方财富取数（无第三方依赖的兜底通道）
# ─────────────────────────────────────────────
def _em_spot(code: str, timeout: int) -> Dict[str, Optional[float]]:
    """实时快照：现价、涨跌幅、换手率。"""
    url = (f"https://push2.eastmoney.com/api/qt/stock/get?"
           f"secid={_secid(code)}&fields=f43,f170,f168")
    raw = _http_get(url, timeout)
    if not raw:
        return {}
    try:
        d = json.loads(raw).get("data") or {}
        return {
            "price": d.get("f43", 0) / 1000 if d.get("f43") else None,
            "change_pct": d.get("f170", 0) / 100 if d.get("f170") is not None else None,
            "turnover": d.get("f168", 0) / 100 if d.get("f168") is not None else None,
        }
    except Exception:
        return {}


def _em_kline(code: str, limit: int, timeout: int) -> List[float]:
    """日线收盘价序列（用于动量、波动率）。"""
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           f"secid={_secid(code)}&klt=101&fqt=1&lmt={limit}"
           f"&fields1=f1&fields2=f51,f53&end=20500101")
    raw = _http_get(url, timeout)
    if not raw:
        return []
    try:
        klines = (json.loads(raw).get("data") or {}).get("klines") or []
        return [float(k.split(",")[1]) for k in klines]
    except Exception:
        return []


# ─────────────────────────────────────────────
# akshare 取数（若已安装，数据更全：含估值分位/规模）
# ─────────────────────────────────────────────
def _try_akshare_valuation(index_code: str, lookback_years: int) -> Optional[float]:
    try:
        import akshare as ak  # noqa
        # 不同 akshare 版本接口不一，统一兜底为 None（→打标记）
        df = ak.index_value_hist_funddb(symbol=index_code, indicator="市盈率")
        if df is None or df.empty:
            return None
        pe = df.iloc[:, 1].dropna().tolist()
        if len(pe) < 30:
            return None
        window = pe[-252 * lookback_years:]
        cur = window[-1]
        rank = sum(1 for x in window if x <= cur) / len(window)
        return round(rank * 100, 1)
    except Exception:
        return None


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────
def fetch_factor_bundle(etf: dict, benchmark_closes: List[float], cfg: dict) -> FactorBundle:
    """抓取单只 ETF 的全部因子，失败项标记状态。"""
    code, name = etf["code"], etf.get("name", "")
    ds = cfg["data_sources"]
    fp = cfg["factor_params"]
    timeout = ds.get("request_timeout_sec", 8)
    ttl = ds.get("cache_ttl_hours", 12)
    bundle = FactorBundle(code=code, name=name)

    cached = _cache_get(f"bundle_{code}", ttl)
    if cached:
        return _bundle_from_dict(cached)

    # 1) 实时快照
    spot = _em_spot(code, timeout)
    bundle.source = "eastmoney"
    if spot.get("price") is not None:
        bundle.price = FactorValue(spot["price"], OK)
        bundle.change_pct = FactorValue(spot.get("change_pct"), OK)
    else:
        bundle.price = FactorValue(None, FAILED, "实时行情取数失败")

    if spot.get("turnover") is not None:
        bundle.turnover = FactorValue(spot["turnover"], OK)
    else:
        bundle.turnover = FactorValue(None, FAILED, "换手率取数失败")

    # 2) 日线 → 动量、波动率、相对强弱
    closes = _em_kline(code, max(fp["momentum_lookback_days"], fp["volatility_lookback_days"]) + 10, timeout)
    if closes:
        mom = _pct_return(closes, fp["momentum_lookback_days"])
        bundle.momentum = FactorValue(round(mom, 2), OK) if mom is not None \
            else FactorValue(None, FAILED, "动量数据不足")
        vol = _annualized_vol(closes, fp["volatility_lookback_days"])
        bundle.volatility = FactorValue(round(vol, 2), OK) if vol is not None \
            else FactorValue(None, FAILED, "波动率数据不足")
        bench_mom = _pct_return(benchmark_closes, fp["momentum_lookback_days"]) if benchmark_closes else None
        if mom is not None and bench_mom is not None:
            bundle.relative_strength = FactorValue(round(mom - bench_mom, 2), OK)
        else:
            bundle.relative_strength = FactorValue(None, FAILED, "基准数据缺失")
    else:
        for attr in ("momentum", "volatility", "relative_strength"):
            setattr(bundle, attr, FactorValue(None, FAILED, "日线取数失败"))

    # 3) 估值分位（akshare 优先；取不到则标记）
    val = _try_akshare_valuation(etf.get("index", ""), fp["valuation_lookback_years"])
    bundle.valuation_pct = FactorValue(val, OK) if val is not None \
        else FactorValue(None, FAILED, "估值分位需 akshare/指数PE历史，未取到")

    # 4) 资金流 / 规模变化：免费接口不稳定，统一标记缺失由用户补
    bundle.fund_flow = FactorValue(None, MISSING, "规模/份额变化需另接数据源")

    if bundle.price.status == OK:
        _cache_put(f"bundle_{code}", _bundle_to_dict(bundle))
    return bundle


def fetch_benchmark_closes(benchmark_code: str, cfg: dict) -> List[float]:
    fp = cfg["factor_params"]
    timeout = cfg["data_sources"].get("request_timeout_sec", 8)
    return _em_kline(benchmark_code, fp["momentum_lookback_days"] + 10, timeout)


# ── 序列化（缓存用） ──
def _fv_to_dict(fv: FactorValue) -> dict:
    return {"value": fv.value, "status": fv.status, "note": fv.note}


def _bundle_to_dict(b: FactorBundle) -> dict:
    return {
        "code": b.code, "name": b.name, "source": b.source,
        **{k: _fv_to_dict(getattr(b, k)) for k in
           ("price", "change_pct", "momentum", "relative_strength",
            "valuation_pct", "fund_flow", "turnover", "volatility")},
    }


def _bundle_from_dict(d: dict) -> FactorBundle:
    b = FactorBundle(code=d["code"], name=d.get("name", ""))
    b.source = d.get("source", "")
    for k in ("price", "change_pct", "momentum", "relative_strength",
              "valuation_pct", "fund_flow", "turnover", "volatility"):
        fv = d.get(k) or {}
        setattr(b, k, FactorValue(fv.get("value"), fv.get("status", MISSING), fv.get("note", "")))
    return b


if __name__ == "__main__":
    cfg = load_config()
    bench = fetch_benchmark_closes(cfg["factor_params"]["relative_benchmark"], cfg)
    print(f"基准 {cfg['factor_params']['relative_benchmark']} 取到 {len(bench)} 根日线")
    print("=" * 60)
    for etf in cfg["universe"][:4]:
        b = fetch_factor_bundle(etf, bench, cfg)
        print(f"\n{b.name}({b.code})  来源={b.source}  完整度={b.completeness():.0%}")
        for k in ("price", "momentum", "relative_strength", "valuation_pct", "turnover", "volatility"):
            fv = getattr(b, k)
            flag = "" if fv.status == OK else f"  ⚠ {fv.note or fv.status}"
            print(f"  {k:18s}: {fv.value}{flag}")
