import streamlit as st

# ---------------------------- 페이지 설정 (가장 먼저) ----------------------------
st.set_page_config(
    page_title="유튜브 댓글 분석 홈",
    page_icon="📊",
    layout="wide",
)

# ---------------------------- 본문 ----------------------------
st.markdown(
    """
# 📊 유튜브 댓글 분석 스튜디오
### 작은 댓글에서 큰 인사이트까지 ✨

---

## 🧭 무엇을 할 수 있나요?
- 인기순으로 댓글을 빠르게 모아와요.
- 단어를 뽑아 빈도를 비교하고 시각화해요.
- 한국어/영어 불용어를 간편하게 관리해요.
- 시간 흐름에 따른 댓글/좋아요 패턴을 살펴봐요.
- 워드클라우드로 핵심 키워드를 한눈에 파악해요.

---

## 🔑 YouTube API Key 발급 안내 (6단계)
1. [Google Cloud Console](https://console.cloud.google.com/)에 로그인해요.
2. 새 프로젝트를 만들거나, 사용할 프로젝트를 선택해요.
3. 왼쪽 메뉴 **APIs & Services → Enabled APIs & services**로 들어가요.
4. 상단 **+ ENABLE APIS AND SERVICES**를 눌러 **YouTube Data API v3**를 검색·활성화해요.
5. **Credentials(사용자 인증 정보)**에서 **+ CREATE CREDENTIALS → API key**를 눌러 키를 만들어요.
6. 발급된 키를 복사한 뒤, 스트림릿 클라우드에서 시크릿으로 저장해요.  
   **⚠️ 절대 코드나 화면에 키를 노출하지 마세요!**

### 📁 스트림릿 클라우드 시크릿 설정 예시
아래 내용을 **`.streamlit/secrets.toml`**에 저장해요:
```toml
youtube_api_key = "여기에_발급받은_API_KEY_붙여넣기"
🚀 시작 안내
왼쪽 사이드바에서 원하는 분석기 (댓글 수집/빈도/불용어/심층/워드클라우드) 를 선택하세요.
"""
)
