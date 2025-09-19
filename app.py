import streamlit as st

# 페이지 설정 (가장 먼저 실행)
st.set_page_config(
    page_title="YouTube 댓글 분석기 🎬",
    page_icon="🎯",
    layout="wide"
)

# 본문 구성
st.markdown("# YouTube 댓글 분석기 🎬")
st.markdown("### 소셜 데이터에서 인사이트를 뽑아내는 도구 🛠️")
st.markdown("---")

st.markdown("## 📌 프로젝트 소개")
st.markdown("""
- 유튜브 영상의 댓글을 인기순으로 모아 분석할 수 있어요.  
- 댓글에서 단어를 뽑아 빈도와 분포를 확인할 수 있어요.  
- 불용어(자주 쓰이는 의미 없는 단어)를 제거하여 더 정밀한 분석이 가능해요.  
- 시각화 도구(막대그래프, 워드클라우드 등)를 통해 결과를 쉽게 볼 수 있어요.  
- 원하는 분석기를 선택해 단계별로 활용할 수 있어요.  
""")

st.markdown("---")
st.markdown("## 🔑 YouTube API Key 발급 안내")

st.markdown("""
1. [Google Cloud Console](https://console.cloud.google.com/)에 접속해요.  
2. 새 프로젝트를 만들거나 기존 프로젝트를 선택해요.  
3. **YouTube Data API v3**를 사용 설정해요.  
4. **API 및 서비스 → 사용자 인증 정보**에서 API 키를 생성해요.  
5. 발급받은 키를 복사해두세요.  
6. 아래처럼 `.streamlit/secrets.toml` 파일을 만들어 키를 넣어주세요.  
""")

st.code(
    '''
[youtube]
youtube_api_key = "여기에_발급받은_API_키_붙여넣기"
''',
    language="toml"
)

st.markdown("⚠️ **API 키는 외부에 노출되지 않도록 꼭 주의하세요!**")

st.markdown("---")
st.markdown("## 🚀 시작 안내")
st.markdown("👉 왼쪽 사이드바에서 원하는 분석기(댓글 수집/빈도/불용어/심층/워드클라우드)를 선택하세요.")
