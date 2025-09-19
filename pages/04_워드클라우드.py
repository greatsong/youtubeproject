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
from wordcloud import WordCloud

# ---------------------------- 기본 설정 ----------------------------
st.set_page_config(page_title="유튜브 댓글 워드클라우드", layout="wide")
st.title("유튜브 댓글 워드클라우드")
st.caption("주소와 최대 댓글 수를 입력하고 버튼을 누르면, 인기순 댓글로 워드클라우드를 만들어요.")

DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# ---------------------------- 캐시 리소스 (폰트) ----------------------------
@st.cache_resource(show_spinner=False)
def get_font_path():
    """나눔고딕 폰트를 처음 한 번만 내려받아 임시 폴더에 저장하고 경로를 돌려줘요."""
    font_name = "NanumGothic-Regular.ttf"
    font_path = os.path.join(tempfile.gettempdir(), font_name)
    if os.path.exists(font_path) and os.path.getsize(font_path) > 0:
        return font_path

    urls = [
        "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
        "https://fonts.gstatic.com/ea/nanumgothic/v5/NanumGothic-Regular.ttf",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200 and r.content:
                with open(font_path, "wb") as f:
                    f.write(r.content)
                return font_path
        except Exception:
            continue
    return None  # 실패하면 None

# ---------------------------- 연결 재사용 ----------------------------
@st.cache_resource(show_spinner=False)
def get_http_session():
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s

# ---------------------------- 도우미 함수들 ----------------------------
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

    # https://www.youtube.com/watch?v=VIDEO_ID
    if "youtube.com" in host:
        if "v" in qs and qs["v"]:
            return qs["v"][0]
        # /embed/VIDEO_ID
        m = re.search(r"/embed/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
        # /shorts/VIDEO_ID
        m = re.search(r"/shorts/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
        # /live/VIDEO_ID
        m = re.search(r"/live/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
    # https://youtu.be/VIDEO_ID
    if "youtu.be" in host:
        m = re.match(r"^/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)

    # 예외적으로 query에 vi=가 올 때
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


def fetch_comment_texts(api_key: str, video_id: str, session: requests.Session, limit: int):
    """인기순으로 댓글 본문만 모아줘요."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "order": "relevance",       # 인기순
        "maxResults": 100,
        "textFormat": "plainText",  # 본문만
    }
    texts = []
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


def tokenize_texts(texts, extra_stopwords):
    """특수문자/이모지를 지우고, 2글자 이상 한글/영어 단어만 남겨서 빈도를 계산해요."""
    # 쉼표로 입력된 불용어 처리(소문자, 공백 제거)
    stop = set()
    for w in extra_stopwords.split(","):
        w = w.strip().lower()
        if w:
            stop.add(w)

    tokens = []
    for t in texts:
        t = t.lower()
        # 한글/영어만 남기고 최소 2글자 단어 추출
        words = re.findall(r"[가-힣a-zA-Z]{2,}", t)
        for w in words:
            w = w.lower()
            if w in stop:
                continue
            tokens.append(w)

    return Counter(tokens)


def sanitize_filename(name: str) -> str:
    """파일명에 쓸 수 없는 문자를 제거해요."""
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name or "wordcloud"


# ---------------------------- 화면 ----------------------------
api_key = st.secrets.get("youtube_api_key", "")
if not api_key:
    st.error("API 키가 없어요. .streamlit/secrets.toml에 넣어 주세요.")

url_input = st.text_input(
    "유튜브 주소를 넣어 주세요.",
    value=DEFAULT_URL,
    placeholder="예) https://youtu.be/VIDEO_ID 또는 https://www.youtube.com/watch?v=VIDEO_ID",
)

col1, col2 = st.columns([1, 1.5])
with col1:
    max_count = st.number_input("최대 댓글 수", min_value=100, max_value=5000, value=500, step=100)
with col2:
    stopwords_input = st.text_input("불용어(쉼표로 구분)", value="", placeholder="예) the, and, 정말, 이런")

make_btn = st.button("워드클라우드 만들기", disabled=(not bool(api_key)))

# 버튼을 누르기 전에는 어떤 연결도 시도하지 않아요.
if make_btn:
    video_id = extract_video_id(url_input)
    if not video_id:
        st.error("주소가 올바르지 않아요.")
        st.stop()

    session = get_http_session()

    with st.spinner("댓글을 모으는 중이에요..."):
        try:
            texts = fetch_comment_texts(api_key, video_id, session, int(max_count))
        except Exception:
            st.error("데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
            st.stop()

    if not texts:
        st.error("분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    freq = tokenize_texts(texts, stopwords_input)
    if not freq or sum(freq.values()) == 0:
        st.error("분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    font_path = get_font_path()
    if not font_path:
        st.error("폰트를 내려받지 못해 워드클라우드를 만들 수 없어요. 잠시 후 다시 시도해 주세요.")
        st.stop()

    # 워드클라우드 생성
    wc = WordCloud(
        width=1600,
        height=1000,
        background_color="white",
        font_path=font_path,
        collocations=False,
        regexp=r"[가-힣a-zA-Z]{2,}",
    ).generate_from_frequencies(freq)

    # 여백 없이 그리기
    fig = plt.figure(figsize=(12, 7.5), dpi=150)
    plt.imshow(wc, interpolation="bilinear")
    plt.axis("off")
    plt.tight_layout(pad=0)

    st.pyplot(fig, use_container_width=True)

    # PNG 내려받기
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    buf.seek(0)

    fname = sanitize_filename(f"wordcloud_{video_id}_{int(max_count)}.png")
    st.download_button(
        label="PNG로 내려받기",
        data=buf.getvalue(),
        file_name=fname,
        mime="image/png",
    )
