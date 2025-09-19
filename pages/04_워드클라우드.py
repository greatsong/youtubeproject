# app.py
import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
import re
from collections import Counter
import pandas as pd
import altair as alt
from io import BytesIO
from wordcloud import WordCloud, STOPWORDS as WC_STOPWORDS
import matplotlib.pyplot as plt
import os
import tempfile

# ---------------------------- 페이지 설정 ----------------------------
st.set_page_config(page_title="🧩 유튜브 댓글 워드클라우드", layout="wide")
st.title("🧩 유튜브 댓글 워드클라우드")
st.caption("🔗 주소와 옵션을 넣고 ▶ 버튼을 눌러 워드클라우드를 만들어 보세요!")

# ---------------------------- 기본값 및 안내 ----------------------------
DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# 대전제 충족: 필요한 라이브러리를 requirements.txt로 저장(자동 생성)
REQUIREMENTS = "\n".join([
    "streamlit",
    "requests",
    "pandas",
    "altair",
    "wordcloud",
    "matplotlib",
    "pillow",
    "tzdata",
])
try:
    with open("requirements.txt", "w", encoding="utf-8") as f:
        f.write(REQUIREMENTS)
except Exception:
    pass

# ---------------------------- 보조 함수들 ----------------------------
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


def sanitize_filename(name: str) -> str:
    """파일명에서 금지 문자를 제거해요."""
    return re.sub(r'[\\/:*?"<>|]+', "", name).strip() or "wordcloud"


@st.cache_resource(show_spinner=False)
def get_korean_font_path() -> str | None:
    """나눔고딕 폰트를 웹에서 받아 임시 폴더에 저장하고 경로를 돌려줘요.
    1차: GitHub Raw → 실패 시 2차: gstatic으로 재시도해요."""
    # 캐시 디렉터리와 파일 경로
    tmp_dir = tempfile.gettempdir()
    font_path = os.path.join(tmp_dir, "NanumGothic.ttf")
    if os.path.exists(font_path) and os.path.getsize(font_path) > 0:
        return font_path

    urls = [
        # 1차: GitHub (Raw)
        "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
        # 2차: gstatic 대체 URL
        "https://fonts.gstatic.com/s/nanumgothic/v26/PN_3Rfi-oW3hYwmKDpxS7F_DpDmS.woff2",  # woff2이지만 일부 환경에서 변환 불가할 수 있어요
    ]

    # 다운로드 시도 (ttf 우선)
    for i, u in enumerate(urls, start=1):
        try:
            r = requests.get(u, timeout=20)
            if r.status_code == 200 and r.content:
                # woff2인 경우에는 matplotlib에서 직접 사용이 어려울 수 있으므로 무시
                if u.endswith(".woff2"):
                    continue
                with open(font_path, "wb") as f:
                    f.write(r.content)
                if os.path.getsize(font_path) > 0:
                    return font_path
        except Exception:
            continue

    return None


def tokens_from_texts(texts: list[str], stop_en: set[str], stop_ko: set[str]) -> list[str]:
    """특수문자/이모지를 제거하고, 2글자 이상 한글/영어 단어만 남겨요."""
    all_tokens: list[str] = []
    pat = re.compile(r"[a-zA-Z가-힣]{2,}")
    for t in texts:
        t = t.replace("\n", " ").lower()
        toks = pat.findall(t)
        # 불용어 제거
        toks = [w for w in toks if (w not in stop_en and w not in stop_ko)]
        all_tokens.extend(toks)
    return all_tokens


def build_wordcloud(tokens: list[str], max_words: int, font_path: str | None) -> BytesIO | None:
    """토큰으로 워드클라우드를 만들고 PNG로 돌려줘요. 폰트가 없으면 None."""
    if font_path is None:
        return None
    text = " ".join(tokens)
    wc = WordCloud(
        width=1600,
        height=900,
        background_color="white",
        max_words=max_words,
        font_path=font_path,
        prefer_horizontal=0.9,
        collocations=False,
        margin=0,
    ).generate(text)

    # 여백 없이 저장
    fig = plt.figure(figsize=(16, 9), dpi=100)
    plt.imshow(wc, interpolation="bilinear")
    plt.axis("off")
    plt.margins(0, 0)
    plt.tight_layout(pad=0)
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf


def fetch_comments_and_title(api_key: str, video_id: str, max_count: int):
    """영상 제목과 인기순 댓글을 모아와요."""
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    # 제목 가져오기
    v_url = "https://www.googleapis.com/youtube/v3/videos"
    v_params = {"id": video_id, "part": "snippet", "key": api_key}
    v_resp = session.get(v_url, params=v_params, timeout=20)
    if v_resp.status_code != 200:
        raise_api_error(v_resp)
    v_data = v_resp.json()
    items = v_data.get("items", [])
    if not items:
        raise RuntimeError("404:notFound")
    title = items[0]["snippet"].get("title", "video")

    # 댓글 가져오기(인기순)
    c_url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "order": "relevance",
        "maxResults": 100,
        "textFormat": "plainText",
    }
    comments = []
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)

        resp = session.get(c_url, params=params, timeout=20)
        if resp.status_code != 200:
            raise_api_error(resp)
        data = resp.json()
        for it in data.get("items", []):
            try:
                sn = it["snippet"]["topLevelComment"]["snippet"]
                text = (sn.get("textDisplay", "") or "").replace("\n", " ").strip()
                like_count = int(sn.get("likeCount", 0))
                published_at = sn.get("publishedAt", "")
                comments.append({"text": text, "like": like_count, "time": published_at})
            except Exception:
                continue
            if len(comments) >= max_count:
                return title, comments
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return title, comments

# ---------------------------- 한글 불용어(120+) ----------------------------
STOP_KO_BASE = {
    "가","가까이","가령","각","각각","각자","각종","간","간단","간혹","갈수록","감사","갑자기","값","강","거","거기","거의","거나",
    "건","것","게","게다가","겨우","결과","결국","결코","겸","경우","계속","고","고려","골","곧","곳","공","과","과거","과연","관계",
    "관련","관해","교","구","구체","국","군데","권","그","그거","그것","그날","그냥","그녀","그들","그때","그래","그래서","그러나",
    "그러면","그러므로","그런","그런데","그럴","그럼","그렇게","그룹","그만","그밖","그분","그야말로","그 owing","그전","그중","근거",
    "근데","근본","근처","글쎄","금방","기간","긴","깊이","까닭","까지","나","나름","나머지","나아가","나중","남","너","너무","넣",
    "네","년","녘","노","놀라","높","놓","누가","누구","눈","뉴스","느껴","느낌","늦게","다","다만","다소","다시","다양","단","단순",
    "달","담","대","대로","대부분","대비","대신","대하여","대한","덜","데","도","도대체","도로","도로서","도움","동안","동시","동안에",
    "뒤","드","든지","들","등","등등","딱","때","때문","또","또는","또한","라며","라서","로","로부터","로서","로나","로나마","롱","루",
    "리","므로","마다","마냥","마저","마치","만","만나","만들","만약","만일","만큼","많이","말","말로","말하","맘","매우","머","먼저",
    "멀리","며","면","면서","몇","모두","모든","모처럼","무엇","무슨","무척","문","문제","문화","및","바","바깥","바로","바탕","박",
    "밖","반면","받","발","발견","발표","방금","방법","번","별","병","보고","보내","보다","보통","봄","부","부분","부족","뿐","뿐만",
    "뿐이다","브","비","비롯","비해","빨리","사람","사실","사항","사이","사용","사이","사회","산","살짝","상","상관","상대","상당",
    "상세","상태","상황","새","생각","생산","서로","서서히","선","선택","설명","성","세계","세","세대","센","소","소수","속","손","솔직",
    "수","수준","순간","순서","쉽게","쉬운","스스로","습관","시간","시기","시대","시작","시점","시험","식","신","실","실제로","실제",
    "심지어","싶","쓰","아","아까","아니","아니라","아닌","아니요","아마","아무","아예","아주","아직","안","안에","않","알","앞","약",
    "약간","양","어느","어떤","어떻게","어때","어려","어울","어쩌면","어찌","언제","얼마","엄청","엉","에게","에게서","에서","여기",
    "여러","여러분","여전히","여튼","연구","연속","열","영","예","예를","예술","예전","오늘","오래","오히려","와","왜","외","요","요즘",
    "우","우리","우선","운","원","원래","원인","월","위","위해","유","육","은","은근","을","음","이","이것","이곳","이날","이다","이러",
    "이런","이래서","이러면","이럴","이렇게","이번","이분","이상","이야","이야말로","이후","인","인해","일","일때","일부","일반","일부러",
    "임","입장","자","자기","자꾸","자신","자신감","자리","자주","작","잔","잘","잠깐","장","저","저거","저것","저기","저녁","저러","저런",
    "저렇게","저번","저분","적","전","전자","전체","전혀","전후","점","정도","정리","정말","정부","정의","정확","제","제대로","제일","조금",
    "조차","존재","졸","좀","종","주","주의","줄","중","중간","중요","즉","지","지나","지난","지금","지만","지속","지역","지원","지적",
    "진짜","질","쪽","차","차라리","참","창","찾","처","처음","처럼","천","첫","첫째","청","체","초","총","최고","최근","최대한","추가",
    "추정","축","취지","측","층","취","치","친","카","크","큰","키","타","특별","특히","틈","파","편","평균","평소","포함","표","풀","프로",
    "필요","하","하고","하게","하나","하니","한다","하는","하여","하지만","한","한번","한편","할","함","해","해서","해도","해도돼","해요",
    "했던","했어요","했다","했는데","해야","호","혹시","혹은","혹","후","후에","훨씬"
}

