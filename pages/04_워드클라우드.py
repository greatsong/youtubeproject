# app.py
import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
import re
from collections import Counter
from io import BytesIO
from pathlib import Path
import tempfile
import matplotlib.pyplot as plt
from wordcloud import WordCloud

# ---------------------------- 기본 설정 ----------------------------
st.set_page_config(page_title="유튜브 댓글 워드클라우드", layout="wide")
st.title("유튜브 댓글 워드클라우드")
st.caption("주소를 넣고 버튼을 누르면 인기순 댓글을 모아 단어 워드클라우드를 만들어요.")

DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# ---------------------------- 유틸 함수들 ----------------------------
def extract_video_id(url: str):
    """여러 형태의 유튜브 주소에서 영상 ID를 뽑아줘요."""
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
    """HTTP 연결을 한 번 만들어 재사용해요."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "User-Agent": "streamlit-app"})
    return s


def fetch_comments_texts(api_key: str, video_id: str, session: requests.Session, limit: int) -> list[str]:
    """인기순으로 최대 limit개의 댓글 본문을 모아와요."""
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
            if len(texts) >= limit:
                return texts

        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return texts


def clean_and_tokenize(text: str) -> list[str]:
    """특수문자·이모지 제거 후 2글자 이상 한글/영어 단어만 소문자로 뽑아요."""
    # 이모지/특수문자 제거 -> 한글/영문만 남기는 토큰화
    # 영문은 소문자로 변환
    tokens = re.findall(r"[A-Za-z]+|[가-힣]+", text)
    tokens = [t.lower() for t in tokens if len(t) >= 2]
    return tokens


def parse_stopwords(user_input: str) -> set[str]:
    """사용자가 쉼표로 입력한 불용어를 소문자로 정리해요."""
    if not user_input:
        return set()
    parts = [p.strip().lower() for p in user_input.split(",")]
    return {p for p in parts if p}


def safe_filename(name: str, default: str = "wordcloud") -> str:
    """파일명에서 사용할 수 없는 문자를 제거해요."""
    name = name.strip() or default
    name = re.sub(r'[\\/*?:"<>|]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name


@st.cache_resource(show_spinner=False)
def get_nanumm_font_path(session: requests.Session) -> str | None:
    """나눔고딕 폰트를 한 번만 웹에서 받아 임시 폴더에 저장해요."""
    tmp_dir = Path(tempfile.gettempdir())
    font_path = tmp_dir / "NanumGothic-Regular.ttf"
    if font_path.exists() and font_path.stat().st_size > 0:
        return str(font_path)

    # 구글 폰트 저장소의 원본 TTF
    font_url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
    try:
        r = session.get(font_url, timeout=30)
        if r.status_code != 200:
            return None
        font_path.write_bytes(r.content)
        return str(font_path)
    except Exception:
        return None


def make_wordcloud_image(freq: dict[str, int], font_path: str, max_words: int) -> bytes:
    """워드클라우드 이미지를 PNG 바이트로 만들어 돌려줘요."""
    wc = WordCloud(
        font_path=font_path,
        background_color="white",
        width=1200,
        height=700,
        max_words=max_words,
        collocations=False,
    ).generate_from_frequencies(freq)

    fig = plt.figure(figsize=(12, 7), dpi=150)
    plt.imshow(wc, interpolation="bilinear")
    plt.axis("off")
    plt.tight_layout(pad=0)

    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ---------------------------- 화면 ----------------------------
api_key = st.secrets.get("youtube_api_key", "")
if not api_key:
    st.error("API 키가 없어요. .streamlit/secrets.toml에 넣어 주세요.")

url_input = st.text_input(
    "유튜브 주소를 넣어 주세요.",
    value=DEFAULT_URL,
    placeholder="예) https://youtu.be/VIDEO_ID 또는 https://www.youtube.com/watch?v=VIDEO_ID",
)
col_a, col_b = st.columns(2)
with col_a:
    max_comments = st.slider("최대 댓글 수 (100~2000)", min_value=100, max_value=2000, step=100, value=500)
with col_b:
    max_words = st.slider("워드클라우드 단어 수 (20~200)", min_value=20, max_value=200, step=10, value=100)

stopwords_input = st.text_input("불용어 목록 (쉼표로 구분, 예: the, and, 그리고, 그래서)")

fetch_btn = st.button("댓글 모으고 워드클라우드 만들기", disabled=(not bool(api_key)))

# 버튼을 누르기 전에는 어떤 연결도 시도하지 않아요.
if fetch_btn:
    video_id = extract_video_id(url_input)
    if not video_id:
        st.error("주소가 올바르지 않아요.")
        st.stop()

    session = get_http_session()

    # 댓글 모으기
    try:
        texts = fetch_comments_texts(api_key, video_id, session, max_comments)
    except RuntimeError as e:
        msg = str(e)
        if ("403" in msg and ("commentsDisabled" in msg or "forbidden" in msg)) or "commentsDisabled" in msg:
            st.error("이 영상은 댓글을 볼 수 없어요.")
            st.stop()
        if "quotaExceeded" in msg or "429" in msg:
            st.error("오늘 사용할 수 있는 조회량이 다 됐어요.")
            st.stop()
        st.error("데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()
    except Exception:
        st.error("데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()

    if not texts:
        st.error("분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    # 토큰화 + 불용어 적용
    user_stop = parse_stopwords(stopwords_input)
    tokens: list[str] = []
    for t in texts:
        toks = clean_and_tokenize(t)
        toks = [w for w in toks if w not in user_stop]
        tokens.extend(toks)

    if not tokens:
        st.error("분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    freq = Counter(tokens)
    if not freq:
        st.error("분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    # 폰트 확보(처음 1회 다운로드 후 재사용)
    font_path = get_nanumm_font_path(session)
    if not font_path or not Path(font_path).exists():
        st.error("나눔고딕 폰트를 받지 못했어요. 잠시 후 다시 시도해 주세요.")
        st.stop()

    # 워드클라우드 생성
    try:
        png_bytes = make_wordcloud_image(freq, font_path, max_words=max_words)
    except Exception:
        st.error("데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()

    st.subheader("워드클라우드")
    st.image(png_bytes, caption="단어 빈도 워드클라우드", use_container_width=True)

    fname = safe_filename(f"wordcloud_{video_id}") + ".png"
    st.download_button("PNG로 내려받기", data=png_bytes, file_name=fname, mime="image/png")
