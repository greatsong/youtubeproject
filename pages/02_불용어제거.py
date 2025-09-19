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
    "https","http","www","
