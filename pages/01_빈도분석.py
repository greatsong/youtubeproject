# app.py
import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
import re
from collections import Counter
import pandas as pd
import altair as alt

# ---------------------------- 기본 설정 ----------------------------
st.set_page_config(page_title="유튜브 댓글 단어 빈도 분석", layout="wide")
st.title("유튜브 댓글 단어 빈도 분석")
st.caption("주소를 넣고 댓글을 인기순으로 모아서, 단어를 뽑아 상위 20개를 그래프로 보여줘요.")

DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# ---------------------------- 도우미 함수들 ----------------------------
def extract_video_id(url: str) -> str | None:
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

    if "vi" in qs and qs["vi"]:
        return qs["vi"][0]

    return None


@st.cache_resource(show_spinner=False)
def get_http_session() -> requests.Session:
    """유튜브 API 호출에 쓸 연결을 한 번 만들고 재사용해요."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


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


def fetch_comment_texts(api_key: str, video_id: str, session: requests.Session, limit: int | None) -> list[str]:
    """인기순으로 댓글 내용을 모아줘요. limit가 None이면 가능한 만큼 모두 모아요."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "order": "relevance",       # 인기순
        "maxResults": 100,          # 한 번에 최대
        "textFormat": "plainText",  # 내용만 받을게요
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
                top = it["snippet"]["topLevelComment"]["snippet"]
                txt = top.get("textDisplay", "").replace("\n", " ").strip()
                if txt:
                    texts.append(txt)
            except Exception:
                continue

            if isinstance(limit, int) and len(texts) >= limit:
                return texts

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return texts


def simple_tokenize_korean_english(text: str) -> list[str]:
    """한글/영문/숫자 섞인 단어를 간단히 뽑아요. 2글자 미만은 버려요."""
    # soynlp의 정규표현 토크나이저와 비슷한 기준으로 단어를 뽑아요.
    # 한글, 영문, 숫자가 섞인 덩어리를 단어로 보고, 2글자 이상만 사용해요.
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text)
    tokens = [t.lower() for t in tokens if len(t) >= 2]
    return tokens


def count_top_words(texts: list[str], topk: int = 20) -> pd.DataFrame:
    """여러 문장에서 단어를 뽑아 빈도를 세고 상위 topk를 표로 돌려줘요."""
    from soynlp.tokenizer import RegexTokenizer  # 가벼운 토크나이저
    regex_tok = RegexTokenizer()

    all_tokens: list[str] = []
    for t in texts:
        # soynlp 토크나이저로 1차 토큰화
        toks = regex_tok.tokenize(t)
        # 간단 규칙으로 2차 정제(2글자 이상만)
        toks = [tok.lower() for tok in toks if len(tok) >= 2]
        # 정규식으로도 보완(이모지/기호 등 제거)
        refined = []
        for tok in toks:
            if re.fullmatch(r"[가-힣A-Za-z0-9]+", tok):
                refined.append(tok)
        # 만약 위에서 너무 걸러졌다면 보조 토크나이저로 보완
        if not refined:
            refined = simple_tokenize_korean_english(t)
        all_tokens.extend(refined)

    if not all_tokens:
        return pd.DataFrame(columns=["단어", "빈도"])

    freq = Counter(all_tokens)
    most = freq.most_common(topk)
    df = pd.DataFrame(most, columns=["단어", "빈도"])
    return df


# ---------------------------- 화면 ----------------------------
api_key = st.secrets.get("youtube_api_key", "")
if not api_key:
    st.error("API 키가 없어요. .streamlit/secrets.toml에 넣어 주세요.")

url_input = st.text_input(
    "유튜브 주소를 넣어 주세요.",
    value=DEFAULT_URL,
    placeholder="예) https://youtu.be/VIDEO_ID 또는 https://www.youtube.com/watch?v=VIDEO_ID",
)

col1, col2, col3 = st.columns([1, 1, 1.2])

with col1:
    quick = st.radio("빠른 선택", options=["100", "500", "1000", "모두"], horizontal=True, index=0)
with col2:
    slider_val = st.slider("슬라이더(100~1000)", min_value=100, max_value=1000, step=100, value=500)
with col3:
    fetch_btn = st.button("댓글 가져와서 분석하기", disabled=(not bool(api_key)))

# 버튼을 누르기 전에는 어떤 연결도 시도하지 않아요.
if fetch_btn:
    video_id = extract_video_id(url_input)
    if not video_id:
        st.error("주소가 올바르지 않아요.")
        st.stop()

    # 실제 개수는 두 값 중 큰 값, 단 '모두'면 제한 없이 가져와요.
    if quick == "모두":
        limit = None
    else:
        try:
            quick_n = int(quick)
        except Exception:
            quick_n = 100
        limit = max(quick_n, slider_val)

    session = get_http_session()

    with st.spinner("댓글을 모으는 중이에요..."):
        try:
            texts = fetch_comment_texts(api_key, video_id, session, limit)
        except RuntimeError as e:
            msg = str(e)
            if ("403" in msg and ("commentsDisabled" in msg or "forbidden" in msg)) or "commentsDisabled" in msg:
                st.error("이 영상은 댓글을 볼 수 없어요.")
                st.stop()
            if "quotaExceeded" in msg or "429" in msg:
                st.error("오늘 사용할 수 있는 조회량이 다 됐어요.")
                st.stop()
            st.error("댓글을 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
            st.stop()
        except Exception:
            st.error("댓글을 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
            st.stop()

    if not texts:
        st.info("가져올 댓글이 없어요.")
        st.stop()

    df_top = count_top_words(texts, topk=20)

    if df_top.empty:
        st.info("단어를 뽑을 수 없었어요.")
        st.stop()

    st.subheader("상위 20개 단어 - 기본 막대그래프")
    st.bar_chart(df_top.set_index("단어"), use_container_width=True)

    st.subheader("상위 20개 단어 - Altair 막대그래프")
    chart = (
        alt.Chart(df_top)
        .mark_bar()
        .encode(
            x=alt.X("단어:N", sort="-y", title="단어"),
            y=alt.Y("빈도:Q", title="빈도"),
            tooltip=["단어", "빈도"],
        )
    )
    st.altair_chart(chart, use_container_width=True)
