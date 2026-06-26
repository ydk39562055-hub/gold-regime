#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_signals.py — 금 레짐 자동수집기

매주(또는 매달) 실행하면 FRED + yfinance에서 빠르게 움직이는 지표를 끌어와
data/snapshot.md 를 최신 숫자로 덮어쓴다. 임계값을 넘은 항목엔 자동으로 ⚠️ 플래그.

사용법 (폴더에서 cmd 열고):
    python data\\fetch_signals.py

필요 패키지:
    pip install requests          (FRED용, 필수)
    pip install yfinance          (달러/금/은용, 선택 — 없으면 그 항목만 건너뜀)

FRED 키: data/.fred_key 파일 첫 줄에서 읽음. 없으면 환경변수 FRED_API_KEY.
키 발급: https://fredaccount.stlouisfed.org/apikeys
"""

import os
import sys
import datetime

# 윈도우 콘솔(cp949)에서 한글/이모지 출력 시 깨짐·크래시 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# FRED 키 로드
# ---------------------------------------------------------------------------
def load_fred_key():
    key_file = os.path.join(HERE, ".fred_key")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            k = f.read().strip()
            if k:
                return k
    env = os.environ.get("FRED_API_KEY", "").strip()
    if env:
        return env
    return None


# ---------------------------------------------------------------------------
# FRED 최신 관측치 가져오기
# ---------------------------------------------------------------------------
def fred_latest(series_id, api_key):
    """(값, 날짜) 반환. 실패 시 (None, None)."""
    import requests
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 8,  # 결측(.) 대비 여유
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        for obs in r.json().get("observations", []):
            v = obs.get("value", ".")
            if v not in (".", "", None):
                return float(v), obs.get("date")
    except Exception as e:
        print(f"  [FRED 실패] {series_id}: {e}")
    return None, None


# ---------------------------------------------------------------------------
# yfinance 최신 종가
# ---------------------------------------------------------------------------
def yf_latest(ticker):
    try:
        import yfinance as yf
    except ImportError:
        return None, None
    try:
        data = yf.Ticker(ticker).history(period="5d")
        if len(data) == 0:
            return None, None
        last = data.iloc[-1]
        return float(last["Close"]), str(data.index[-1].date())
    except Exception as e:
        print(f"  [yfinance 실패] {ticker}: {e}")
        return None, None


def stooq_latest(sym):
    """yfinance 폴백 (클라우드에서 Yahoo 막힐 때). (값, 날짜)."""
    import requests
    url = f"https://stooq.com/q/l/?s={sym}&f=sd2t2c&e=csv"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        line = r.text.strip().splitlines()[-1]
        parts = line.split(",")
        # 형식: Symbol,Date,Time,Close
        close, date = parts[-1], parts[1]
        if close not in ("N/D", "", None):
            return float(close), date
    except Exception as e:
        print(f"  [stooq 실패] {sym}: {e}")
    return None, None


# ---------------------------------------------------------------------------
# 임계값 자동 판정 (간단한 것만 — 레짐 판정은 사람이)
# ---------------------------------------------------------------------------
def flag(name, val):
    if val is None:
        return ""
    if name == "DFII10":
        if val >= 2.30:
            return "⚠️ 2.30%↑ 악재구간 (달러 103↑과 동시면 강한 매도)"
        if val <= 2.0:
            return "우호 (2.0% 부근/하락)"
        return "중립"
    if name == "DXY":
        if val >= 103:
            return "⚠️ 103↑ 악재 (실질금리와 동시면 강한 매도)"
        if val <= 99:
            return "우호 (99 부근)"
        return "중립"
    if name == "T10Y2Y":
        if val < 0:
            return "⚠️ 역전(음수) — 침체 임박 신호"
        if val < 0.2:
            return "축소 중 (단 완만화 ≠ 역전, 신호는 역전부터)"
        return "정상(양수)"
    if name == "DGS10":
        if val >= 5.5:
            return "⚠️ 5.5%↑ — 금→국채 자금역류 트리거"
        return ""
    if name == "MICH":
        if val >= 4.6:
            return "⚠️ 4.6%↑ 기대인플레 고착 우려"
        return ""
    if name == "DEBT_GDP":
        if val >= 120:
            return "재정지배 압력 (120%+)"
        return ""
    if name == "GS_RATIO":
        if val >= 85:
            return "⚠️ 85:1↑ — 침체 초기 신호(은 약세)"
        return "평균권(60:1 부근)"
    return ""


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def fmt(v, nd=2):
    return f"{v:.{nd}f}" if v is not None else "—(수집 실패)"


def flag_level(fl):
    """플래그 문자열 → 카드 색 등급."""
    if "⚠" in fl:   # ⚠️
        return "warn"
    if "우호" in fl or "정상" in fl or "평균권" in fl:
        return "good"
    return "neutral"


# ---------------------------------------------------------------------------
# 폰에서 보는 단일 HTML 대시보드 생성 (데이터 박아서 자체완결)
# ---------------------------------------------------------------------------
def build_dashboard(rows_week, rows_month, gold_str, updated):
    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def cards(rows):
        out = []
        for name, code, val, date, fl in rows:
            lvl = flag_level(fl)
            flag_html = f'<span class="flag {lvl}">{esc(fl)}</span>' if fl else ""
            out.append(f"""<div class="ind {lvl}">
      <div class="ind-top"><span class="ind-name">{esc(name)}</span><span class="ind-val">{esc(val)}</span></div>
      <div class="ind-meta"><span class="ind-src">{esc(code)} · {esc(date or '—')}</span>{flag_html}</div>
    </div>""")
        return "\n    ".join(out)

    warn_count = sum(1 for r in (rows_week + rows_month) if "⚠" in r[4])
    if warn_count == 0:
        read = "임계값 경고 없음 — 레짐 유지가 기본값."
        read_lvl = "good"
    else:
        read = f"임계값 경고 {warn_count}개 — 월간 카드에서 의미 점검."
        read_lvl = "warn"

    week_cards = cards(rows_week)
    month_cards = cards(rows_month)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>금 레짐 대시보드</title>
<style>
  :root{{
    --bg:#0f1115; --surface:#181b22; --surface2:#1f232c; --border:#2a2f3a;
    --text:#e6e8ec; --muted:#8b929e; --muted2:#5d646f;
    --warn:#e0a23a; --good:#4a8fd6; --gold:#d9b25a; --radius:14px;
  }}
  *{{box-sizing:border-box; -webkit-tap-highlight-color:transparent;}}
  html,body{{margin:0;padding:0;}}
  body{{background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
    line-height:1.45; font-size:16px; max-width:560px; margin:0 auto;
    padding:0 0 40px;}}
  header{{padding:18px 16px 12px; border-bottom:1px solid var(--border);}}
  .h-title{{font-size:14px; color:var(--muted); font-weight:600;}}
  .h-gold{{font-size:34px; font-weight:800; color:var(--gold); margin-top:2px;}}
  .h-gold small{{font-size:14px; color:var(--muted); font-weight:600;}}
  .h-upd{{font-size:11px; color:var(--muted2); margin-top:4px;}}
  .read{{margin:12px; padding:12px 14px; border-radius:var(--radius);
    background:var(--surface); border:1px solid var(--border); font-size:14px; font-weight:600;}}
  .read.warn{{border-color:rgba(224,162,58,.5); background:rgba(224,162,58,.08); color:#f0c266;}}
  .read.good{{border-color:rgba(74,143,214,.4); background:rgba(74,143,214,.07);}}
  h2.sec{{font-size:13px; color:var(--muted); margin:20px 16px 8px; font-weight:700; letter-spacing:.3px;}}
  .ind{{margin:8px 12px; padding:11px 13px; background:var(--surface);
    border:1px solid var(--border); border-left:4px solid var(--border); border-radius:10px;}}
  .ind.warn{{border-left-color:var(--warn);}}
  .ind.good{{border-left-color:var(--good);}}
  .ind-top{{display:flex; justify-content:space-between; align-items:baseline; gap:8px;}}
  .ind-name{{font-size:14px; color:var(--muted);}}
  .ind-val{{font-size:20px; font-weight:800;}}
  .ind-meta{{display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:5px;}}
  .ind-src{{font-size:11px; color:var(--muted2);}}
  .flag{{font-size:11px; font-weight:700; padding:2px 7px; border-radius:999px;}}
  .flag.warn{{background:rgba(224,162,58,.16); color:var(--warn);}}
  .flag.good{{background:rgba(74,143,214,.14); color:var(--good);}}
  .flag.neutral{{background:var(--surface2); color:var(--muted);}}
  .check{{margin:8px 12px; padding:6px 4px;}}
  .check label{{display:flex; align-items:flex-start; gap:10px; padding:10px 12px;
    background:var(--surface); border:1px solid var(--border); border-radius:10px;
    margin-bottom:7px; cursor:pointer; font-size:14px;}}
  .check input{{width:22px; height:22px; flex:none; margin-top:1px; accent-color:var(--warn);}}
  .check label.on{{border-color:rgba(224,162,58,.4); background:rgba(224,162,58,.06);}}
  table.mtx{{width:calc(100% - 24px); margin:8px 12px; border-collapse:collapse; font-size:12.5px;}}
  table.mtx th,table.mtx td{{border:1px solid var(--border); padding:7px 8px; text-align:center;}}
  table.mtx th{{background:var(--surface2); color:var(--muted); font-weight:700;}}
  table.mtx td.bull{{color:var(--gold); font-weight:800;}}
  table.mtx td.bear{{color:var(--good); font-weight:800;}}
  .note{{font-size:12px; color:var(--muted2); margin:14px 16px; line-height:1.7;}}
  .note b{{color:var(--muted);}}
</style>
</head>
<body>
<header>
  <div class="h-title">금 레짐 대시보드 · 주간 점검</div>
  <div class="h-gold">${esc(gold_str)} <small>/oz</small></div>
  <div class="h-upd">갱신: {esc(updated)} · 손절선 $4,180 / 리스크모드 $3,900</div>
</header>

<div class="read {read_lvl}">{esc(read)}</div>

<h2 class="sec">주간 지표 (빠르게 움직임)</h2>
    {week_cards}

<h2 class="sec">월간 / 분기 지표 (FRED)</h2>
    {month_cards}

<h2 class="sec">이번 주 빠른 판단 (5개)</h2>
<div class="check" id="chk">
  <label><input type="checkbox" data-k="1"><span>금가 vs 손절선 $4,180 / $3,900 확인</span></label>
  <label><input type="checkbox" data-k="2"><span>실질금리 2.30%↑? · 달러 103↑? (동시면 강한 악재)</span></label>
  <label><input type="checkbox" data-k="3"><span>스프레드 역전(음수)? — 완만화는 신호 아님</span></label>
  <label><input type="checkbox" data-k="4"><span>반증조건(PART 4) 점등 늘었나?</span></label>
  <label><input type="checkbox" data-k="5"><span>→ 레짐 유지 / 눌림목 / 과열 / ⚠️월간 당김 중 결정</span></label>
</div>

<h2 class="sec">레짐 매트릭스 (월간 판정용)</h2>
<table class="mtx">
  <tr><th>Q1 금리로 잡나</th><th>Q2 바닥 살았나</th><th>레짐</th></tr>
  <tr><td>NO</td><td>YES</td><td class="bull">금 강세 (분할매수·보유)</td></tr>
  <tr><td>NO</td><td>NO</td><td>바닥약화 (신중)</td></tr>
  <tr><td>YES</td><td>YES</td><td>천장강화 (관망·박스)</td></tr>
  <tr><td>YES</td><td>NO</td><td class="bear">금 약세 (보수·헷지)</td></tr>
</table>

<div class="note">
  <b>주간은 레짐을 안 바꾼다.</b> 반증 2개+ 켜지면 월간 정밀판정을 당긴다.<br>
  자동수집 안 됨(분기 손수): 중앙은행 톤(WGC) · ETF 톤 · COT · COFER 달러비중.<br>
  이 파일은 <b>python data/fetch_signals.py</b> 실행 때마다 새 숫자로 덮어쓴다.
</div>

<script>
// 주차별 체크 상태 저장 (월요일 기준 주차 키)
function weekKey(){{
  var d=new Date(); var day=(d.getDay()+6)%7; d.setDate(d.getDate()-day);
  return 'goldchk:'+d.getFullYear()+'-'+(d.getMonth()+1)+'-'+d.getDate();
}}
var KEY=weekKey();
var saved={{}};
try{{ saved=JSON.parse(localStorage.getItem(KEY)||'{{}}'); }}catch(e){{}}
document.querySelectorAll('#chk input').forEach(function(cb){{
  var k=cb.getAttribute('data-k');
  cb.checked=!!saved[k];
  if(cb.checked) cb.closest('label').classList.add('on');
  cb.addEventListener('change', function(){{
    saved[k]=cb.checked; localStorage.setItem(KEY, JSON.stringify(saved));
    cb.closest('label').classList.toggle('on', cb.checked);
  }});
}});
</script>
</body>
</html>"""


