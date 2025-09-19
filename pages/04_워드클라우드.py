# app.py
import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
import re
from collections import Counter
from io import BytesIO
from datetime import datetime
from pathlib import Path
from wordcloud import WordCloud
import matplotlib.pyplot as plt

# ---------------------------- 기본 설정 ----------------------------
st.set_page_config(page_title="유튜브 댓글 워드클라우드", layout="wide")
st.title("유튜브 댓글 워드클라우드")
st.caption("주소와 최대 댓글 수를 정하고, 인기순 댓글로 워드클라우드를 만들어요.")

DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# ---------------------------- 폰트(나눔고딕) 준비 ----------------------------
@st.cache_resource(show_spinner=False)
def get_nanumgothic_path() -> str | None:
    """앱이 처음 실행될 때 웹에서 나눔고딕 폰트를 받아와 임시 폴더에 저장해요."""
    url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
    dest = Path(st.experimental_get_query_params().get("_cache_dir", [str(Path.cwd() / ".tmp")])[0])
    dest.mkdir(parents=True, exist_ok=True)
    fp = dest / "NanumGothic-Regular.ttf"
    try:
        if not fp.exists() or fp.stat().st_size == 0:
            resp = requests.get(url, timeout=20)
            if resp.status_code == 200:
                fp.write_bytes(resp.content)
        return str(fp) if fp.exists() and fp.stat().st_size > 0 else None
    except Exception:
        return None

FONT_PATH = get_nanumgothic_path()

# ---------------------------- 유틸리티 ----------------------------
def extract_video_id(url: str) -> str | None:
    """여러 형태의 유튜브 주소(일반/짧은/shorts/embed/live 등)에서 영상 ID를 뽑아줘요."""
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


def raise_api_error(resp: requests.Response) -> None:
    """API 오류를 읽어서 예외로 올려줘요."""
    try:
        data = resp.json()
        reason = data.get("error", {}).get("errors", [{}])[0].get("reason", "")
        code = data.get("error", {}).get("code", resp.status_code)
    except Exception:
        reason = ""
        code = resp.status_code
    raise RuntimeError(f"{code}:{reason}")


@st.cache_resource(show_spinner=False)
def get_http_session() -> requests.Session:
    """유튜브 API 호출용 세션을 한 번 만들고 재사용해요."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


def fetch_comments_plaintext(api_key: str, video_id: str, session: requests.Session, limit: int) -> list[str]:
    """인기순으로 댓글 본문만 모아줘요(최대 limit개)."""
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
                txt = (sn.get("textDisplay") or sn.get("textOriginal") or "").replace("\n", " ").strip()
                if txt:
                    texts.append(txt)
            except Exception:
                continue
            if len(texts) >= limit:
                return texts

        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return texts


# 이모지 제거(정규식 범위로 처리)
EMOJI_PATTERN = re.compile(
    "["  # 대표적인 이모지/심볼 블록들
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "\U0001F3FB-\U0001F3FF"
    "]+",
    flags=re.UNICODE,
)

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", flags=re.I)

def clean_and_tokenize(text: str) -> list[str]:
    """특수문자·이모지 제거 후, 2글자 이상 한글/영문 단어만 소문자로 뽑아요."""
    t = text.lower()
    t = URL_PATTERN.sub(" ", t)
    t = EMOJI_PATTERN.sub(" ", t)
    # 특수문자는 공백으로 치환
    t = re.sub(r"[^가-힣a-z\s]", " ", t)
    # 2글자 이상 한글/영문 토큰 추출
    tokens = re.findall(r"[가-힣a-z]{2,}", t)
    return tokens


def parse_stopwords(base_csv: str) -> set[str]:
    """쉼표로 구분된 불용어 문자열을 집합으로 바꿔줘요(소문자/공백 제거)."""
    words = [w.strip().lower() for w in base_csv.split(",") if w.strip()]
    return set(words)


def sanitize_filename(name: str) -> str:
    """파일 이름에서 사용할 수 없는 문자를 제거해요."""
    name = re.sub(r"[^\w\-]+", "_", name)
    return name.strip("_") or "wordcloud"


# ---------------------------- 기본 불용어(편집 가능) ----------------------------
DEFAULT_STOPWORDS = ", ".join([
    # 한국어 예시
    "이","그","저","것","수","등","좀","잘","더","정말","진짜","너무","완전","근데","그래서","그리고","하지만","이제","영상","구독","좋아요","ㅋㅋ","ㅎㅎ","ㅠㅠ","^^",
    # 영어 예시
    "the","a","an","is","are","be","to","of","and","in","that","it","with","for","on","this","i","you","he","she","we","they","my","your","lol","omg","btw",
    # 이모지 예시(쉼표로 나열)
    "😂","🤣","😍","👍","🙏","🔥","✨","🎉","❤️","💯","😅","🥲","😭","😢","👏","💖","😁","😊","😉","🙌",
])

# ---------------------------- 화면 ----------------------------
api_key = st.secrets.get("youtube_api_key", "")
if not api_key:
    st.error("API 키가 없어요. .streamlit/secrets.toml에 넣어 주세요.")

url_input = st.text_input("유튜브 주소를 넣어 주세요.", value=DEFAULT_URL)
max_comments = st.slider("최대 댓글 수 (100~2000, 100 단위)", min_value=100, max_value=2000, step=100, value=500)
max_words = st.slider("워드클라우드 단어 수 (20~200, 10 단위)", min_value=20, max_value=200, step=10, value=100)

st.write("불용어 목록을 쉼표로 수정/추가할 수 있어요.")
stopwords_csv = st.text_area("확장 불용어(쉼표로 구분)", value=DEFAULT_STOPWORDS, height=120)

run_btn = st.button("댓글 모으고 워드클라우드 만들기", disabled=(not bool(api_key)))

# 버튼을 누르기 전에는 어떤 연결도 시도하지 않아요(유튜브 API).
if run_btn:
    # 주소 확인
    vid = extract_video_id(url_input)
    if not vid:
        st.error("주소가 올바르지 않아요.")
        st.stop()

    # 댓글 가져오기
    session = get_http_session()
    try:
        texts = fetch_comments_plaintext(api_key, vid, session, max_comments)
    except Exception:
        st.error("데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()

    if not texts:
        st.error("분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    # 전처리 + 토큰화
    tokens: list[str] = []
    for t in texts:
        tokens.extend(clean_and_tokenize(t))

    # 불용어 적용(기본 + 사용자가 입력한 확장 목록)
    user_stop = parse_stopwords(stopwords_csv)
    # 이모지는 전처리에서 지워지지만, 혹시 남아있을 수 있어 함께 제거
    tokens = [w for w in tokens if (len(w) >= 2 and w not in user_stop)]

    if not tokens:
        st.error("분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    # 빈도 계산
    freq = Counter(tokens)
    if not freq:
        st.error("분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    # 워드클라우드 생성
    max_words = int(max_words)
    wc = WordCloud(
        font_path=FONT_PATH,              # 한글 표시를 위해 폰트 적용
        width=1200,
        height=700,
        background_color="white",
        max_words=max_words,
        collocations=False,
    ).generate_from_frequencies(freq)

    # 화면에 그리기
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    st.pyplot(fig, use_container_width=True)

    # PNG로 내려받기
    img = wc.to_image()
    buf = BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    safe_name = sanitize_filename(f"wordcloud_{vid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    st.download_button(
        label="PNG로 내려받기",
        data=png_bytes,
        file_name=f"{safe_name}.png",
        mime="image/png",
    )
