# app.py
import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
import re
import pandas as pd
import altair as alt

# ---------------------------- 기본 설정 ----------------------------
st.set_page_config(page_title="유튜브 댓글 시간 분석기", layout="wide")
st.title("유튜브 댓글 시간 분석기")
st.caption("주소를 넣고 버튼을 누르면 업로드일을 확인하고, 댓글을 인기순으로 모아 시간 기반 그래프를 보여줘요.")

DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# ---------------------------- 유틸리티 ----------------------------
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


@st.cache_resource(show_spinner=False)
def get_http_session() -> requests.Session:
    """유튜브 API 호출용 세션을 한 번 만들고 재사용해요."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


def get_video_published_at(api_key: str, video_id: str, session: requests.Session) -> str:
    """영상 업로드 시각(ISO8601, UTC)을 가져와요."""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"id": video_id, "part": "snippet", "key": api_key}
    resp = session.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        raise_api_error(resp)
    data = resp.json()
    items = data.get("items", [])
    if not items:
        raise RuntimeError("404:notFound")
    return items[0]["snippet"]["publishedAt"]  # 예: '2020-01-01T12:34:56Z'


def fetch_comments(api_key: str, video_id: str, session: requests.Session, limit: int | None):
    """인기순 댓글을 모아와요. limit가 None이면 가능한 만큼 모두 모아요."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "order": "relevance",       # 인기순
        "maxResults": 100,
        "textFormat": "plainText",  # 본문만
    }
    items = []
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
        items.extend(data.get("items", []))
        if isinstance(limit, int) and len(items) >= limit:
            items = items[:limit]
            break

        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


def build_dataframe(items):
    """표로 보여줄 데이터프레임을 만들어요. 시간은 KST로 변환해요."""
    rows = []
    for it in items:
        try:
            sn = it["snippet"]["topLevelComment"]["snippet"]
            text = (sn.get("textDisplay", "") or "").replace("\n", " ").strip()
            published_at = sn.get("publishedAt", "")
            like_count = int(sn.get("likeCount", 0))
            rows.append(
                {
                    "댓글 내용": text,
                    "작성 시각": published_at,  # 일단 문자열(UTC)
                    "좋아요 수": like_count,
                }
            )
        except Exception:
            continue

    df = pd.DataFrame(rows, columns=["댓글 내용", "작성 시각", "좋아요 수"])
    if df.empty:
        return df

    # pandas.to_datetime으로 UTC -> KST(+9) 변환
    # publishedAt는 보통 Z(UTC) 포맷이므로 utc=True로 파싱한 뒤 tz_convert
    df["작성 시각"] = pd.to_datetime(df["작성 시각"], utc=True).dt.tz_convert("Asia/Seoul")
    return df


def make_cumulative_chart(df: pd.DataFrame, upload_kst: pd.Timestamp):
    """시간순 누적선과 1주일 내 최대 증가 시점(빨간 점선)을 그려요."""
    # 시간순 정렬 및 누적 개수 계산
    d = df.sort_values("작성 시각").copy()
    d["누적 개수"] = range(1, len(d) + 1)

    base = (
        alt.Chart(d)
        .mark_line()
        .encode(
            x=alt.X("작성 시각:T", title="시간"),
            y=alt.Y("누적 개수:Q", title="누적 개수"),
            tooltip=[alt.Tooltip("작성 시각:T", title="시간"), alt.Tooltip("누적 개수:Q", title="누적")]
        )
    )

    # 업로드일 기준 7일 구간에서 시간대(1시간)별 증가량 계산
    seven_days_end = upload_kst + pd.Timedelta(days=7)
    d7 = d[(d["작성 시각"] >= upload_kst) & (d["작성 시각"] < seven_days_end)].copy()

    rule_layer = None
    if not d7.empty:
        # 시간 단위로 리샘플해서 해당 시간에 새로 달린 댓글 수(증가량) 계산
        hourly = (
            d7.set_index("작성 시각")
            .resample("H")["누적 개수"]
            .count()  # 해당 시간 구간에 추가된 개수
        )

        if hourly.sum() > 0:
            max_hour = hourly.idxmax()  # 증가가 가장 큰 시각(시간 구간의 시작)
            rule_layer = (
                alt.Chart(pd.DataFrame({"x": [max_hour]}))
                .mark_rule(color="red", strokeDash=[6, 4])
                .encode(x="x:T")
            )

    return base if rule_layer is None else base + rule_layer


