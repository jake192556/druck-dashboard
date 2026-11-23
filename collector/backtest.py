"""
유동성 나침반 점수 백테스트
------------------------------
질문: 종합 점수(−100~+100)가 높을 때 S&P500(SPY)의 이후 수익률이 실제로 더 좋았나?

방법
- 2007년 중반부터 매주 금요일 종가 기준으로 engine.evaluate()를 다시 돌린다 (지금 앱과 같은 코드·같은 기준값).
- FRED 지표는 실제 발표 시차만큼 날짜를 늦춰서 '그날 알 수 없던 숫자'를 쓰지 않는다.
- SPY 이후 수익률은 신호 다음 거래일 종가부터 잰다 (신호 당일 종가 매수 가정 금지).
- 비교 기준: 그냥 보유(Buy & Hold), 단순 200일선 추세(SPY > 200일선).

한계 (보고서에도 적는다)
- FRED는 지금 시점의 수정된 값이다 (당시 최초 발표치 아님). 주간 신호를 겹쳐 쓰므로 표본이 서로 독립이 아니다.
- 기준값은 이미 정해진 것을 그대로 평가한다. 여기서 기준값을 고르면 과최적화가 된다.

실행: python collector/backtest.py           (GitHub Actions, 실제 데이터)
      python collector/backtest.py --sample  (네트워크 없이 형식 점검)
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402
import engine  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backtest"
EVAL_START = "2007-07-01"
HORIZONS = {"1m": 21, "3m": 63, "6m": 126}
COST = 0.0005  # 편도 거래비용 (전환 시)

# 관측일 → 실제로 알 수 있게 되는 날까지의 지연 (달력일, 보수적으로)
PUBLICATION_LAG_DAYS = {
    "WALCL": 2,         # 수요일 기준, 목요일 오후 발표
    "WTREGEN": 2,
    "RRPONTSYD": 1,
    "DFF": 1,
    "M2SL": 55,         # 월초 날짜로 기록, 다음 달 말께 발표
    "BAMLH0A0HYM2": 1,
    "DFII10": 1,
    "DTWEXBGS": 7,      # 주간 발표
    "T10Y2Y": 1,
}


# ---------------------------------------------------------------- data
def load(sample: bool):
    if sample:
        fred, px, _ = collect.load_sample()
        return fred, px
    collect.START = "2006-01-01"
    fred = {}
    for sid in engine.FRED_SERIES:
        try:
            fred[sid] = collect.fetch_fred(sid)
            print(f"  FRED {sid}: {fred[sid].index[0].date()} ~ {fred[sid].index[-1].date()} ({len(fred[sid])})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  FRED {sid} 실패: {e}", flush=True)
    px = collect.fetch_prices(engine.PRICE_TICKERS, budget_end=time.time() + 600, period="max")
    px = px[px.index >= "2005-01-01"]
    for t in engine.PRICE_TICKERS:
        s = px[t].dropna() if t in px else pd.Series(dtype=float)
        print(f"  {t}: {s.index[0].date() if len(s) else '-'} ~ {s.index[-1].date() if len(s) else '-'}", flush=True)
    return fred, px


def lag_fred(fred: dict) -> dict:
    out = {}
    for k, s in fred.items():
        lag = PUBLICATION_LAG_DAYS.get(k, 1)
        out[k] = pd.Series(s.values, index=s.index + pd.Timedelta(days=lag)).sort_index()
    return out


# ---------------------------------------------------------------- weekly scores
def weekly_scores(fred_l: dict, px: pd.DataFrame) -> pd.DataFrame:
    spy = px["SPY"].dropna()
    fridays = pd.date_range(max(pd.Timestamp(EVAL_START), spy.index[0]), spy.index[-1], freq="W-FRI")
    rows, last = [], None
    t0 = time.time()
    for f in fridays:
        asof = spy.index[spy.index <= f]
        if not len(asof):
            continue
        asof = asof[-1]
        if asof == last:
            continue  # 휴장 주
        last = asof
        r = engine.evaluate(fred_l, px, asof)
        row = {"date": asof, "score": r["score"], "regime": r["regime"]["key"]}
        for p in r["pillars"]:
            row[f"p_{p['id']}"] = p["score"]
            row[f"n_{p['id']}"] = sum(1 for i in p["indicators"] if not i["info"] and i["signal"] is not None)
        rows.append(row)
    print(f"  주간 평가 {len(rows)}회 ({time.time() - t0:.0f}초)", flush=True)
    df = pd.DataFrame(rows).set_index("date")

    # SPY 200일선 추세 (비교 기준)
    ma200 = spy.rolling(200).mean()
    df["trend200"] = [bool(spy.loc[d] > ma200.loc[d]) if not math.isnan(ma200.loc[d]) else np.nan for d in df.index]

    # 이후 수익률: 신호 다음 거래일 종가에 진입
    pos = {d: i for i, d in enumerate(spy.index)}
    for name, h in HORIZONS.items():
        vals, mins = [], []
        for d in df.index:
            i0 = pos[d] + 1
            i1 = i0 + h
            if i1 < len(spy):
                vals.append(spy.iloc[i1] / spy.iloc[i0] - 1)
                mins.append(spy.iloc[i0:i1 + 1].min() / spy.iloc[i0] - 1)
            else:
                vals.append(np.nan)
                mins.append(np.nan)
        df[f"fwd_{name}"] = vals
        df[f"worst_{name}"] = mins
    return df


# ---------------------------------------------------------------- stats
def spearman(a: pd.Series, b: pd.Series):
    m = pd.concat([a, b], axis=1).dropna()
    n = len(m)
    if n < 10:
        return None, n, None
    rho = float(m.iloc[:, 0].rank().corr(m.iloc[:, 1].rank()))
    t = rho * math.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
    return rho, n, t


def corr_block(df: pd.DataFrame, col: str, fwd: str, step: int) -> dict:
    """전체(겹침) + 겹치지 않는 표본(step주 간격) 순위상관."""
    full = spearman(df[col], df[fwd])
    sub = df.iloc[::step]
    non = spearman(sub[col], sub[fwd])
    return {"rho_overlap": full[0], "n_overlap": full[1],
            "rho_nonoverlap": non[0], "n_nonoverlap": non[1], "t_nonoverlap": non[2]}


def bucket_table(df: pd.DataFrame, key: pd.Series, order: list) -> list:
    out = []
    for k in order:
        g = df[key == k]
        row = {"bucket": str(k), "weeks": int(len(g)), "share": round(len(g) / max(1, len(df)) * 100, 1)}
        for name in HORIZONS:
            v = g[f"fwd_{name}"].dropna()
            row[f"mean_{name}"] = None if v.empty else round(v.mean() * 100, 2)
            row[f"median_{name}"] = None if v.empty else round(v.median() * 100, 2)
            row[f"hit_{name}"] = None if v.empty else round((v > 0).mean() * 100, 1)
        w = g["worst_3m"].dropna()
        row["worst3m_mean"] = None if w.empty else round(w.mean() * 100, 2)
        row["dd10_rate"] = None if w.empty else round((w <= -0.10).mean() * 100, 1)
        out.append(row)
    return out


# ---------------------------------------------------------------- strategy
def strategy(df: pd.DataFrame, px: pd.DataFrame, fred: dict, signals: dict) -> list:
    """매주 신호 → 다음 거래일 종가에 SPY 보유/현금 전환. 현금은 연방기금금리."""
    spy = px["SPY"].dropna()
    pos = {d: i for i, d in enumerate(spy.index)}
    dff = fred.get("DFF")
    dates = list(df.index)
    out = []
    for name, sig in signals.items():
        equity, eq_curve, prev_in, switches, weeks_in = 1.0, [], None, 0, 0
        rets = []
        for k in range(len(dates) - 1):
            d, nd = dates[k], dates[k + 1]
            i0, i1 = pos[d] + 1, pos[nd] + 1
            if i1 >= len(spy):
                break
            inn = bool(sig.iloc[k]) if not pd.isna(sig.iloc[k]) else True
            if inn:
                r = spy.iloc[i1] / spy.iloc[i0] - 1
                weeks_in += 1
            else:
                rate = 0.0
                if dff is not None:
                    s = dff[dff.index <= d]
                    rate = float(s.iloc[-1]) / 100 if len(s) else 0.0
                r = rate * (spy.index[i1] - spy.index[i0]).days / 365
            if prev_in is not None and inn != prev_in:
                r -= COST
                switches += 1
            prev_in = inn
            equity *= 1 + r
            rets.append(r)
            eq_curve.append((nd, equity))
        rets = np.array(rets)
        years = (eq_curve[-1][0] - dates[0]).days / 365.25 if eq_curve else 1
        cagr = equity ** (1 / years) - 1 if years > 0 else 0
        vol = rets.std() * math.sqrt(52) if len(rets) else 0
        curve = pd.Series([e for _, e in eq_curve], index=[d for d, _ in eq_curve])
        mdd = float((curve / curve.cummax() - 1).min()) if len(curve) else 0
        out.append({
            "strategy": name,
            "cagr": round(cagr * 100, 2),
            "vol": round(vol * 100, 2),
            "sharpe_like": round(cagr / vol, 2) if vol else None,
            "max_drawdown": round(mdd * 100, 1),
            "time_in_market": round(weeks_in / max(1, len(rets)) * 100, 1),
            "switches": switches,
            "final_multiple": round(equity, 2),
            "_curve": curve,
        })
    return out


# ---------------------------------------------------------------- report
def fmt(v, suf=""):
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v}{suf}"


def report(meta, corr, pillar_corr, regimes, quint, strat, periods, coverage) -> str:
    L = []
    L.append("# 유동성 나침반 점수 백테스트\n")
    L.append(f"- 기간: {meta['start']} ~ {meta['end']} · 주간 신호 {meta['weeks']}개")
    L.append("- FRED 지표는 발표 시차만큼 늦춰 사용, SPY 이후 수익률은 신호 다음 거래일 종가부터")
    L.append("- 기준값·가중치는 앱과 동일 (백테스트로 고르지 않음)")
    if meta.get("sample"):
        L.append("\n> ⚠️ 샘플(가짜) 데이터로 돌린 형식 점검 결과입니다. 숫자에 의미 없음.\n")
    L.append("\n## 1. 점수와 이후 수익률의 순위상관 (Spearman)\n")
    L.append("| 기간 | ρ (전체, 겹침) | ρ (겹치지 않는 표본) | 표본 수 | t값 |")
    L.append("|---|---|---|---|---|")
    for h, c in corr.items():
        L.append(f"| {h} | {fmt(round(c['rho_overlap'], 3) if c['rho_overlap'] is not None else None)} | "
                 f"{fmt(round(c['rho_nonoverlap'], 3) if c['rho_nonoverlap'] is not None else None)} | "
                 f"{c['n_nonoverlap']} | {fmt(round(c['t_nonoverlap'], 2) if c['t_nonoverlap'] is not None else None)} |")
    L.append("\n대략 |t| ≥ 2 이면 우연으로 보기 어렵다는 뜻입니다.\n")
    L.append("## 2. 축별 순위상관 (3개월, 겹치지 않는 표본)\n")
    L.append("| 축 | ρ | t값 | 표본 |")
    L.append("|---|---|---|---|")
    for k, c in pillar_corr.items():
        L.append(f"| {k} | {fmt(round(c['rho_nonoverlap'], 3) if c['rho_nonoverlap'] is not None else None)} | "
                 f"{fmt(round(c['t_nonoverlap'], 2) if c['t_nonoverlap'] is not None else None)} | {c['n_nonoverlap']} |")
    for title, table in (("3. 국면별 SPY 이후 수익률", regimes), ("4. 점수 5분위별 SPY 이후 수익률", quint)):
        L.append(f"\n## {title}\n")
        L.append("| 구간 | 주수 | 비중 | 3개월 평균 | 3개월 상승확률 | 6개월 평균 | 3개월 내 최악 평균 | 3개월 내 −10% 이상 하락 빈도 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in table:
            L.append(f"| {r['bucket']} | {r['weeks']} | {r['share']}% | {fmt(r['mean_3m'], '%')} | {fmt(r['hit_3m'], '%')} | "
                     f"{fmt(r['mean_6m'], '%')} | {fmt(r['worst3m_mean'], '%')} | {fmt(r['dd10_rate'], '%')} |")
    L.append("\n## 5. 단순 전략 비교 (주간 전환, 현금은 연방기금금리, 전환 비용 0.05%)\n")
    L.append("| 전략 | 연수익률 | 변동성 | 수익/변동성 | 최대낙폭 | 시장 참여 | 전환 횟수 | 최종 배수 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in strat:
        L.append(f"| {s['strategy']} | {s['cagr']}% | {s['vol']}% | {fmt(s['sharpe_like'])} | {s['max_drawdown']}% | "
                 f"{s['time_in_market']}% | {s['switches']} | {s['final_multiple']}x |")
    L.append("\n## 6. 기간별 안정성 (3개월 순위상관, 겹치지 않는 표본)\n")
    L.append("| 기간 | ρ | t값 | 표본 |")
    L.append("|---|---|---|---|")
    for k, c in periods.items():
        L.append(f"| {k} | {fmt(round(c['rho_nonoverlap'], 3) if c['rho_nonoverlap'] is not None else None)} | "
                 f"{fmt(round(c['t_nonoverlap'], 2) if c['t_nonoverlap'] is not None else None)} | {c['n_nonoverlap']} |")
    L.append("\n## 7. 지표 데이터 확보율 (평가 주 중 신호 계산된 비율)\n")
    L.append("| 축 | 평균 지표 수 | 최소 |")
    L.append("|---|---|---|")
    for k, v in coverage.items():
        L.append(f"| {k} | {v['mean']} | {v['min']} |")
    L.append("\n## 한계\n")
    L.append("- FRED 값은 현재 시점의 수정치입니다. 당시 최초 발표치와 다를 수 있습니다.")
    L.append("- 주간 신호의 3·6개월 수익률은 기간이 겹쳐 독립 표본이 아닙니다. 판단은 '겹치지 않는 표본' 기준으로 하세요.")
    L.append("- 일부 ETF는 상장 전 구간에서 빠져 있어 초기 점수는 더 적은 지표로 계산됐습니다 (7번 표).")
    L.append("- 과거 성과가 미래를 보장하지 않습니다.")
    return "\n".join(L) + "\n"


def main():
    sample = "--sample" in sys.argv
    OUT.mkdir(exist_ok=True)
    print("데이터 로드..." + (" (샘플)" if sample else ""), flush=True)
    fred, px = load(sample)
    fred_l = lag_fred(fred)
    global EVAL_START
    if sample:
        EVAL_START = str((px.index[0] + pd.Timedelta(days=400)).date())
    df = weekly_scores(fred_l, px)
    df.to_csv(OUT / "weekly.csv", float_format="%.5f")

    valid = df.dropna(subset=["fwd_3m"])
    step = {"1m": 4, "3m": 13, "6m": 26}
    corr = {h: corr_block(valid if h != "6m" else df.dropna(subset=["fwd_6m"]), "score", f"fwd_{h}", step[h]) for h in HORIZONS}
    pillar_corr = {pid: corr_block(valid, f"p_{pid}", "fwd_3m", 13) for pid, _, _ in engine.PILLARS}
    pillar_corr["trend200 (비교)"] = corr_block(valid.assign(t=valid["trend200"].astype(float)), "t", "fwd_3m", 13)

    labels = {k: l for _, k, l, _ in engine.REGIMES}
    reg_key = valid["regime"].map(labels)
    regimes = bucket_table(valid, reg_key, [labels[k] for _, k, _, _ in engine.REGIMES])
    q = pd.qcut(valid["score"].rank(method="first"), 5, labels=["Q1 (최저)", "Q2", "Q3", "Q4", "Q5 (최고)"])
    quint = bucket_table(valid, q, ["Q1 (최저)", "Q2", "Q3", "Q4", "Q5 (최고)"])
    for r, lab in zip(quint, ["Q1 (최저)", "Q2", "Q3", "Q4", "Q5 (최고)"]):
        g = valid[q == lab]["score"]
        r["bucket"] = f"{lab} [{int(g.min())}~{int(g.max())}]"

    strat = strategy(df, px, fred, {
        "그냥 보유 (Buy & Hold)": pd.Series(True, index=df.index),
        "점수 > −15 일 때만 보유": df["score"] > -15,
        "점수 ≥ 15 일 때만 보유": df["score"] >= 15,
        "SPY > 200일선 일 때만 보유": df["trend200"],
        "점수 > −15 AND 200일선 위": (df["score"] > -15) & (df["trend200"] == True),  # noqa: E712
    })
    periods = {}
    for a, b in (("2007-07", "2012-12"), ("2013-01", "2019-12"), ("2020-01", "2026-12")):
        sub = valid[(valid.index >= a) & (valid.index <= b + "-31")]
        periods[f"{a} ~ {b}"] = corr_block(sub, "score", "fwd_3m", 13)
    coverage = {pid: {"mean": round(float(df[f"n_{pid}"].mean()), 1), "min": int(df[f"n_{pid}"].min())} for pid, _, _ in engine.PILLARS}

    meta = {"start": str(df.index[0].date()), "end": str(df.index[-1].date()), "weeks": int(len(df)), "sample": sample,
            "score_distribution": {k: round(float(v), 1) for k, v in df["score"].describe().items()}}
    curves = {s["strategy"]: [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in s.pop("_curve").iloc[::4].items()] for s in strat}
    res = {"meta": meta, "corr": corr, "pillar_corr": pillar_corr, "regimes": regimes, "quintiles": quint,
           "strategies": strat, "periods": periods, "coverage": coverage, "curves": curves}
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), "utf-8")
    (OUT / "REPORT.md").write_text(report(meta, corr, pillar_corr, regimes, quint, strat, periods, coverage), "utf-8")
    print((OUT / "REPORT.md").read_text("utf-8"))


if __name__ == "__main__":
    main()
