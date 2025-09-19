# app.py
import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
import re
from collections import Counter
from io import BytesIO
import tempfile
import os
import matplotlib.pyplot as plt
from matplotlib import font_manager
from wordcloud import WordCloud, STOPWORDS as WC_STOPWORDS

# ============================ 페이지 설정 ============================
st.set_page_config(page_title="🎈 유튜브 댓글 워드클라우드", layout="wide")
st.title("🎈 유튜브 댓글 워드클라우드")
st.caption("🧩 주소를 넣고 최대 댓글 수를 고른 뒤 버튼을 눌러 워드클라우드를 만들어봐요.")

DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# ============================ 유틸 함수들 ============================
def extract_video_id(url: str):
    """여러 형태의 유튜브 주소에서 영상 ID를 뽑아요."""
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    qs = parse_qs(parsed.query or "")

    if "youtube.com" in host:
        if "v" in qs and qs["v"]:
            return qs["v"][0]
        m = re.search(r"/embed/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
        m = re.search(r"/shorts/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
        m = re.search(r"/live/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
    if "youtu.be" in host:
        m = re.match(r"^/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
    if "vi" in qs and qs["vi"]:
        return qs["vi"][0]
    return None


@st.cache_resource(show_spinner=False)
def get_session() -> requests.Session:
    """API 호출용 세션을 한 번 만들고 재사용해요."""
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (WordcloudApp/1.0)"
    })
    return s


def raise_api_error(resp: requests.Response) -> None:
    """API 오류를 사람이 이해하기 쉬운 예외로 바꿔요."""
    try:
        data = resp.json()
        reason = data.get("error", {}).get("errors", [{}])[0].get("reason", "")
        code = data.get("error", {}).get("code", resp.status_code)
    except Exception:
        reason = ""
        code = resp.status_code
    raise RuntimeError(f"{code}:{reason}")


def fetch_video_title(api_key: str, video_id: str, session: requests.Session) -> str:
    """영상 제목을 가져와요(파일명에 쓸 거예요)."""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"id": video_id, "part": "snippet", "key": api_key}
    resp = session.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        raise_api_error(resp)
    items = resp.json().get("items", [])
    if not items:
        raise RuntimeError("404:notFound")
    return items[0]["snippet"]["title"] or "video"


def fetch_comment_texts(api_key: str, video_id: str, session: requests.Session, max_count: int) -> list[str]:
    """인기순으로 댓글 본문을 최대 max_count개 모아요."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "order": "relevance",
        "maxResults": 100,
        "textFormat": "plainText",
    }
    texts: list[str] = []
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)
        resp = session.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            raise_api_error(resp)
        data = resp.json()
        for it in data.get("items", []):
            try:
                sn = it["snippet"]["topLevelComment"]["snippet"]
                txt = (sn.get("textDisplay", "") or "").replace("\n", " ").strip()
                if txt:
                    texts.append(txt)
            except Exception:
                continue
            if len(texts) >= max_count:
                return texts
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return texts


def sanitize_filename(name: str) -> str:
    """파일명에 쓸 수 없는 문자를 제거해요."""
    name = re.sub(r"[\\/*?:\"<>|]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "wordcloud"


def tokenize_clean(text: str) -> list[str]:
    """특수문자/이모지 제거, 2글자 이상 한/영/숫자 단어만 남겨요."""
    cleaned = re.sub(r"[^가-힣A-Za-z0-9\s]", " ", text)
    cleaned = cleaned.lower()
    tokens = re.findall(r"[가-힣a-z0-9]+", cleaned)
    return [t for t in tokens if len(t) >= 2]


# --------- 한글 기본 불용어(넉넉하게, 조사/대명사/추임새/상투어 포함) ----------
BASE_KO_STOPWORDS = {
    "그리고","그러나","하지만","그래서","또한","및","등","또","아니라","보다","위해","대한","때문","때문에","으로","으로써","으로서","에서",
    "에게","에게서","부터","까지","이다","되다","하다","합니다","해요","한다","했다","하는","하면","하며","하여","하니","하고",
    "됩니다","되는","되어","됐다","있다","없다","같다","수","것","거","들","그","이","저","그것","이것","저것","때","좀","아주","너무","매우",
    "진짜","정말","그냥","아마","이미","다시","다른","최근","처럼","같이","우리","저희","내","내가","나","너","니","니가","너가","그녀",
    "그는","그녀는","저는","나는","우리는","여러분","오늘","영상","댓글","유튜브","보기","요","네","죠","요즘","거의","현재","그게","이게","저게",
    "뭔가","뭐","뭔","이런","저런","그런","뭔지","어떤","무엇","그래도","또는","만","라도","까지도","에서만","부터도","에는","이며","이나","라도요",
    "ㅋㅋ","ㅎㅎ","ㅠㅠ","ㅜㅜ","ㅠ","ㅜ"
}

# ============================ 폰트 경로(캐시) ============================
@st.cache_resource(show_spinner=False)
def get_korean_font_path() -> str:
    """나눔고딕/노토산스KR 중 가능한 폰트를 내려받아 임시 폴더에 저장하고 경로를 돌려줘요. (인자 없음)"""
    # 1) 로컬에 한글 폰트가 이미 있으면 그걸 사용
    candidates_local = ["Malgun Gothic", "AppleGothic", "NanumGothic", "NanumSquare", "Noto Sans CJK KR", "Noto Sans KR"]
    for f in font_manager.findSystemFonts(fontpaths=None, fontext="ttf") + font_manager.findSystemFonts(fontpaths=None, fontext="otf"):
        try:
            p = font_manager.FontProperties(fname=f)
            name = font_manager.get_font(f).family_name
        except Exception:
            continue
        if any(k in (name or "") for k in candidates_local):
            return f

    # 2) 웹에서 내려받기(여러 URL 후보를 순차 시도)
    urls = [
        # Noto Sans KR (공식 저장소 raw)
        "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Korean/NotoSansKR-Regular.otf",
        # NanumGothic (네이버 배포)
        "https://github.com/naver/nanumfont/releases/download/VER2.5/NanumGothic.ttf",
        # Noto Sans KR 또 다른 가중치
        "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Korean/NotoSansKR-Medium.otf",
    ]
    session = get_session()
    tmp_dir = tempfile.gettempdir()
    for u in urls:
        filename = os.path.basename(u.split("?")[0]) or "font.otf"
        font_path = os.path.join(tmp_dir, filename)
        try:
            if not os.path.exists(font_path) or os.path.getsize(font_path) < 50000:
                r = session.get(u, timeout=30)
                r.raise_for_status()
                if len(r.content) < 50000:
                    continue
                with open(font_path, "wb") as f:
                    f.write(r.content)
            # 간단 검증: matplotlib이 읽을 수 있나 확인
            _ = font_manager.get_font(font_path)
            return font_path
        except Exception:
            continue
    return ""  # 모두 실패


# ============================ 화면 구성 ============================
api_key = st.secrets.get("youtube_api_key", "")
if not api_key:
    st.error("🔐 API 키가 없어요. .streamlit/secrets.toml에 넣어 주세요.")
url = st.text_input("📮 유튜브 주소", value=DEFAULT_URL, placeholder="예) https://youtu.be/VIDEO_ID 또는 https://www.youtube.com/watch?v=VIDEO_ID")
max_comments = st.slider("🧲 최대 댓글 수 (인기순)", 100, 2000, 500, step=100)
max_words = st.slider("🧱 워드클라우드 단어 수", 20, 200, 100, step=10)

with st.expander("🧹 불용어 편집 (쉼표로 구분해서 추가해요)", expanded=False):
    col_a, col_b = st.columns(2)
    with col_a:
        user_stop_en = st.text_area("🇺🇸 영어 불용어 추가", placeholder="ex) video, youtube, like")
    with col_b:
        user_stop_ko = st.text_area("🇰🇷 한글 불용어 추가", placeholder="ex) 정말, 그냥, 영상")

go = st.button("🚀 워드클라우드 만들기", disabled=(not bool(api_key)))

# ============================ 동작 ============================
if go:
    video_id = extract_video_id(url)
    if not video_id:
        st.error("❗ 주소가 올바르지 않아요.")
        st.stop()

    session = get_session()

    # 영상 제목
    try:
        with st.spinner("🔎 영상 정보를 확인하고 있어요..."):
            title = fetch_video_title(api_key, video_id, session)
    except Exception:
        st.error("❌ 데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()

    # 댓글 수집
    try:
        with st.spinner("💬 댓글을 모으는 중이에요... (인기순)"):
            texts = fetch_comment_texts(api_key, video_id, session, max_comments)
    except Exception:
        st.error("❌ 데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()

    if not texts:
        st.warning("🪫 분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    # 토큰화 + 불용어
    with st.spinner("🧪 텍스트를 정리하는 중이에요..."):
        tokens_all: list[str] = []
        for t in texts:
            tokens_all.extend(tokenize_clean(t))

        stop_en = set(WC_STOPWORDS)
        if user_stop_en:
            stop_en |= {w.strip().lower() for w in user_stop_en.split(",") if w.strip()}

        stop_ko = set(w.lower() for w in BASE_KO_STOPWORDS)
        if user_stop_ko:
            stop_ko |= {w.strip().lower() for w in user_stop_ko.split(",") if w.strip()}

        all_stop = stop_en | stop_ko
        tokens_valid = [w for w in tokens_all if w not in all_stop and len(w) >= 2]

    if not tokens_valid:
        st.info("ℹ️ 분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    freq = Counter(tokens_valid)
    if not freq:
        st.info("ℹ️ 분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    most = dict(freq.most_common(max_words))

    # 폰트 준비(여러 경로 시도 후 실패 시 안내)
    with st.spinner("🔤 한글 폰트를 준비하는 중이에요..."):
        font_path = get_korean_font_path()
        if not font_path or not os.path.exists(font_path):
            st.error("⚠️ 폰트를 내려받지 못했어요. 한글이 깨질 수 있어 워드클라우드를 생략할게요.")
            st.stop()

    # 워드클라우드 생성
    with st.spinner("🎨 워드클라우드를 만드는 중이에요..."):
        wc = WordCloud(
            width=1200,
            height=600,
            background_color="white",
            font_path=font_path,
            max_words=max_words,
            collocations=False,
            prefer_horizontal=0.9,
            regexp=r"[가-힣a-z0-9]+",
        ).generate_from_frequencies(most)

        fig = plt.figure(figsize=(12, 6), dpi=150)
        plt.imshow(wc, interpolation="bilinear")
        plt.axis("off")
        plt.tight_layout(pad=0)

    st.success("✅ 워드클라우드를 만들었어요!")
    st.image(wc.to_array(), use_column_width=True, caption="☁️ 워드클라우드")

    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    buf.seek(0)
    safe_name = sanitize_filename(title)
    st.download_button(
        "⬇️ PNG로 내려받기",
        data=buf,
        file_name=f"{safe_name}_wordcloud.png",
        mime="image/png",
    )
