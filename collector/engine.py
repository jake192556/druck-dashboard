"""
드러켄밀러식 시장 판단 엔진
-----------------------------
원칙
  1) 유동성이 방향을 정한다 (연준·순유동성·정책금리)
  2) 신용·금리·달러가 위험선호를 보여준다
  3) 시장 내부(경기민감 업종 상대강도)가 경제보다 먼저 말한다
  4) 추세는 타이밍 도구다
  5) 18~24개월 앞을 본다 → 수준보다 '변화'에 점수를 준다

이 모듈은 네트워크를 쓰지 않는다. collect.py가 데이터를 받아 넘겨준다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

PILLARS = [
    ("liquidity", "유동성", 0.35),
    ("credit", "신용·금리·달러", 0.25),
    ("internals", "시장 내부 신호", 0.25),
    ("trend", "추세 (타이밍)", 0.15),
]

SECTOR_NAMES = {
    "KRE": "지역은행",
    "IYT": "운송",
    "XHB": "주택건설",
    "XRT": "소매",
    "SMH": "반도체",
    "IWM": "소형주",
}

FRED_SERIES = [
    "WALCL",         # 연준 총자산 (백만$, 주간)
    "WTREGEN",       # 재무부 일반계정 TGA (백만$, 주간)
    "RRPONTSYD",     # 역레포 (십억$, 일간)
    "DFF",           # 연방기금 실효금리
    "M2SL",          # M2 (십억$, 월간)
    "BAMLH0A0HYM2",  # 하이일드 스프레드 (%)
    "DFII10",        # 10년 실질금리 (%)
    "DTWEXBGS",      # 광의 달러지수
    "T10Y2Y",        # 10Y-2Y 금리차
]

PRICE_TICKERS = [
    "SPY", "RSP", "KRE", "IYT", "XHB", "XRT", "SMH", "IWM",
    "XLY", "XLP", "HYG", "IEF", "HG=F", "GC=F",
    "^KS11", "^KQ11", "KRW=X", "EWY", "EEM",
]


@dataclass
class Indicator:
    id: str
    pillar: str
    name: str
    value: Optional[float]
    unit: str
    change: Optional[float]
    change_label: str
    signal: Optional[int]          # +1 우호 / 0 중립 / -1 비우호 / None 데이터 없음
    note: str
    info: bool = False             # True면 참고용 (점수 제외)

    def to_dict(self):
        d = asdict(self)
        for k in ("value", "change"):
            if d[k] is not None and (isinstance(d[k], float) and not math.isfinite(d[k])):
                d[k] = None
            elif d[k] is not None:
                d[k] = round(float(d[k]), 3)
        return d


# ---------------------------------------------------------------- helpers
def _clean(s: Optional[pd.Series], asof) -> Optional[pd.Series]:
    if s is None:
        return None
    s = s.dropna()
    s = s[s.index <= asof]
    return s if len(s) else None


def _ago(s: pd.Series, days: int) -> float:
    target = s.index[-1] - pd.Timedelta(days=days)
    prior = s[s.index <= target]
    return float(prior.iloc[-1]) if len(prior) else float("nan")


def _sig(x: float, pos: float, neg: float, higher_is_good=True) -> Optional[int]:
    """x가 pos 이상이면 +1, neg 이하면 -1 (higher_is_good=False면 반대)."""
    if x is None or not math.isfinite(x):
        return None
    if higher_is_good:
        return 1 if x >= pos else (-1 if x <= neg else 0)
    return 1 if x <= pos else (-1 if x >= neg else 0)


def _fmt_signed(x: float, digits=1, suffix="") -> str:
    if x is None or not math.isfinite(x):
        return "-"
    return f"{x:+.{digits}f}{suffix}"


def _rel_return(px: pd.DataFrame, a: str, b: str, n: int = 63) -> float:
    if a not in px or b not in px:
        return float("nan")
    pair = px[[a, b]].dropna()
    if len(pair) <= n:
        return float("nan")
    ra = pair[a].iloc[-1] / pair[a].iloc[-1 - n] - 1
    rb = pair[b].iloc[-1] / pair[b].iloc[-1 - n] - 1
    return float((ra - rb) * 100)


def _ret(px: pd.DataFrame, a: str, n: int = 63) -> float:
    if a not in px:
        return float("nan")
    p = px[a].dropna()
    if len(p) <= n:
        return float("nan")
    return float((p.iloc[-1] / p.iloc[-1 - n] - 1) * 100)


def net_liquidity(fred: dict) -> Optional[pd.Series]:
    """순유동성(십억$) = 연준자산 - TGA - 역레포, 주간(수요일) 기준."""
    try:
        w = fred["WALCL"] / 1000
        t = fred["WTREGEN"] / 1000
        r = fred["RRPONTSYD"]
    except KeyError:
        return None
    df = pd.concat({"w": w, "t": t, "r": r}, axis=1).sort_index().ffill()
    df = df.dropna()
    if df.empty:
        return None
    nl = (df["w"] - df["t"] - df["r"]).resample("W-WED").last().dropna()
    return nl


# ---------------------------------------------------------------- pillars
def _liquidity(fred, asof) -> list[Indicator]:
    out = []
    nl = _clean(net_liquidity(fred), asof)
    if nl is not None and len(nl) > 14:
        cur, prev = float(nl.iloc[-1]), _ago(nl, 91)
        pct = (cur / prev - 1) * 100
        out.append(Indicator(
            "net_liq", "liquidity", "순유동성 (연준자산−TGA−역레포)", cur, "십억$",
            cur - prev, f"13주 {_fmt_signed(cur - prev, 0, 'B')} ({_fmt_signed(pct, 1, '%')})",
            _sig(pct, 1.0, -1.0),
            "시장에 풀린 달러가 늘어나는 중" if pct >= 1 else
            ("시장에서 달러가 빠져나가는 중" if pct <= -1 else "유동성 큰 변화 없음"),
        ))
    w = _clean(fred.get("WALCL"), asof)
    if w is not None and len(w) > 14:
        cur, prev = float(w.iloc[-1]) / 1e6, _ago(w, 91) / 1e6
        pct = (cur / prev - 1) * 100
        out.append(Indicator(
            "fed_bs", "liquidity", "연준 총자산 (QE/QT)", cur, "조$",
            pct, f"13주 {_fmt_signed(pct, 1, '%')}",
            _sig(pct, 0.5, -0.5),
            "대차대조표 확대 (QE 성격)" if pct >= 0.5 else
            ("양적긴축(QT) 진행 중" if pct <= -0.5 else "대차대조표 정체"),
        ))
    d = _clean(fred.get("DFF"), asof)
    if d is not None and len(d) > 100:
        cur, prev = float(d.iloc[-1]), _ago(d, 91)
        ch = cur - prev
        out.append(Indicator(
            "policy_rate", "liquidity", "연방기금금리 방향", cur, "%",
            ch, f"3개월 {_fmt_signed(ch * 100, 0, 'bp')}",
            _sig(ch, -0.15, 0.15, higher_is_good=False),
            "연준이 금리를 내리는 중" if ch <= -0.15 else
            ("연준이 금리를 올리는 중" if ch >= 0.15 else "금리 동결 구간"),
        ))
    m = _clean(fred.get("M2SL"), asof)
    if m is not None and len(m) > 13:
        cur, prev = float(m.iloc[-1]), _ago(m, 365)
        yoy = (cur / prev - 1) * 100
        out.append(Indicator(
            "m2", "liquidity", "M2 통화량 (전년비)", yoy, "%",
            yoy, f"YoY {_fmt_signed(yoy, 1, '%')}",
            _sig(yoy, 5.0, 0.0),
            "통화량 빠르게 증가" if yoy >= 5 else ("통화량 감소" if yoy <= 0 else "완만한 증가"),
        ))
    return out


def _credit(fred, px, asof) -> list[Indicator]:
    out = []
    hy = _clean(fred.get("BAMLH0A0HYM2"), asof)
    if hy is not None and len(hy) > 100:
        cur, prev = float(hy.iloc[-1]), _ago(hy, 91)
        ch = cur - prev
        last5 = hy[hy.index >= hy.index[-1] - pd.Timedelta(days=365 * 5)]
        pctile = float((last5 < cur).mean() * 100)
        out.append(Indicator(
            "hy_spread", "credit", "하이일드 신용 스프레드", cur, "%",
            ch, f"3개월 {_fmt_signed(ch * 100, 0, 'bp')} · 5년 백분위 {pctile:.0f}% (낮을수록 양호)",
            _sig(ch, -0.25, 0.50, higher_is_good=False),
            "신용시장 위험선호 개선" if ch <= -0.25 else
            ("신용 스트레스 확대 — 주식보다 먼저 경고하는 경우 많음" if ch >= 0.5 else "신용시장 안정"),
        ))
    rr = _clean(fred.get("DFII10"), asof)
    if rr is not None and len(rr) > 100:
        cur, prev = float(rr.iloc[-1]), _ago(rr, 91)
        ch = cur - prev
        out.append(Indicator(
            "real_rate", "credit", "10년 실질금리", cur, "%",
            ch, f"3개월 {_fmt_signed(ch * 100, 0, 'bp')}",
            _sig(ch, -0.25, 0.25, higher_is_good=False),
            "실질금리 하락 — 자산가격에 우호" if ch <= -0.25 else
            ("실질금리 상승 — 밸류에이션 압박" if ch >= 0.25 else "실질금리 횡보"),
        ))
    dx = _clean(fred.get("DTWEXBGS"), asof)
    if dx is not None and len(dx) > 100:
        cur, prev = float(dx.iloc[-1]), _ago(dx, 91)
        pct = (cur / prev - 1) * 100
        out.append(Indicator(
            "dollar", "credit", "달러지수 (광의)", cur, "",
            pct, f"3개월 {_fmt_signed(pct, 1, '%')}",
            _sig(pct, -2.0, 2.0, higher_is_good=False),
            "달러 약세 — 글로벌 유동성 완화" if pct <= -2 else
            ("달러 강세 — 글로벌 유동성 긴축" if pct >= 2 else "달러 보합"),
        ))
    rel = _rel_return(px, "HYG", "IEF")
    if math.isfinite(rel):
        out.append(Indicator(
            "hyg_ief", "credit", "하이일드채 vs 국채 (HYG/IEF)", None, "",
            rel, f"3개월 상대 {_fmt_signed(rel, 1, '%p')}",
            _sig(rel, 1.0, -1.0),
            "채권시장이 위험을 사는 중" if rel >= 1 else
            ("채권시장이 안전자산으로 도피" if rel <= -1 else "중립"),
        ))
    yc = _clean(fred.get("T10Y2Y"), asof)
    if yc is not None and len(yc) > 100:
        cur, prev = float(yc.iloc[-1]), _ago(yc, 91)
        ch = cur - prev
        if cur < 0:
            note = "장단기 금리 역전 상태"
        elif prev < 0 <= cur:
            note = "역전 해소 직후 — 과거엔 경기침체 직전에 자주 나타남"
        else:
            note = "정상 기울기"
        out.append(Indicator(
            "yield_curve", "credit", "장단기 금리차 (10Y−2Y)", cur, "%p",
            ch, f"3개월 {_fmt_signed(ch * 100, 0, 'bp')}", 0, note, info=True,
        ))
    return out


def _internals(px) -> list[Indicator]:
    out = []
    for t, name in SECTOR_NAMES.items():
        rel = _rel_return(px, t, "SPY")
        if math.isfinite(rel):
            out.append(Indicator(
                f"rs_{t}", "internals", f"{name} ({t}) vs S&P500", None, "",
                rel, f"3개월 상대 {_fmt_signed(rel, 1, '%p')}",
                _sig(rel, 2.0, -2.0),
                "시장보다 강함" if rel >= 2 else ("시장보다 약함" if rel <= -2 else "시장과 비슷"),
            ))
    rel = _rel_return(px, "XLY", "XLP")
    if math.isfinite(rel):
        out.append(Indicator(
            "cyc_def", "internals", "경기소비재 vs 필수소비재", None, "",
            rel, f"3개월 상대 {_fmt_signed(rel, 1, '%p')}",
            _sig(rel, 2.0, -2.0),
            "소비자 경기 낙관" if rel >= 2 else ("방어주로 이동 — 경기 둔화 우려" if rel <= -2 else "중립"),
        ))
    rel = _rel_return(px, "HG=F", "GC=F")
    if math.isfinite(rel):
        out.append(Indicator(
            "cu_au", "internals", "구리/금 비율", None, "",
            rel, f"3개월 상대 {_fmt_signed(rel, 1, '%p')}",
            _sig(rel, 3.0, -3.0),
            "실물경기 기대 상승" if rel >= 3 else ("성장 둔화·안전선호" if rel <= -3 else "중립"),
        ))
    return out


def _trend_ind(px, ticker, label, pillar) -> Optional[Indicator]:
    if ticker not in px:
        return None
    p = px[ticker].dropna()
    if len(p) < 220:
        return None
    ma200 = p.rolling(200).mean()
    cur, m = float(p.iloc[-1]), float(ma200.iloc[-1])
    slope = float(ma200.iloc[-1] / ma200.iloc[-21] - 1) * 100
    gap = (cur / m - 1) * 100
    if cur > m and slope > 0:
        s, note = 1, "200일선 위 + 200일선 상승 — 상승 추세"
    elif cur < m and slope < 0:
        s, note = -1, "200일선 아래 + 200일선 하락 — 하락 추세"
    else:
        s, note = 0, "추세 전환 구간"
    return Indicator(
        f"trend_{ticker}", pillar, label, cur, "",
        gap, f"200일선 대비 {_fmt_signed(gap, 1, '%')}", s, note,
    )


def _trend(px) -> list[Indicator]:
    out = []
    ind = _trend_ind(px, "SPY", "S&P500 추세", "trend")
    if ind:
        out.append(ind)
    if "SPY" in px:
        p = px["SPY"].dropna()
        if len(p) > 210:
            m50, m200 = p.rolling(50).mean().iloc[-1], p.rolling(200).mean().iloc[-1]
            gap = float(m50 / m200 - 1) * 100
            out.append(Indicator(
                "golden", "trend", "50일선 vs 200일선", None, "",
                gap, f"격차 {_fmt_signed(gap, 1, '%')}",
                1 if gap > 0 else -1,
                "골든크로스 상태" if gap > 0 else "데드크로스 상태",
            ))
    rel = _rel_return(px, "RSP", "SPY")
    if math.isfinite(rel):
        out.append(Indicator(
            "breadth", "trend", "시장 폭 (동일가중 vs 시총가중)", None, "",
            rel, f"3개월 상대 {_fmt_signed(rel, 1, '%p')}",
            _sig(rel, 1.0, -3.0),
            "상승이 넓게 퍼짐" if rel >= 1 else
            ("소수 대형주만 오름 — 상승 기반 좁음" if rel <= -3 else "보통"),
        ))
    return out


def _korea(px) -> list[Indicator]:
    out = []
    for t, label in (("^KS11", "코스피 추세"), ("^KQ11", "코스닥 추세")):
        ind = _trend_ind(px, t, label, "korea")
        if ind:
            out.append(ind)
    ch = _ret(px, "KRW=X")
    if math.isfinite(ch):
        cur = float(px["KRW=X"].dropna().iloc[-1])
        out.append(Indicator(
            "usdkrw", "korea", "원/달러 환율", cur, "원",
            ch, f"3개월 {_fmt_signed(ch, 1, '%')}",
            _sig(ch, -2.0, 2.0, higher_is_good=False),
            "원화 강세 — 외국인 자금 유입에 우호" if ch <= -2 else
            ("원화 약세 — 외국인 이탈 압력" if ch >= 2 else "환율 안정"),
        ))
    rel = _rel_return(px, "EWY", "EEM")
    if math.isfinite(rel):
        out.append(Indicator(
            "ewy_eem", "korea", "한국 vs 신흥국 (EWY/EEM)", None, "",
            rel, f"3개월 상대 {_fmt_signed(rel, 1, '%p')}",
            _sig(rel, 2.0, -2.0),
            "신흥국 내 한국 선호" if rel >= 2 else ("한국 소외" if rel <= -2 else "중립"),
        ))
    return out


# ---------------------------------------------------------------- scoring
REGIMES = [
    (40, "strong_on", "강한 Risk-on", "유동성과 시장 신호가 같은 방향. 확신이 있는 아이디어에 집중 투자할 수 있는 구간."),
    (15, "on", "Risk-on", "우호적 환경. 주도 업종 중심으로 비중 유지·확대."),
    (-15, "neutral", "중립", "신호가 엇갈림. 포지션을 줄이고 확인을 기다리는 구간."),
    (-40, "off", "Risk-off", "역풍이 우세. 현금 비중을 늘리고 약한 포지션부터 정리."),
    (-999, "strong_off", "강한 Risk-off", "유동성·신용·시장 모두 경고. 자본 보존이 최우선."),
]


def _pillar_score(inds: list[Indicator]) -> Optional[float]:
    s = [i.signal for i in inds if not i.info and i.signal is not None]
    return float(np.mean(s)) if s else None


def _regime(score: float):
    for th, key, label, desc in REGIMES:
        if score >= th:
            return {"key": key, "label": label, "desc": desc}
    return {"key": REGIMES[-1][1], "label": REGIMES[-1][2], "desc": REGIMES[-1][3]}


def evaluate(fred: dict, px: pd.DataFrame, asof=None) -> dict:
    if asof is None:
        dates = [s.index[-1] for s in fred.values() if s is not None and len(s)]
        if len(px):
            dates.append(px.index[-1])
        asof = max(dates)
    asof = pd.Timestamp(asof)
    pxa = px[px.index <= asof]

    groups = {
        "liquidity": _liquidity(fred, asof),
        "credit": _credit(fred, pxa, asof),
        "internals": _internals(pxa),
        "trend": _trend(pxa),
    }
    pillars, num, den = [], 0.0, 0.0
    for pid, name, w in PILLARS:
        sc = _pillar_score(groups[pid])
        pillars.append({
            "id": pid, "name": name, "weight": w,
            "score": None if sc is None else round(sc * 100),
            "indicators": [i.to_dict() for i in groups[pid]],
        })
        if sc is not None:
            num += w * sc
            den += w
    total = round(num / den * 100) if den else 0

    korea = _korea(pxa)
    ksc = _pillar_score(korea)

    return {
        "asof": asof.strftime("%Y-%m-%d"),
        "score": total,
        "regime": _regime(total),
        "pillars": pillars,
        "korea": {
            "score": None if ksc is None else round(ksc * 100),
            "indicators": [i.to_dict() for i in korea],
        },
        "brief": _brief(total, pillars, korea),
    }


# ---------------------------------------------------------------- brief
def _brief(total, pillars, korea) -> dict:
    by = {p["id"]: p for p in pillars}
    liq = by["liquidity"]["score"]
    mkt_parts = [by[k]["score"] for k in ("internals", "trend") if by[k]["score"] is not None]
    mkt = float(np.mean(mkt_parts)) if mkt_parts else None

    # 드러켄밀러 핵심: 유동성(원인) vs 시장(확인)의 일치/불일치
    if liq is None or mkt is None:
        stance = "데이터가 부족해 판단을 보류합니다."
    elif liq > 0 and mkt > 0:
        stance = "유동성이 받쳐주고 시장도 확인해 주는 '확신 구간'. 가장 강한 아이디어에 크게 베팅할 수 있는 환경입니다."
    elif liq > 0 and mkt <= 0:
        stance = "유동성은 우호적인데 시장이 아직 확인해 주지 않습니다. 시장 신호를 존중해 비중 확대는 확인 후로 미룹니다."
    elif liq <= 0 and mkt > 0:
        stance = "시장은 강하지만 유동성은 역풍입니다. 추세는 따라가되 손절 기준을 엄격히 하고 레버리지는 피합니다."
    else:
        stance = "유동성과 시장이 모두 약합니다. 자본 보존이 우선이고, 공격은 유동성이 돌아선 뒤에 합니다."

    weight = {p["id"]: p["weight"] for p in pillars}
    flat = [(i, weight[p["id"]]) for p in pillars for i in p["indicators"] if not i["info"]]
    supports = [i for i, _ in sorted(flat, key=lambda x: -x[1]) if i["signal"] == 1][:4]
    risks = [i for i, _ in sorted(flat, key=lambda x: -x[1]) if i["signal"] == -1][:4]
    watch = [i for i, _ in sorted(flat, key=lambda x: -x[1]) if i["signal"] == 0][:3]

    def line(i):
        return f"{i['name']}: {i['change_label']} — {i['note']}"

    leaders = sorted(
        [i for i in by["internals"]["indicators"] if i["id"].startswith("rs_") and i["change"] is not None],
        key=lambda i: -i["change"],
    )
    lead_txt = ""
    if len(leaders) >= 2:
        lead_txt = (f"주도: {leaders[0]['name'].split(' (')[0]}, {leaders[1]['name'].split(' (')[0]} / "
                    f"부진: {leaders[-1]['name'].split(' (')[0]}")

    k_sc = _pillar_score(korea) if korea else None
    if k_sc is None:
        k_txt = "한국 데이터 없음"
    elif k_sc > 0.3:
        k_txt = "한국 시장 신호 우호적 (추세·환율·상대강도)"
    elif k_sc < -0.3:
        k_txt = "한국 시장 신호 약함 — 환율과 외국인 흐름 확인 필요"
    else:
        k_txt = "한국 시장 신호 엇갈림"

    return {
        "headline": f"종합 {total:+d}점 · {_regime(total)['label']}",
        "stance": stance,
        "leadership": lead_txt,
        "korea": k_txt,
        "supports": [line(i) for i in supports],
        "risks": [line(i) for i in risks],
        "watch": [line(i) for i in watch],
    }


# ---------------------------------------------------------------- charts
def score_history(fred, px, weeks=104) -> list:
    """과거 시점마다 엔진을 다시 돌려 점수 추이를 만든다 (첫 실행부터 차트가 보이게)."""
    if px is None or px.empty:
        return []
    end = px.index[-1]
    dates = pd.date_range(end=end, periods=weeks, freq="W-FRI")
    out = []
    for d in dates:
        try:
            r = evaluate(fred, px, d)
            out.append([d.strftime("%Y-%m-%d"), r["score"]])
        except Exception:
            continue
    return out


def liquidity_vs_spy(fred, px, weeks=156) -> list:
    nl = net_liquidity(fred)
    if nl is None or "SPY" not in px:
        return []
    spy = px["SPY"].dropna().resample("W-WED").last()
    df = pd.concat({"nl": nl, "spy": spy}, axis=1).ffill().dropna().tail(weeks)
    return [[d.strftime("%Y-%m-%d"), round(float(r.nl), 1), round(float(r.spy), 2)] for d, r in df.iterrows()]


def relative_strength(px) -> list:
    out = []
    for t, name in {**SECTOR_NAMES, "XLY": "경기소비재", "XLP": "필수소비재", "RSP": "동일가중"}.items():
        rel = _rel_return(px, t, "SPY")
        if math.isfinite(rel):
            out.append({"ticker": t, "name": name, "rel": round(rel, 2)})
    return sorted(out, key=lambda x: -x["rel"])