def main():
    key = load_fred_key()
    if not key:
        print("FRED 키를 찾지 못함. data/.fred_key 파일을 만들고 키를 한 줄 넣거나")
        print("환경변수 FRED_API_KEY 를 설정하세요. (발급: fredaccount.stlouisfed.org/apikeys)")
        sys.exit(1)

    print("수집 중...")

    # --- FRED (주간/일간) ---
    dfii10, d1 = fred_latest("DFII10", key)      # 10년 실질금리
    t10y2y, d2 = fred_latest("T10Y2Y", key)      # 장단기 스프레드
    dgs10, d3 = fred_latest("DGS10", key)        # 10년 명목
    # --- FRED (월간/분기) ---
    mich, d4 = fred_latest("MICH", key)          # 기대인플레(미시간 1년)
    pce, d5 = fred_latest("PCEPILFE", key)       # 근원 PCE (지수)
    debt, d6 = fred_latest("GFDEGDQ188S", key)   # 부채/GDP (%)

    # --- yfinance (일간) + 클라우드 폴백(stooq) ---
    dxy, d7 = yf_latest("DX-Y.NYB")              # 달러지수
    if dxy is None:
        dxy, d7 = stooq_latest("dx.f")           # ICE 달러지수 선물
    gold, d8 = yf_latest("GC=F")                 # 금 선물
    if gold is None:
        gold, d8 = stooq_latest("xauusd")        # 금 현물
    silver, d9 = yf_latest("SI=F")               # 은 선물
    if silver is None:
        silver, d9 = stooq_latest("xagusd")      # 은 현물
    gs_ratio = (gold / silver) if (gold and silver) else None

    rows_week = [
        ("금 현재가($)", "GC=F", fmt(gold), d8, ""),
        ("실질금리 DFII10(%)", "DFII10", fmt(dfii10), d1, flag("DFII10", dfii10)),
        ("달러 DXY", "DX-Y.NYB", fmt(dxy), d7, flag("DXY", dxy)),
        ("스프레드 T10Y2Y(%p)", "T10Y2Y", fmt(t10y2y), d2, flag("T10Y2Y", t10y2y)),
        ("명목 10년 DGS10(%)", "DGS10", fmt(dgs10), d3, flag("DGS10", dgs10)),
        ("금-은 비율", "XAU/XAG", fmt(gs_ratio, 1), d8, flag("GS_RATIO", gs_ratio)),
    ]
    rows_month = [
        ("기대인플레 MICH(%)", "MICH", fmt(mich, 1), d4, flag("MICH", mich)),
        ("근원 PCE(지수)", "PCEPILFE", fmt(pce), d5, ""),
        ("부채/GDP(%)", "GFDEGDQ188S", fmt(debt, 1), d6, flag("DEBT_GDP", debt)),
    ]

    def table(rows):
        out = ["| 지표 | 코드 | 값 | 기준일 | 자동판정 |", "|---|---|---|---|---|"]
        for name, code, val, date, fl in rows:
            out.append(f"| {name} | `{code}` | **{val}** | {date or '—'} | {fl} |")
        return "\n".join(out)

    md = f"""# data/snapshot.md — 최신 수치 (자동생성)

> `python data/fetch_signals.py` 가 덮어쓴다. 손으로 고치지 말 것.
> ⚠️ 표시는 임계값 자동 플래그. **레짐 판정은 사람이** (`01_regime_card`).

## 주간 지표 (빠르게 움직임 — 매주 확인)
{table(rows_week)}

## 월간/분기 지표 (FRED 자동)
{table(rows_month)}

## 자동수집 안 되는 것 (분기마다 손으로)
- 중앙은행 순매수(톤) — WGC goldhub
- ETF 보유량(톤) — WGC ETF Flows
- COMEX 투기(COT) — CFTC
- 외환보유고 달러비중 — IMF COFER

---
### 이번 주 빠른 판단 (5개)
- [ ] 금가 vs 손절선 $4,180 / $3,900
- [ ] 실질금리 2.30%↑? · 달러 103↑? (동시면 강한 악재)
- [ ] 스프레드 역전(음수)?
- [ ] 반증조건 점등 늘었나? (PART 4)
- [ ] → 레짐 유지 / 눌림목 / 과열 / ⚠️월간 당김
"""

    out_path = os.path.join(HERE, "snapshot.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"완료 → {out_path}")

    # --- 폰용 단일 HTML 대시보드 (프로젝트 루트에 index.html 로 생성) ---
    # index.html 인 이유: 깃허브 페이지 배포 시 루트 URL로 바로 열림.
    # 갱신시각은 한국시간(KST)으로 고정 — 로컬이든 Actions(UTC)든 동일하게 표기.
    kst = datetime.datetime.now(datetime.timezone.utc).astimezone(
        datetime.timezone(datetime.timedelta(hours=9)))
    updated = kst.strftime("%Y-%m-%d %H:%M") + " KST"
    html = build_dashboard(rows_week, rows_month, fmt(gold), updated)
    dash_path = os.path.abspath(os.path.join(HERE, "..", "index.html"))
    with open(dash_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"완료 → {dash_path}")
    print("index.html 을 열면 폰/PC에서 한눈에 봅니다.")


if __name__ == "__main__":
    main()
