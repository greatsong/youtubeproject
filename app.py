# app.py
import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
from io import StringIO

# ---------------------------- 기본 설정 ----------------------------
st.set_page_config(page_title="유튜브 댓글 수집기", layout="wide")

st.title("유튜브 댓글 수집기")
st.caption("주소를 넣고 버튼을 누르면 인기순 댓글을 가져와요. 표는 화면 너비에 맞게 보여줘요.")

DEFAULT_URL = "https://www.youtube.com/watch?v=WXuK6gekU1Y"

# ---------------------------- 도우미 함수들 ----------------------------
def extract_video_id(url: str) -> str | None:
    """여러 형태의 유튜브 주소에서 영상 ID를 뽑아줘요."""
    if not url:
        return None
    url = url.strip()

    # 완전한 URL이 아니더라도 처리 시도
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    qs = parse_qs(parsed.query or "")

    # 1) https://www.youtube.com/watch?v=VIDEO_ID
    if "youtube.com" in host:
        if "v" in qs and qs["v"]:
            return qs["v"][0]
        # 2) /embed/VIDEO_ID
        m = re.search(r"/embed/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
        # 3) /shorts/VIDEO_ID
        m = re.search(r"/shorts/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
        # 4) /live/VIDEO_ID (간혹 있음)
        m = re.search(r"/live/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)
    # 5) https://youtu.be/VIDEO_ID
    if "youtu.be" in host:
        m = re.match(r"^/([A-Za-z0-9_-]{6,})", path)
        if m:
            return m.group(1)

    # 예외적으로 query에 vi=가 들어오는 경우
    if "vi" in qs and qs["vi"]:
        return qs["vi"][0]

    return None


def to_kst(iso_utc: str) -> str:
    """UTC ISO 시간을 한국 시간(Asia/Seoul)으로 바꿔서 보기 좋게 돌려줘요."""
    try:
        dt_utc = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
        dt_kst = dt_utc.astimezone(ZoneInfo("Asia/Seoul"))
        return dt_kst.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_utc


def build_comments_dataframe(items: list[dict]) -> pd.DataFrame:
    """API 응답 아이템에서 표로 보여줄 데이터를 만들어줘요."""
    rows = []
    for it in items:
        try:
            snippet = it["snippet"]
            top = snippet["topLevelComment"]["snippet"]
            text = top.get("textDisplay", "").replace("\n", " ").strip()
            published_at = top.get("publishedAt", "")
            like_count = int(top.get("likeCount", 0))
            rows.append(
                {
                    "댓글 내용": text,
                    "작성 시각": to_kst(published_at),
                    "좋아요 수": like_count,
                }
            )
        except Exception:
            # 개별 항목 문제가 있어도 전체는 계속 진행
            continue
    df = pd.DataFrame(rows, columns=["댓글 내용", "작성 시각", "좋아요 수"])
    return df


def as_csv_utf8_sig(df: pd.DataFrame) -> bytes:
    """엑셀에서 한글이 안 깨지도록 UTF-8-SIG(BOM)로 저장해요."""
    buffer = StringIO()
    df.to_csv(buffer, index=False, encoding="utf-8-sig")
    return buffer.getvalue().encode("utf-8-sig")


@st.cache_resource(show_spinner=False)
def get_http_session() -> requests.Session:
    """한 번 만든 연결을 재사용해요."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


def fetch_all_comments(api_key: str, video_id: str, session: requests.Session, max_total: int = 1000) -> list[dict]:
    """유튜브 댓글 스레드를 인기순으로 모두(최대 max_total개) 모아와요."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "order": "relevance",
        "maxResults": 100,
        "textFormat": "html",
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
        if len(items) >= max_total:
            items = items[:max_total]
            break

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return items


def raise_api_error(resp: requests.Response) -> None:
    """API 오류를 파악해서 예외를 올려줘요."""
    try:
        data = resp.json()
    except Exception:
        data = {}
    reason = ""
    try:
        reason = data["error"]["errors"][0].get("reason", "")
    except Exception:
        pass
    # 응답 코드와 사유를 함께 담아 올려요.
    raise RuntimeError(f"{resp.status_code}:{reason}")


# ---------------------------- 화면 ----------------------------
api_key = st.secrets.get("youtube_api_key", "")

if not api_key:
    st.error("API 키가 없어요. .streamlit/secrets.toml에 넣어 주세요.")

url_input = st.text_input(
    "유튜브 주소를 넣어 주세요.",
    value=DEFAULT_URL,
    placeholder="예) https://youtu.be/VIDEO_ID 또는 https://www.youtube.com/watch?v=VIDEO_ID",
)

# API 키가 없으면 버튼을 막아요.
fetch_btn = st.button("댓글 가져오기", disabled=(not bool(api_key)))

# 버튼을 누르기 전에는 어떤 연결도 시도하지 않아요.
if fetch_btn:
    video_id = extract_video_id(url_input)
    if not video_id:
        st.error("주소가 올바르지 않아요.")
        st.stop()

    session = get_http_session()

    with st.spinner("댓글을 가져오는 중이에요..."):
        try:
            items = fetch_all_comments(api_key, video_id, session)
        except RuntimeError as e:
            msg = str(e)
            # 댓글 꺼짐/차단
            if ("403" in msg and ("commentsDisabled" in msg or "forbidden" in msg)) or "commentsDisabled" in msg:
                st.error("이 영상은 댓글을 볼 수 없어요.")
                st.stop()
            # 조회량(쿼터) 초과
            if "quotaExceeded" in msg or "429" in msg:
                st.error("오늘 사용할 수 있는 조회량이 다 됐어요.")
                st.stop()
            # 그 밖의 오류
            st.error("댓글을 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
            st.stop()
        except Exception:
            st.error("댓글을 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
            st.stop()

    df = build_comments_dataframe(items)

    if df.empty:
        st.info("가져올 댓글이 없어요.")
    else:
        st.dataframe(df, use_container_width=True)
        csv_bytes = as_csv_utf8_sig(df)
        st.download_button(
            label="CSV로 내려받기",
            data=csv_bytes,
            file_name="youtube_comments.csv",
            mime="text/csv",
        )