# ---------------------------- UI ----------------------------
api_key = st.secrets.get("youtube_api_key", "")
if not api_key:
    st.error("🔐 API 키가 없어요. .streamlit/secrets.toml에 넣어 주세요.")
st.markdown("### ✏️ 입력 옵션")

with st.form("config_form"):
    url_input = st.text_input(
        "🔗 유튜브 주소",
        value=DEFAULT_URL,
        placeholder="예) https://youtu.be/VIDEO_ID 또는 https://www.youtube.com/watch?v=VIDEO_ID",
    )

    c1, c2 = st.columns(2)
    with c1:
        max_comments = st.slider("🧮 최대 댓글 수 (100~2000)", 100, 2000, 1000, step=100)
    with c2:
        max_words = st.slider("☁️ 워드클라우드 단어 수 (20~200)", 20, 200, 100, step=10)

    with st.expander("📝 영어/한국어 불용어 편집 (쉼표 , 로 구분해요)", expanded=False):
        s1, s2 = st.columns(2)
        with s1:
            user_en_stop = st.text_area("🇬🇧 영어 불용어 추가", placeholder="예) video, comment, like")
        with s2:
            user_ko_stop = st.text_area("🇰🇷 한글 불용어 추가", placeholder="예) 영상, 댓글, 좋아요")

    submit = st.form_submit_button("▶ 워드클라우드 만들기", use_container_width=True, disabled=(not bool(api_key)))

# ---------------------------- 실행 ----------------------------
if submit:
    # 주소 확인
    video_id = extract_video_id(url_input)
    if not video_id:
        st.error("❌ 주소가 올바르지 않아요.")
        st.stop()

    # 불용어 합치기 (중복 자동 제거)
    en_stop = set(WC_STOPWORDS)
    if user_en_stop:
        add_en = {w.strip().lower() for w in user_en_stop.split(",") if w.strip()}
        en_stop |= add_en
    ko_stop = set(w.lower() for w in STOP_KO_BASE)
    if user_ko_stop:
        add_ko = {w.strip().lower() for w in user_ko_stop.split(",") if w.strip()}
        ko_stop |= add_ko

    # 데이터 가져오기
    with st.spinner("⏳ 데이터 가져오는 중이에요..."):
        try:
            title, comments = fetch_comments_and_title(api_key, video_id, max_comments)
        except RuntimeError as e:
            msg = str(e)
            if ("403" in msg and ("commentsDisabled" in msg or "forbidden" in msg)) or "commentsDisabled" in msg:
                st.error("🚫 이 영상은 댓글을 볼 수 없어요.")
                st.stop()
            if "quotaExceeded" in msg or "429" in msg:
                st.error("⏱️ 오늘 사용할 수 있는 조회량이 다 됐어요.")
                st.stop()
            st.error("⚠️ 데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
            st.stop()
        except Exception:
            st.error("⚠️ 데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
            st.stop()

    if not comments:
        st.warning("ℹ️ 댓글이 없어요.")
        st.stop()

    # 표용 데이터프레임(원하는 경우 참고용으로 사용 가능)
    df = pd.DataFrame(comments)
    df.rename(columns={"text": "댓글 내용", "time": "작성 시각", "like": "좋아요 수"}, inplace=True)

    # 토큰화 및 불용어 처리
    with st.spinner("🧹 전처리와 단어 추출 중이에요..."):
        texts = [c["text"] for c in comments if c.get("text")]
        tokens = tokens_from_texts(texts, en_stop, ko_stop)

    if len(tokens) == 0:
        st.warning("🫥 분석을 진행할 만큼의 단어를 찾지 못했어요.")
        st.stop()

    # 폰트 준비
    with st.spinner("🔤 한글 폰트 준비 중이에요..."):
        font_path = get_korean_font_path()
        if font_path:
            try:
                plt.rcParams["font.family"] = "NanumGothic"
                plt.rcParams["font.sans-serif"] = ["NanumGothic"]
            except Exception:
                pass

    # 워드클라우드 생성
    with st.spinner("☁️ 워드클라우드 만드는 중이에요..."):
        img_buf = build_wordcloud(tokens, max_words=max_words, font_path=font_path)

    if img_buf is None:
        st.info("🪄 폰트를 준비하지 못해 워드클라우드 생성을 건너뛰었어요. 불용어를 조정해 다시 시도해 주세요.")
        st.stop()

    # 화면 표시
    st.success("✅ 워드클라우드를 만들었어요!")
    st.image(img_buf, caption="워드클라우드", use_column_width=True)

    # 파일명 정리 후 다운로드 버튼 제공
    clean_title = sanitize_filename(title)
    file_name = f"{clean_title or 'wordcloud'}.png"
    st.download_button(
        "⬇️ 워드클라우드 PNG 내려받기",
        data=img_buf,
        file_name=file_name,
        mime="image/png",
        use_container_width=True,
    )