def make_scatter_likes(df: pd.DataFrame):
    """작성 시각 ↔ 좋아요 수 산점도"""
    chart = (
        alt.Chart(df)
        .mark_point()
        .encode(
            x=alt.X("작성 시각:T", title="시간"),
            y=alt.Y("좋아요 수:Q", title="좋아요 수"),
            tooltip=[alt.Tooltip("작성 시각:T", title="시간"), alt.Tooltip("좋아요 수:Q", title="좋아요 수"), alt.Tooltip("댓글 내용:N", title="댓글")],
        )
    )
    return chart


def make_hourly_like_barchart(df: pd.DataFrame):
    """시간대(시)별 좋아요 수 합계 막대그래프"""
    d = df.copy()
    d["시간대"] = d["작성 시각"].dt.hour
    agg = d.groupby("시간대", as_index=False)["좋아요 수"].sum().sort_values("시간대")
    chart = (
        alt.Chart(agg)
        .mark_bar()
        .encode(
            x=alt.X("시간대:O", title="시간대(시)"),
            y=alt.Y("좋아요 수:Q", title="좋아요 수 합계"),
            tooltip=["시간대", "좋아요 수"],
        )
    )
    return chart


def make_hourly_like_boxplot(df: pd.DataFrame):
    """시간대별 좋아요 분포(박스플롯)"""
    d = df.copy()
    d["시간대"] = d["작성 시각"].dt.hour
    chart = (
        alt.Chart(d)
        .mark_boxplot()
        .encode(
            x=alt.X("시간대:O", title="시간대(시)"),
            y=alt.Y("좋아요 수:Q", title="좋아요 수 분포"),
            tooltip=["시간대"]
        )
    )
    return chart


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
    slider_val = st.slider("슬라이더(100~1000, 100단위)", min_value=100, max_value=1000, step=100, value=500)
with col3:
    fetch_btn = st.button("업로드일 확인 후 댓글 모으기", disabled=(not bool(api_key)))

# 버튼을 누르기 전에는 어떤 연결도 시도하지 않아요.
if fetch_btn:
    video_id = extract_video_id(url_input)
    if not video_id:
        st.error("주소가 올바르지 않아요.")
        st.stop()

    # 실제 개수는 두 값 중 큰 값, 단 '모두'면 가능한 만큼
    if quick == "모두":
        limit = None
    else:
        try:
            quick_n = int(quick)
        except Exception:
            quick_n = 100
        limit = max(quick_n, slider_val)

    session = get_http_session()

    # 업로드일(UTC) 가져오기
    try:
        published_utc = get_video_published_at(api_key, video_id, session)
    except RuntimeError:
        st.error("데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()
    except Exception:
        st.error("데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()

    # 업로드일을 pandas로 파싱하고 KST로 변환
    try:
        upload_kst = pd.to_datetime(published_utc, utc=True).tz_convert("Asia/Seoul")
    except Exception:
        st.error("데이터를 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
        st.stop()

    # 댓글 모으기
    with st.spinner("댓글을 모으는 중이에요..."):
        try:
            items = fetch_comments(api_key, video_id, session, limit)
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

    df = build_dataframe(items)
    if df.empty:
        st.info("가져올 댓글이 없어요.")
        st.stop()

    # 표 보여주기
    st.subheader("댓글 표")
    st.dataframe(df[["댓글 내용", "작성 시각", "좋아요 수"]], use_container_width=True)

    # 누적선 + 1주일 내 최대 증가 시점 표시
    st.subheader("시간순 누적선 (빨간 점선: 1주일 내 최대 증가 시점)")
    cum_chart = make_cumulative_chart(df, upload_kst)
    st.altair_chart(cum_chart, use_container_width=True)

    # 작성 시각 ↔ 좋아요 수 산점도
    st.subheader("작성 시각 ↔ 좋아요 수 (산점도)")
    st.altair_chart(make_scatter_likes(df), use_container_width=True)

    # 시간대(시)별 좋아요 수 합계
    st.subheader("시간대(시)별 좋아요 수 합계")
    st.altair_chart(make_hourly_like_barchart(df), use_container_width=True)

    # 시간대별 좋아요 분포(박스플롯)
    st.subheader("시간대별 좋아요 분포(박스플롯)")
    st.altair_chart(make_hourly_like_boxplot(df), use_container_width=True)
