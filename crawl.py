#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매일동향 인사이트 크롤러
Usage:
  python crawl.py          # 오늘 기사 (daily, 기본값)
  python crawl.py --days 7 # 이번주 기사 (초기 실행용)
"""

import os, sys, re, json, time, argparse, textwrap, io
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
import anthropic

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_JS       = os.path.join(BASE_DIR, "data.js")
HISTORY_JS    = os.path.join(BASE_DIR, "history.js")
SEEN_URLS_JSON= os.path.join(BASE_DIR, "seen_urls.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# ── 카테고리 정의 ──
# significance_criteria: Claude에게 "이런 사건이 유의미하다"고 알려주는 기준
CATEGORIES = {
    "macro": {
        "title": "국내 매크로 경제",
        "queries": [
            "소비자물가지수", "근원물가",
            "기준금리", "금통위",
            "가계대출", "주택담보대출 연체",
            "원달러 환율", "국제유가",
            "경제성장률", "실업률",
        ],
        "significance_criteria": """
주요 관심 지표 (아래 항목 관련 기사는 반드시 포함):
- 가계대출·가계부채: 전월/전년 대비 증감 규모, 규제 변화, 연체율 변화
- 소비자물가·근원물가: 예상 대비 등락, 특정 품목 이상 급등
- 금리: 기준금리 인상/인하/동결 결정 및 전망
- 환율: 급격한 움직임과 경제 파급 효과
- 내수·경기: GDP, 소비, 투자 등 주요 경기 지표 발표
- 고용: 실업률·취업자 수의 뚜렷한 변화
- 주요 경제 정책 발표 (추경, 세제 개편 등)
- 국제 유가·원자재 가격이 국내 물가·경기에 미치는 영향
- 글로벌 리스크(지정학적 긴장, 미국 경기 등)가 국내 거시경제에 미치는 파급 효과

반드시 제외:
- 개별 기업 실적 기사 (거시경제 지표와 무관한 것)
- 특정 지역 한정 고용·소비 통계 (전국 단위가 아닌 경우)
        """,
    },
    "pm_domestic": {
        "title": "국내 PM 시장",
        "queries": [
            "킥고잉", "일레클", "더스윙", "빔모빌리티",
            "피유엠피 PUMP", "지쿠", "공유킥보드 시장",
            "전동킥보드 업체", "퍼스널모빌리티 업계",
        ],
        "significance_criteria": """
대상 브랜드: 킥고잉, 일레클, 더스윙, 빔모빌리티, 피유엠피(PUMP), 지쿠, 공유킥보드 전반
유의미한 사건 (기사의 주제가 PM이어야 함):
- 업체 신규 진입 / 서비스 종료 / 철수
- 투자 유치 / 인수합병 / 파산·회생
- 운영 지역 확대 / 축소
- 사용량·점유율의 뚜렷한 변화
- 규제 변화 (법 개정, 지자체 조례, 단속 강화)
- 대형 사고 또는 브랜드 이미지에 영향을 주는 사건
- 신기술·신서비스 출시 (새 기종, 구독제, 파트너십 등)

반드시 제외:
- PM/킥보드가 기사의 부수적 언급에 불과한 경우 (예: 공연·행사·교통통제 기사에서 킥보드 운행 금지를 곁들여 언급한 것)
- 공연, 축제, 스포츠 행사 관련 교통 통제 기사
- 캠페인·안전교육 등 일회성 홍보성 행사
        """,
    },
    "ebike_delivery": {
        "title": "국내 B2C 전기자전거/배달 시장",
        "queries": [
            "모토벨로", "퀄리스포츠", "전기자전거 시장",
            "배달의민족", "쿠팡이츠", "요기요",
            "배달 전기이륜차", "배달라이더", "배달 플랫폼 수수료",
        ],
        "significance_criteria": """
