# app.py
import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
import re
from collections import Counter
from typing import Optional, List
import pandas as pd
import altair as alt

# ---------------------------- 기본 설정 ----------------------------
st.set_page_config(page_title="유튜브 댓글 단어 빈도 분석", layout="wide")
st.title("유튜브 댓글 단어 빈도 분석")
st.caption("주소를 넣고 댓글을 인기순으로 모아서, 단어를 뽑아 상위 20개를 그래프로 보여줘요.")

DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# ---------------------------- 불용어 목록(간단) ----------------------------
STOP_EN = {
    "a","an","the","and","or","but","if","then","else","for","with","about","into","over","after","before","between","under",
    "to","of","in","on","at","by","as","from","up","down","out","off","than","so","too","very","just","only","also","not",
    "no","nor","all","any","both","each","few","more","most","other","some","such","own","same","once","ever","never","can",
    "will","would","could","should","is","am","are","was","were","be","been","being","do","does","did","doing","don","doesn",
    "didn","i","you","he","she","it","we","they","me","my","mine","your","yours","our","ours","their","theirs","this","that",
    "these","those","here","there","when","where","why","how"
}
STOP_KO = {
    "그리고","그러나","하지만","그래서","또한","및","등","등등","또","아니라","보다","위해","대한","때문","때문에","으로","으로써","으로서",
    "에서","에게","에게서","부터","까지","하다","한다","했다","하는","한","하면","하며","하여","하니","하고","돼","된다","되는","되어","됐다",
    "되다","이다","입니다","있는","있다","없다","같다","거","것","수","들","그","이","저","그것","이것","저것","때","일","좀","등등","자",
    "너무","정말","매우","많이","많다","더","또는","만","라도","에게로","까지도","에서의","에서만","부터도","에는","에는가","이며","이나","이나요",
    "요","네","죠","거의","현재","영상","댓글","유튜브","보기","저희","여러분","오늘","진짜","근데","그냥","아마","이미","다시","다른","최근",
    "처럼","같이","우리","제가","너가","니가","제가요","내가","제가요","그게","이게","저게","때가","때는","때에"
}
STOP_ETC = {
    "https","http","www","com","net","org","kr","co","youtu","youtube","watch","video","amp"
}
STOPWORDS = {w.lower() for w in (STOP_EN | STOP_KO | STOP_ETC | {"ㅋㅋ","ㅎㅎ","ㅠㅠ","ㅜㅜ","ㅠ","ㅜ"})}

# ---------------------------- 도우미 함수들 ----------------------------
def extract_video_id(url: str) -> Optional[str]:
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


@st.cache_data(show_spinner=False, ttl=600)
def fetch_comment_texts(api_key: str, video_id: str, limit: Optional[int]) -> List[str]:
    """인기순으로 댓글 본문만 모아줘요. limit가 None이면 가능한 만큼 모두 모아요."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "order": "relevance",       # 인기순
        "maxResults": 100,          # 한 번에 최대
        "textFormat": "plainText",  # 본문만 받을게요
    }
    texts: List[str] = []
    page_token = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)

        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            raise_api_error(resp)

        data = resp.json()
        for it in data.get("items", []):
            try:
                top = it["snippet"]["topLevelComment"]["snippet"]
                txt = top.get("textDisplay", "")
                txt = txt.replace("\n", " ").strip()
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


@st.cache_data(show_spinner=False, ttl=600)
def count_top_words(texts: List[str], topk: int = 20) -> pd.DataFrame:
    """댓글에서 단어를 뽑고(soynlp), 소문자/2글자 이상/불용어 제거 후 상위 topk를 돌려줘요."""
    from soynlp.tokenizer import RegexTokenizer
    regex_tok = RegexTokenizer()

    all_tokens: List[str] = []
    for t in texts:
        # 1차: soynlp 토크나이저
        toks = regex_tok.tokenize(t)
        refined = []
        for tok in toks:
            tok = tok.lower()
            # 한글/영문/숫자만 남겨요
            m = re.fullmatch(r"[가-힣a-z0-9]+", tok)
            if not m:
                continue
            if len(tok) < 2:
                continue
            if tok in STOPWORDS:
                continue
            refined.append(tok)

        # 보조: 너무 걸러졌다면 간단 규칙으로 추가 추출
        if not refined:
            extra = re.findall(r"[가-힣a-z0-9]+", t.lower())
            refined = [w for w in extra if len(w) >= 2 and w not in STOPWORDS]

        all_tokens.extend(refined)

    if not all_tokens:
        return pd.DataFrame(columns=["단어", "빈도"])

    freq = Counter(all_tokens)
    most = freq.most_common(topk)
    return pd.DataFrame(most, columns=["단어", "빈도"])


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
    slider_val = st.slider("슬라이더(100~1000, 100단위)", 100, 1000, 500, step=100)
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

    with st.spinner("댓글을 모으는 중이에요..."):
        try:
            texts = fetch_comment_texts(api_key, video_id, limit)
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
