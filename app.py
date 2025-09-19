import streamlit as st

# 페이지 설정 (가장 먼저 실행)
st.set_page_config(
    page_title="YouTube 댓글 분석 홈",
    page_icon="🎬",
    layout="wide",
)

# 1) 프로젝트 제목 + 부제
st.markdown("# 🎬 YouTube 댓글 분석 허브")
st.markdown("### 🔍 댓글 수집 · 빈도 분석 · 불용어 관리 · 심층 분석 · 워드클라우드")

st.markdown("---")

# 2) 프로젝트 소개 (무엇을 할 수 있는지 4~5개 불릿)
st.markdown("#### ✨ 무엇을 할 수 있나요?")
st.markdown("- 유튜브 **영상 주소**로 인기순 **댓글 수집**")
st.markdown("- 댓글에서 **단어 추출·빈도 분석** 및 **불용어 관리**")
st.markdown("- 시간 기반 **심층 분석**(누적선, 시간대별 좋아요, 산점도)")
st.markdown("- **워드클라우드** 생성 및 **PNG 다운로드**")
st.markdown("- 결과를 **표/그래프**로 깔끔하게 확인")

st.markdown("---")

# 3) YouTube API Key 발급 안내 (6단계 + 스트림릿 시크릿 예시)
st.markdown("#### 🔑 YouTube API Key 발급 안내 (간단 6단계)")
st.markdown("1. [Google Cloud Console](https://console.cloud.google.com/) 에 접속해요.")
st.markdown("2. 새 **프로젝트**를 만들거나 기존 프로젝트를 선택해요.")
st.markdown("3. **APIs & Services → Library**에서 **YouTube Data API v3**를 검색해요.")
st.markdown("4. **Enable(사용 설정)** 버튼을 눌러 API를 활성화해요.")
st.markdown("5. **APIs & Services → Credentials**에서 **API key**를 생성해요.")
st.markdown("6. 생성된 **API Key**를 아래 예시처럼 스트림릿 **Secrets**에 저장해요.")
st.markdown("**⚠️ 키는 코드나 저장소에 노출하지 마세요. 반드시 Secrets에만 보관해요.**")

st.markdown("##### 📦 Streamlit Cloud Secrets 예시")
st.code(
    """
# .streamlit/secrets.toml
youtube_api_key = "여기에_발급받은_API_KEY_입력"
""".strip(),
    language="toml",
)

st.markdown("---")

# 4) 시작 안내
st.markdown("#### 🚀 시작하기")
st.markdown("왼쪽 **사이드바**에서 원하는 분석기(**댓글 수집/빈도/불용어/심층/워드클라우드**)를 선택하세요.")