대상: 모토벨로·퀄리스포츠 등 전기자전거 브랜드, 배달의민족·쿠팡이츠·요기요 등 배달 플랫폼
유의미한 사건 (기사의 주제가 전기자전거 또는 배달 시장이어야 함):
- 전기자전거 제조사·브랜드의 신제품 출시, 사업 확장/축소, M&A
- 전기자전거 시장 규모·판매량의 의미 있는 변화
- 배달 플랫폼의 라이더 정책 변화 (수수료, 보험, 고용 형태)
- 배달 플랫폼의 사업 구조 변화 (진입·철수·합병)
- 배달 라이더 관련 규제·제도 변화 (산재, 처우 기준)
- 전기자전거 배달 도입·확대 관련 뉴스

반드시 제외:
- 배달·자전거가 기사의 부수적 언급에 불과한 경우
- AI·테크 기업 기사에서 배달 앱을 예시로 언급한 것
- 일반 물류·택배 기사 (전기자전거·배달 플랫폼이 주제가 아닌 경우)
        """,
    },
}

SUBSTACK_URL = "https://micromobility.substack.com"
SUBSTACK_RSS = "https://micromobility.substack.com/feed"

# ─────────────────────────────────────────
# 언론사 신뢰도 티어 (URL 도메인 기반)
# ─────────────────────────────────────────
DOMAIN_PRESS = {
    # S티어
    "yna.co.kr":       ("연합뉴스", "S"),
    "kbs.co.kr":       ("KBS", "S"),
    "news.kbs.co.kr":  ("KBS", "S"),
    "imnews.imbc.com": ("MBC", "S"),
    "mbc.co.kr":       ("MBC", "S"),
    "chosun.com":      ("조선일보", "S"),
    "donga.com":       ("동아일보", "S"),
    "joongang.co.kr":  ("중앙일보", "S"),
    "joins.com":       ("중앙일보", "S"),
    # A티어
    "hani.co.kr":      ("한겨레", "A"),
    "khan.co.kr":      ("경향신문", "A"),
    "news.sbs.co.kr":  ("SBS", "A"),
    "sbs.co.kr":       ("SBS", "A"),
    "jtbc.co.kr":      ("JTBC", "A"),
    "news.jtbc.co.kr": ("JTBC", "A"),
    "ytn.co.kr":       ("YTN", "A"),
    "hankyung.com":    ("한국경제", "A"),
    # B티어
    "mk.co.kr":        ("매일경제", "B"),
    "mbn.co.kr":       ("MBN", "B"),
    "tvchosun.com":    ("TV조선", "B"),
    "seoul.co.kr":     ("서울신문", "B"),
    "moneytoday.co.kr":("머니투데이", "B"),
    "mt.co.kr":        ("머니투데이", "B"),
    "edaily.co.kr":    ("이데일리", "B"),
    "newsis.com":      ("뉴시스", "B"),
    "chosunbiz.com":   ("조선비즈", "B"),
    "news1.kr":        ("뉴스1", "B"),
    # C티어
    "ohmynews.com":    ("오마이뉴스", "C"),
    "pressian.com":    ("프레시안", "C"),
    "newdaily.co.kr":  ("뉴데일리", "C"),
    "dailian.co.kr":   ("데일리안", "C"),
    "mediatoday.co.kr":("미디어오늘", "C"),
    "hankookilbo.com": ("한국일보", "C"),
}
TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}

def get_press(url: str) -> tuple[str, str]:
    """URL에서 (언론사명, 티어) 반환. 미등록이면 ('', 'D')"""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lstrip("www.")
        # 서브도메인 포함 매칭 (e.g. news.kbs.co.kr)
        for domain, info in DOMAIN_PRESS.items():
            if host == domain or host.endswith("." + domain):
                return info
        # 도메인 일부 매칭 (e.g. *.hankyung.com)
        for domain, info in DOMAIN_PRESS.items():
            if domain in host:
                return info
    except Exception:
        pass
    return ("", "D")
OVERSEAS_SIGNIFICANCE = """
대상 브랜드: Lime, Bird, Bolt, Tier, Dott, Superpedestrian, Voi, Spin, Link, Third Lane Mobility 등 글로벌 마이크로모빌리티 업체
유의미한 사건:
- 업체의 신규 도시/국가 진출 또는 철수
- 투자 유치, 상장, 인수합병, 파산·구조조정
- 사용량·트립 수·수익의 의미 있는 변화 (수치 포함 시 우선)
- 주요 도시/정부의 허가·금지·규제 변화
- 새로운 기기·기술·서비스 출시 (e-bike 전환, AI 배치 등)
- 브랜드 이미지에 영향을 주는 대형 사건 (사고, 소송, 언론 노출)
- 시장 전체의 트렌드 변화 (점유율 변동, 신흥 플레이어 부상)
- 주요 도시의 마이크로모빌리티 이용 실적 데이터 (트립 수, 사용량 통계 등)

