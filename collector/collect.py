"""
데이터 수집 → 판단 → docs/data/latest.json 저장 → (선택) 텔레그램 알림

환경변수 (모두 선택)
  FRED_API_KEY        있으면 FRED 공식 API, 없으면 공개 CSV 사용
  TELEGRAM_BOT_TOKEN  텔레그램 봇 토큰
  TELEGRAM_CHAT_ID    받을 채팅 ID
  TELEGRAM_DAILY      "1"이면 매일 발송, 아니면 국면이 바뀔 때만 발송
  DASHBOARD_URL       알림에 붙일 대시보드 주소

로컬 테스트: python collector/collect.py --sample   (네트워크 없이 가짜 데이터로 실행)
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "data"
START = "2018-01-01"


# ---------------------------------------------------------------- fetch
def fetch_fred(series_id: str) -> pd.Series:
    import requests
    key = os.getenv("FRED_API_KEY")
    for attempt in range(3):
        try:
            if key:
                r = requests.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={"series_id": series_id, "api_key": key,
                            "file_type": "json", "observation_start": START},
                    timeout=30,
                )
                r.raise_for_status()
                obs = r.json()["observations"]
                s = pd.Series(
                    {pd.Timestamp(o["date"]): float(o["value"]) for o in obs if o["value"] not in (".", "")}
                )
            else:
                r = requests.get(
                    "https://fred.stlouisfed.org/graph/fredgraph.csv",
                    params={"id": series_id, "cosd": START}, timeout=30,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                r.raise_for_status()
                df = pd.read_csv(io.StringIO(r.text))
                s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").values,
                              index=pd.to_datetime(df.iloc[:, 0]))
            return s.dropna().sort_index()
        except Exception as e:  # noqa: BLE001
            print(f"  FRED {series_id} 재시도 {attempt + 1}: {e}")
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"FRED {series_id} 실패")


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(tickers, period="4y", auto_adjust=True, progress=False, threads=True)
    close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": tickers[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna(how="all")


def load_real():
    fred, failed = {}, []
    for sid in engine.FRED_SERIES:
        try:
            fred[sid] = fetch_fred(sid)
            print(f"  FRED {sid}: {len(fred[sid])}개, 최근 {fred[sid].index[-1].date()}")
        except Exception as e:  # noqa: BLE001
            failed.append(sid)
            print(f"  FRED {sid} 건너뜀: {e}")
    px = fetch_prices(engine.PRICE_TICKERS)
    missing = [t for t in engine.PRICE_TICKERS if t not in px or px[t].dropna().empty]
    print(f"  가격 {px.shape[1]}종목, 최근 {px.index[-1].date()}, 누락 {missing}")
    return fred, px, failed + missing


# ---------------------------------------------------------------- sample
def load_sample(seed=7):
    """네트워크 없이 UI·엔진을 시험하기 위한 가짜 데이터."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(START, dt.date.today())
    n = len(days)

    def walk(start, vol, drift=0.0):
        return pd.Series(start * np.exp(np.cumsum(rng.normal(drift, vol, n))), index=days)

    def level(start, vol):
        return pd.Series(start + np.cumsum(rng.normal(0, vol, n)), index=days)

    wk = pd.date_range(START, dt.date.today(), freq="W-WED")
    fred = {
        "WALCL": pd.Series(np.linspace(7.4e6, 6.6e6, len(wk)) + rng.normal(0, 2e4, len(wk)), index=wk),
        "WTREGEN": pd.Series(750e3 + rng.normal(0, 8e4, len(wk)), index=wk),
        "RRPONTSYD": level(400, 6).clip(lower=0),
        "DFF": pd.Series(np.r_[np.full(n - 250, 5.33), np.linspace(5.33, 3.9, 250)], index=days),
        "M2SL": pd.Series(np.linspace(20800, 22300, len(pd.date_range(START, dt.date.today(), freq="MS"))),
                          index=pd.date_range(START, dt.date.today(), freq="MS")),
        "BAMLH0A0HYM2": level(3.4, 0.03).clip(2.5, 9),
        "DFII10": level(1.9, 0.02),
        "DTWEXBGS": walk(122, 0.003),
        "T10Y2Y": level(0.3, 0.02),
    }
    px = pd.DataFrame({
        "SPY": walk(450, 0.010, 0.0004), "RSP": walk(150, 0.010, 0.0003),
        "KRE": walk(50, 0.016, 0.0003), "IYT": walk(250, 0.012, 0.0002),
        "XHB": walk(90, 0.014, 0.0004), "XRT": walk(70, 0.013, 0.0002),
        "SMH": walk(230, 0.018, 0.0008), "IWM": walk(200, 0.013, 0.0003),
        "XLY": walk(180, 0.011, 0.0004), "XLP": walk(75, 0.007, 0.0001),
        "HYG": walk(78, 0.003, 0.00005), "IEF": walk(95, 0.004),
        "HG=F": walk(4.2, 0.013, 0.0002), "GC=F": walk(2300, 0.009, 0.0004),
        "^KS11": walk(2600, 0.011, 0.0003), "^KQ11": walk(850, 0.013, 0.0001),
        "KRW=X": walk(1350, 0.004), "EWY": walk(65, 0.013, 0.0003), "EEM": walk(42, 0.010, 0.0001),
    }, index=days)
    return fred, px, []


# ---------------------------------------------------------------- notify
def send_telegram(result: dict, prev: dict | None) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    changed = prev is None or prev.get("regime", {}).get("key") != result["regime"]["key"]
    if not changed and os.getenv("TELEGRAM_DAILY") != "1":
        print("  국면 변화 없음 → 알림 생략")
        return
    import requests
    b = result["brief"]
    lines = []
    if changed and prev:
        lines.append(f"⚠️ 국면 전환: {prev['regime']['label']} → {result['regime']['label']}")
    lines += [f"📊 {b['headline']} ({result['asof']})", "", b["stance"], ""]
    lines += ["▲ " + s for s in b["supports"][:3]]
    lines += ["▼ " + s for s in b["risks"][:3]]
    if b.get("leadership"):
        lines += ["", b["leadership"]]
    lines.append(f"🇰🇷 {b['korea']}")
    if os.getenv("DASHBOARD_URL"):
        lines += ["", os.getenv("DASHBOARD_URL")]
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": "\n".join(lines)}, timeout=20)
        print(f"  텔레그램 발송: {r.status_code}")
    except Exception as e:  # noqa: BLE001
        print(f"  텔레그램 실패: {e}")


# ---------------------------------------------------------------- main
def main():
    sample = "--sample" in sys.argv
    print("데이터 수집 중..." + (" (샘플)" if sample else ""))
    fred, px, missing = load_sample() if sample else load_real()

    result = engine.evaluate(fred, px)
    result["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    result["sample"] = sample
    result["missing"] = missing
    result["charts"] = {
        "score_history": engine.score_history(fred, px),
        "liquidity": engine.liquidity_vs_spy(fred, px),
        "relative": engine.relative_strength(px),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    latest = OUT_DIR / "latest.json"
    prev = json.loads(latest.read_text("utf-8")) if latest.exists() else None
    if prev and prev.get("sample"):
        prev = None  # 샘플 데이터와는 비교하지 않음

    latest.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    print(f"저장: {latest}  →  {result['brief']['headline']}")

    if not sample:
        send_telegram(result, prev)


if __name__ == "__main__":
    main()
