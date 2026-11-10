# 유동성 나침반 — 드러켄밀러식 시장 신호 대시보드

연준 유동성, 신용, 시장 내부 신호, 추세를 매일 모아 **Risk-on/Risk-off 점수(−100~+100)**로 정리하는 무료 PWA입니다.
안드로이드 크롬에서 "앱 설치"를 하면 일반 앱처럼 쓸 수 있습니다.

```
GitHub Actions (평일 매일)  →  collector/collect.py  →  docs/data/latest.json
                                     │                         │
                              텔레그램 알림(선택)        GitHub Pages(PWA)  →  휴대폰
```

## 판단 구조

| 축 | 가중치 | 보는 것 |
|---|---|---|
| 유동성 | 35% | 순유동성(연준자산−TGA−역레포) 13주 변화, 연준 총자산(QE/QT), 연방기금금리 방향, M2 전년비 |
| 신용·금리·달러 | 25% | 하이일드 스프레드, 10년 실질금리, 달러지수, HYG/IEF · 장단기금리차는 참고용 |
| 시장 내부 | 25% | 지역은행·운송·주택·소매·반도체·소형주의 S&P500 대비 3개월 상대강도, 경기소비재/필수소비재, 구리/금 |
| 추세 | 15% | S&P500 200일선, 50/200일선, 동일가중 vs 시총가중(시장 폭) |
| 🇰🇷 한국 | 별도 표시 | 코스피·코스닥 추세, 원/달러, EWY/EEM |

- 지표마다 +1(우호), 0(중립), −1(비우호) 신호를 매깁니다. 축 점수는 신호의 평균이고, 종합 점수는 축 점수의 가중합입니다.
- 지표의 수준보다 **변화(3개월·13주)**에 점수를 줍니다. 18~24개월 앞을 보라는 원칙을 반영한 것입니다.
- **"드러켄밀러라면"** 문장은 유동성(원인)과 시장(확인)이 같은 방향인지 엇갈리는지에 따라 네 가지로 나뉩니다.
- 임계값은 모두 `collector/engine.py`에 있으니 원하는 대로 조정하면 됩니다.

## 설치 (10분, 전부 무료)

1. **저장소 만들기**: GitHub에서 새 저장소(public)를 만들고 이 폴더 전체를 올립니다.
2. **Pages 켜기**: Settings → Pages → Source: `Deploy from a branch` → Branch: `main` / 폴더 `/docs` → Save
   - 주소는 `https://<아이디>.github.io/<저장소명>/` 입니다.
3. **Actions 쓰기 권한**: Settings → Actions → General → Workflow permissions → `Read and write permissions` 선택
4. **(권장) FRED API 키**: https://fred.stlouisfed.org/docs/api/api_key.html 에서 무료로 발급
   - Settings → Secrets and variables → Actions → New repository secret → 이름 `FRED_API_KEY`
   - 키가 없어도 공개 CSV로 동작하지만, 키를 쓰는 쪽이 더 안정적입니다.
5. **첫 실행**: Actions 탭 → `update-data` → `Run workflow`
   - 1~2분 뒤 대시보드가 실제 데이터로 바뀝니다. 그 전까지는 샘플 데이터라는 배너가 보입니다.
6. **휴대폰 설치**: 안드로이드 크롬으로 Pages 주소 접속 → 상단 `설치` 버튼 또는 메뉴 ⋮ → `앱 설치`

## 텔레그램 알림 (선택)

1. 텔레그램에서 `@BotFather` → `/newbot` → 봇 토큰을 받습니다.
2. 만든 봇에게 아무 메시지나 보낸 뒤 `https://api.telegram.org/bot<토큰>/getUpdates`를 열어 `chat.id`를 확인합니다.
3. Secrets에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`를 추가합니다.
4. (선택) Variables에 다음을 추가합니다.
   - `DASHBOARD_URL`: Pages 주소
   - `TELEGRAM_DAILY`: `1` (매일 발송) · 비워두면 **국면이 바뀔 때만** 알림이 옵니다.

## 로컬 테스트

```bash
pip install -r collector/requirements.txt
python collector/collect.py --sample   # 네트워크 없이 가짜 데이터로 실행
python collector/collect.py            # 실제 데이터
cd docs && python -m http.server 8000  # http://localhost:8000
```

## APK로 만들고 싶다면

Pages 주소를 https://www.pwabuilder.com 에 넣고 Android 패키지를 받으면 APK로 설치할 수 있습니다(무료). 플레이스토어에 올릴 때만 등록비 $25가 한 번 듭니다.

## 주의

- 데이터는 대부분 일 단위입니다. 연준 대차대조표와 TGA는 주 단위로 갱신됩니다.
- yfinance는 비공식 라이브러리라 가끔 일부 종목이 누락될 수 있습니다. 누락되면 화면에 표시되고, 나머지 지표로 점수를 계산합니다.
- 공개 데이터를 규칙으로 점수화한 참고 자료이며 투자 조언이 아닙니다.