반드시 제외:
- 컨퍼런스·행사 파티 안내, 이벤트 초대 등 홍보성 공지
- 단순 행사 일정 안내
"""


# ─────────────────────────────────────────
# 네이버 뉴스 크롤링
# ─────────────────────────────────────────
def naver_date_fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")

def search_naver(query: str, start_dt: datetime, end_dt: datetime, tag: str = "") -> list[dict]:
    url = (
        "https://search.naver.com/search.naver"
        f"?where=news&query={quote(query)}&sort=1"
        f"&nso=so:dd,p:from{naver_date_fmt(start_dt)}to{naver_date_fmt(end_dt)}"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [Naver] 실패 ({query}): {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    dates_raw = re.findall(r"(\d{4})[\.\-](\d{2})[\.\-](\d{2})", resp.text)
    dates = [f"{y}-{m}-{d}" for y, m, d in dates_raw]
    today = datetime.now().strftime("%Y-%m-%d")

    seen: dict[str, dict] = {}
    date_idx = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = re.sub(r"\s+", " ", a.get_text(separator=" ", strip=True))
        if (
            href.startswith("https://")
            and "naver.com" not in href
            and len(text) > 8
        ):
            if href not in seen:
                date_str = dates[date_idx] if date_idx < len(dates) else today
                date_idx += 1
                press, tier = get_press(href)
                seen[href] = {"title": text, "snippet": "", "link": href,
                              "source": press, "tier": tier, "date": date_str,
                              "tag": tag or query}
            elif not seen[href]["snippet"] and text != seen[href]["title"]:
                seen[href]["snippet"] = text

    return list(seen.values())[:6]


# 카테고리별 제목 하드 필터 (Python 레벨, Claude 전)
# 어떤 맥락에서도 업황과 무관한 단어만 (연예인명, 가상화폐, 스포츠 경기결과 등)
HARD_EXCLUDE_GLOBAL = [
    "BTS", "블랙핑크", "뉴진스", "아이유", "NCT", "르세라핌",
    "비트코인", "이더리움", "NFT", "밈코인", "가상화폐", "코인 시세",
    "야구 경기", "축구 경기", "올림픽", "월드컵",
]

# ─────────────────────────────────────────
# 본 기사 추적 (일간 중복 방지)
# ─────────────────────────────────────────
def load_seen_urls() -> set:
    try:
        with open(SEEN_URLS_JSON, encoding="utf-8") as f:
            return set(json.load(f).get("urls", []))
    except Exception:
        return set()

def save_seen_urls(seen: set) -> None:
    with open(SEEN_URLS_JSON, "w", encoding="utf-8") as f:
        json.dump({"urls": sorted(seen)}, f, ensure_ascii=False, indent=2)

def load_history() -> dict:
    try:
        with open(HISTORY_JS, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"window\.historyData\s*=\s*(\{.*\});", text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
    except Exception:
        pass
    return {}

def save_history(history: dict) -> None:
    js = "// Auto-generated by crawl.py\n"
    js += f"window.historyData = {json.dumps(history, ensure_ascii=False, indent=2)};\n"
    with open(HISTORY_JS, "w", encoding="utf-8") as f:
        f.write(js)


def hard_filter(articles: list[dict], category: str) -> list[dict]:
    """맥락과 무관하게 절대 업황 기사가 될 수 없는 경우만 제외"""
    out = []
    for a in articles:
        title = a.get("title", "")
        if any(k in title for k in HARD_EXCLUDE_GLOBAL):
            continue
        out.append(a)
    return out


def best_per_tag(articles: list[dict]) -> list[dict]:
    """태그(검색 키워드)당 티어 최고 기사 1건만 유지"""
    by_tag: dict[str, dict] = {}
    for a in articles:
        tag = a.get("tag", "")
        existing = by_tag.get(tag)
        if not existing:
            by_tag[tag] = a
        elif TIER_ORDER.get(a.get("tier", "D"), 4) < TIER_ORDER.get(existing.get("tier", "D"), 4):
            by_tag[tag] = a
    return list(by_tag.values())


def dedup(articles: list[dict]) -> list[dict]:
    seen_urls, seen_titles, out = set(), set(), []
    for a in articles:
        url  = a.get("link", "").split("?")[0].rstrip("/")
        tkey = re.sub(r"\s+", "", a.get("title", ""))[:18]
        if url in seen_urls or tkey in seen_titles:
            continue
        seen_urls.add(url); seen_titles.add(tkey)
        out.append(a)
    return out


# ─────────────────────────────────────────
# 기사 본문 추출
# ─────────────────────────────────────────
def fetch_body(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup.find_all(["nav", "header", "footer", "script",
                                   "style", "aside", "noscript", "iframe"]):
            tag.decompose()
        for sel in ["#dic_area", "#articleBodyContents", "#newsct_article",
                    "#article-view-content-div", "#articeBody",
                    ".article_body", ".news_view", ".article-body",
                    ".view_con", "article"]:
            el = soup.select_one(sel)
            if el:
                t = el.get_text(separator="\n", strip=True)
                if len(t) > 100:
                    return t[:2500]
        paras = [p.get_text(strip=True) for p in soup.find_all("p")
                 if len(p.get_text(strip=True)) > 60]
        return "\n".join(paras[:10])[:2500]
    except Exception:
        return ""


# ─────────────────────────────────────────
# Substack 크롤링
# ─────────────────────────────────────────
def fetch_substack(days: int) -> list[dict]:
    """
    Substack은 주 1회 발행이라 날짜 컷오프 대신
    최근 N개를 가져와서 Claude가 유의미한 것을 선별.
    - daily (days=1): 최근 5개 (지난주까지 커버)
    - weekly (days>=7): 최근 12개 (약 3개월치)
    """
    n_posts = 5 if days <= 1 else 12
    try:
        resp = requests.get(SUBSTACK_RSS, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "xml")
    except Exception as e:
        print(f"  [Substack] RSS 실패: {e}")
        return []

    articles = []
    for item in soup.find_all("item")[:n_posts]:
        title_tag = item.find("title")
        link_tag  = item.find("link")
        pub_tag   = item.find("pubDate")
        desc_tag  = item.find("description")
        if not (title_tag and link_tag):
            continue

        title   = title_tag.get_text(strip=True)
        link    = link_tag.get_text(strip=True)
        snippet = BeautifulSoup(
            desc_tag.get_text() if desc_tag else "", "html.parser"
        ).get_text(strip=True)[:800]

        date_str = ""
        if pub_tag:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub_tag.get_text(strip=True))
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        articles.append({"title": title, "link": link,
                         "source": "Micromobility Substack",
                         "date": date_str, "snippet": snippet,
                         "tag": "Micromobility Substack"})
    return articles


# ─────────────────────────────────────────
# Claude: 유의미한 기사 선별 + 중복 제거
# ─────────────────────────────────────────
def pick_significant(
    client: anthropic.Anthropic,
    articles: list[dict],
    significance_criteria: str,
    max_n: int = 3,
) -> list[dict]:
    """
    후보 기사 목록에서 업계 동향으로 유의미한 것만 골라
    같은 사건은 1건으로 묶어 최대 max_n건 반환.
    """
    if not articles:
        return []

    lines = "\n".join(
        f"{i+1}. [{a.get('tier','D')}티어/{a.get('source','미상')}] [{a['date']}] {a['title']}\n   {a['snippet'][:250]}"
        for i, a in enumerate(articles)
    )

    prompt = textwrap.dedent(f"""
        너는 업계 동향 분석가야. 아래 기사 목록에서 다음 기준에 해당하는 유의미한 기사만 골라줘.

        [유의미한 사건 기준]
        {significance_criteria.strip()}

        [제외 기준]
        - 단순 행사 안내, 캠페인 홍보, 인사 발령
        - 같은 사건을 다룬 기사가 여러 개면 신뢰도 높은 언론사(S>A>B>C>D티어) 것 1건만 선택
          단, 해당 언론사만 단독으로 낸 기사(타 언론사 보도 없음)는 티어 무관하게 포함

        [기사 목록]
        {lines}

        핵심 판단 기준 — 기사의 **주제**가 위 조건이어야 함:
        - 해당 키워드가 기사 내 부수적 언급·곁들임에 불과하면 제외
          예) 공연·행사 교통통제 기사에서 킥보드 운행 금지를 부수적으로 언급 → 제외
          예) AI·테크 기업 기사에서 배달 앱·전기자전거를 예시로 언급 → 제외
          예) 지역 행사 기사에서 해당 지역 공유킥보드 운영을 잠깐 언급 → 제외
        - 반면 해당 업계·지표가 기사의 핵심 주인공이면 단독 보도라도 포함

        ★ 출력 형식: 선택한 기사 번호만 콤마로. 설명·분석 금지.
        ★ 최대 {max_n}건. 같은 주제는 1건씩만.
        ★ 경계선상이면 포함. 정말 0건일 때만 "없음".
        출력 예시(이 형식만 허용): 2,5,9   또는   없음
    """).strip()

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}]
        )
        result = msg.content[0].text.strip()
        if "없음" in result and not any(c.isdigit() for c in result):
            return []
        idxs = [int(x.strip()) - 1
                for x in re.split(r"[,\s]+", result)
                if x.strip().isdigit()]
        return [articles[i] for i in idxs if 0 <= i < len(articles)][:max_n]
    except Exception as e:
        print(f"  [Claude] 선별 실패: {e}")
        return articles[:max_n]


# ─────────────────────────────────────────
# Claude: 기사 요약 (2불렛)
# ─────────────────────────────────────────
def summarize(client: anthropic.Anthropic, title: str, body: str,
              lang: str = "ko") -> list[str]:
    content = (body or "(본문 없음)")[:2000]
    lang_note = "한국어로" if lang == "ko" else "in Korean (한국어로)"

    prompt = textwrap.dedent(f"""
        다음 기사의 핵심을 {lang_note} 2가지 불렛으로 요약해줘.
        - 각 불렛은 1~2문장 (60자 내외), 핵심 사실 위주
        - 수치/퍼센트 있으면 반드시 포함
        - 첫 불렛: 무슨 일이 일어났는지 (사실)
        - 둘째 불렛: 업계에 어떤 의미인지
        - 불렛 마커 없이 텍스트만, 줄바꿈으로 구분

        제목: {title}
        본문:
        {content}
    """).strip()

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip()
        bullets = [b.strip().lstrip("•-·*").strip()
                   for b in text.split("\n") if b.strip()]
        return bullets[:2] if bullets else [title]
    except Exception as e:
        print(f"  [Claude] 요약 실패: {e}")
        return [title]


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[!] ANTHROPIC_API_KEY 없음 — 스니펫만 사용")
    client = anthropic.Anthropic(api_key=api_key) if api_key else None

    # 일간 모드: 이미 본 기사 제외 / 주간 초기 모드: 전체 표시 후 seen에 추가
    is_daily = args.days <= 1
    seen_urls = load_seen_urls()
    history   = load_history()

    KST = timezone(timedelta(hours=9))
    end_dt   = datetime.now(KST)
    start_dt = end_dt - timedelta(days=args.days)
    print(f"[{end_dt.strftime('%Y-%m-%d %H:%M')}] "
          f"수집 기간: {start_dt.strftime('%m/%d')} ~ {end_dt.strftime('%m/%d')} ({args.days}일)\n")

    sections = {}

    # ── 국내 3개 카테고리 ──
    for cat_key, cat in CATEGORIES.items():
        print(f"▶ {cat['title']}")
        raw = []
        for q in cat["queries"]:
            hits = search_naver(q, start_dt, end_dt, tag=q)
            raw.extend(hits)
            time.sleep(0.4)

        raw = dedup(raw)
        raw = hard_filter(raw, cat_key)
        raw = best_per_tag(raw)   # 태그당 최고 티어 1건
        print(f"  후보 {len(raw)}건 수집")

        # Claude로 유의미한 기사 선별
        if client:
            selected = pick_significant(client, raw, cat["significance_criteria"], max_n=len(raw))
        else:
            selected = raw

        print(f"  선별 {len(selected)}건")

        final = []
        for art in selected:
            print(f"  → {art['title'][:50]}...")
            if client:
                body = fetch_body(art["link"])
                time.sleep(0.3)
                bullets = summarize(client, art["title"], body or art["snippet"])
            else:
                snippet = art["snippet"][:200].strip()
                bullets = [snippet] if snippet else [art["title"]]

            final.append({
                "title":   art["title"],
                "link":    art["link"],
                "source":  art.get("source", ""),
                "tier":    art.get("tier", "D"),
                "date":    art["date"],
                "tag":     art.get("tag", ""),
                "bullets": bullets,
            })
            time.sleep(0.4)

        pass  # seen_urls 필터 제거 — 항상 최신 24시간 기사 표시

        sections[cat_key] = {"title": cat["title"], "articles": final}
        print()

    # ── 해외 PM (Substack) ──
    print("▶ 해외 PM 시장 (Substack)")
    substack_raw = fetch_substack(days=args.days)
    print(f"  RSS {len(substack_raw)}건 수신")

    # Substack은 본문을 fetch해서 snippet 보강 후 선별
    for art in substack_raw:
        if not art["snippet"] or len(art["snippet"]) < 100:
            body = fetch_body(art["link"])
            if body:
                art["snippet"] = body[:600]
            time.sleep(0.3)

    if client:
        selected_overseas = pick_significant(
            client, substack_raw, OVERSEAS_SIGNIFICANCE, max_n=5
        )
    else:
        selected_overseas = substack_raw[:5]

    print(f"  선별 {len(selected_overseas)}건")

    final_overseas = []
    for art in selected_overseas:
        print(f"  → {art['title'][:55]}...")
        if client:
            body = fetch_body(art["link"])
            time.sleep(0.3)
            bullets = summarize(client, art["title"], body or art["snippet"], lang="ko")
        else:
            snippet = art["snippet"][:200].strip()
            bullets = [snippet] if snippet else [art["title"]]

        final_overseas.append({
            "title":   art["title"],
            "link":    art["link"],
            "source":  art["source"],
            "date":    art["date"],
            "bullets": bullets,
        })
        time.sleep(0.4)

    pass  # seen_urls 필터 제거

    sections["pm_overseas"] = {"title": "해외 PM 시장", "articles": final_overseas}
    print()

    # ── seen_urls & history 업데이트 ──
    today_str = end_dt.strftime("%Y-%m-%d")
    today_articles = {}
    new_urls = set()

    for cat_key, sec in sections.items():
        arts = sec.get("articles", [])
        if arts:
            today_articles[cat_key] = [
                {"title": a["title"], "link": a["link"], "source": a.get("source",""),
                 "tier": a.get("tier",""), "date": a.get("date","")}
                for a in arts
            ]
        for a in arts:
            new_urls.add(a["link"])

    if today_articles:
        history[today_str] = today_articles

    seen_urls.update(new_urls)
    save_seen_urls(seen_urls)
    save_history(history)

    # ── data.js 저장 ──
    data = {
        "lastUpdated": end_dt.strftime("%Y-%m-%d %H:%M"),
        "isDaily": is_daily,
        "sections": sections,
    }
    js = "// Auto-generated by crawl.py — do not edit manually\n"
    js += f"window.newsData = {json.dumps(data, ensure_ascii=False, indent=2)};\n"

    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write(js)

    print(f"[OK] 저장 완료 -> {DATA_JS}")
    total = sum(len(s.get("articles",[])) for s in sections.values())
    print(f"     총 {total}건 표시 | seen_urls {len(seen_urls)}개 누적")


if __name__ == "__main__":
    main()
