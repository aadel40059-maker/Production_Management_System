import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os
import calendar
import json
import matplotlib.pyplot as plt
import numpy as np
import base64
import io
import time
import uuid
from datetime import datetime, time as dtime, timedelta

# matplotlib بيرسم النص العربي زي ما هو من غير ما يظبط اتجاهه أو يوصل الحروف ببعض،
# فبيطلع مقلوب/متقطع. المكتبتين دول بيصلحوا الشكل قبل ما نبعته لأي رسم بياني.
try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    def ar_text(text):
        try:
            return get_display(arabic_reshaper.reshape(str(text)))
        except Exception:
            return str(text)
except Exception:
    def ar_text(text):
        return str(text)

# ---------- هوية الألوان الموحدة للرسومات البيانية في البرنامج كله ----------
BRAND_GREEN = "#013e37"
BRAND_GREEN_LIGHT = "#0d6b5c"
BRAND_GOLD = "#e0a92e"
BRAND_PALETTE = ["#013e37", "#e0a92e", "#4c8c7d", "#a06f0f", "#7fb5a6", "#0d6b5c", "#c98f1f", "#025e51"]


def _flat_html(s):
    """بتحول أي HTML متعدد الأسطر (بمسافات بادئة) لسطر واحد متصل، عشان مفسّر الماركداون
    مايفهمهاش غلط كـ 'code block' ويطلعها نص خام بدل ما يعرضها كتصميم فعلي."""
    return "".join(line.strip() for line in s.strip().splitlines())

# ==========================================================
# الاتصال بجوجل شيت (مستخدم في صفحات الأعطال والعمال والإنتاج والباكينج)
# ==========================================================
GSHEETS_ENABLED = False
try:
    import gspread
    from gspread.exceptions import APIError as _GspreadAPIError
    from google.oauth2.service_account import Credentials
    GSHEETS_ENABLED = "gcp_service_account" in st.secrets and "gsheets" in st.secrets
except Exception:
    GSHEETS_ENABLED = False


@st.cache_resource
def _get_gsheet_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=scopes
    )
    return gspread.authorize(creds)


def _gspread_retry(func, *args, max_attempts=5, **kwargs):
    """بينفذ أي نداء لجوجل شيت، ولو حصل رفض مؤقت من الـ API (429 Quota / 500 / 503) بيعيد المحاولة
    بعد شوية ثانية بدل ما البرنامج يقع فجأة برسالة خطأ حمراء طويلة. أي خطأ تاني (زي تاب مش موجود)
    بيتسيب يطلع على طول من غير تأخير."""
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except _GspreadAPIError as e:
            status = None
            try:
                status = e.response.status_code
            except Exception:
                pass
            if attempt < max_attempts - 1 and (status is None or status in (429, 500, 502, 503, 504)):
                time.sleep(2 * (attempt + 1))
                continue
            raise


@st.cache_resource(show_spinner=False)
def _get_spreadsheet():
    """بنفتح الـ spreadsheet مرة واحدة بس ونحتفظ بيه، لأن فتحه (open_by_key) بيجيب بيانات
    كل التابات مرة واحدة وده نداء تقيل على الـ API — تكراره في كل عملية كان بيستهلك الكوتة بسرعة"""
    client = _get_gsheet_client()
    return _gspread_retry(client.open_by_key, st.secrets["gsheets"]["sheet_id"])


def _get_worksheet(sheet_name):
    spreadsheet = _get_spreadsheet()
    safe_name = sheet_name[:99]  # حد أقصى لاسم التاب في جوجل شيت
    try:
        ws = _gspread_retry(spreadsheet.worksheet, safe_name)
    except gspread.WorksheetNotFound:
        ws = _gspread_retry(spreadsheet.add_worksheet, title=safe_name, rows=2000, cols=60)
        _get_spreadsheet.clear()  # التاب الجديد لازم يتحدث في الكاش عشان يبان في المرات الجاية
    return ws


def gsheet_exists(sheet_name):
    """بيرجع True لو فيه بيانات فعلية جوه الشيت ده (مش بس هيدر أو فاضي)"""
    if not GSHEETS_ENABLED:
        return False
    try:
        ws = _get_worksheet(sheet_name)
        values = _gspread_retry(ws.get_all_values)
        return len(values) > 1
    except Exception:
        return False


@st.cache_data(ttl=40, show_spinner=False)
def _read_gsheet_cached(sheet_name):
    """قراءة مؤقتة (20 ثانية) عشان نقلل عدد النداءات لجوجل شيت في نفس التحميل
    ونتجنب رسالة 'quota exceeded' لو الصفحة عملت أكتر من قراءة لنفس الشيت"""
    ws = _get_worksheet(sheet_name)
    records = _gspread_retry(ws.get_all_records)
    return records


def read_gsheet(sheet_name):
    try:
        records = _read_gsheet_cached(sheet_name)
    except Exception:
        st.warning(
            f"⚠ تعذّر الاتصال بجوجل شيت مؤقتًا (شيت: {sheet_name}). "
            "ده غالبًا بسبب ضغط على الـ API، جرب تاني بعد كام ثانية."
        )
        return pd.DataFrame()
    return pd.DataFrame(records)


def read_gsheet_strict(sheet_name):
    """زي read_gsheet بالظبط، بس بترجع None (مش DataFrame فاضي) لو فشل الاتصال فعلاً،
    عشان نقدر نفرّق بين 'الشيت فاضي فعلاً' و 'فشلنا نقراه'. مهم جداً قبل أي عملية بتدمج/تكتب
    فوق بيانات قديمة — لو مانفرقناش، فشل اتصال مؤقت ممكن يخلي البرنامج يمسح بيانات شهور فاتت
    بالغلط لأنه هيفتكرها مش موجودة أصلاً."""
    try:
        ws = _get_worksheet(sheet_name)
        records = _gspread_retry(ws.get_all_records)
        return pd.DataFrame(records)
    except Exception:
        return None


def _sanitize_cell_for_gsheet(v):
    """بيحول أي قيمة (numpy int/float/bool، NaN، Timestamp، ...) لنوع بايثون عادي آمن
    للإرسال كـ JSON لجوجل شيت. بيمنع أخطاء 'InvalidJSONError' اللي بتحصل لو فضلت قيمة
    من نوع numpy أو NaN فعلي في البيانات."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


def write_gsheet(sheet_name, df):
    ws = _get_worksheet(sheet_name)
    header = [str(c) for c in df.columns]
    if df.empty:
        _gspread_retry(ws.clear)
        _gspread_retry(ws.update, [header])
        _read_gsheet_cached.clear()
        return

    # نكتب البيانات الجديدة الأول (من غير ما نمسح حاجة) عشان الشيت مايفضلش فاضي لحظة واحدة
    body_rows = [[_sanitize_cell_for_gsheet(v) for v in row] for row in df.values.tolist()]
    values = [header] + body_rows
    _gspread_retry(ws.update, values)

    # لو الجدول القديم كان أطول من الجديد، نمسح الصفوف الزيادة القديمة بس (تحت البيانات الجديدة)
    try:
        old_row_count = ws.row_count
        new_row_count = len(values)
        if old_row_count > new_row_count:
            _gspread_retry(ws.batch_clear, [f"A{new_row_count + 1}:ZZ{old_row_count}"])
    except Exception:
        pass

    _read_gsheet_cached.clear()


def append_gsheet(sheet_name, df_rows):
    ws = _get_worksheet(sheet_name)
    header = [str(c) for c in df_rows.columns]

    # بنتأكد من صف الهيدر بالاسم مباشرة (بدل الاعتماد على "الشيت فاضي كله ولا لأ")،
    # عشان لو حصل تعارض توقيت بين حفظتين (double click / إعادة تحميل) الهيدر يفضل مكتوب صح
    # في الصف الأول برضو، بدل ما البيانات تتحط من غير هيدر أصلا
    try:
        first_row = _gspread_retry(ws.row_values, 1)
    except Exception:
        first_row = []
    if not first_row or [str(c) for c in first_row] != header:
        _gspread_retry(ws.update, "A1", [header])

    body_rows = [[_sanitize_cell_for_gsheet(v) for v in row] for row in df_rows.values.tolist()]
    _gspread_retry(ws.append_rows, body_rows)
    _read_gsheet_cached.clear()



st.set_page_config(
    page_title="Production by eng/ahmed adel",
    page_icon="🏭",
    layout="wide"
)

# ---------- زرار تبديل نهاري / ليلي ----------
if "app_theme" not in st.session_state:
    st.session_state.app_theme = "dark"

theme_pick = st.sidebar.radio(
    "🎨 الوضع", ["🌞 نهاري", "🌙 ليلي"],
    index=0 if st.session_state.app_theme == "light" else 1,
    horizontal=True, key="theme_toggle"
)
st.session_state.app_theme = "light" if theme_pick == "🌞 نهاري" else "dark"

if st.session_state.app_theme == "light":
    theme_css = """
    <style>
    :root {
        --accent: #013e37;
        --accent-soft: #ffefb3;
        --bg: #fffbea;
        --card-bg: #ffefb3;
        --text: #013e37;
    }
    /* ---------- ثيم الزبدي والأخضر الغامق ---------- */
    .stApp { background-color: var(--bg); color: var(--text); }
    [data-testid="stSidebar"] { background-color: var(--accent); }
    [data-testid="stSidebar"] * { color: var(--accent-soft) !important; }

    .stButton>button, .stDownloadButton>button {
        background-color: var(--accent); color: var(--accent-soft) !important; border: 2px solid var(--accent);
        border-radius: 9px; font-weight: 800; padding: 9px 20px; font-size: 16px;
        box-shadow: 0 2px 5px rgba(1,62,55,0.18); transition: all 0.15s;
    }
    .stButton>button:hover, .stDownloadButton>button:hover {
        filter: brightness(1.25); color: var(--accent-soft) !important;
        transform: translateY(-1px); box-shadow: 0 4px 10px rgba(1,62,55,0.28);
    }

    [data-testid="stMetric"] {
        background-color: var(--card-bg); border: 2px solid var(--accent);
        border-radius: 14px; padding: 16px 18px; box-shadow: 0 2px 6px rgba(1,62,55,0.15);
    }
    [data-testid="stMetricLabel"] { color: var(--accent) !important; font-weight: 700 !important; }
    [data-testid="stMetricValue"] { color: var(--accent) !important; font-weight: 800 !important; }
    </style>
    """
else:
    theme_css = """
    <style>
    :root {
        --accent: #ffefb3;
        --accent-soft: #ffefb3;
        --bg: #012620;
        --card-bg: #013e37;
        --text: #ffefb3;
    }
    /* ---------- ثيم الأخضر الغامق (ليلي) بلمسة زبدي ---------- */
    .stApp { background-color: var(--bg); color: var(--text); }
    [data-testid="stSidebar"] { background-color: #011a16; }
    [data-testid="stSidebar"] * { color: #ffefb3 !important; }

    .stButton>button, .stDownloadButton>button {
        background-color: #ffefb3; color: #013e37 !important; border: 2px solid #ffefb3;
        border-radius: 9px; font-weight: 800; padding: 9px 20px; font-size: 16px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.35); transition: all 0.15s;
    }
    .stButton>button:hover, .stDownloadButton>button:hover {
        filter: brightness(0.9); color: #013e37 !important;
        transform: translateY(-1px); box-shadow: 0 4px 10px rgba(0,0,0,0.45);
    }

    [data-testid="stMetric"] {
        background-color: var(--card-bg); border: 2px solid #ffefb3;
        border-radius: 14px; padding: 16px 18px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    }
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"] { color: #ffefb3 !important; }
    [data-testid="stMetricValue"] { font-weight: 800 !important; }
    [data-testid="stMetricLabel"] { font-weight: 700 !important; }
    </style>
    """

st.markdown(theme_css, unsafe_allow_html=True)

# ---------- ستايل عام مشترك بين الوضعين: خط احترافي + جداول + سايد منيو + عناوين ----------
common_css = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, .stDataFrame,
[data-testid="stWidgetLabel"] p, .stButton>button, .stDownloadButton>button,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"] {
    font-family: 'Cairo', 'Segoe UI', Tahoma, Arial, sans-serif !important;
}

h1, h2, h3 { font-weight: 800 !important; letter-spacing: -0.3px; color: var(--accent) !important; }
h4, h5, h6 { font-weight: 800 !important; color: var(--accent) !important; }
p, span, label, div, li { font-weight: 600; }

/* تكبير الخط العام شوية في كل الصفحة */
html, body, [class*="css"], .stMarkdown, .stText, [data-testid="stWidgetLabel"] p {
    font-size: 17px !important;
}

/* ---------- بانر العنوان الرئيسي ---------- */
.app-header-banner {
    background: #013e37;
    border-radius: 16px; padding: 22px 26px; margin-bottom: 18px;
    box-shadow: 0 4px 14px rgba(1,62,55,0.25);
    display: flex; align-items: center; gap: 16px;
}
.app-header-banner .icon { font-size: 40px; }
.app-header-banner h1 {
    color: #ffefb3 !important; margin: 0; font-size: 26px !important; font-weight: 900 !important;
}
.app-header-banner p { color: #ffefb3 !important; margin: 2px 0 0; font-size: 14px !important; opacity: 0.92; font-weight: 600; }

/* ---------- بانر عنوان الصفحة الفرعية (Dashboard/Production/Packing...) ---------- */
.page-banner {
    background: #013e37;
    border-radius: 12px; padding: 14px 20px; margin: 4px 0 18px;
    display: flex; align-items: center; gap: 14px;
    box-shadow: 0 3px 10px rgba(1,62,55,0.2);
}
.page-banner .icon { font-size: 26px; }
.page-banner h2 { color: #ffefb3 !important; margin: 0; font-size: 20px !important; font-weight: 900 !important; }
.page-banner p { color: #ffefb3 !important; margin: 2px 0 0; font-size: 12.5px !important; opacity: 0.9; font-weight: 600; }

/* ---------- كروت الـ KPI (أيقونة دائرية + رقم كبير) ---------- */
.kpi-card {
    background: var(--card-bg); border: 1.5px solid rgba(1,62,55,0.18);
    border-radius: 14px; padding: 16px 18px;
    box-shadow: 0 2px 8px rgba(1,62,55,0.1);
}
.kpi-card .kpi-icon {
    width: 40px; height: 40px; border-radius: 10px;
    background: rgba(1,62,55,0.12); display: flex; align-items: center; justify-content: center;
    font-size: 20px; margin-bottom: 10px;
}
.kpi-card .kpi-label { font-size: 12.5px; font-weight: 700; color: #6b7280; margin-bottom: 4px; }
.kpi-card .kpi-value { font-size: 25px; font-weight: 900; color: var(--accent); }

/* ---------- بطاقات التنقل في الصفحة الرئيسية ---------- */
.nav-tile {
    display: block; text-decoration: none;
    background: var(--card-bg); border: 1.5px solid rgba(1,62,55,0.18);
    border-radius: 16px; padding: 20px 18px; height: 100%;
    box-shadow: 0 2px 10px rgba(1,62,55,0.1);
    transition: all 0.18s ease;
}
.nav-tile:hover { transform: translateY(-3px); box-shadow: 0 6px 16px rgba(1,62,55,0.22); }
.nav-tile .nav-tile-icon { font-size: 30px; margin-bottom: 10px; display: block; }
.nav-tile .nav-tile-title { font-size: 17px; font-weight: 900; color: var(--accent); margin-bottom: 4px; display: block; }
.nav-tile .nav-tile-desc { font-size: 12.5px; font-weight: 600; color: #6b7280; display: block; }

/* ---------- تحسين شكل الجداول (st.dataframe) ---------- */
[data-testid="stDataFrame"] {
    border-radius: 12px !important; overflow: hidden;
    box-shadow: 0 2px 8px rgba(1,62,55,0.12);
    border: 1px solid rgba(1,62,55,0.15) !important;
    font-weight: 600;
}
[data-testid="stDataFrameResizable"] { border-radius: 12px !important; }

/* الجداول الخام (HTML) في أي مكان بره الطباعة */
.stMarkdown table {
    border-collapse: collapse; width: 100%; border-radius: 10px; overflow: hidden;
    box-shadow: 0 2px 8px rgba(1,62,55,0.1); font-size: 14px;
}
.stMarkdown table th {
    background-color: var(--accent) !important; color: var(--accent-soft) !important;
    padding: 8px 10px; font-weight: 800;
}
.stMarkdown table td { padding: 7px 10px; border-bottom: 1px solid rgba(1,62,55,0.1); }

/* ---------- السايد منيو الاحترافي ---------- */
[data-testid="stSidebar"] {
    box-shadow: 3px 0 12px rgba(0,0,0,0.18);
}
[data-testid="stSidebar"] > div:first-child { padding-top: 8px; }

[data-testid="stSidebar"] hr { border-color: rgba(255,239,179,0.25); margin: 10px 0; }

[data-testid="stSidebar"] [data-testid="stRadio"] > label > div:first-child p {
    font-size: 12px !important; font-weight: 800 !important; opacity: 0.75;
    text-transform: uppercase; letter-spacing: 0.5px;
}

[data-testid="stSidebar"] [data-testid="stRadio"] > div {
    gap: 6px;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    display: flex; align-items: center;
    width: 100%; padding: 12px 16px;
    border-radius: 10px;
    background-color: rgba(255,239,179,0.08);
    margin-bottom: 5px;
    font-weight: 800;
    font-size: 16px;
    cursor: pointer;
    border-inline-start: 4px solid transparent;
    transition: all 0.18s ease;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background-color: rgba(255,239,179,0.2);
    transform: translateX(-2px);
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
    background-color: #ffefb3;
    border-inline-start: 4px solid #013e37;
    box-shadow: 0 2px 6px rgba(0,0,0,0.2);
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) * {
    color: #013e37 !important;
}

/* ---------- عناصر الإدخال (نص/أرقام/تاريخ/قوائم) ---------- */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    border-radius: 9px !important;
    border: 1.5px solid rgba(1,62,55,0.35) !important;
    font-weight: 600 !important;
    background-color: var(--card-bg) !important;
    color: var(--text) !important;
}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div * {
    color: var(--text) !important;
}
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {
    background-color: var(--card-bg) !important;
    color: var(--text) !important;
    border: 1.5px solid rgba(1,62,55,0.35) !important;
    border-radius: 9px !important;
}
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div * {
    color: var(--text) !important;
}
/* قائمة الاختيارات المنسدلة نفسها (بتترندر في البوب أوفر) — لازم تتظبط لوحدها عشان الألوان تتوارث صح */
div[data-baseweb="popover"] div[data-baseweb="menu"],
div[data-baseweb="popover"] ul[role="listbox"] {
    background-color: var(--card-bg) !important;
}
div[data-baseweb="popover"] li,
div[data-baseweb="popover"] li * {
    color: var(--text) !important;
}
div[data-baseweb="popover"] li:hover {
    background-color: rgba(128,128,128,0.18) !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stDateInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 2px rgba(1,62,55,0.15) !important;
}

/* ---------- القوائم القابلة للطي (expander) ---------- */
[data-testid="stExpander"] {
    border-radius: 12px !important;
    border: 1.5px solid rgba(1,62,55,0.18) !important;
    box-shadow: 0 2px 6px rgba(1,62,55,0.08);
    overflow: hidden;
}
[data-testid="stExpander"] summary {
    font-weight: 800 !important; font-size: 16px !important;
}

/* ---------- رسائل التنبيه (info/success/warning/error) ---------- */
[data-testid="stAlert"] {
    border-radius: 10px !important; font-weight: 700 !important;
    border-inline-start: 5px solid currentColor !important;
}

/* ---------- التبويبات (tabs) ---------- */
[data-testid="stTabs"] button[role="tab"] {
    font-weight: 800 !important; font-size: 15px !important;
    border-radius: 8px 8px 0 0 !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--accent) !important;
    border-bottom: 3px solid var(--accent) !important;
}

/* الفواصل والعناوين الفرعية داخل الصفحات */
hr { border-color: rgba(1,62,55,0.15) !important; }
</style>
"""
st.markdown(common_css, unsafe_allow_html=True)


def page_banner(icon, title, subtitle=None):
    """بانر ملون في بداية كل صفحة رئيسية عشان الشكل يبقى موحّد واحترافي"""
    sub_html = f'<p>{subtitle}</p>' if subtitle else ""
    html = f"""
    <div class="page-banner">
        <div class="icon">{icon}</div>
        <div><h2>{title}</h2>{sub_html}</div>
    </div>
    """
    st.markdown(_flat_html(html), unsafe_allow_html=True)

DATA_FILE = "production_history.csv"
# اسم تاب جوجل شيت لبيانات الإنتاج — اتغيّر لاسم جديد (تاب جديد يتحط تحت التابات القديمة تلقائي)
# بعد تبسيط أعمدة الجدول (الفعلي/المستهدف بس)، عشان منخلطش البيانات الجديدة بالهيكل القديم
PRODUCTION_SHEET = "production_history_v2"
SHIFTS = ["First Shift", "Second Shift", "Third Shift"]

if "production_lines" not in st.session_state:
    st.session_state.production_lines = [
        "المستمر",
        "الإيطالي",
        "الاكلير ص١",
        "الاكلير ص٣",
        "الطوفي",
    ]

logo_path = None
for candidate in ["logo.jpg", "logo.jpeg", "logo.png"]:
    if os.path.exists(candidate):
        logo_path = candidate
        break

st.sidebar.markdown("### 📏 القائمة الرئيسية")
PAGE_ICONS = {
    "الرئيسية": "🏠",
    "Dashboard": "📊",
    "Production": "🏭",
    "Packing": "📦",
    "التصدير": "🚢",
    "الأعطال": "⚠️",
    "الكسر": "🔨",
    "Inventory": "🗃️",
    "Workers": "👷",
    "الكابستي": "📈",
    "Reports": "📑",
    "Settings": "⚙️",
}

# بيسمح لبطاقات صفحة "الرئيسية" إنها تنقّل المستخدم لأي صفحة تانية عن طريق رابط (?nav=...)
try:
    _qp_nav = st.query_params.get("nav")
    if _qp_nav in PAGE_ICONS:
        st.session_state["main_nav_radio"] = _qp_nav
        st.query_params.clear()
except Exception:
    pass

page = st.sidebar.radio(
    "choose a page",
    list(PAGE_ICONS.keys()),
    format_func=lambda p: f"{PAGE_ICONS.get(p, '•')}  {p}",
    label_visibility="collapsed",
    key="main_nav_radio",
)


def build_production_table():
    """يبني جدول فاضي مبني على قائمة الخطوط الحالية في session_state
    الأعمدة بقت الفعلي والمستهدف بس (الهدر والأعطال اتشالوا — الأعطال بقت متابعة من صفحة الأعطال لوحدها)"""
    data = []
    for line in st.session_state.production_lines:
        data.append({
            "Line": f"🏭 {line}",
            "Shift": "All Shifts",
            "المستهدف (KG)": 0,
            "الفعلي (KG)": 0,
        })
        for shift in SHIFTS:
            data.append({
                "Line": "",
                "Shift": shift,
                "المستهدف (KG)": 0,
                "الفعلي (KG)": 0,
            })
    return pd.DataFrame(data)


def fig_to_base64_img(fig, style="width:100%; max-width:680px; display:block; margin:6px auto;"):
    """بيحوّل أي matplotlib figure لصورة PNG base64 جاهزة للتضمين جوه HTML (للتقرير القابل للطباعة)"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return f'<img src="data:image/png;base64,{b64}" style="{style}" />'


def build_line_production_chart(line_summary_df, line_col="الخط",
                                 target_col="المستهدف (KG)", actual_col="الفعلي (KG)",
                                 chart_title="إنتاج كل خط: الفعلي مقابل المستهدف (KG)"):
    """رسم بياني احترافي (أعمدة مزدوجة) بألوان هوية البرنامج (أخضر غامق/ذهبي) يقارن الفعلي بالمستهدف لكل خط إنتاج"""
    if line_summary_df is None or line_summary_df.empty:
        return None
    labels = [ar_text(l) for l in line_summary_df[line_col]]
    x = np.arange(len(labels))
    width = 0.35

    BRAND_GREEN = "#013e37"
    BRAND_GOLD = "#e0a92e"

    fig, ax = plt.subplots(figsize=(7.4, 3.8))
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    bars_t = ax.bar(x - width / 2, line_summary_df[target_col], width,
                     label=ar_text("المستهدف"), color=BRAND_GOLD, edgecolor="#a06f0f",
                     linewidth=0.7, zorder=3)
    bars_a = ax.bar(x + width / 2, line_summary_df[actual_col], width,
                     label=ar_text("الفعلي"), color=BRAND_GREEN, edgecolor="#00201c",
                     linewidth=0.7, zorder=3)

    for bars in (bars_t, bars_a):
        for b in bars:
            h = b.get_height()
            if h > 0:
                ax.annotate(f"{h:,.0f}", xy=(b.get_x() + b.get_width() / 2, h),
                            xytext=(0, 4), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8, fontweight="bold", color="#1a1d21")

    ax.set_title(ar_text(chart_title), fontsize=14, fontweight="bold", color=BRAND_GREEN, pad=14)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10.5, fontweight="bold", color="#1a1d21")
    ax.tick_params(axis="y", labelsize=9, colors="#4b5563")
    legend = ax.legend(loc="upper right", frameon=True, fontsize=9.5, facecolor="#ffffff",
                        edgecolor="#e5e7eb")
    for text in legend.get_texts():
        text.set_fontweight("bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#d1d5db")
    ax.spines["bottom"].set_color("#d1d5db")
    ax.grid(axis="y", linestyle="--", alpha=0.4, color="#c9cfd6", zorder=0)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return fig


def build_donut_chart(series, title="التوزيع", center_label="الإجمالي", unit=""):
    """رسم دونات احترافي بألوان البراند، ورقم الإجمالي في النص النص — زي شكل 'Production by Line' في التصميم"""
    if series is None or series.empty or series.sum() == 0:
        return None
    fig, ax = plt.subplots(figsize=(4.4, 4.4))
    fig.patch.set_facecolor("#ffffff")
    colors = [BRAND_PALETTE[i % len(BRAND_PALETTE)] for i in range(len(series))]
    ax.pie(
        series.values, colors=colors, startangle=90, counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": "#ffffff", "linewidth": 2.5}
    )
    total = series.sum()
    ax.text(0, 0.07, f"{total:,.0f}{unit}", ha="center", va="center",
             fontsize=19, fontweight="bold", color=BRAND_GREEN)
    ax.text(0, -0.13, ar_text(center_label), ha="center", va="center",
             fontsize=10, color="#6b7280", fontweight="bold")
    if title:
        ax.set_title(ar_text(title), fontsize=13, fontweight="bold", color=BRAND_GREEN, pad=12)
    ax.axis("equal")
    fig.tight_layout()
    return fig


def _squarify_layout(values, x, y, w, h):
    """خوارزمية Squarified Treemap — بترتب مستطيلات نسبها قريبة من المربع (بدون أي مكتبة خارجية)"""
    def worst_ratio(row, length):
        if not row:
            return float("inf")
        row_sum = sum(row)
        if row_sum <= 0:
            return float("inf")
        row_max, row_min = max(row), min(row)
        return max((length ** 2 * row_max) / (row_sum ** 2), (row_sum ** 2) / (length ** 2 * row_min))

    remaining = list(values)
    rects = []
    cx, cy, cw, ch = x, y, w, h
    while remaining:
        length = min(cw, ch)
        row = [remaining[0]]
        i = 1
        while i < len(remaining) and worst_ratio(row, length) >= worst_ratio(row + [remaining[i]], length):
            row.append(remaining[i])
            i += 1
        row_sum = sum(row)
        if cw >= ch:
            row_len = (row_sum / ch) if ch > 0 else 0
            ry = cy
            for v in row:
                rh = (v / row_sum) * ch if row_sum > 0 else 0
                rects.append((cx, ry, row_len, rh))
                ry += rh
            cx += row_len
            cw -= row_len
        else:
            row_len = (row_sum / cw) if cw > 0 else 0
            rx = cx
            for v in row:
                rw = (v / row_sum) * cw if row_sum > 0 else 0
                rects.append((rx, cy, rw, row_len))
                rx += rw
            cy += row_len
            ch -= row_len
        remaining = remaining[len(row):]
    return rects


def _text_color_for_bg(hex_color):
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#1a1d21" if luminance > 0.6 else "#ffffff"


def build_treemap_chart(series, title="", unit="", figsize=(8, 4.6)):
    """رسم Treemap احترافي (مربعات ملونة بحجم نسبي للقيمة) — بنفس روح تصميمات لوحات البيانات الحديثة"""
    if series is None or series.empty or series.sum() == 0:
        return None
    series = series.sort_values(ascending=False)
    total = series.sum()

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("#ffffff")

    W, H = 100, 58
    # المساحة المستطيلة الكلية (W×H) لازم تتوزع بالتناسب مع نسبة كل قيمة من الإجمالي
    normalized_areas = [(v / total) * (W * H) for v in series.values.tolist()]
    rects = _squarify_layout(normalized_areas, 0, 0, W, H)

    for i, ((rx, ry, rw, rh), (label, val)) in enumerate(zip(rects, series.items())):
        color = BRAND_PALETTE[i % len(BRAND_PALETTE)]
        pct = (val / total * 100) if total > 0 else 0
        rect_patch = plt.Rectangle((rx, ry), rw, rh, facecolor=color, edgecolor="#ffffff", linewidth=2.2, zorder=2)
        ax.add_patch(rect_patch)

        text_color = _text_color_for_bg(color)
        pad = 1.2
        if rw > 10 and rh > 7:
            ax.text(rx + pad, ry + rh - pad, ar_text(str(label)), ha="left", va="top",
                     fontsize=min(11, 7 + rw / 14), fontweight="bold", color=text_color, zorder=3, wrap=True)
            ax.text(rx + pad, ry + rh - pad - (rh * 0.28 if rh > 14 else 4.2),
                     f"{val:,.0f}{unit}  ({pct:.1f}%)", ha="left", va="top",
                     fontsize=min(9.5, 6.5 + rw / 18), color=text_color, alpha=0.92, zorder=3)
        elif rw > 4 and rh > 4:
            ax.text(rx + rw / 2, ry + rh / 2, f"{pct:.0f}%", ha="center", va="center",
                     fontsize=8, fontweight="bold", color=text_color, zorder=3)

    if title:
        ax.set_title(ar_text(title), fontsize=13, fontweight="bold", color=BRAND_GREEN, pad=10)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.invert_yaxis()
    ax.axis("off")
    fig.tight_layout()
    return fig


def build_dashboard_html(kpis, trend_dates, trend_actual, trend_target,
                          line_names, line_target, line_actual,
                          pack_cat_names, pack_cat_values,
                          faults_line_names, faults_line_values, oee):
    """داشبورد كامل مبني كـ HTML/CSS/Chart.js حقيقي (مش عناصر Streamlit) عشان نتحكم بالشكل زي أي
    لوحة بيانات احترافية حقيقية — ده بيتعرض جوه iframe منعزل فمفيش أي تعارض مع ماركداون Streamlit"""

    palette = ["#0d6b5c", "#e0a92e", "#4c8c7d", "#a06f0f", "#7fb5a6", "#2563eb", "#c98f1f", "#7c3aed"]
    line_colors_json = json.dumps([palette[i % len(palette)] for i in range(len(line_names))])
    pack_colors_json = json.dumps([palette[i % len(palette)] for i in range(len(pack_cat_names))])

    total_line_actual = sum(line_actual) if line_actual else 0

    kpi_cards_html = ""
    for k in kpis:
        spark_id = f"spark_{k['id']}"
        kpi_cards_html += f"""
        <div class="kpi">
            <div class="kpi-top">
                <div class="kpi-icon" style="background:{k['color']}1f; color:{k['color']};">{k['icon']}</div>
                <div>
                    <div class="kpi-label">{k['label']}</div>
                    <div class="kpi-value">{k['value']}</div>
                </div>
            </div>
            <div style="height:34px; position:relative; margin-top:4px;">
                <canvas id="{spark_id}"></canvas>
            </div>
        </div>
        """

    prod_table_rows = ""
    for i, name in enumerate(line_names):
        t, a = line_target[i], line_actual[i]
        pct = (a / t * 100) if t > 0 else 0
        pct_color = "#0d6b5c" if pct >= 100 else ("#e0a92e" if pct >= 80 else "#dc2626")
        prod_table_rows += f"""
        <tr>
            <td class="line-cell"><span class="dot" style="background:{palette[i % len(palette)]}"></span>{name}</td>
            <td>{t:,.0f}</td>
            <td>{a:,.0f}</td>
            <td><span class="pct-pill" style="background:{pct_color}1f; color:{pct_color};">{pct:.0f}%</span></td>
        </tr>
        """
    total_t = sum(line_target) if line_target else 0
    total_a = sum(line_actual) if line_actual else 0
    total_pct = (total_a / total_t * 100) if total_t > 0 else 0

    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Cairo', 'Segoe UI', Tahoma, sans-serif;
            background: #fdf9ef; margin: 0; padding: 18px; color: #013e37;
        }}
        .grid {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }}
        .kpi {{
            flex: 1; min-width: 168px; background: #ffefb3; border: 1px solid rgba(1,62,55,0.15);
            border-radius: 16px; padding: 16px; box-shadow: 0 2px 10px rgba(1,62,55,0.08);
            overflow: hidden;
        }}
        .kpi-top {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
        .kpi-icon {{
            width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center;
            justify-content: center; font-size: 20px; flex-shrink: 0;
        }}
        .kpi-label {{ font-size: 12px; font-weight: 700; color: #4b6b63; }}
        .kpi-value {{ font-size: 21px; font-weight: 900; color: #013e37; }}
        .panel {{
            background: #ffffff; border: 1px solid rgba(1,62,55,0.12); border-radius: 16px;
            padding: 18px; box-shadow: 0 2px 10px rgba(1,62,55,0.06); margin-bottom: 16px;
        }}
        .panel-title {{ font-size: 16px; font-weight: 900; color: #013e37; margin-bottom: 12px; }}
        .row {{ display: flex; gap: 16px; flex-wrap: wrap; align-items: stretch; }}
        .col-2 {{ flex: 2; min-width: 320px; }}
        .col-1 {{ flex: 1; min-width: 260px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
        th {{
            background: #013e37; color: #ffefb3; padding: 9px 10px; text-align: center;
            font-weight: 800; font-size: 12.5px;
        }}
        td {{ padding: 9px 10px; text-align: center; border-bottom: 1px solid rgba(1,62,55,0.08); font-weight: 700; }}
        .line-cell {{ text-align: right; display: flex; align-items: center; gap: 8px; font-weight: 800; }}
        .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        .pct-pill {{ padding: 3px 10px; border-radius: 20px; font-weight: 800; font-size: 12.5px; }}
        tr.total-row td {{ background: #ffefb3; font-weight: 900; border-top: 2px solid #013e37; }}
        .legend-item {{ display: flex; align-items: center; justify-content: space-between; padding: 6px 2px;
                         border-bottom: 1px solid rgba(1,62,55,0.06); font-size: 13px; }}
        .legend-left {{ display: flex; align-items: center; gap: 8px; font-weight: 700; }}
        .gauge-wrap {{ display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        .gauge-value {{ font-size: 26px; font-weight: 900; color: #013e37; margin-top: -60px; }}
        .gauge-label {{ font-size: 12px; color: #6b7280; font-weight: 700; }}
    </style>
    </head>
    <body>

    <div class="grid">
        {kpi_cards_html}
    </div>

    <div class="row">
        <div class="col-2 panel">
            <div class="panel-title">📈 نظرة عامة على الإنتاج (آخر 7 أيام)</div>
            <canvas id="overviewChart" height="105"></canvas>
        </div>
        <div class="col-1 panel">
            <div class="panel-title">🏭 إنتاج الخطوط (KG)</div>
            <div style="display:flex; align-items:center; gap:14px;">
                <div style="position:relative; width:150px; height:150px; flex-shrink:0;">
                    <canvas id="lineDonut" width="150" height="150"></canvas>
                </div>
                <div style="flex:1;">
                    <div id="lineLegend"></div>
                </div>
            </div>
        </div>
    </div>

    <div class="row">
        <div class="col-2 panel">
            <div class="panel-title">📋 الإنتاج لكل خط (KG)</div>
            <table>
                <tr><th>الخط</th><th>المستهدف</th><th>الفعلي</th><th>نسبة التحقيق</th></tr>
                {prod_table_rows}
                <tr class="total-row"><td class="line-cell">الإجمالي</td><td>{total_t:,.0f}</td><td>{total_a:,.0f}</td>
                    <td><span class="pct-pill" style="background:#0132271f; color:#013e37;">{total_pct:.0f}%</span></td></tr>
            </table>
        </div>
        <div class="col-1 panel gauge-wrap">
            <div class="panel-title" style="align-self:flex-start;">⚡ كفاءة OEE التقريبية</div>
            <div style="width:220px; height:130px; position:relative;">
                <canvas id="oeeGauge"></canvas>
            </div>
            <div class="gauge-value">{oee:.1f}%</div>
            <div class="gauge-label">Availability × Performance × Quality</div>
        </div>
    </div>

    <div class="row">
        <div class="col-1 panel">
            <div class="panel-title">📦 الباكينج حسب الفئة</div>
            <canvas id="packBar" height="180"></canvas>
        </div>
        <div class="col-1 panel">
            <div class="panel-title">⚠ توزيع وقت التوقف حسب الخط (دقيقة)</div>
            <canvas id="faultsBar" height="180"></canvas>
        </div>
    </div>

    <script>
    const brandGreen = "#013e37";
    const brandGold = "#e0a92e";
    const gridColor = "rgba(1,62,55,0.08)";
    Chart.defaults.font.family = "'Cairo','Segoe UI',sans-serif";
    Chart.defaults.color = "#4b6b63";

    // ---- Sparklines لكروت الـ KPI ----
    const sparkActual = {json.dumps(trend_actual)};
    const sparkTarget = {json.dumps(trend_target)};
    const sparkData = {{ "prod": sparkActual, "target": sparkTarget }};
    document.querySelectorAll('canvas[id^="spark_"]').forEach(cv => {{
        const key = cv.id.replace("spark_", "");
        const data = sparkData[key] || sparkActual;
        new Chart(cv, {{
            type: 'line',
            data: {{ labels: data.map((_, i) => i), datasets: [{{
                data: data, borderColor: brandGreen, borderWidth: 2, pointRadius: 0,
                fill: true, backgroundColor: "rgba(1,62,55,0.08)", tension: 0.35
            }}]}},
            options: {{
                responsive: true, maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }},
                scales: {{ x: {{ display: false }}, y: {{ display: false }} }}
            }}
        }});
    }});

    // ---- نظرة عامة على الإنتاج ----
    new Chart(document.getElementById('overviewChart'), {{
        type: 'line',
        data: {{
            labels: {json.dumps(trend_dates)},
            datasets: [
                {{ label: 'الفعلي', data: {json.dumps(trend_actual)}, borderColor: brandGreen,
                   backgroundColor: 'rgba(1,62,55,0.10)', fill: true, tension: 0.35, pointRadius: 3 }},
                {{ label: 'المستهدف', data: {json.dumps(trend_target)}, borderColor: brandGold,
                   borderDash: [6,4], fill: false, tension: 0.2, pointRadius: 0 }}
            ]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ position: 'top', labels: {{ usePointStyle: true }} }} }},
            scales: {{
                y: {{ beginAtZero: true, grid: {{ color: gridColor }} }},
                x: {{ grid: {{ display: false }} }}
            }}
        }}
    }});

    // ---- دونات إنتاج الخطوط ----
    const lineNames = {json.dumps(line_names)};
    const lineActualVals = {json.dumps(line_actual)};
    const lineColors = {line_colors_json};
    new Chart(document.getElementById('lineDonut'), {{
        type: 'doughnut',
        data: {{ labels: lineNames, datasets: [{{ data: lineActualVals, backgroundColor: lineColors, borderColor: '#fff', borderWidth: 2 }}] }},
        options: {{ responsive: true, maintainAspectRatio: false, cutout: '62%', plugins: {{ legend: {{ display: false }} }} }}
    }});
    const legendBox = document.getElementById('lineLegend');
    const totalLineActual = {total_line_actual};
    lineNames.forEach((name, i) => {{
        const val = lineActualVals[i];
        const pct = totalLineActual > 0 ? (val/totalLineActual*100).toFixed(1) : 0;
        legendBox.innerHTML += `<div class="legend-item"><div class="legend-left">
            <span class="dot" style="background:${{lineColors[i]}}"></span>${{name}}</div>
            <div>${{val.toLocaleString()}} <span style="color:#6b7280;">(${{pct}}%)</span></div></div>`;
    }});

    // ---- مقياس OEE ----
    new Chart(document.getElementById('oeeGauge'), {{
        type: 'doughnut',
        data: {{ datasets: [{{
            data: [{oee}, 100 - {oee}],
            backgroundColor: [{oee} >= 80 ? '#0d6b5c' : ({oee} >= 50 ? '#e0a92e' : '#dc2626'), '#eef2ee'],
            borderWidth: 0
        }}]}},
        options: {{
            responsive: true, maintainAspectRatio: false,
            rotation: -90, circumference: 180, cutout: '75%',
            plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }}
        }}
    }});

    // ---- الباكينج حسب الفئة ----
    new Chart(document.getElementById('packBar'), {{
        type: 'bar',
        data: {{ labels: {json.dumps(pack_cat_names)}, datasets: [{{
            data: {json.dumps(pack_cat_values)}, backgroundColor: {pack_colors_json}, borderRadius: 6
        }}]}},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{ y: {{ beginAtZero: true, grid: {{ color: gridColor }} }}, x: {{ grid: {{ display: false }} }} }}
        }}
    }});

    // ---- توزيع الأعطال ----
    new Chart(document.getElementById('faultsBar'), {{
        type: 'bar',
        data: {{ labels: {json.dumps(faults_line_names)}, datasets: [{{
            data: {json.dumps(faults_line_values)}, backgroundColor: '#dc2626', borderRadius: 6
        }}]}},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{ x: {{ beginAtZero: true, grid: {{ color: gridColor }} }}, y: {{ grid: {{ display: false }} }} }}
        }}
    }});

    // ---- تظبيط ارتفاع الإطار تلقائيًا حسب المحتوى الفعلي (يمنع السكرول المزدوج) ----
    function reportHeight() {{
        const h = document.documentElement.scrollHeight;
        window.parent.postMessage({{ type: "streamlit:setFrameHeight", height: h }}, "*");
    }}
    window.addEventListener("load", reportHeight);
    setTimeout(reportHeight, 300);
    setTimeout(reportHeight, 900);
    setTimeout(reportHeight, 1800);
    </script>
    </body>
    </html>
    """
    return html



def build_line_summary_html(kpis, line_names, line_target, line_actual, chart_title="مقارنة الفعلي بالمستهدف لكل خط"):
    """كارت ملخص احترافي (KPI + رسم أعمدة مزدوج + دونات + جدول) بنفس ستايل الداشبورد — لأي صفحة فيها بيانات خطوط"""
    palette = ["#0d6b5c", "#e0a92e", "#4c8c7d", "#a06f0f", "#7fb5a6", "#2563eb", "#c98f1f", "#7c3aed"]
    line_colors_json = json.dumps([palette[i % len(palette)] for i in range(len(line_names))])
    total_actual = sum(line_actual) if line_actual else 0

    kpi_cards_html = ""
    for k in kpis:
        kpi_cards_html += f"""
        <div class="kpi">
            <div class="kpi-top">
                <div class="kpi-icon" style="background:{k['color']}1f; color:{k['color']};">{k['icon']}</div>
                <div>
                    <div class="kpi-label">{k['label']}</div>
                    <div class="kpi-value">{k['value']}</div>
                </div>
            </div>
        </div>
        """

    table_rows = ""
    for i, name in enumerate(line_names):
        t, a = line_target[i], line_actual[i]
        pct = (a / t * 100) if t > 0 else 0
        pct_color = "#0d6b5c" if pct >= 100 else ("#e0a92e" if pct >= 80 else "#dc2626")
        table_rows += f"""
        <tr>
            <td class="line-cell"><span class="dot" style="background:{palette[i % len(palette)]}"></span>{name}</td>
            <td>{t:,.0f}</td>
            <td>{a:,.0f}</td>
            <td><span class="pct-pill" style="background:{pct_color}1f; color:{pct_color};">{pct:.0f}%</span></td>
        </tr>
        """
    total_t = sum(line_target) if line_target else 0
    total_a = sum(line_actual) if line_actual else 0
    total_pct = (total_a / total_t * 100) if total_t > 0 else 0

    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: 'Cairo','Segoe UI',Tahoma,sans-serif; background: #fdf9ef; margin: 0; padding: 18px; color: #013e37; }}
        .grid {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }}
        .kpi {{ flex: 1; min-width: 168px; background: #ffefb3; border: 1px solid rgba(1,62,55,0.15);
                border-radius: 16px; padding: 16px; box-shadow: 0 2px 10px rgba(1,62,55,0.08); }}
        .kpi-top {{ display: flex; align-items: center; gap: 10px; }}
        .kpi-icon {{ width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center;
                     justify-content: center; font-size: 20px; flex-shrink: 0; }}
        .kpi-label {{ font-size: 12px; font-weight: 700; color: #4b6b63; }}
        .kpi-value {{ font-size: 21px; font-weight: 900; color: #013e37; }}
        .panel {{ background: #ffffff; border: 1px solid rgba(1,62,55,0.12); border-radius: 16px;
                  padding: 18px; box-shadow: 0 2px 10px rgba(1,62,55,0.06); margin-bottom: 16px; }}
        .panel-title {{ font-size: 16px; font-weight: 900; color: #013e37; margin-bottom: 12px; }}
        .row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
        .col-2 {{ flex: 2; min-width: 320px; }}
        .col-1 {{ flex: 1; min-width: 260px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
        th {{ background: #013e37; color: #ffefb3; padding: 9px 10px; text-align: center; font-weight: 800; font-size: 12.5px; }}
        td {{ padding: 9px 10px; text-align: center; border-bottom: 1px solid rgba(1,62,55,0.08); font-weight: 700; }}
        .line-cell {{ text-align: right; display: flex; align-items: center; gap: 8px; font-weight: 800; }}
        .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        .pct-pill {{ padding: 3px 10px; border-radius: 20px; font-weight: 800; font-size: 12.5px; }}
        tr.total-row td {{ background: #ffefb3; font-weight: 900; border-top: 2px solid #013e37; }}
        .legend-item {{ display: flex; align-items: center; justify-content: space-between; padding: 6px 2px;
                         border-bottom: 1px solid rgba(1,62,55,0.06); font-size: 13px; }}
        .legend-left {{ display: flex; align-items: center; gap: 8px; font-weight: 700; }}
    </style>
    </head>
    <body>
    <div class="grid">{kpi_cards_html}</div>
    <div class="row">
        <div class="col-2 panel">
            <div class="panel-title">📊 {chart_title}</div>
            <canvas id="lineBarChart" height="110"></canvas>
        </div>
        <div class="col-1 panel">
            <div class="panel-title">🏭 توزيع الإنتاج الفعلي</div>
            <div style="display:flex; align-items:center; gap:14px;">
                <div style="position:relative; width:140px; height:140px; flex-shrink:0;">
                    <canvas id="lineDonut2" width="140" height="140"></canvas>
                </div>
                <div style="flex:1;"><div id="lineLegend2"></div></div>
            </div>
        </div>
    </div>
    <div class="panel">
        <div class="panel-title">📋 التفاصيل لكل خط</div>
        <table>
            <tr><th>الخط</th><th>المستهدف</th><th>الفعلي</th><th>نسبة التحقيق</th></tr>
            {table_rows}
            <tr class="total-row"><td class="line-cell">الإجمالي</td><td>{total_t:,.0f}</td><td>{total_a:,.0f}</td>
                <td><span class="pct-pill" style="background:#0132271f; color:#013e37;">{total_pct:.0f}%</span></td></tr>
        </table>
    </div>
    <script>
    Chart.defaults.font.family = "'Cairo','Segoe UI',sans-serif";
    Chart.defaults.color = "#4b6b63";
    const gridColor = "rgba(1,62,55,0.08)";
    const lNames = {json.dumps(line_names)};
    const lTarget = {json.dumps(line_target)};
    const lActual = {json.dumps(line_actual)};
    const lColors = {line_colors_json};

    new Chart(document.getElementById('lineBarChart'), {{
        type: 'bar',
        data: {{ labels: lNames, datasets: [
            {{ label: 'المستهدف', data: lTarget, backgroundColor: '#e0a92e', borderRadius: 6 }},
            {{ label: 'الفعلي', data: lActual, backgroundColor: '#0d6b5c', borderRadius: 6 }}
        ]}},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ position: 'top', labels: {{ usePointStyle: true }} }} }},
            scales: {{ y: {{ beginAtZero: true, grid: {{ color: gridColor }} }}, x: {{ grid: {{ display: false }} }} }}
        }}
    }});

    new Chart(document.getElementById('lineDonut2'), {{
        type: 'doughnut',
        data: {{ labels: lNames, datasets: [{{ data: lActual, backgroundColor: lColors, borderColor: '#fff', borderWidth: 2 }}] }},
        options: {{ responsive: true, maintainAspectRatio: false, cutout: '62%', plugins: {{ legend: {{ display: false }} }} }}
    }});
    const legendBox2 = document.getElementById('lineLegend2');
    const totalActual2 = {total_actual};
    lNames.forEach((name, i) => {{
        const val = lActual[i];
        const pct = totalActual2 > 0 ? (val/totalActual2*100).toFixed(1) : 0;
        legendBox2.innerHTML += `<div class="legend-item"><div class="legend-left">
            <span class="dot" style="background:${{lColors[i]}}"></span>${{name}}</div>
            <div>${{val.toLocaleString()}} <span style="color:#6b7280;">(${{pct}}%)</span></div></div>`;
    }});

    // ---- تظبيط ارتفاع الإطار تلقائيًا حسب المحتوى الفعلي (يمنع السكرول المزدوج) ----
    function reportHeight() {{
        const h = document.documentElement.scrollHeight;
        window.parent.postMessage({{ type: "streamlit:setFrameHeight", height: h }}, "*");
    }}
    window.addEventListener("load", reportHeight);
    setTimeout(reportHeight, 300);
    setTimeout(reportHeight, 900);
    </script>
    </body>
    </html>
    """
    return html


def build_daily_trend_html(dates, series_by_line, table_rows_html, table_header_html):
    """رسم بياني احترافي (خط متعدد لكل خط إنتاج) لاتجاه الإنتاج اليومي + جدول يومي بجانبه"""
    palette = ["#0d6b5c", "#e0a92e", "#4c8c7d", "#a06f0f", "#7fb5a6", "#2563eb", "#c98f1f", "#7c3aed"]
    datasets_js = ""
    for i, (line_name, values) in enumerate(series_by_line.items()):
        color = palette[i % len(palette)]
        datasets_js += f"""{{
            label: {json.dumps(line_name)}, data: {json.dumps(values)}, borderColor: "{color}",
            backgroundColor: "{color}22", tension: 0.3, pointRadius: 3, fill: false
        }},"""

    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: 'Cairo','Segoe UI',Tahoma,sans-serif; background: #fdf9ef; margin: 0; padding: 18px; color: #013e37; }}
        .panel {{ background: #ffffff; border: 1px solid rgba(1,62,55,0.12); border-radius: 16px;
                  padding: 18px; box-shadow: 0 2px 10px rgba(1,62,55,0.06); margin-bottom: 16px; }}
        .panel-title {{ font-size: 16px; font-weight: 900; color: #013e37; margin-bottom: 12px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ background: #013e37; color: #ffefb3; padding: 8px 9px; text-align: center; font-weight: 800; font-size: 11.5px; position: sticky; top: 0; }}
        td {{ padding: 8px 9px; text-align: center; border-bottom: 1px solid rgba(1,62,55,0.08); font-weight: 700; }}
        .table-wrap {{ max-height: 420px; overflow-y: auto; border-radius: 10px; }}
        tr:nth-child(even) td {{ background: rgba(1,62,55,0.03); }}
        tr.total-row td {{ background: #ffefb3 !important; font-weight: 900; border-top: 2px solid #013e37; }}
    </style>
    </head>
    <body>
    <div class="panel">
        <div class="panel-title">📈 اتجاه الإنتاج اليومي لكل خط (الشهر الحالي)</div>
        <canvas id="dailyTrend" height="90"></canvas>
    </div>
    <div class="panel">
        <div class="panel-title">📅 سجل الإنتاج اليومي</div>
        <div class="table-wrap">
        <table>
            <thead>{table_header_html}</thead>
            <tbody>{table_rows_html}</tbody>
        </table>
        </div>
    </div>
    <script>
    Chart.defaults.font.family = "'Cairo','Segoe UI',sans-serif";
    Chart.defaults.color = "#4b6b63";
    new Chart(document.getElementById('dailyTrend'), {{
        type: 'line',
        data: {{ labels: {json.dumps(dates)}, datasets: [{datasets_js}] }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ position: 'top', labels: {{ usePointStyle: true }} }} }},
            scales: {{
                y: {{ beginAtZero: true, grid: {{ color: "rgba(1,62,55,0.08)" }} }},
                x: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
    function reportHeight() {{
        const h = document.documentElement.scrollHeight;
        window.parent.postMessage({{ type: "streamlit:setFrameHeight", height: h }}, "*");
    }}
    window.addEventListener("load", reportHeight);
    setTimeout(reportHeight, 300);
    setTimeout(reportHeight, 900);
    </script>
    </body>
    </html>
    """
    return html


def build_shift_share_html(line_names, shift_names, matrix):
    """رسم أعمدة مكدّسة (Stacked Bar) يوضح نصيب كل شيفت من إنتاج كل خط + جدول تفصيلي
    matrix: dict{line: {shift: value}}"""
    palette = ["#0d6b5c", "#e0a92e", "#2563eb"]
    shift_colors = {sh: palette[i % len(palette)] for i, sh in enumerate(shift_names)}

    datasets_js = ""
    for i, sh in enumerate(shift_names):
        values = [matrix.get(ln, {}).get(sh, 0) for ln in line_names]
        datasets_js += f"""{{
            label: {json.dumps(sh)}, data: {json.dumps(values)},
            backgroundColor: "{shift_colors[sh]}", borderRadius: 4
        }},"""

    table_rows = ""
    for ln in line_names:
        line_total = sum(matrix.get(ln, {}).get(sh, 0) for sh in shift_names)
        for sh in shift_names:
            val = matrix.get(ln, {}).get(sh, 0)
            pct = (val / line_total * 100) if line_total > 0 else 0
            table_rows += f"""
            <tr>
                <td class="line-cell"><span class="dot" style="background:{shift_colors[sh]}"></span>{ln}</td>
                <td>{sh}</td>
                <td>{val:,.0f}</td>
                <td>{pct:.1f}%</td>
            </tr>
            """
        table_rows += f"""
        <tr class="total-row"><td colspan="2">إجمالي {ln}</td><td>{line_total:,.0f}</td><td>100%</td></tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: 'Cairo','Segoe UI',Tahoma,sans-serif; background: #fdf9ef; margin: 0; padding: 18px; color: #013e37; }}
        .panel {{ background: #ffffff; border: 1px solid rgba(1,62,55,0.12); border-radius: 16px;
                  padding: 18px; box-shadow: 0 2px 10px rgba(1,62,55,0.06); margin-bottom: 16px; }}
        .panel-title {{ font-size: 16px; font-weight: 900; color: #013e37; margin-bottom: 12px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
        th {{ background: #013e37; color: #ffefb3; padding: 9px 10px; text-align: center; font-weight: 800; font-size: 12.5px; }}
        td {{ padding: 8px 10px; text-align: center; border-bottom: 1px solid rgba(1,62,55,0.08); font-weight: 700; }}
        .line-cell {{ text-align: right; display: flex; align-items: center; gap: 8px; font-weight: 800; }}
        .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        tr.total-row td {{ background: #ffefb3; font-weight: 900; }}
    </style>
    </head>
    <body>
    <div class="panel">
        <div class="panel-title">👷 نصيب كل شيفت من إنتاج كل خط (KG)</div>
        <canvas id="shiftStacked" height="100"></canvas>
    </div>
    <div class="panel">
        <div class="panel-title">📋 تفاصيل نصيب كل شيفت</div>
        <table>
            <tr><th>الخط</th><th>الشيفت</th><th>الفعلي (KG)</th><th>نسبة من الخط</th></tr>
            {table_rows}
        </table>
    </div>
    <script>
    Chart.defaults.font.family = "'Cairo','Segoe UI',sans-serif";
    Chart.defaults.color = "#4b6b63";
    new Chart(document.getElementById('shiftStacked'), {{
        type: 'bar',
        data: {{ labels: {json.dumps(line_names)}, datasets: [{datasets_js}] }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ position: 'top', labels: {{ usePointStyle: true }} }} }},
            scales: {{
                x: {{ stacked: true, grid: {{ display: false }} }},
                y: {{ stacked: true, beginAtZero: true, grid: {{ color: "rgba(1,62,55,0.08)" }} }}
            }}
        }}
    }});
    function reportHeight() {{
        const h = document.documentElement.scrollHeight;
        window.parent.postMessage({{ type: "streamlit:setFrameHeight", height: h }}, "*");
    }}
    window.addEventListener("load", reportHeight);
    setTimeout(reportHeight, 300);
    setTimeout(reportHeight, 900);
    </script>
    </body>
    </html>
    """
    return html


def build_breakage_report_html(totals, line_rows, trend_dates, trend_out_pct, trend_in_pct,
                                report_date_str, report_title="تحليل الكسر لخطوط إنتاج مصنع الكاندي",
                                page_height_mm=None):
    """تقرير احترافي لتحليل الكسر بنظام الرصيد (رصيد أول المدة + كسر خارج = إجمالي الكسر، وبعد خصم
    الكسر الداخل بيبقى متبقي الرصيد) — لكل خط في صف لوحده تحت بعض. صفحة واحدة متصلة عند الطباعة."""
    palette = ["#0d6b5c", "#e0a92e", "#4c8c7d", "#a06f0f", "#7fb5a6", "#2563eb", "#c98f1f", "#7c3aed"]

    line_names = [r["name"] for r in line_rows]
    out_vals = [float(r["out"]) for r in line_rows]
    in_vals = [float(r["in"]) for r in line_rows]

    # ---------- جدول الخطوط: رصيد أول المدة → الكسر الخارج → إجمالي الكسر → الكسر الداخل → متبقي الرصيد ----------
    table_rows_html = ""
    tot_open = tot_out = tot_in = tot_total = tot_remain = 0
    for i, r in enumerate(line_rows):
        pct_color = "#16a34a" if r["pct"] <= 5 else ("#0d6b5c" if r["pct"] <= 10 else
                     ("#e0a92e" if r["pct"] <= 15 else ("#ea580c" if r["pct"] <= 20 else "#dc2626")))
        table_rows_html += f"""
        <tr>
            <td class="line-cell"><span class="dot" style="background:{palette[i % len(palette)]}"></span>{r['name']}</td>
            <td>{r['opening']:,.0f}</td>
            <td>{r['out']:,.0f}</td>
            <td style="font-weight:900;">{r['total']:,.0f}</td>
            <td>{r['in']:,.0f}</td>
            <td style="font-weight:900; color:#013e37;">{r['remaining']:,.0f}</td>
            <td><span class="pct-pill" style="background:{pct_color}1f; color:{pct_color};">{r['pct']:.2f}%</span></td>
        </tr>
        """
        tot_open += r["opening"]; tot_out += r["out"]; tot_in += r["in"]
        tot_total += r["total"]; tot_remain += r["remaining"]
    table_rows_html += f"""
    <tr class="total-row">
        <td>الإجمالي</td><td>{tot_open:,.0f}</td><td>{tot_out:,.0f}</td>
        <td>{tot_total:,.0f}</td><td>{tot_in:,.0f}</td><td>{tot_remain:,.0f}</td><td>-</td>
    </tr>
    """

    # ---------- كروت KPI (الخارج والداخل فيهم نسبة % وكجم/طن تحت الرقم الرئيسي) ----------
    kpi_cards_html = f"""
    <div class="kpi" style="border-inline-start:4px solid #dc2626;">
        <div class="kpi-icon2" style="color:#dc2626;">⬆️</div>
        <div class="kpi-label">إجمالي الكسر الخارج</div>
        <div class="kpi-value">{totals['out']:,.0f} KG</div>
        <div class="kpi-sub">{totals['out_pct']:.2f}% من الإنتاج &nbsp;|&nbsp; {totals['out_kgton']:.2f} KG/Ton</div>
    </div>
    <div class="kpi" style="border-inline-start:4px solid #e0a92e;">
        <div class="kpi-icon2" style="color:#e0a92e;">⬇️</div>
        <div class="kpi-label">إجمالي الكسر الداخل</div>
        <div class="kpi-value">{totals['in']:,.0f} KG</div>
        <div class="kpi-sub">{totals['in_pct']:.2f}% من الإنتاج &nbsp;|&nbsp; {totals['in_kgton']:.2f} KG/Ton</div>
    </div>
    <div class="kpi" style="border-inline-start:4px solid #0d6b5c;">
        <div class="kpi-icon2" style="color:#0d6b5c;">🏦</div>
        <div class="kpi-label">متبقي الرصيد</div>
        <div class="kpi-value">{totals['remaining']:,.0f} KG</div>
    </div>
    <div class="kpi" style="border-inline-start:4px solid #2563eb;">
        <div class="kpi-icon2" style="color:#2563eb;">📦</div>
        <div class="kpi-label">إجمالي الإنتاج</div>
        <div class="kpi-value">{totals['production']:,.0f} KG</div>
    </div>
    <div class="kpi" style="border-inline-start:4px solid #dc2626;">
        <div class="kpi-icon2" style="color:#dc2626;">⚠️</div>
        <div class="kpi-label">نسبة الكسر من الإنتاج</div>
        <div class="kpi-value">{totals['break_pct']:.2f}%</div>
    </div>
    <div class="kpi" style="border-inline-start:4px solid #7c3aed;">
        <div class="kpi-icon2" style="color:#7c3aed;">🥇</div>
        <div class="kpi-label">الكفاءة</div>
        <div class="kpi-value">{totals['efficiency']:.2f}%</div>
    </div>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{ box-sizing: border-box; }}
        html, body {{ height: auto !important; }}
        body {{ font-family: 'Cairo','Segoe UI',Tahoma,sans-serif; background: #fdf9ef; margin: 0; padding: 18px; color: #013e37; }}
        .report-title {{ font-size: 21px; font-weight: 900; margin-bottom: 2px; text-align: center; }}
        .report-date {{ font-size: 12.5px; font-weight: 700; color: #6b7280; text-align: center; margin-bottom: 14px; }}
        .grid {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }}
        .kpi {{ flex: 1; min-width: 160px; background: #ffffff; border: 1px solid rgba(1,62,55,0.15);
                border-radius: 12px; padding: 14px; box-shadow: 0 2px 8px rgba(1,62,55,0.08); text-align: center; }}
        .kpi-icon2 {{ font-size: 20px; margin-bottom: 4px; }}
        .kpi-label {{ font-size: 11.5px; font-weight: 700; color: #6b7280; margin-bottom: 4px; }}
        .kpi-value {{ font-size: 19px; font-weight: 900; color: #013e37; }}
        .kpi-sub {{ font-size: 10.5px; font-weight: 800; color: #4b6b63; margin-top: 5px; }}
        .panel {{ background: #ffffff; border: 1px solid rgba(1,62,55,0.12); border-radius: 16px;
                  padding: 18px; box-shadow: 0 2px 10px rgba(1,62,55,0.06); margin-bottom: 16px; page-break-inside: avoid; }}
        .panel-title {{ font-size: 15px; font-weight: 900; color: #013e37; margin-bottom: 12px; text-align:center; }}
        .row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
        .col-1 {{ flex: 1; min-width: 280px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
        th {{ background: #013e37; color: #ffefb3; padding: 8px 9px; text-align: center; font-weight: 800; font-size: 11.5px; }}
        td {{ padding: 8px 9px; text-align: center; border-bottom: 1px solid rgba(1,62,55,0.08); font-weight: 700; }}
        .line-cell {{ text-align: right; display: flex; align-items: center; gap: 8px; font-weight: 800; }}
        .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        .pct-pill {{ padding: 3px 10px; border-radius: 20px; font-weight: 800; font-size: 12px; }}
        tr.total-row td {{ background: #ffefb3; font-weight: 900; border-top: 2px solid #013e37; }}
        /* ---------- طباعة صفحة واحدة متصلة (بدون تقسيم لصفحات) ---------- */
        @media print {{
            @page {{ size: 297mm {page_height_mm or 400}mm; margin: 8mm; }}
            body {{ padding: 6mm; }}
            .panel {{ break-inside: avoid; }}
        }}
        .app-brand {{ text-align: center; margin-bottom: 10px; }}
        .app-brand .app-name {{ font-size: 15px; font-weight: 900; color: #013e37; }}
        .app-brand .app-dev {{ font-size: 11px; font-weight: 700; color: #6b7280; margin-top: 2px; }}
    </style>
    </head>
    <body>
    <div class="app-brand">
        <div class="app-name">🏭 Production Management System</div>
        <div class="app-dev">Developed by Eng. Ahmed Adel</div>
    </div>
    <div class="report-title">🔨 {report_title}</div>
    <div class="report-date">التاريخ: {report_date_str}</div>
    <div class="grid">{kpi_cards_html}</div>

    <div class="panel">
        <div class="panel-title">📋 جدول الكسر لكل الخطوط (رصيد أول المدة → متبقي الرصيد)</div>
        <table>
            <tr>
                <th>اسم الخط</th><th>رصيد أول المدة (KG)</th><th>الكسر الخارج (KG)</th>
                <th>إجمالي الكسر (KG)</th><th>الكسر الداخل (KG)</th><th>متبقي الرصيد (KG)</th><th>نسبة الكسر %</th>
            </tr>
            {table_rows_html}
        </table>
        <div style="font-size:11.5px; color:#6b7280; font-weight:700; margin-top:8px; text-align:center;">
            إجمالي الكسر = رصيد أول المدة + الكسر الخارج &nbsp;&nbsp;|&nbsp;&nbsp; متبقي الرصيد = إجمالي الكسر − الكسر الداخل
        </div>
    </div>

    <div class="row">
        <div class="col-1 panel">
            <div class="panel-title">📊 الكسر الخارج مقابل الداخل لكل خط (KG)</div>
            <div style="position:relative; width:100%; height:220px;">
                <canvas id="lineBar"></canvas>
            </div>
        </div>
        <div class="col-1 panel">
            <div class="panel-title">🥧 توزيع إجمالي الكسر بين الخطوط</div>
            <div style="position:relative; width:100%; max-width:260px; height:260px; margin:0 auto;">
                <canvas id="lineDonutB"></canvas>
            </div>
        </div>
    </div>

    <div class="panel">
        <div class="panel-title">📈 نسبة الكسر (الداخل والخارج) — آخر 7 أيام</div>
        <div style="max-width:640px; margin:0 auto;">
            <canvas id="trendChartB" height="70"></canvas>
        </div>
    </div>

    <script>
    Chart.defaults.font.family = "'Cairo','Segoe UI',sans-serif";
    Chart.defaults.color = "#4b6b63";
    const gridColor = "rgba(1,62,55,0.08)";

    new Chart(document.getElementById('lineBar'), {{
        type: 'bar',
        data: {{ labels: {json.dumps(line_names)}, datasets: [
            {{ label: 'الكسر الخارج', data: {json.dumps(out_vals)}, backgroundColor: '#dc2626', borderRadius: 5 }},
            {{ label: 'الكسر الداخل', data: {json.dumps(in_vals)}, backgroundColor: '#e0a92e', borderRadius: 5 }}
        ]}},
        options: {{
            responsive: true, maintainAspectRatio: false,
            plugins: {{ legend: {{ position: 'top', labels: {{ usePointStyle: true }} }} }},
            scales: {{ y: {{ beginAtZero: true, grid: {{ color: gridColor }} }}, x: {{ grid: {{ display: false }} }} }}
        }}
    }});

    new Chart(document.getElementById('lineDonutB'), {{
        type: 'doughnut',
        data: {{ labels: {json.dumps(line_names)}, datasets: [{{
            data: {json.dumps([o + i for o, i in zip(out_vals, in_vals)])},
            backgroundColor: {json.dumps(palette[:len(line_names)])}, borderColor: '#fff', borderWidth: 2
        }}]}},
        options: {{
            responsive: true, maintainAspectRatio: false,
            plugins: {{ legend: {{ position: 'bottom', labels: {{ usePointStyle: true, font: {{ size: 10 }} }} }} }}
        }}
    }});

    new Chart(document.getElementById('trendChartB'), {{
        type: 'line',
        data: {{ labels: {json.dumps(trend_dates)}, datasets: [
            {{ label: 'نسبة الكسر الخارج %', data: {json.dumps(trend_out_pct)}, borderColor: '#dc2626',
               backgroundColor: '#dc262622', fill: true, tension: 0.3, pointRadius: 2.5 }},
            {{ label: 'نسبة الكسر الداخل %', data: {json.dumps(trend_in_pct)}, borderColor: '#e0a92e',
               backgroundColor: '#e0a92e22', fill: true, tension: 0.3, pointRadius: 2.5 }}
        ]}},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ position: 'top', labels: {{ usePointStyle: true, boxWidth: 8, font: {{ size: 10 }} }} }} }},
            scales: {{
                y: {{ beginAtZero: true, grid: {{ color: gridColor }}, ticks: {{ callback: v => v + '%', font: {{ size: 9 }} }} }},
                x: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 9 }} }} }}
            }}
        }}
    }});

    function reportHeight() {{
        const h = document.documentElement.scrollHeight;
        window.parent.postMessage({{ type: "streamlit:setFrameHeight", height: h }}, "*");
    }}
    window.addEventListener("load", reportHeight);
    setTimeout(reportHeight, 300);
    setTimeout(reportHeight, 900);
    setTimeout(reportHeight, 1600);
    </script>
    </body>
    </html>
    """
    return html


def kpi_row(cards):
    """صف كروت KPI بشكل دائرة ملونة لكل أيقونة (حسب نوع المؤشر) + رقم كبير + وصف — زي التصميم المرفق"""
    html = '<div style="display:flex; gap:14px; margin:6px 0 20px; flex-wrap:wrap;">'
    for c in cards:
        delta_html = ""
        if c.get("delta"):
            d_color = c.get("delta_color", "#16a34a")
            delta_html = f'<div style="font-size:11.5px; font-weight:800; color:{d_color}; margin-top:4px;">{c["delta"]}</div>'
        icon_color = c.get("color", "#013e37")
        icon_style = (
            f'background:{icon_color}22; color:{icon_color};'
        )
        card_html = f"""
        <div class="kpi-card" style="flex:1; min-width:170px;">
            <div class="kpi-icon" style="{icon_style}">{c['icon']}</div>
            <div class="kpi-label">{c['label']}</div>
            <div class="kpi-value">{c['value']}</div>
            {delta_html}
        </div>
        """
        html += _flat_html(card_html)
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def categorize_product(name):
    """يصنف الصنف حسب أول كلمة في اسمه: سولا / طوفي / اكلير"""
    name = str(name).strip()
    if name.startswith("سولا"):
        return "هارد كاندي"
    elif name.startswith("طوفي"):
        return "طوفي"
    elif name.startswith("اكلير") or name.startswith("إكلير"):
        return "اكلير"
    else:
        return "أخرى"


def _df_to_html_highlighted(df, highlight_mask, highlight_color="#fff3b0", row_colors=None):
    """بيبني جدول HTML يدوي عشان نقدر نلوّن صفوف معينة (زي الخطوط المتعطلة) بلون مميز.
    لو row_colors موجودة (قائمة لون لكل صف أو None)، بتاخد أولوية على highlight_mask —
    مفيدة لما نحتاج أكتر من لون (أخضر/برتقالي/أحمر) مش بس تظليل واحد."""
    cols = df.columns.tolist()
    header_html = "".join(f"<th>{c}</th>" for c in cols)
    rows_html = ""
    highlight_mask = list(highlight_mask) if highlight_mask is not None else None
    row_colors = list(row_colors) if row_colors is not None else None
    for i, (_, row) in enumerate(df.iterrows()):
        if row_colors is not None and i < len(row_colors) and row_colors[i]:
            row_style = f' style="background-color:{row_colors[i]};"'
        else:
            is_hl = bool(highlight_mask[i]) if highlight_mask is not None and i < len(highlight_mask) else False
            row_style = f' style="background-color:{highlight_color};"' if is_hl else ""
        cells_html = "".join(f"<td>{'' if pd.isna(row[c]) else row[c]}</td>" for c in cols)
        rows_html += f"<tr{row_style}>{cells_html}</tr>"
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{rows_html}</tbody></table>"


def build_printable_html(title, subtitle, df, extra_title=None, extra_df=None, extra_tables=None,
                          landscape=False, extra_html=None, top_html=None, highlight_mask=None,
                          highlight_color="#fff3b0", row_colors=None, base_font_size=10, compact=False,
                          bold=False, row_padding=None, single_page_height_mm=None):
    """يبني صفحة HTML جاهزة للطباعة/تحويل PDF من المتصفح (Ctrl+P > Save as PDF)
    extra_tables: قائمة اختيارية [(عنوان, DataFrame), ...] تتحط كلها جنب الجدول الرئيسي فوق بعض
    top_html: أي HTML إضافي (زي بطاقات ملخص KPI) يتحط فوق الجدول الرئيسي مباشرة
    extra_html: أي HTML إضافي (زي جدول ملخص أو صورة رسم بياني) يتحط تحت الجدول الرئيسي مباشرة
    highlight_mask: قائمة True/False بنفس عدد صفوف df — الصف اللي True بيتلوّن بلون highlight_color
    row_colors: قائمة لون CSS لكل صف (أو '' / None بدون تلوين) — بتاخد أولوية على highlight_mask
    base_font_size: حجم خط الجدول الرئيسي (px) — كبّره شوية لو عايز الخط يبقى أوضح
    compact: لو True بيقلل الهوامش والمسافات عشان التقرير يتظبط في صفحة واحدة
    bold: لو True بيخلي نص الجدول الرئيسي تقيل (bold) مش بس العناوين
    row_padding: تحكم يدوي في تباعد الصفوف، مثلاً '10px 8px' — لو مذكور بيتجاهل إعداد compact الافتراضي
    single_page_height_mm: لو محدد (رقم بالمليمتر)، بيطلع PDF بصفحة واحدة طويلة بارتفاع مناسب للمحتوى
                            بدل ورق A4 عادي — مفيد للإرسال أونلاين، مش لطباعة ورق فعلي. المفروض المتصل
                            (caller) يحسب الرقم ده بناءً على عدد الصفوف الفعلي عشان الصفحة متبقاش فاضية"""
    if highlight_mask is not None or row_colors is not None:
        table_html = _df_to_html_highlighted(df, highlight_mask, highlight_color, row_colors)
    else:
        table_html = df.to_html(index=False, border=0, justify="center", na_rep="-")

    tables_list = list(extra_tables) if extra_tables else []
    if extra_df is not None:
        tables_list.append((extra_title or "", extra_df))

    if tables_list:
        side_blocks = ""
        for t_title, t_df in tables_list:
            t_html = t_df.to_html(index=False, border=0, justify="center", na_rep="-")
            side_blocks += f'<div class="side-block"><h2>{t_title}</h2>{t_html}</div>'

        layout_html = f"""
        <table class="layout-wrapper" width="100%">
        <tr>
            <td class="main-cell" valign="top">{table_html}</td>
            <td class="side-cell" valign="top">{side_blocks}</td>
        </tr>
        </table>
        """
    else:
        layout_html = table_html

    if single_page_height_mm:
        page_width = "297mm" if landscape else "210mm"
        page_size = f"{page_width} {single_page_height_mm}mm"
    else:
        page_size = "A4 landscape" if landscape else "A4"
    page_margin = "4mm" if compact else "6mm"
    body_pad = "3px" if compact else "6px"
    h1_size = "14px" if compact else "16px"
    sub_font = "8px" if compact else "9px"
    cell_padding = row_padding if row_padding else ("2px 3px" if compact else "3px 5px")
    main_font_weight = 700 if bold else 400

    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        @page {{ size: {page_size}; margin: {page_margin}; }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; margin: 0; padding: {body_pad}; color: #1a1d21; }}
        h1 {{ font-size: {h1_size}; margin: 0 0 2px; }}
        h2 {{ color: #0b1f3a; font-size: {base_font_size + 1}px; margin: 8px 0 4px; }}
        p.dev {{ color: #374151; margin: 0 0 4px; font-size: 10px; font-weight: 600; }}
        p.sub {{ color: #6b7280; margin: 0 0 6px; font-size: {sub_font}; }}

        table.layout-wrapper {{ border-collapse: collapse; }}
        table.layout-wrapper > tr > td {{ border: none; padding: 0; }}
        td.main-cell {{ width: 74%; padding-left: 10px !important; }}
        td.side-cell {{ width: 26%; }}
        .side-block {{ margin-bottom: 10px; }}
        .side-block:first-child h2 {{ margin-top: 0; }}

        table:not(.layout-wrapper) {{ border-collapse: collapse; width: 100%; font-size: {base_font_size}px; font-weight: {main_font_weight}; }}
        table:not(.layout-wrapper) th, table:not(.layout-wrapper) td {{
            border: 1px solid #d1d5db; padding: {cell_padding}; text-align: center;
        }}
        table:not(.layout-wrapper) tr {{ page-break-inside: avoid; }}
        table:not(.layout-wrapper) thead {{ display: table-header-group; }}
        table:not(.layout-wrapper) th {{ background-color: #f4f7fb; font-weight: 700; }}
        table:not(.layout-wrapper) tr:nth-child(even):not([style]) {{ background-color: #fafafa; }}
        table:not(.layout-wrapper) tr:last-child:not([style]) {{ font-weight: 700; background-color: #eef2f7; }}
        .side-cell table {{ font-size: 9px; font-weight: 400; }}

        @media print {{
            body {{ padding: 0; }}
        }}
    </style>
    </head>

    <body>
        <h1>🏭 Production Management System</h1>
        <p class="dev">Developed by Eng. Ahmed Adel</p>
        <h1 style="font-size:12px; margin-top:6px;">{title}</h1>
        <p class="sub">{subtitle}</p>
        {top_html or ''}
        {layout_html}
        {extra_html or ''}
    </body>
    </html>
    """
    return html


DASH_ACCENTS = {
    "overview": ("#7a5b0e", "#e0a92e", "🏠"),
    "production": ("#1e3a8a", "#2563eb", "🏭"),
    "packing": ("#065f46", "#16a34a", "📦"),
    "breakage": ("#9a3412", "#ea580c", "🔨"),
    "faults": ("#7f1d1d", "#dc2626", "⚠️"),
}


def dash_kpi_card(icon, value, label, color, delta=None, delta_positive=None):
    """بطاقة KPI بنفس طابع لوحات التحكم الاحترافية: أيقونة + رقم كبير + وصف صغير + سهم مقارنة اختياري بالشهر اللي فات"""
    delta_html = ""
    if delta:
        arrow = "▲" if delta_positive else "▼"
        dcolor = "#16a34a" if delta_positive else "#dc2626"
        delta_html = f'<div class="kpi-delta" style="color:{dcolor};">{arrow} {delta}</div>'
    return f"""
    <div class="kpi-card">
        <div class="kpi-icon" style="background:{color}22; color:{color};">{icon}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-label">{label}</div>
        {delta_html}
    </div>
    """


def dash_chart_card(title, img_html):
    """بطاقة بيضا فيها عنوان صغير ورسم بياني (صورة base64) — تصميم شبيه بكروت الرسوم في اللوحات الاحترافية"""
    return f"""
    <div class="chart-card">
        <div class="chart-card-title">{title}</div>
        {img_html}
    </div>
    """


NAV_LABELS = {
    "overview": "🏠 Overview",
    "production": "🏭 Production",
    "packing": "📦 Packing",
    "faults": "⚠️ Faults",
    "breakage": "🔨 Breakage",
}


def build_dashboard_document(overall_title, overall_subtitle, sections):
    """بيبني صفحة HTML واحدة بطابع لوحة تحكم احترافية (Dashboard) فيها Sidebar جانبي — تنفع تتنشر كصفحة ويب
    مستقلة (HTML خام بدون أي اعتماد على إنترنت أو مكتبات خارجية) وتنفع كمان تتحول PDF من المتصفح (Ctrl+P).

    لو الأقسام أكتر من واحد (حالة البورتفوليو): الـ Sidebar بيبقى فيه زرار لكل قسم، كل زرار بيورّي قسمه ويخفي
    الباقي — بورتفوليو حقيقي تفاعلي. وعند الطباعة/تصدير PDF كل الأقسام بتظهر مع بعض تلقائيًا، كل واحد في صفحة
    لوحده (page-break)، بغض النظر عن التاب المفتوح على الشاشة.

    sections: قائمة dicts، كل واحد فيه:
        key        : "production" / "packing" / "breakage" / "faults" (بيحدد لون واسم القسم)
        title      : عنوان القسم
        subtitle   : وصف قصير تحت العنوان
        kpi_html   : HTML بطاقات الـ KPI (ناتج dash_kpi_card مجمّعة)
        chart_html : HTML كروت الرسوم البيانية (ناتج dash_chart_card مجمّعة)
        table_title: عنوان الجدول
        table_df   : DataFrame الجدول الرئيسي للقسم
    """
    is_portfolio = len(sections) > 1

    brand_strip_html = f"""
        <div class="brand-strip">
            <div>🏭 Production Management System &nbsp;•&nbsp; Developed by Eng. Ahmed Adel</div>
            <div>{overall_title}</div>
        </div>
    """
    sidebar_buttons = []
    blocks = []
    for i, sec in enumerate(sections):
        accent_dark, accent, icon = DASH_ACCENTS.get(sec.get("key"), ("#0b1f3a", "#2563eb", "📊"))
        section_id = f"sec-{i}"
        table_html = sec["table_df"].to_html(index=False, border=0, justify="center", na_rep="-")
        active_class = "active" if i == 0 else ""

        nav_label = NAV_LABELS.get(sec.get("key"), sec["title"])
        clickable = f"""onclick="pmsShowSection('{section_id}')" style="--nav-accent:{accent}; cursor:pointer;" """ \
            if is_portfolio else f'style="--nav-accent:{accent}; cursor:default;"'
        sidebar_buttons.append(
            f'<button class="sidebar-nav-btn {active_class}" data-target="{section_id}" {clickable}>'
            f'{nav_label}</button>'
        )

        main_table_block = f"""
            <div class="table-card">
                <div class="table-card-header" style="background:{accent};">{sec.get('table_title', '')}</div>
                {table_html}
            </div>
        """
        extra_block = sec.get("extra_html") or ""
        if extra_block.strip():
            tables_block = f'<div class="tables-row">{main_table_block}{extra_block}</div>'
        else:
            tables_block = main_table_block

        blocks.append(f"""
        <div class="report-page {active_class}" id="{section_id}">
            {brand_strip_html if i == 0 else ''}
            <div class="dash-header" style="background:linear-gradient(135deg,{accent_dark},{accent});">
                <div class="dash-header-left">
                    <div class="dash-icon">{icon}</div>
                    <div>
                        <div class="dash-title">{sec['title']}</div>
                        <div class="dash-subtitle">{sec.get('subtitle', '')}</div>
                    </div>
                </div>
                <div class="dash-badge">{overall_subtitle}</div>
            </div>
            <div class="kpi-grid">{sec.get('kpi_html') or ''}</div>
            <div class="chart-grid">{sec.get('chart_html') or ''}</div>
            {tables_block}
        </div>
        """)

    script_html = """
    <script>
        function pmsShowSection(id) {
            document.querySelectorAll('.report-page').forEach(function (el) {
                el.classList.remove('active');
            });
            document.querySelectorAll('.sidebar-nav-btn').forEach(function (el) {
                el.classList.remove('active');
            });
            var target = document.getElementById(id);
            if (target) { target.classList.add('active'); }
            var btn = document.querySelector('.sidebar-nav-btn[data-target="' + id + '"]');
            if (btn) { btn.classList.add('active'); }
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    </script>
    """ if is_portfolio else ""

    html = f"""
    <!DOCTYPE html>
    <html lang="en" dir="ltr">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{overall_title}</title>
    <style>
        :root {{
            --navy: #0b1f3a; --navy-light: #13294f; --bg: #0f172a;
            --card: #1e293b; --border: #334155; --text: #e5e7eb; --muted: #94a3b8;
        }}
        * {{ box-sizing: border-box; }}
        @page {{ size: A4 landscape; margin: 6mm; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background: var(--bg);
            margin: 0; padding: 0; color: var(--text); font-size: 13px;
        }}

        .dash-layout {{ display: flex; direction: ltr; min-height: 100vh; }}

        .dash-sidebar {{
            direction: ltr; width: 168px; flex-shrink: 0; background: linear-gradient(180deg, var(--navy), var(--navy-light));
            color: #fff; padding: 16px 10px; position: sticky; top: 0; align-self: flex-start;
            height: 100vh; overflow-y: auto;
        }}
        .sidebar-logo {{ display: flex; align-items: center; gap: 8px; margin-bottom: 18px; padding: 0 2px; }}
        .sidebar-logo-icon {{
            width: 32px; height: 32px; border-radius: 8px; background: rgba(255,255,255,.15);
            display: flex; align-items: center; justify-content: center; font-size: 15px; flex-shrink: 0;
        }}
        .sidebar-logo-text {{ font-size: 11.5px; font-weight: 800; line-height: 1.2; }}
        .sidebar-logo-sub {{ font-size: 6.5px; color: #b9c6e0; line-height: 1.2; }}
        .sidebar-nav-btn {{
            display: block; width: 100%; text-align: left; border: none; background: transparent;
            color: #c7d2e8; font-family: inherit; font-size: 10.5px; font-weight: 700; padding: 9px 10px;
            border-radius: 8px; margin-bottom: 3px; transition: all .15s ease;
        }}
        .sidebar-nav-btn:hover {{ background: rgba(255,255,255,.08); }}
        .sidebar-nav-btn.active {{ background: var(--nav-accent, #2563eb); color: #fff; }}
        .sidebar-footer {{
            margin-top: 16px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,.12);
            font-size: 7.5px; color: #9fb0d0; text-align: center; line-height: 1.5;
        }}

        .dash-main {{ direction: ltr; flex: 1; min-width: 0; padding: 10px; }}

        .brand-strip {{
            text-align: center; font-size: 9px; font-weight: 700; color: var(--muted);
            margin: 0 0 6px; padding: 0 0 6px; border-bottom: 1px solid var(--border);
            line-height: 1.5;
        }}

        .tables-row {{
            display: flex; gap: 8px; align-items: stretch;
            page-break-inside: avoid; break-inside: avoid;
        }}
        .tables-row .table-card {{ flex: 1; min-width: 0; }}

        .report-page {{ display: none; margin-bottom: 10px; }}
        .report-page.active {{ display: block; }}

        .dash-header {{
            display: flex; justify-content: space-between; align-items: center;
            border-radius: 10px; padding: 11px 16px; margin-bottom: 10px; color: #fff; gap: 10px;
            page-break-inside: avoid; break-inside: avoid;
        }}
        .dash-header-left {{ display: flex; align-items: center; gap: 9px; min-width: 0; flex: 1 1 auto; overflow: hidden; }}
        .dash-icon {{
            width: 32px; height: 32px; border-radius: 8px; background: rgba(255,255,255,.18);
            display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0;
        }}
        .dash-title {{
            font-size: 12.5px; font-weight: 800; letter-spacing: .3px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .dash-subtitle {{
            font-size: 8.5px; color: #d7e0f2; margin-top: 2px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .dash-badge {{
            background: rgba(255,255,255,.18); padding: 4px 11px; border-radius: 7px;
            font-size: 9.5px; font-weight: 700; white-space: nowrap; flex-shrink: 0;
        }}

        .kpi-grid {{
            display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap;
        }}
        .kpi-card {{
            flex: 1; min-width: 80px; background: var(--card); border: 1px solid var(--border);
            border-radius: 7px; padding: 6px 5px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,.25);
            page-break-inside: avoid; break-inside: avoid;
        }}
        .kpi-icon {{
            width: 20px; height: 20px; border-radius: 6px; display: flex; align-items: center;
            justify-content: center; margin: 0 auto 3px; font-size: 10px;
        }}
        .kpi-value {{ font-size: 11.5px; font-weight: 800; color: #f1f5f9; line-height: 1.1; }}
        .kpi-label {{ font-size: 7px; color: var(--muted); font-weight: 700; margin-top: 2px; line-height: 1.15; }}
        .kpi-delta {{ font-size: 7px; font-weight: 800; margin-top: 2px; }}

        .chart-grid {{
            display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap;
        }}
        .chart-card {{
            flex: 1; min-width: 190px; background: var(--card); border: 1px solid var(--border);
            border-radius: 7px; padding: 5px; box-shadow: 0 1px 4px rgba(0,0,0,.25);
            page-break-inside: avoid; break-inside: avoid;
        }}
        .chart-card-title {{ font-size: 8.5px; font-weight: 800; color: #f1f5f9; margin-bottom: 3px; }}
        .chart-card img {{ width: 100%; display: block; border-radius: 4px; }}
        .chart-card select {{
            width: 100%; margin-bottom: 5px; padding: 4px 6px; border-radius: 6px;
            border: 1px solid var(--border); background: #0f172a; color: var(--text); font-size: 8.5px; font-weight: 700;
        }}

        .table-card {{
            background: var(--card); border: 1px solid var(--border); border-radius: 7px;
            overflow: hidden; page-break-inside: avoid; break-inside: avoid;
        }}
        .table-card-header {{ padding: 6px 12px; font-size: 9.5px; font-weight: 800; color: #fff; }}
        table.dash-table, .table-card table {{ border-collapse: collapse; width: 100%; font-size: 8px; }}
        .table-card table th, .table-card table td {{
            padding: 4px 5px; text-align: center; border-bottom: 1px solid var(--border); color: var(--text);
        }}
        .table-card table th {{ background: #0f172a; color: #f1f5f9; font-weight: 800; }}
        .table-card table tr {{ page-break-inside: avoid; break-inside: avoid; }}
        .table-card table tr:nth-child(even) td {{ background: rgba(255,255,255,0.02); }}
        .table-card table tr:last-child {{ font-weight: 800; background: #0f172a; }}

        p.dev-footer {{ text-align: center; font-size: 8px; color: var(--muted); margin-top: 8px; }}

        @media print {{
            body {{ padding: 0; background: var(--bg); }}
            .dash-layout {{ display: block; }}
            .dash-sidebar {{ display: none; }}
            .dash-main {{ padding: 3mm; }}
            .report-page {{
                display: block !important;
                page-break-before: always; break-before: page;
            }}
            .report-page:first-child {{ page-break-before: auto; break-before: auto; }}
            .kpi-card, .chart-card, .table-card, .dash-header {{
                page-break-inside: avoid; break-inside: avoid;
            }}
        }}
    </style>
    </head>
    <body>
        <div class="dash-layout">
            <div class="dash-sidebar">
                <div class="sidebar-logo">
                    <div class="sidebar-logo-icon">🏭</div>
                    <div>
                        <div class="sidebar-logo-text">PMS</div>
                        <div class="sidebar-logo-sub">Production Management System</div>
                    </div>
                </div>
                {''.join(sidebar_buttons)}
                <div class="sidebar-footer">
                    {overall_subtitle}<br>Developed by Eng. Ahmed Adel
                </div>
            </div>
            <div class="dash-main">
                {''.join(blocks)}
                <p class="dev-footer">🏭 Production Management System &nbsp;•&nbsp; Developed by Eng. Ahmed Adel</p>
            </div>
        </div>
        {script_html}
    </body>
    </html>
    """
    return html



if page == "الرئيسية":
    if logo_path:
        st.image(logo_path, width=260)

    home_banner_html = """
    <div class="app-header-banner">
        <div class="icon">🏭</div>
        <div>
            <h1>Production Management System</h1>
            <p>Developed by Eng/Ahmed Adel &nbsp;•&nbsp; Track production, inventory, and performance in one place</p>
            <p>نظام متابعة وإدارة الإنتاج</p>
        </div>
    </div>
    """
    st.markdown(_flat_html(home_banner_html), unsafe_allow_html=True)

    st.markdown("#### اختر القسم اللي عايز تدخله 👇")

    HOME_TILES = [
        ("Dashboard", "📊", "نظرة سريعة على أداء الإنتاج والباكينج والأعطال"),
        ("Production", "🏭", "تسجيل ومتابعة إنتاج كل خط بالشيفت"),
        ("Packing", "📦", "تسجيل تعبئة الأصناف وتقارير الشيفتات"),
        ("الأعطال", "⚠️", "تسجيل ومتابعة توقفات خطوط الإنتاج"),
        ("Inventory", "🗃️", "متابعة أرصدة المواد الخام والجرد الدفتري والفعلي"),
        ("Workers", "👷", "إدارة بيانات وحضور العمال"),
        ("Reports", "📑", "تقارير شاملة عن الأداء الشهري"),
        ("Settings", "⚙️", "الإعدادات العامة وخطوط الإنتاج"),
    ]

    tile_cols = st.columns(4)
    for i, (name, icon, desc) in enumerate(HOME_TILES):
        with tile_cols[i % 4]:
            tile_html = f"""
            <a class="nav-tile" href="?nav={name}" target="_self">
                <span class="nav-tile-icon">{icon}</span>
                <span class="nav-tile-title">{name}</span>
                <span class="nav-tile-desc">{desc}</span>
            </a>
            """
            st.markdown(_flat_html(tile_html), unsafe_allow_html=True)
            st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

elif page == "Dashboard":
    page_banner("🏭", "لوحة المتابعة الشاملة", "نظرة سريعة على أداء الإنتاج والباكينج والأعطال")

    current_month_str = datetime.now().strftime("%Y-%m")
    today_day_num = datetime.now().day

    # ---------- بيانات الإنتاج (خطوط) ----------
    prod_target = prod_actual = 0
    prod_by_line = pd.DataFrame()
    trend_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    trend_actual = [0.0] * 7
    trend_target = [0.0] * 7
    if GSHEETS_ENABLED and gsheet_exists(PRODUCTION_SHEET):
        hist_df = read_gsheet(PRODUCTION_SHEET)
        hist_df["Date"] = hist_df["Date"].astype(str)
        all_shifts_hist = hist_df[hist_df["Shift"] == "All Shifts"].copy()
        for nc in ["المستهدف (KG)", "الفعلي (KG)"]:
            all_shifts_hist[nc] = pd.to_numeric(all_shifts_hist[nc], errors="coerce").fillna(0)

        month_hist = all_shifts_hist[all_shifts_hist["Date"].str.startswith(current_month_str)]
        if not month_hist.empty:
            prod_target = month_hist["المستهدف (KG)"].sum()
            prod_actual = month_hist["الفعلي (KG)"].sum()
            prod_by_line = month_hist.groupby("Line")[["المستهدف (KG)", "الفعلي (KG)"]].sum()

        # اتجاه آخر 7 أيام (بيانات حقيقية من شيت الإنتاج، مش تقديرية)
        daily_totals = all_shifts_hist.groupby("Date")[["المستهدف (KG)", "الفعلي (KG)"]].sum()
        for i, d in enumerate(trend_dates):
            if d in daily_totals.index:
                trend_target[i] = float(daily_totals.loc[d, "المستهدف (KG)"])
                trend_actual[i] = float(daily_totals.loc[d, "الفعلي (KG)"])

    # ---------- بيانات الباكينج ----------
    pack_target = pack_actual = 0
    pack_by_cat = pd.DataFrame()
    pack_sheet_dash = f"packing_monthly_{current_month_str}"
    if GSHEETS_ENABLED and gsheet_exists(pack_sheet_dash):
        pack_df = read_gsheet(pack_sheet_dash)
        day_cols_dash = [c for c in pack_df.columns if c.startswith("يوم")]
        if day_cols_dash:
            for dc in day_cols_dash:
                pack_df[dc] = pd.to_numeric(pack_df[dc], errors="coerce").fillna(0)
            pack_df["إجمالي الكراتين"] = pack_df[day_cols_dash].sum(axis=1)
            pack_df["المخطط بالكراتين (شهري)"] = pd.to_numeric(pack_df["المخطط بالكراتين (شهري)"], errors="coerce").fillna(0)
            pack_target = pack_df["المخطط بالكراتين (شهري)"].sum()
            pack_actual = pack_df["إجمالي الكراتين"].sum()
            pack_df["الفئة"] = pack_df["الصنف"].apply(categorize_product)
            pack_by_cat = pack_df.groupby("الفئة")["إجمالي الكراتين"].sum()

    # ---------- بيانات الأعطال (من نفس شيت جوجل اللي بتتسجل فيه صفحة الأعطال) ----------
    faults_total_min = 0
    faults_by_line = pd.Series(dtype=float)
    faults_sheet_dash = f"faults_monthly_{current_month_str}"
    if GSHEETS_ENABLED and gsheet_exists(faults_sheet_dash):
        faults_df = read_gsheet(faults_sheet_dash)
        day_cols_f_dash = [c for c in faults_df.columns if c.startswith("يوم")]
        if day_cols_f_dash and "الخط" in faults_df.columns:
            for dc in day_cols_f_dash:
                faults_df[dc] = pd.to_numeric(faults_df[dc], errors="coerce").fillna(0)
            faults_df["إجمالي التوقف"] = faults_df[day_cols_f_dash].sum(axis=1)
            faults_total_min = faults_df["إجمالي التوقف"].sum()
            faults_by_line = faults_df.set_index("الخط")["إجمالي التوقف"]

    # ---------- حساب OEE تقريبي (Availability × Performance × Quality) ----------
    num_lines = max(len(st.session_state.production_lines), 1)
    total_planned_minutes = num_lines * today_day_num * 24 * 60
    availability = max(0, (total_planned_minutes - faults_total_min) / total_planned_minutes) if total_planned_minutes > 0 else 1
    performance = (prod_actual / prod_target) if prod_target > 0 else 0
    performance = min(performance, 1.2)  # حد أقصى منطقي
    # ملحوظة: مؤشر الهدر اتشال من تسجيل الإنتاج، فعامل الجودة بيتحسب افتراضيًا 1 (بدون خصم هدر)
    quality = 1
    oee = max(0, min(availability * performance * quality * 100, 100))

    prod_achv_dash = (prod_actual / prod_target * 100) if prod_target > 0 else 0

    kpis = [
        {"id": "prod", "icon": "📦", "label": "إجمالي الإنتاج (KG)", "value": f"{prod_actual:,.0f}", "color": "#0d6b5c"},
        {"id": "target", "icon": "🎯", "label": "المستهدف (KG)", "value": f"{prod_target:,.0f}", "color": "#e0a92e"},
        {"id": "oee", "icon": "⚡", "label": "كفاءة OEE", "value": f"{oee:.1f}%", "color": "#2563eb"},
        {"id": "down", "icon": "⏰", "label": "إجمالي التوقف (ساعة)", "value": f"{faults_total_min/60:,.1f}", "color": "#dc2626"},
        {"id": "achv", "icon": "🥇", "label": "نسبة تحقيق الإنتاج", "value": f"{prod_achv_dash:.1f}%", "color": "#7c3aed"},
    ]

    line_names_list = list(prod_by_line.index) if not prod_by_line.empty else []
    line_target_list = [float(v) for v in prod_by_line["المستهدف (KG)"]] if not prod_by_line.empty else []
    line_actual_list = [float(v) for v in prod_by_line["الفعلي (KG)"]] if not prod_by_line.empty else []

    pack_cat_names_list = list(pack_by_cat.index) if not pack_by_cat.empty else []
    pack_cat_values_list = [float(v) for v in pack_by_cat.values] if not pack_by_cat.empty else []

    faults_names_list = list(faults_by_line.index) if not faults_by_line.empty else []
    faults_values_list = [float(v) for v in faults_by_line.values] if not faults_by_line.empty else []

    dashboard_html = build_dashboard_html(
        kpis, trend_dates, trend_actual, trend_target,
        line_names_list, line_target_list, line_actual_list,
        pack_cat_names_list, pack_cat_values_list,
        faults_names_list, faults_values_list, oee
    )
    components.html(dashboard_html, height=900, scrolling=False)

    st.caption("⚠ مؤشر OEE تقريبي مبني على افتراض تشغيل 24 ساعة لكل الخطوط، فهو للاسترشاد فقط وليس رقمًا دقيقًا معتمدًا.")

elif page == "Production":
    page_banner("🏭", "Production Management", "تسجيل الإنتاج اليومي بكل خط وشيفت — شهر كامل في جدول واحد زي الباكينج")

    PACKPROD_PASSWORD = "pack2026"
    if "packprod_unlocked" not in st.session_state:
        st.session_state.packprod_unlocked = False

    if not st.session_state.packprod_unlocked:
        st.subheader("🔒 صفحة محمية")
        st.caption("نفس الباسورد ده بيفتح صفحتي Packing وProduction مع بعض")
        pw_input = st.text_input("كلمة مرور الصفحة", type="password", key="production_page_pw")
        if st.button("دخول", key="production_page_unlock_btn"):
            if pw_input == PACKPROD_PASSWORD:
                st.session_state.packprod_unlocked = True
                st.rerun()
            else:
                st.error("كلمة المرور غلط")
        st.stop()

    if not GSHEETS_ENABLED:
        st.error(
            "⚠ البيانات دي مربوطة بجوجل شيت، ومحتاجة إعداد Secrets صح على Streamlit Cloud "
            "(gcp_service_account + gsheets sheet_id). راجع الإعداد وحاول تاني."
        )
        st.stop()

    TOTAL_SHIFT_LABEL = "الإجمالي (كل الشيفتات)"

    # ---------- اختيار الشهر (بالظبط زي صفحة الباكينج) ----------
    today_pr = datetime.now().date()
    month_options_pr = []
    for i in range(-6, 7):
        y = today_pr.year + (today_pr.month - 1 + i) // 12
        m = (today_pr.month - 1 + i) % 12 + 1
        month_options_pr.append(f"{y}-{m:02d}")
    default_index_pr = month_options_pr.index(today_pr.strftime("%Y-%m"))
    selected_month_pr = st.selectbox("📅 اختر الشهر", month_options_pr, index=default_index_pr, key="production_month_select")

    year_pr, month_num_pr = map(int, selected_month_pr.split("-"))
    days_in_month_pr = calendar.monthrange(year_pr, month_num_pr)[1]
    day_cols_pr = [f"يوم {d}" for d in range(1, days_in_month_pr + 1)]
    all_lines_clean_pr = [str(l).replace("🏭", "").strip() for l in st.session_state.production_lines]

    def _empty_production_rows(lines_for_default, p_day_cols):
        rows = []
        for l in lines_for_default:
            rows.append({
                "الخط": l, "الشيفت": TOTAL_SHIFT_LABEL,
                "التارجت اليومي (KG)": 0, **{dc: 0 for dc in p_day_cols}
            })
            for sh in SHIFTS:
                rows.append({
                    "الخط": l, "الشيفت": sh,
                    "التارجت اليومي (KG)": 0, **{dc: 0 for dc in p_day_cols}
                })
        return rows

    def load_production_month_grid(month_str, lines_for_default):
        """الجدول الشهري: كل خط وتحته شيفتاته الثلاثة، عمود تارجت يومي (بيتكتب مرة واحدة وينطبق
        على كل أيام الشهر تلقائي)، وعمود لكل يوم في الشهر للإنتاج الفعلي.
        نفس فلسفة جدول الباكينج بالظبط عشان التسجيل يبقى موحّد وسهل.
        بيرجع None في المكان الأول لو فشل الاتصال بجوجل شيت، عشان الصفحة توقف بدل ما تعرض
        جدول فاضي ممكن المستخدم يكتب فيه ويحفظه فوق بياناته الحقيقية بالغلط."""
        p_year, p_month = map(int, month_str.split("-"))
        p_days = calendar.monthrange(p_year, p_month)[1]
        p_day_cols = [f"يوم {d}" for d in range(1, p_days + 1)]
        p_cols = ["الخط", "الشيفت", "التارجت اليومي (KG)"] + p_day_cols
        p_path = f"production_monthly_{month_str}"

        grid_raw = read_gsheet_strict(p_path)
        if grid_raw is None:
            return None, p_path, p_day_cols

        if grid_raw.empty:
            grid = pd.DataFrame(_empty_production_rows(lines_for_default, p_day_cols))
        else:
            grid = grid_raw
            # توافق مع الشيتات القديمة اللي كانت باسم "المخطط الشهري (KG)" — نحولها تلقائي لتارجت يومي
            if "التارجت اليومي (KG)" not in grid.columns and "المخطط الشهري (KG)" in grid.columns:
                grid["التارجت اليومي (KG)"] = pd.to_numeric(
                    grid["المخطط الشهري (KG)"], errors="coerce"
                ).fillna(0) / p_days
            for c in p_cols:
                if c not in grid.columns:
                    if c in ["الخط", "الشيفت"]:
                        grid[c] = ""
                    else:
                        grid[c] = 0
            grid = grid[p_cols]

        # تنظيف: نشيل صفوف خطوط اتلغت من الإعدادات، ونضيف أي خط/شيفت جديد ناقص، بنفس ترتيب الخطوط الحالي
        valid_pairs = set()
        order_map = {}
        idx = 0
        for l in lines_for_default:
            valid_pairs.add((l, TOTAL_SHIFT_LABEL))
            order_map[(l, TOTAL_SHIFT_LABEL)] = idx
            idx += 1
            for sh in SHIFTS:
                valid_pairs.add((l, sh))
                order_map[(l, sh)] = idx
                idx += 1

        grid["الخط"] = grid["الخط"].astype(str).str.strip()
        grid["الشيفت"] = grid["الشيفت"].astype(str).str.strip()
        pair_mask = pd.Series(
            [(l, s) in valid_pairs for l, s in zip(grid["الخط"], grid["الشيفت"])],
            index=grid.index, dtype=bool
        )
        grid = grid[pair_mask].reset_index(drop=True)

        existing_pairs = set(zip(grid["الخط"], grid["الشيفت"]))
        missing_rows = [
            {"الخط": l, "الشيفت": sh, "التارجت اليومي (KG)": 0, **{dc: 0 for dc in p_day_cols}}
            for l in lines_for_default
            for sh in [TOTAL_SHIFT_LABEL] + SHIFTS
            if (l, sh) not in existing_pairs
        ]
        if missing_rows:
            grid = pd.concat([grid, pd.DataFrame(missing_rows)], ignore_index=True)

        grid["__order"] = [order_map.get((l, s), 9999) for l, s in zip(grid["الخط"], grid["الشيفت"])]
        grid = grid.sort_values("__order").drop(columns="__order").reset_index(drop=True)

        # تثبيت الأنواع عشان القيم ما تتزحلقش من قراءة لتانية
        grid["التارجت اليومي (KG)"] = pd.to_numeric(grid["التارجت اليومي (KG)"], errors="coerce").fillna(0)
        for dc in p_day_cols:
            grid[dc] = pd.to_numeric(grid[dc], errors="coerce").fillna(0)

        return grid, p_path, p_day_cols

    month_grid_pr, PRODUCTION_MONTH_SHEET, day_cols_pr = load_production_month_grid(selected_month_pr, all_lines_clean_pr)

    if month_grid_pr is None:
        st.error(
            "⚠️ تعذّر الاتصال بجوجل شيت دلوقتي (زحمة مؤقتة على الـ API). "
            "بياناتك القديمة المحفوظة **آمنة ومتأثرتش**، بس معرفناش نجيبها عشان نعرضها في الجدول. "
            "**متكتبش أي بيانات دلوقتي** — استنى كام ثانية واعمل تحديث للصفحة (F5) وجرب تاني."
        )
        st.stop()

    st.caption(
        "📌 اكتب 'التارجت اليومي' مرة واحدة لكل خط، وهو هينطبق تلقائي على كل أيام الشهر (زيه زي عمود المخطط في الباكينج). "
        "بعدين سجّل الفعلي كل يوم في عموده تحت كل خط وشيفته — البيانات بتتحفظ ومتتمسحش، وتقدر تعدّل فيها في أي وقت وتحفظ تاني. "
        "عمود 'الخط' والشيفتات تحته ثابت (Pinned) وبيفضل ظاهر وانت بتسكرول على أيام الشهر. "
        "لو الثبات ما ظهرش تلقائي عندك، تقدر تثبّته يدوي من زرار القائمة (⋮) اللي بيظهر فوق عمود 'الخط' واختار Pin column."
    )

    # ---------- إخفاء أعمدة أيام معينة من العرض (بدل إخفاء الصفوف) ----------
    hide_cols_key_pr = f"production_hidden_day_cols_{selected_month_pr}"
    if hide_cols_key_pr not in st.session_state:
        st.session_state[hide_cols_key_pr] = []

    col_hide_a_pr, col_hide_b_pr = st.columns([3, 1])
    with col_hide_a_pr:
        hidden_day_cols_pr = st.multiselect(
            "🙈 إخفاء أعمدة أيام من العرض (البيانات فيها متتمسحش، بس مش هتظهر في الجدول دلوقتي)",
            options=day_cols_pr,
            key=hide_cols_key_pr,
        )
    with col_hide_b_pr:
        st.write("")
        if st.button("إخفاء الأيام اللي فاتت", key="production_hide_past_days_btn"):
            if (year_pr, month_num_pr) < (today_pr.year, today_pr.month):
                past_days_pr = list(day_cols_pr)
            elif (year_pr, month_num_pr) == (today_pr.year, today_pr.month):
                past_days_pr = [f"يوم {d}" for d in range(1, today_pr.day)]
            else:
                past_days_pr = []
            st.session_state[hide_cols_key_pr] = past_days_pr
            st.rerun()

    visible_day_cols_pr = [dc for dc in day_cols_pr if dc not in hidden_day_cols_pr]
    display_cols_pr = ["الخط", "الشيفت", "التارجت اليومي (KG)"] + visible_day_cols_pr

    edited_display_pr = st.data_editor(
        month_grid_pr[display_cols_pr],
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key=f"production_monthly_editor_{selected_month_pr}",
        disabled=["الخط", "الشيفت"],
        column_config={
            "الخط": st.column_config.TextColumn("🏭 الخط", pinned=True, width="medium"),
            "الشيفت": st.column_config.TextColumn("👷 الشيفت", pinned=True, width="medium"),
            "التارجت اليومي (KG)": st.column_config.NumberColumn(
                "🎯 التارجت اليومي (KG)", format="%.0f", step=1, min_value=0,
                help="اكتبه مرة واحدة لكل خط — بيتطبق تلقائي على كل أيام الشهر"
            ),
            **{dc: st.column_config.NumberColumn(dc, format="%.0f", step=1, min_value=0) for dc in visible_day_cols_pr},
        }
    )

    # نرجّع الأعمدة المعدّلة (اللي كانت ظاهرة بس) لمكانها في الجدول الكامل
    for c in display_cols_pr:
        if c not in ["الخط", "الشيفت"]:
            month_grid_pr[c] = edited_display_pr[c]

    st.divider()

    # ---------- حساب النسب زي الباكينج بالظبط: نسبة للتحقيق بالنسبة لعدد أيام الخطة اللي عدت ----------
    if (year_pr, month_num_pr) < (today_pr.year, today_pr.month):
        days_elapsed_pr = days_in_month_pr
    elif (year_pr, month_num_pr) == (today_pr.year, today_pr.month):
        days_elapsed_pr = today_pr.day
    else:
        days_elapsed_pr = 0

    lines_only_pr = month_grid_pr[month_grid_pr["الشيفت"] == TOTAL_SHIFT_LABEL].copy()
    elapsed_day_cols_pr = [f"يوم {d}" for d in range(1, days_elapsed_pr + 1)]
    actual_working_days_pr = sum(1 for dc in elapsed_day_cols_pr if lines_only_pr[dc].sum() > 0) if elapsed_day_cols_pr else 0
    day_ratio_pr = (actual_working_days_pr / days_in_month_pr) if days_in_month_pr else 0

    total_daily_target_pr = lines_only_pr["التارجت اليومي (KG)"].sum()
    total_target_pr = total_daily_target_pr * days_in_month_pr
    total_actual_pr = lines_only_pr[day_cols_pr].sum(axis=1).sum() if day_cols_pr else 0
    total_expected_pr = total_target_pr * day_ratio_pr
    achievement_pr = (total_actual_pr / total_expected_pr * 100) if total_expected_pr > 0 else 0
    full_plan_pct_pr = (total_actual_pr / total_target_pr * 100) if total_target_pr > 0 else 0

    kpi_row([
        {"icon": "🎯", "label": "إجمالي التارجت اليومي", "value": f"{total_daily_target_pr:,.0f} KG", "color": "#e0a92e"},
        {"icon": "📅", "label": "المخطط الكامل للشهر", "value": f"{total_target_pr:,.0f} KG", "color": "#a06f0f"},
        {"icon": "📦", "label": "الفعلي حتى الآن", "value": f"{total_actual_pr:,.0f} KG", "color": "#0d6b5c"},
        {"icon": "⏳", "label": "المتوقع حتى الآن", "value": f"{total_expected_pr:,.0f} KG", "color": "#4c8c7d"},
        {"icon": "🥇", "label": "نسبة التحقيق (بالنسبة لعدد الأيام)", "value": f"{achievement_pr:.1f}%", "color": "#7c3aed"},
        {"icon": "📈", "label": "نسبة إنجاز الخطة الكاملة", "value": f"{full_plan_pct_pr:.1f}%", "color": "#2563eb"},
    ])

    # ---------- تجميع الإنتاج لكل خط ----------
    st.divider()
    st.markdown("#### 📊 إجمالي الإنتاج لكل خط هذا الشهر")

    line_summary_pr = lines_only_pr[["الخط", "التارجت اليومي (KG)"]].copy().reset_index(drop=True)
    line_summary_pr["المستهدف (KG)"] = (line_summary_pr["التارجت اليومي (KG)"] * days_in_month_pr)
    line_summary_pr["المتوقع حتى الآن (KG)"] = (line_summary_pr["المستهدف (KG)"] * day_ratio_pr)
    line_summary_pr["الفعلي (KG)"] = lines_only_pr[day_cols_pr].sum(axis=1).values if day_cols_pr else 0
    line_summary_pr["نسبة التحقيق %"] = line_summary_pr.apply(
        lambda r: round((r["الفعلي (KG)"] / r["المتوقع حتى الآن (KG)"] * 100), 1)
        if r["المتوقع حتى الآن (KG)"] > 0 else 0,
        axis=1
    )

    if line_summary_pr["المستهدف (KG)"].sum() == 0 and line_summary_pr["الفعلي (KG)"].sum() == 0:
        st.info("سجّل قيم فعلي/مخطط في الجدول فوق عشان يظهر تجميع الإنتاج لكل خط والرسم البياني")
    else:
        st.dataframe(line_summary_pr, use_container_width=True, hide_index=True)

        fig_lines = build_line_production_chart(line_summary_pr)
        if fig_lines is not None:
            st.pyplot(fig_lines)

        st.markdown("###### 🏭 توزيع الإنتاج الفعلي بين الخطوط")
        line_actual_series_pr = line_summary_pr.set_index("الخط")["الفعلي (KG)"]
        fig_prod_tree = build_treemap_chart(line_actual_series_pr, unit=" KG")
        if fig_prod_tree is not None:
            st.pyplot(fig_prod_tree)

    st.divider()

    if st.button("💾 حفظ بيانات الشهر", key="production_save_month_btn"):
        to_save_pr = month_grid_pr.copy()

        try:
            write_gsheet(PRODUCTION_MONTH_SHEET, to_save_pr)
        except Exception as e:
            st.error(
                f"❌ فشل حفظ جدول الشهر — الاتصال بجوجل شيت اتقطع أو الكوتة خلصت مؤقتًا. "
                f"البيانات اللي كتبتها لسه في الجدول فوق، ماتعملش Refresh للصفحة، وجرب تضغط 'حفظ' تاني بعد كام ثانية. "
                f"(تفاصيل: {e})"
            )
            st.stop()

        # ---------- نزامن نفس البيانات جوه شيت السجل الطويل (PRODUCTION_SHEET) ----------
        # عشان الداشبورد وتقرير الباكينج والتقرير الشهري وصفحة الكسر يفضلوا شغالين بنفس الشكل
        # من غير ما نلمسهم، بننسخ "التارجت اليومي" اللي اتكتب مرة واحدة على كل أيام الشهر
        saved_at_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        long_cols = ["Date", "Saved At", "Line", "Shift", "المستهدف (KG)", "الفعلي (KG)"]
        long_rows = []
        for _, r in to_save_pr.iterrows():
            line_name = str(r["الخط"]).strip()
            shift_name = "All Shifts" if r["الشيفت"] == TOTAL_SHIFT_LABEL else str(r["الشيفت"])
            daily_target = float(r["التارجت اليومي (KG)"]) if pd.notna(r["التارجت اليومي (KG)"]) else 0.0

            for day_num, dc in enumerate(day_cols_pr, start=1):
                actual_val = float(r[dc]) if pd.notna(r[dc]) else 0.0
                if daily_target == 0 and actual_val == 0:
                    continue
                long_rows.append({
                    "Date": f"{selected_month_pr}-{day_num:02d}",
                    "Saved At": saved_at_str,
                    "Line": line_name,
                    "Shift": shift_name,
                    "المستهدف (KG)": round(daily_target, 3),
                    "الفعلي (KG)": actual_val,
                })

        # بنستخدم القراءة "الصارمة" هنا عشان لو الاتصال فشل، البرنامج يوقف فوراً
        # بدل ما يفتكر إن الشيت فاضي ويكتب فوق بيانات شهور تانية بالغلط
        existing_long_pr = read_gsheet_strict(PRODUCTION_SHEET)
        if existing_long_pr is None:
            st.error(
                "⚠️ جدول الشهر اتحفظ ✔، لكن فشلنا نقرأ السجل التاريخي من جوجل شيت (زحمة مؤقتة على الـ API)، "
                "فوقفنا هنا عمداً عشان منمسحش بيانات شهور تانية بالغلط. "
                "اضغط 'حفظ بيانات الشهر' تاني بعد كام ثانية عشان تكمل مزامنة الداشبورد والتقارير."
            )
            st.stop()

        if not existing_long_pr.empty and "Date" in existing_long_pr.columns:
            existing_long_pr["Date"] = existing_long_pr["Date"].astype(str)
            other_months_long_pr = existing_long_pr[~existing_long_pr["Date"].str.startswith(selected_month_pr)]
        elif not existing_long_pr.empty:
            # فيه بيانات في الشيت بس شكلها مش المتوقع (عمود Date مش لاقيه) — بنوقف بدل
            # ما نفتكر إنه فاضي ونمسح بيانات موجودة فعلاً بالغلط
            st.error(
                "⚠️ جدول الشهر اتحفظ ✔، لكن السجل التاريخي (اللي بيغذي الداشبورد) شكله مش طبيعي "
                "(عمود 'Date' مش موجود فيه)، فوقفنا هنا عمداً عشان منمسحش بيانات موجودة بالغلط. "
                "من فضلك ابعتلي اسم شيت 'PRODUCTION_SHEET' كامل زي ما هو في جوجل شيت عشان أشوف المشكلة."
            )
            st.stop()
        else:
            other_months_long_pr = pd.DataFrame(columns=long_cols)

        new_long_pr = pd.DataFrame(long_rows, columns=long_cols)
        merged_long_pr = pd.concat([other_months_long_pr, new_long_pr], ignore_index=True)

        # ---------- شبكة أمان أخيرة: البيانات النهائية لازم متكونش أقل من بيانات الشهور التانية
        # اللي كانت موجودة فعلاً — لو حصل كده يبقى فيه حاجة غلط، نوقف بدل ما نكتب ونمسح بيانات ----------
        if len(merged_long_pr) < len(other_months_long_pr):
            st.error(
                "⚠️ البرنامج لاحظ إن عدد صفوف البيانات هيقل عن المتوقع بعد الحفظ، فوقف الحفظ تحسباً "
                "عشان منمسحش بيانات موجودة. البيانات الحالية في الجدول ماتأثرتش، جرب تحفظ تاني أو كلم الدعم الفني."
            )
            st.stop()

        try:
            write_gsheet(PRODUCTION_SHEET, merged_long_pr)
        except Exception as e:
            st.error(
                f"❌ جدول الشهر اتحفظ ✔، لكن فشلت مزامنة السجل التاريخي (اللي بيغذي الداشبورد والتقارير). "
                f"جرب تضغط 'حفظ' تاني. (تفاصيل: {e})"
            )
            st.stop()

        st.success(f"اتحفظت بيانات إنتاج شهر {selected_month_pr} ✔ (تقدر تعدّل فيها في أي وقت وتحفظ تاني من غير أي تكرار)")
        st.rerun()

    # ================= سجل الإنتاج اليومي + إجمالي الشهر المختار حتى الآن =================
    st.divider()
    st.markdown("### 📅 سجل الإنتاج اليومي وإجمالي الشهر حتى الآن")

    current_month_str_p = selected_month_pr

    if not GSHEETS_ENABLED or not gsheet_exists(PRODUCTION_SHEET):
        st.info("لسه مفيش بيانات إنتاج محفوظة عشان نعرض السجل اليومي وإجمالي الشهر")
    else:
        hist_df_p = read_gsheet(PRODUCTION_SHEET)
        hist_df_p["Date"] = hist_df_p["Date"].astype(str)
        all_shifts_p = hist_df_p[hist_df_p["Shift"] == "All Shifts"].copy()
        all_shifts_p["Line"] = all_shifts_p["Line"].astype(str).str.strip()
        all_shifts_p = all_shifts_p[all_shifts_p["Line"] != ""]
        for nc in ["المستهدف (KG)", "الفعلي (KG)"]:
            all_shifts_p[nc] = pd.to_numeric(all_shifts_p[nc], errors="coerce").fillna(0)

        month_data_p = all_shifts_p[all_shifts_p["Date"].str.startswith(current_month_str_p)]

        if month_data_p.empty:
            st.info("لسه مفيش بيانات إنتاج محفوظة لشهر ده عشان نعرض السجل اليومي وإجمالي الشهر")
        else:
            # ---------- جدول + رسم الإنتاج اليومي (Date × Line) ----------
            daily_pivot = month_data_p.pivot_table(
                index="Date", columns="Line", values="الفعلي (KG)", aggfunc="sum", fill_value=0
            )
            daily_pivot = daily_pivot.reindex(columns=all_lines_clean_pr, fill_value=0)
            daily_pivot = daily_pivot.sort_index()
            daily_pivot["الإجمالي"] = daily_pivot.sum(axis=1)

            dates_list = list(daily_pivot.index)
            series_by_line = {ln: [float(v) for v in daily_pivot[ln]] for ln in all_lines_clean_pr}

            table_header_html = "<tr><th>التاريخ</th>" + "".join(f"<th>{ln}</th>" for ln in all_lines_clean_pr) + "<th>الإجمالي</th></tr>"
            table_rows_html = ""
            for d in dates_list:
                row = daily_pivot.loc[d]
                cells = "".join(f"<td>{row[ln]:,.0f}</td>" for ln in all_lines_clean_pr)
                table_rows_html += f"<tr><td style='font-weight:800;'>{d}</td>{cells}<td style='font-weight:900;'>{row['الإجمالي']:,.0f}</td></tr>"
            grand_total_row = daily_pivot[all_lines_clean_pr].sum()
            total_cells = "".join(f"<td>{grand_total_row[ln]:,.0f}</td>" for ln in all_lines_clean_pr)
            table_rows_html += f"<tr class='total-row'><td>الإجمالي</td>{total_cells}<td>{daily_pivot['الإجمالي'].sum():,.0f}</td></tr>"

            daily_html = build_daily_trend_html(dates_list, series_by_line, table_rows_html, table_header_html)
            components.html(daily_html, height=900, scrolling=False)

            # ---------- إجمالي الإنتاج من بداية الشهر حتى الآن (تجميعي لكل خط) ----------
            st.markdown("### 📊 إجمالي الإنتاج من بداية الشهر حتى الآن")
            month_by_line = month_data_p.groupby("Line")[["المستهدف (KG)", "الفعلي (KG)"]].sum()
            month_by_line = month_by_line.reindex(all_lines_clean_pr, fill_value=0)

            m_target_total = month_by_line["المستهدف (KG)"].sum()
            m_actual_total = month_by_line["الفعلي (KG)"].sum()
            m_achv = (m_actual_total / m_target_total * 100) if m_target_total > 0 else 0

            month_kpis = [
                {"icon": "🎯", "label": "مستهدف الشهر", "value": f"{m_target_total:,.0f} KG", "color": "#e0a92e"},
                {"icon": "📦", "label": "فعلي الشهر", "value": f"{m_actual_total:,.0f} KG", "color": "#0d6b5c"},
                {"icon": "🥇", "label": "نسبة تحقيق الشهر", "value": f"{m_achv:.1f}%", "color": "#7c3aed"},
            ]
            month_line_names = list(month_by_line.index)
            month_target_vals = [float(v) for v in month_by_line["المستهدف (KG)"]]
            month_actual_vals = [float(v) for v in month_by_line["الفعلي (KG)"]]

            month_html = build_line_summary_html(
                month_kpis, month_line_names, month_target_vals, month_actual_vals,
                chart_title="مقارنة الفعلي بالمستهدف لكل خط — من بداية الشهر"
            )
            components.html(month_html, height=900, scrolling=False)

            # ---------- نصيب كل شيفت من إنتاج كل خط (لنفس الشهر المختار) ----------
            st.markdown("### 👷 نصيب كل شيفت من إنتاج كل خط")

            shifts_only_p = hist_df_p[hist_df_p["Shift"] != "All Shifts"].copy()
            shifts_only_p["Date"] = shifts_only_p["Date"].astype(str)
            shifts_only_p["Line"] = shifts_only_p["Line"].astype(str).str.strip()
            shifts_only_p = shifts_only_p[shifts_only_p["Line"] != ""]
            shifts_only_p["الفعلي (KG)"] = pd.to_numeric(shifts_only_p["الفعلي (KG)"], errors="coerce").fillna(0)
            shifts_month_p = shifts_only_p[shifts_only_p["Date"].str.startswith(current_month_str_p)]

            if shifts_month_p.empty:
                st.info("لسه مفيش بيانات إنتاج مسجلة بالشيفت (مش 'All Shifts') عشان نعرض نصيب كل شيفت")
            else:
                shift_pivot = shifts_month_p.groupby(["Line", "Shift"])["الفعلي (KG)"].sum()
                shift_matrix = {}
                for ln in all_lines_clean_pr:
                    shift_matrix[ln] = {}
                    for sh in SHIFTS:
                        shift_matrix[ln][sh] = float(shift_pivot.get((ln, sh), 0))

                shift_share_html = build_shift_share_html(all_lines_clean_pr, SHIFTS, shift_matrix)
                components.html(shift_share_html, height=900, scrolling=False)

elif page == "Packing":
    page_banner("📦", "Packing", "تسجيل ومتابعة تعبئة الأصناف بالشيفت والفئة")

    PACKPROD_PASSWORD = "pack2026"
    if "packprod_unlocked" not in st.session_state:
        st.session_state.packprod_unlocked = False

    if not st.session_state.packprod_unlocked:
        st.subheader("🔒 صفحة محمية")
        st.caption("نفس الباسورد ده بيفتح صفحتي Packing وProduction مع بعض")
        pw_input = st.text_input("كلمة مرور الصفحة", type="password", key="packing_page_pw")
        if st.button("دخول", key="packing_page_unlock_btn"):
            if pw_input == PACKPROD_PASSWORD:
                st.session_state.packprod_unlocked = True
                st.rerun()
            else:
                st.error("كلمة المرور غلط")
        st.stop()

    if not GSHEETS_ENABLED:
        st.error(
            "⚠ البيانات دي مربوطة بجوجل شيت، ومحتاجة إعداد Secrets صح على Streamlit Cloud "
            "(gcp_service_account + gsheets sheet_id). راجع الإعداد وحاول تاني."
        )
        st.stop()

    today = datetime.now().date()
    month_options = []
    for i in range(-6, 7):
        y = today.year + (today.month - 1 + i) // 12
        m = (today.month - 1 + i) % 12 + 1
        month_options.append(f"{y}-{m:02d}")
    default_index = month_options.index(today.strftime("%Y-%m"))
    selected_month = st.selectbox("📅 اختر الشهر", month_options, index=default_index, key="packing_month_select")

    year, month_num = map(int, selected_month.split("-"))
    days_in_month = calendar.monthrange(year, month_num)[1]
    day_cols = [f"يوم {d}" for d in range(1, days_in_month + 1)]

    PACKING_SHEET = f"packing_monthly_{selected_month}"
    base_cols = ["الصنف", "الفئة", "وزن الكرتونة (كيلو)", "المخطط بالكراتين (شهري)"] + day_cols

    if gsheet_exists(PACKING_SHEET):
        month_grid = read_gsheet(PACKING_SHEET)
        for c in base_cols:
            if c not in month_grid.columns:
                month_grid[c] = "" if c in ["الصنف", "الفئة"] else 0
        month_grid = month_grid[base_cols]
    else:
        month_grid = pd.DataFrame([{
            "الصنف": "",
            "الفئة": "",
            "وزن الكرتونة (كيلو)": 0.0,
            "المخطط بالكراتين (شهري)": 0,
            **{dc: 0 for dc in day_cols}
        }])

    # نثبت نوع كل عمود رقمي عشان مايتغيرش من قراءة لتانية (وده كان بيسبب تقريب الوزن العشري غلط)
    month_grid["الصنف"] = (
        month_grid["الصنف"].astype(str)
        .str.replace(r"\\n", " ", regex=True)
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    # لو الفئة فاضية (صف جديد أو ملف قديم من قبل ما العمود يتضاف)، بنقترحها تلقائي بس تفضل قابلة للتعديل بعد كده
    def _suggest_category(row):
        existing = str(row["الفئة"]).strip()
        if existing and existing.lower() != "nan":
            return existing
        auto = categorize_product(row["الصنف"])
        return "فورية" if auto == "أخرى" else auto

    month_grid["الفئة"] = month_grid.apply(_suggest_category, axis=1)
    month_grid["وزن الكرتونة (كيلو)"] = pd.to_numeric(month_grid["وزن الكرتونة (كيلو)"], errors="coerce").fillna(0.0).astype(float)
    month_grid["المخطط بالكراتين (شهري)"] = pd.to_numeric(month_grid["المخطط بالكراتين (شهري)"], errors="coerce").fillna(0).astype(int)
    for dc in day_cols:
        month_grid[dc] = pd.to_numeric(month_grid[dc], errors="coerce").fillna(0).astype(int)

    st.caption("سجل تعبئة كل يوم في عموده — البيانات بتتحفظ تلقائي ومش بتتمسح. تقدر تضيف صنف جديد في آخر الجدول من (+)")

    with st.expander("➕ إضافة صنف في مكان معين جوه الجدول (مش في الآخر بس)"):
        ins_c1, ins_c2, ins_c3 = st.columns([2, 2, 1])
        with ins_c1:
            insert_name = st.text_input("اسم الصنف الجديد", key="packing_insert_name")
        with ins_c2:
            position_options = ["في الأول"] + [f"بعد: {n}" for n in month_grid["الصنف"].tolist()]
            insert_position = st.selectbox("المكان", position_options, key="packing_insert_position")
        with ins_c3:
            st.write("")
            st.write("")
            insert_clicked = st.button("➕ إضافة", key="packing_insert_btn")

        if insert_clicked:
            clean_name = insert_name.strip()
            if not clean_name:
                st.warning("اكتب اسم الصنف الأول ⚠")
            elif clean_name in month_grid["الصنف"].values:
                st.warning("الصنف ده موجود بالفعل ⚠")
            else:
                auto_cat = categorize_product(clean_name)
                auto_cat = "فورية" if auto_cat == "أخرى" else auto_cat
                new_row = {"الصنف": clean_name, "الفئة": auto_cat, "وزن الكرتونة (كيلو)": 0.0,
                           "المخطط بالكراتين (شهري)": 0, **{dc: 0 for dc in day_cols}}
                if insert_position == "في الأول":
                    insert_idx = 0
                else:
                    after_name = insert_position.replace("بعد: ", "")
                    insert_idx = month_grid[month_grid["الصنف"] == after_name].index[0] + 1

                top = month_grid.iloc[:insert_idx]
                bottom = month_grid.iloc[insert_idx:]
                month_grid = pd.concat([top, pd.DataFrame([new_row]), bottom], ignore_index=True)
                write_gsheet(PACKING_SHEET, month_grid)
                st.session_state.pop(f"packing_monthly_editor_{selected_month}", None)
                st.success(f"اتضاف صنف '{clean_name}' في المكان المطلوب ✔")
                st.rerun()

    edited_grid = st.data_editor(
        month_grid,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"packing_monthly_editor_{selected_month}",
        column_config={
            "الفئة": st.column_config.SelectboxColumn(
                "الفئة", options=["هارد كاندي", "طوفي", "اكلير", "فورية"]
            ),
            "وزن الكرتونة (كيلو)": st.column_config.NumberColumn(
                "وزن الكرتونة (كيلو)", format="%.2f", step=0.01, min_value=0.0
            ),
            "المخطط بالكراتين (شهري)": st.column_config.NumberColumn(
                "المخطط بالكراتين (شهري)", format="%d", step=1, min_value=0
            ),
        }
    )

    if st.button("💾 حفظ بيانات الشهر"):
        to_save = edited_grid.copy()
        to_save = to_save[to_save["الصنف"].astype(str).str.strip() != ""]
        if to_save.empty:
            st.warning("اكتب اسم صنف واحد على الأقل قبل الحفظ ⚠")
        else:
            write_gsheet(PACKING_SHEET, to_save)
            st.success(f"اتحفظت بيانات شهر {selected_month} ✔")

    # ==========================
    # تسجيل تعبئة حسب الشيفت — سجل تفصيلي منفصل، وبيتجمّع تلقائي في عمود اليوم بالجدول الشهري
    # ==========================
    st.divider()
    st.markdown("#### 👷 تسجيل تعبئة حسب الشيفت")
    st.caption(
        "بدل ما تسجل تعبئة اليوم كله مرة واحدة، تقدر تسجل كل شيفت لوحده هنا. "
        "إجمالي الشيفتات بيتجمّع تلقائي في عمود اليوم بالجدول الشهري فوق."
    )

    SHIFT_LOG_SHEET = "packing_shift_log"
    SHIFT_OPTIONS_P = ["الوردية الأولى", "الوردية الثانية", "الوردية الثالثة"]

    def load_shift_log():
        cols = ["التاريخ", "الشيفت", "الصنف", "الكمية (كرتونة)"]
        if gsheet_exists(SHIFT_LOG_SHEET):
            log_df = read_gsheet(SHIFT_LOG_SHEET)
            for c in cols:
                if c not in log_df.columns:
                    log_df[c] = 0 if c == "الكمية (كرتونة)" else ""
            log_df = log_df[cols]
            log_df["الكمية (كرتونة)"] = pd.to_numeric(log_df["الكمية (كرتونة)"], errors="coerce").fillna(0)
        else:
            log_df = pd.DataFrame(columns=cols)
        return log_df

    sc1, sc2 = st.columns(2)
    with sc1:
        month_start_date = datetime(year, month_num, 1).date()
        month_end_date = datetime(year, month_num, days_in_month).date()
        default_shift_date = today if month_start_date <= today <= month_end_date else month_start_date
        shift_log_date = st.date_input(
            "📅 التاريخ", value=default_shift_date,
            min_value=month_start_date, max_value=month_end_date,
            key="packing_shift_log_date"
        )
    with sc2:
        shift_log_pick = st.selectbox("👷 الشيفت", SHIFT_OPTIONS_P, key="packing_shift_log_pick")

    shift_log_date_str = shift_log_date.strftime("%Y-%m-%d")
    shift_log_all = load_shift_log()
    existing_shift = shift_log_all[
        (shift_log_all["التاريخ"] == shift_log_date_str) & (shift_log_all["الشيفت"] == shift_log_pick)
    ]
    existing_qty_map = dict(zip(existing_shift["الصنف"], existing_shift["الكمية (كرتونة)"]))

    item_list_for_shift = edited_grid[edited_grid["الصنف"].astype(str).str.strip() != ""]["الصنف"].tolist()
    shift_entry_df = pd.DataFrame({
        "الصنف": item_list_for_shift,
        "الكمية (كرتونة)": [existing_qty_map.get(item, 0) for item in item_list_for_shift]
    })

    edited_shift_entry = st.data_editor(
        shift_entry_df,
        use_container_width=True,
        hide_index=True,
        disabled=["الصنف"],
        key=f"packing_shift_editor_{shift_log_date_str}_{shift_log_pick}"
    )

    if st.button(f"💾 حفظ تعبئة {shift_log_pick} — {shift_log_date_str}"):
        shift_log_all = shift_log_all[
            ~((shift_log_all["التاريخ"] == shift_log_date_str) & (shift_log_all["الشيفت"] == shift_log_pick))
        ]
        new_rows = edited_shift_entry[edited_shift_entry["الكمية (كرتونة)"] > 0].copy()
        new_rows["التاريخ"] = shift_log_date_str
        new_rows["الشيفت"] = shift_log_pick
        new_rows = new_rows[["التاريخ", "الشيفت", "الصنف", "الكمية (كرتونة)"]]
        shift_log_all = pd.concat([shift_log_all, new_rows], ignore_index=True)
        write_gsheet(SHIFT_LOG_SHEET, shift_log_all)

        # مزامنة عمود اليوم في الجدول الشهري = إجمالي كل الشيفتات المسجلة لنفس اليوم لكل صنف
        sync_grid = month_grid.copy()
        day_col_sync = f"يوم {shift_log_date.day}"
        day_totals = shift_log_all[shift_log_all["التاريخ"] == shift_log_date_str].groupby("الصنف")["الكمية (كرتونة)"].sum()
        for item, total in day_totals.items():
            if item in sync_grid["الصنف"].values and day_col_sync in sync_grid.columns:
                idx = sync_grid[sync_grid["الصنف"] == item].index[0]
                sync_grid.at[idx, day_col_sync] = total
        write_gsheet(PACKING_SHEET, sync_grid)

        st.success(f"اتحفظت تعبئة {shift_log_pick} ليوم {shift_log_date_str} ✔ (اتزامن عمود اليوم تلقائي)")
        st.rerun()

    # ---------- تقرير: تعبئة الشيفتات + إنتاج الخطوط لنفس اليوم ----------
    with st.expander("📊 تقرير تعبئة الشيفتات + إنتاج الخطوط لنفس اليوم"):
        report_shift_date = st.date_input("📅 اختر اليوم", value=shift_log_date, key="packing_shift_report_date")
        report_shift_date_str = report_shift_date.strftime("%Y-%m-%d")

        day_shift_log = shift_log_all[shift_log_all["التاريخ"] == report_shift_date_str]
        if day_shift_log.empty:
            st.info("مفيش أي تعبئة مسجلة بالشيفت لليوم ده لسه")
        else:
            weight_map = edited_grid.set_index("الصنف")["وزن الكرتونة (كيلو)"].to_dict()

            grand_total_cartons = 0.0
            grand_total_kg = 0.0
            shift_pack_tables = {}  # جدول تعبئة منفصل لكل شيفت (للعرض والطباعة)

            st.markdown(f"##### 📦 تعبئة كل شيفت — {report_shift_date_str}")
            for sh in SHIFT_OPTIONS_P:
                sh_data = day_shift_log[day_shift_log["الشيفت"] == sh][["الصنف", "الكمية (كرتونة)"]].copy()
                sh_data = sh_data[sh_data["الكمية (كرتونة)"] > 0].reset_index(drop=True)

                st.markdown(f"**👷 {sh}**")
                if sh_data.empty:
                    st.caption("مفيش تعبئة مسجلة في الشيفت ده")
                    shift_pack_tables[sh] = pd.DataFrame(columns=["الصنف", "الكمية (كرتونة)", "الوزن (كيلو)"])
                    continue

                sh_data["الوزن (كيلو)"] = sh_data.apply(
                    lambda r: r["الكمية (كرتونة)"] * weight_map.get(r["الصنف"], 0), axis=1
                ).round(1)

                shift_total_cartons = sh_data["الكمية (كرتونة)"].sum()
                shift_total_kg = sh_data["الوزن (كيلو)"].sum()
                grand_total_cartons += shift_total_cartons
                grand_total_kg += shift_total_kg

                total_row = pd.DataFrame([{
                    "الصنف": "الإجمالي",
                    "الكمية (كرتونة)": shift_total_cartons,
                    "الوزن (كيلو)": round(shift_total_kg, 1)
                }])
                sh_display = pd.concat([sh_data, total_row], ignore_index=True)
                shift_pack_tables[sh] = sh_display
                st.dataframe(sh_display, use_container_width=True, hide_index=True)

            gc1, gc2 = st.columns(2)
            gc1.metric("📦 إجمالي كل الشيفتات (كرتونة)", f"{grand_total_cartons:,.0f}")
            gc2.metric("⚖️ إجمالي كل الشيفتات (كيلو)", f"{grand_total_kg:,.1f}")

            # ---------- إنتاج الخطوط لكل شيفت لنفس اليوم (من صفحة Production) — جدول منفصل لكل شيفت بكل الخطوط ----------
            st.markdown(f"##### 🏭 إنتاج خطوط الإنتاج لكل شيفت — {report_shift_date_str}")

            all_lines_clean = [
                str(l).replace("🏭", "").strip() for l in st.session_state.production_lines
            ]
            shift_prod_tables = {}  # جدول إنتاج منفصل لكل شيفت، فيه كل الخطوط (بدون صف إجمالي - للحسابات)
            shift_prod_display_tables = {}  # نفس الجدول بس فيه صف إجمالي تحت الخطوط (للعرض والطباعة)
            day_shift_prod = pd.DataFrame()

            if GSHEETS_ENABLED and gsheet_exists(PRODUCTION_SHEET):
                hist_df_shift = read_gsheet(PRODUCTION_SHEET)
                if "Date" not in hist_df_shift.columns or hist_df_shift.empty:
                    st.warning(
                        "⚠ الشيت فيه بيانات فعلاً، بس القراءة فشلت مؤقتًا (غالبًا ضغط على الـ API). "
                        "دوس الزرار وجرب تاني."
                    )
                    if st.button("🔄 حاول تاني", key="retry_prod_shift_read"):
                        _read_gsheet_cached.clear()
                        st.rerun()
                else:
                    hist_df_shift["Date"] = hist_df_shift["Date"].astype(str)
                    day_shift_prod = hist_df_shift[
                        (hist_df_shift["Date"] == report_shift_date_str) & (hist_df_shift["Shift"] != "All Shifts")
                    ].copy()
                    if not day_shift_prod.empty:
                        for nc in ["المستهدف (KG)", "الفعلي (KG)"]:
                            day_shift_prod[nc] = pd.to_numeric(day_shift_prod[nc], errors="coerce").fillna(0)
                        # اسم الخط ممكن يوصل فاضي لو جاي من بيانات قديمة، فبنستبعد الصفوف اللي مالهاش اسم خط واضح
                        day_shift_prod["Line"] = day_shift_prod["Line"].astype(str).str.strip()
                        day_shift_prod = day_shift_prod[day_shift_prod["Line"] != ""]
            else:
                st.info("مفيش بيانات إنتاج متاحة (تأكد من تسجيل الإنتاج بالشيفت في صفحة Production)")

            for pack_sh, prod_sh in zip(SHIFT_OPTIONS_P, SHIFTS):
                if not day_shift_prod.empty:
                    sh_prod = day_shift_prod[day_shift_prod["Shift"] == prod_sh]
                    sh_prod_grouped = sh_prod.groupby("Line")[["المستهدف (KG)", "الفعلي (KG)"]].sum()
                else:
                    sh_prod_grouped = pd.DataFrame(columns=["المستهدف (KG)", "الفعلي (KG)"])
                # بنعرض كل الخطوط المعرّفة دايمًا، حتى لو مالهاش بيانات مسجلة في الشيفت ده (تبقى صفر)
                sh_prod_full = sh_prod_grouped.reindex(all_lines_clean, fill_value=0).reset_index()
                sh_prod_full.columns = ["الخط", "المستهدف (KG)", "الفعلي (KG)"]
                sh_prod_full["نسبة التحقيق %"] = sh_prod_full.apply(
                    lambda r: round((r["الفعلي (KG)"] / r["المستهدف (KG)"] * 100), 1) if r["المستهدف (KG)"] > 0 else 0,
                    axis=1
                )
                shift_prod_tables[pack_sh] = sh_prod_full  # بدون صف إجمالي — مستخدم في حساب الرسم البياني والكروت

                # نسخة للعرض والطباعة فيها صف إجمالي الإنتاج تحت كل الخطوط بتاعة نفس الشيفت
                sh_target_sum = sh_prod_full["المستهدف (KG)"].sum()
                sh_actual_sum = sh_prod_full["الفعلي (KG)"].sum()
                sh_total_row = pd.DataFrame([{
                    "الخط": "الإجمالي",
                    "المستهدف (KG)": sh_target_sum,
                    "الفعلي (KG)": sh_actual_sum,
                    "نسبة التحقيق %": round((sh_actual_sum / sh_target_sum * 100), 1) if sh_target_sum > 0 else 0,
                }])
                sh_prod_display = pd.concat([sh_prod_full, sh_total_row], ignore_index=True)
                shift_prod_display_tables[pack_sh] = sh_prod_display

                st.markdown(f"**👷 {pack_sh}**")
                st.dataframe(sh_prod_display, use_container_width=True, hide_index=True)

            prod_target_all = sum(t["المستهدف (KG)"].sum() for t in shift_prod_tables.values())
            prod_actual_all = sum(t["الفعلي (KG)"].sum() for t in shift_prod_tables.values())
            prod_achv_all = (prod_actual_all / prod_target_all * 100) if prod_target_all > 0 else 0

            # ---------- تقرير قابل للطباعة احترافي: كروت KPI + جدول لكل شيفت (تعبئة + إنتاج) + رسم بياني ----------
            st.divider()
            st.markdown("##### 🖨️ تحميل تقرير الشيفتات القابل للطباعة")

            def _shift_kpi_card(icon, value, label, color):
                return f"""
                <div style="flex:1; background:#fff; border:1px solid #e5e7eb; border-right:5px solid {color};
                            border-radius:8px; padding:10px 8px; text-align:center;">
                    <div style="font-size:18px;">{icon}</div>
                    <div style="font-size:18px; font-weight:800; color:#0b1f3a;">{value}</div>
                    <div style="font-size:10px; color:#6b7280; font-weight:700;">{label}</div>
                </div>
                """

            shift_top_html = '<div style="display:flex; gap:8px; margin:8px 0 14px;">' + "".join([
                _shift_kpi_card("📦", f"{grand_total_cartons:,.0f}", "إجمالي التعبئة (كرتونة)", "#0891b2"),
                _shift_kpi_card("⚖️", f"{grand_total_kg:,.1f} كجم", "إجمالي التعبئة بالوزن", "#0891b2"),
                _shift_kpi_card("🎯", f"{prod_target_all:,.0f} KG", "إجمالي مستهدف الإنتاج", "#2563eb"),
                _shift_kpi_card("📈", f"{prod_actual_all:,.0f} KG", "إجمالي الفعلي للإنتاج", "#16a34a"),
                _shift_kpi_card("🥇", f"{prod_achv_all:.1f}%", "نسبة تحقيق الإنتاج", "#7c3aed"),
            ]) + "</div>"

            SHIFT_SECTION_COLORS = {
                SHIFT_OPTIONS_P[0]: "#2563eb",
                SHIFT_OPTIONS_P[1]: "#7c3aed",
                SHIFT_OPTIONS_P[2]: "#0891b2",
            }

            shift_sections_html = ""
            for pack_sh in SHIFT_OPTIONS_P:
                color = SHIFT_SECTION_COLORS.get(pack_sh, "#0b1f3a")
                pack_html = shift_pack_tables.get(pack_sh, pd.DataFrame()).to_html(
                    index=False, border=0, justify="center", na_rep="-"
                )
                prod_html = shift_prod_display_tables.get(pack_sh, pd.DataFrame()).to_html(
                    index=False, border=0, justify="center", na_rep="-"
                )
                shift_sections_html += f"""
                <div style="margin-top:14px; page-break-inside:avoid;">
                    <h2 style="background:{color}; color:#fff; padding:6px 10px; border-radius:6px; margin-bottom:6px;">
                        👷 {pack_sh}
                    </h2>
                    <table class="layout-wrapper" width="100%">
                        <tr>
                            <td class="main-cell" valign="top" style="width:52%; padding-left:10px;">
                                <h3 style="margin:0 0 4px; font-size:11px; color:#374151;">📦 تعبئة الشيفت</h3>
                                {pack_html}
                            </td>
                            <td class="side-cell" valign="top" style="width:48%;">
                                <h3 style="margin:0 0 4px; font-size:11px; color:#374151;">🏭 إنتاج الخطوط</h3>
                                {prod_html}
                            </td>
                        </tr>
                    </table>
                </div>
                """

            # رسم بياني احترافي: إجمالي إنتاج كل خط (على مستوى اليوم كله) فعلي مقابل مستهدف
            shift_chart_html = ""
            line_totals_for_chart = pd.DataFrame({"الخط": all_lines_clean, "المستهدف (KG)": 0, "الفعلي (KG)": 0})
            if shift_prod_tables:
                combined_prod = pd.concat(shift_prod_tables.values(), ignore_index=True)
                line_totals_for_chart = combined_prod.groupby("الخط", sort=False)[
                    ["المستهدف (KG)", "الفعلي (KG)"]
                ].sum().reindex(all_lines_clean).reset_index().rename(columns={"index": "الخط"})

            if line_totals_for_chart[["المستهدف (KG)", "الفعلي (KG)"]].sum().sum() > 0:
                fig_shift_chart = build_line_production_chart(
                    line_totals_for_chart, line_col="الخط",
                    chart_title=f"إجمالي إنتاج الخطوط (كل الشيفتات) — {report_shift_date_str}"
                )
                if fig_shift_chart is not None:
                    shift_chart_html = (
                        f'<div style="margin-top:16px; page-break-inside:avoid;">'
                        f'<h2 style="background:#0b1f3a; color:#fff; padding:6px 10px; border-radius:6px; margin-bottom:6px;">'
                        f'📊 إنتاج الخطوط — الفعلي مقابل المستهدف</h2>'
                        f'{fig_to_base64_img(fig_shift_chart)}</div>'
                    )

            overview_df = pd.DataFrame()  # مفيش جدول ملخص رئيسي — كل حاجة بقت في الكروت والأقسام تحت

            shift_single_page = st.checkbox(
                "📄 نسخة صفحة واحدة متصلة بالطول (للإرسال أونلاين — مش مقاس ورق طابعة عادي)",
                value=True,
                key="shift_single_page_toggle",
                help="لو مفعّل: هيطلع التقرير كله في صفحة واحدة طويلة من غير تقسيم صفحات. "
                     "لو عايز تطبعه على ورق A4 عادي، سيبه مطفي."
            )

            single_page_height_mm = None
            if shift_single_page:
                shift_rows_total = sum(
                    max(len(shift_pack_tables.get(sh, [])), len(shift_prod_display_tables.get(sh, [])))
                    for sh in SHIFT_OPTIONS_P
                )
                has_chart = line_totals_for_chart[["المستهدف (KG)", "الفعلي (KG)"]].sum().sum() > 0
                single_page_height_mm = 130 + (shift_rows_total * 8) + (len(SHIFT_OPTIONS_P) * 18) + (110 if has_chart else 0)

            shift_printable_html = build_printable_html(
                "تقرير الشيفتات — تعبئة وإنتاج الخطوط",
                f"يوم {report_shift_date_str} — تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                overview_df,
                landscape=True,
                base_font_size=13,
                bold=True,
                row_padding="8px 6px",
                top_html=shift_top_html,
                extra_html=shift_sections_html + shift_chart_html,
                single_page_height_mm=single_page_height_mm,
            )
            st.download_button(
                "🖨️ تحميل تقرير الشيفتات (PDF) — للإدارة",
                data=shift_printable_html.encode("utf-8"),
                file_name=f"shift_report_{report_shift_date_str}.html",
                mime="text/html",
                help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' عشان تحوله PDF أو تطبعه",
                key="shift_report_print_btn"
            )

            # ==========================
            # تقرير التخطيط الكامل بالأصناف — بيتحط تحت تقرير الشيفتات مباشرة، ولنفس اليوم المختار هنا
            # ==========================
            st.divider()
            st.markdown("##### 🗓️ تقرير التخطيط — تعبئة اليوم (نفس يوم تقرير الشيفتات)")
            st.caption(
                f"تقرير مخصوص للأصناف اللي اتعبأت يوم {report_shift_date.day} بس، "
                "وبيوضح كل صنف ده بيمثل قد ايه من خطته الشهرية"
            )

            shift_plan_day = report_shift_date.day
            shift_plan_day_col = f"يوم {shift_plan_day}"

            shift_plan_source = edited_grid[edited_grid["الصنف"].astype(str).str.strip() != ""].copy()
            for dc in day_cols:
                shift_plan_source[dc] = pd.to_numeric(shift_plan_source[dc], errors="coerce").fillna(0)
            shift_plan_source["وزن الكرتونة (كيلو)"] = pd.to_numeric(
                shift_plan_source["وزن الكرتونة (كيلو)"], errors="coerce"
            ).fillna(0.0)
            shift_plan_source["المخطط بالكراتين (شهري)"] = pd.to_numeric(
                shift_plan_source["المخطط بالكراتين (شهري)"], errors="coerce"
            ).fillna(0)
            shift_plan_source["إجمالي الكراتين"] = shift_plan_source[day_cols].sum(axis=1)

            if shift_plan_day_col not in shift_plan_source.columns:
                st.info("مفيش عمود لليوم ده في الجدول")
            else:
                shift_plan_df = shift_plan_source[shift_plan_source[shift_plan_day_col] > 0][[
                    "الصنف", "الفئة", shift_plan_day_col, "وزن الكرتونة (كيلو)",
                    "إجمالي الكراتين", "المخطط بالكراتين (شهري)"
                ]].copy()

                if shift_plan_df.empty:
                    st.info(f"مفيش أي صنف اتعبأ يوم {shift_plan_day} لغاية دلوقتي 📭")
                else:
                    shift_plan_df = shift_plan_df.rename(columns={shift_plan_day_col: "تعبئة اليوم (كرتونة)"})
                    shift_plan_df["وزن اليوم (كجم)"] = (
                        shift_plan_df["تعبئة اليوم (كرتونة)"] * shift_plan_df["وزن الكرتونة (كيلو)"]
                    ).round(1)
                    shift_plan_df["نسبة من الخطة الشهرية %"] = shift_plan_df.apply(
                        lambda r: round((r["تعبئة اليوم (كرتونة)"] / r["المخطط بالكراتين (شهري)"] * 100), 1)
                        if r["المخطط بالكراتين (شهري)"] > 0 else None,
                        axis=1
                    )
                    shift_plan_df = shift_plan_df.sort_values("تعبئة اليوم (كرتونة)", ascending=False).reset_index(drop=True)

                    # نسخة كاملة (فيها الفئة) تُستخدم لحساب الرسم الدائري فقط
                    shift_plan_df_full = shift_plan_df.copy()

                    # نسخة العرض والجدول: من غير عمود الفئة
                    shift_plan_df = shift_plan_df[[
                        "الصنف", "تعبئة اليوم (كرتونة)", "إجمالي الكراتين", "وزن اليوم (كجم)",
                        "المخطط بالكراتين (شهري)", "نسبة من الخطة الشهرية %"
                    ]]

                    # ---------- بطاقات KPI للتخطيط ----------
                    sp_items_today = len(shift_plan_df)
                    sp_total_qty_today = shift_plan_df["تعبئة اليوم (كرتونة)"].sum()
                    sp_total_weight_today = shift_plan_df["وزن اليوم (كجم)"].sum()
                    sp_monthly_plan_total = shift_plan_source["المخطط بالكراتين (شهري)"].sum()
                    sp_today_share = (sp_total_qty_today / sp_monthly_plan_total * 100) if sp_monthly_plan_total > 0 else 0
                    sp_top_item = shift_plan_df.iloc[0]
                    sp_items_hit_plan = int(
                        (pd.to_numeric(shift_plan_df["نسبة من الخطة الشهرية %"], errors="coerce") >= 100).sum()
                    )

                    shift_plan_top_html = (
                        '<div style="display:flex; gap:8px; margin:8px 0 8px;">' + "".join([
                            _shift_kpi_card("📋", f"{sp_items_today}", "عدد الأصناف المعبأة اليوم", "#2563eb"),
                            _shift_kpi_card("📦", f"{sp_total_qty_today:,.0f}", "إجمالي كراتين اليوم", "#0d6b5c"),
                            _shift_kpi_card("⚖️", f"{sp_total_weight_today:,.0f} كجم", "إجمالي وزن اليوم", "#0891b2"),
                            _shift_kpi_card("🎯", f"{sp_today_share:.1f}%",
                                            "نسبة تعبئة اليوم من إجمالي الخطة الشهرية", "#e0a92e"),
                            _shift_kpi_card("🏆", str(sp_top_item["الصنف"])[:18],
                                            f"أعلى صنف ({sp_top_item['تعبئة اليوم (كرتونة)']:,.0f} كرتونة)", "#7c3aed"),
                            _shift_kpi_card("✅", f"{sp_items_hit_plan} صنف",
                                            "حققوا 100% من خطتهم الشهرية في يوم واحد", "#16a34a"),
                        ]) + "</div>"
                    )
                    st.markdown(_flat_html(shift_plan_top_html), unsafe_allow_html=True)
                    st.dataframe(shift_plan_df, use_container_width=True, hide_index=True)

                    # ---------- اتجاه الإنتاج آخر 7 أيام ----------
                    sp_trend_days = [d for d in range(max(1, shift_plan_day - 6), shift_plan_day + 1)]
                    sp_trend_cols = [f"يوم {d}" for d in sp_trend_days]
                    sp_trend_totals = [
                        shift_plan_source[c].sum() if c in shift_plan_source.columns else 0 for c in sp_trend_cols
                    ]

                    def _build_sp_trend_fig(figsize=(7.2, 3.2), title_size=12):
                        fig_t, ax_t = plt.subplots(figsize=figsize)
                        fig_t.patch.set_facecolor("#ffffff")
                        ax_t.plot(sp_trend_days, sp_trend_totals, marker="o", linewidth=2.4, color=BRAND_GREEN,
                                  markerfacecolor="#ffffff", markeredgecolor=BRAND_GREEN, markeredgewidth=2,
                                  markersize=7, zorder=3)
                        ax_t.fill_between(sp_trend_days, sp_trend_totals, color=BRAND_GREEN, alpha=0.08, zorder=2)
                        for x, y in zip(sp_trend_days, sp_trend_totals):
                            ax_t.annotate(f"{y:,.0f}", xy=(x, y), xytext=(0, 8), textcoords="offset points",
                                          ha="center", fontsize=8, fontweight="bold", color="#1a1d21")
                        ax_t.set_xticks(sp_trend_days)
                        ax_t.set_xticklabels([ar_text(f"يوم {d}") for d in sp_trend_days], fontsize=9, fontweight="bold")
                        ax_t.tick_params(axis="y", labelsize=9, colors="#4b5563")
                        ax_t.spines["top"].set_visible(False)
                        ax_t.spines["right"].set_visible(False)
                        ax_t.grid(axis="y", linestyle="--", alpha=0.4, color="#c9cfd6", zorder=0)
                        ax_t.set_axisbelow(True)
                        ax_t.set_title(ar_text("اتجاه الإنتاج — آخر 7 أيام (إجمالي الكراتين)"),
                                        fontsize=title_size, fontweight="bold", color=BRAND_GREEN, pad=10)
                        fig_t.tight_layout()
                        return fig_t

                    st.caption("📈 اتجاه الإنتاج — آخر 7 أيام (إجمالي الكراتين)")
                    st.pyplot(_build_sp_trend_fig())

                    # ---------- توزيع الفئات ----------
                    sp_cat_totals = shift_plan_df_full.groupby("الفئة")["تعبئة اليوم (كرتونة)"].sum()

                    st.caption("🥧 توزيع تعبئة اليوم بالفئات")
                    fig_sp_pie, ax_sp_pie = plt.subplots()
                    fig_sp_pie.patch.set_facecolor("#ffffff")
                    wedges_sp, texts_sp, autotexts_sp = ax_sp_pie.pie(
                        sp_cat_totals.values, labels=[ar_text(l) for l in sp_cat_totals.index],
                        autopct="%1.1f%%", startangle=90, colors=BRAND_PALETTE,
                        textprops={"fontsize": 9, "fontweight": "bold", "color": "#1a1d21"},
                        wedgeprops={"edgecolor": "#ffffff", "linewidth": 1.5}
                    )
                    for at in autotexts_sp:
                        at.set_color("#ffffff")
                    ax_sp_pie.axis("equal")
                    st.pyplot(fig_sp_pie)

                    # ---------- نفس الرسمين بجودة طباعة، يتحطوا جوه تقرير الـ PDF (فوق بعض عشان الصفحة بالطول) ----------
                    fig_sp_pie_print, ax_sp_pie_print = plt.subplots(figsize=(4.6, 4.2))
                    fig_sp_pie_print.patch.set_facecolor("#ffffff")
                    wedges_spp, texts_spp, autotexts_spp = ax_sp_pie_print.pie(
                        sp_cat_totals.values, labels=[ar_text(l) for l in sp_cat_totals.index],
                        autopct="%1.1f%%", startangle=90, colors=BRAND_PALETTE,
                        textprops={"fontsize": 9, "fontweight": "bold", "color": "#1a1d21"},
                        wedgeprops={"edgecolor": "#ffffff", "linewidth": 1.5}
                    )
                    for at in autotexts_spp:
                        at.set_color("#ffffff")
                    ax_sp_pie_print.axis("equal")
                    ax_sp_pie_print.set_title(ar_text("توزيع تعبئة اليوم بالفئات"),
                                               fontsize=12, fontweight="bold", color=BRAND_GREEN, pad=10)

                    shift_plan_charts_html = f"""
                    <div style="margin-top:8px; page-break-inside:avoid;">
                        {fig_to_base64_img(_build_sp_trend_fig())}
                    </div>
                    <div style="margin-top:8px; page-break-inside:avoid; text-align:center;">
                        {fig_to_base64_img(fig_sp_pie_print, style="width:65%; max-width:420px; display:block; margin:6px auto;")}
                    </div>
                    """

                    shift_plan_single_page_height_mm = 150 + (len(shift_plan_df) * 7) + 210

                    shift_plan_html = build_printable_html(
                        f"تقرير التخطيط — تعبئة يوم {shift_plan_day}",
                        f"شهر {selected_month} — الأصناف اللي اتعبأت يوم {report_shift_date_str} فقط — "
                        f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        shift_plan_df,
                        landscape=False,
                        base_font_size=13,
                        bold=True,
                        row_padding="8px 6px",
                        top_html=shift_plan_top_html,
                        extra_html=shift_plan_charts_html,
                        single_page_height_mm=shift_plan_single_page_height_mm,
                    )

                    st.download_button(
                        "🖨️ تحميل تقرير التخطيط (صفحة واحدة)",
                        data=shift_plan_html.encode("utf-8"),
                        file_name=f"packing_planning_{selected_month}_day{shift_plan_day}.html",
                        mime="text/html",
                        help="تقرير صفحة واحدة بالأصناف اللي اتعبأت يوم تقرير الشيفتات بس + بطاقات + رسوم بيانية — "
                             "افتحه ودوس Ctrl+P واختار 'Save as PDF'",
                        key="shift_planning_report_print_btn"
                    )

    st.divider()
    st.subheader(f"📊 ملخص شهر {selected_month}")

    summary = edited_grid.copy()
    summary = summary[summary["الصنف"].astype(str).str.strip() != ""]

    if summary.empty:
        st.info("سجل بيانات صنف واحد على الأقل عشان يظهر الملخص")
    else:
        for dc in day_cols:
            summary[dc] = pd.to_numeric(summary[dc], errors="coerce").fillna(0)
        summary["وزن الكرتونة (كيلو)"] = pd.to_numeric(summary["وزن الكرتونة (كيلو)"], errors="coerce").fillna(0.0)
        summary["المخطط بالكراتين (شهري)"] = pd.to_numeric(summary["المخطط بالكراتين (شهري)"], errors="coerce").fillna(0)

        summary["إجمالي الكراتين"] = summary[day_cols].sum(axis=1)
        summary["الوزن الفعلي (كيلو)"] = (summary["إجمالي الكراتين"] * summary["وزن الكرتونة (كيلو)"]).round(1)
        summary["المخطط بالوزن (كيلو)"] = (summary["المخطط بالكراتين (شهري)"] * summary["وزن الكرتونة (كيلو)"]).round(1)
        summary["نسبة التحقيق %"] = summary.apply(
            lambda r: round((r["إجمالي الكراتين"] / r["المخطط بالكراتين (شهري)"] * 100), 1)
            if r["المخطط بالكراتين (شهري)"] > 0 else 0,
            axis=1
        )
        display_summary = summary[[
            "الصنف", "الفئة", "وزن الكرتونة (كيلو)", "إجمالي الكراتين",
            "المخطط بالكراتين (شهري)", "الوزن الفعلي (كيلو)",
            "المخطط بالوزن (كيلو)", "نسبة التحقيق %"
        ]]
        st.dataframe(display_summary, use_container_width=True, hide_index=True)

        total_target_sum = summary["المخطط بالكراتين (شهري)"].sum()
        total_pct = round(
            (summary["إجمالي الكراتين"].sum() / total_target_sum * 100) if total_target_sum > 0 else 0, 1
        )
        kpi_row([
            {"icon": "🎯", "label": "إجمالي المخطط", "value": f"{summary['المخطط بالكراتين (شهري)'].sum():,.0f} كرتونة", "color": "#e0a92e"},
            {"icon": "📦", "label": "إجمالي المُنتج", "value": f"{summary['إجمالي الكراتين'].sum():,.0f} كرتونة", "color": "#0d6b5c"},
            {"icon": "🥇", "label": "نسبة التحقيق", "value": f"{total_pct}%", "color": "#7c3aed"},
            {"icon": "⚖️", "label": "الوزن الفعلي", "value": f"{summary['الوزن الفعلي (كيلو)'].sum():,.1f} كجم", "color": "#2563eb"},
        ])

        st.download_button(
            "⬇ تحميل بيانات الشهر CSV",
            data=summary.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"packing_{selected_month}.csv",
            mime="text/csv"
        )

        st.divider()
        st.subheader("📅 ملخص يوم معين بالفئات")
        st.caption("زي جدول الإكسيل بتاعك — المسلم بالطن والكرتونة لكل فئة في يوم واحد")

        day_pick = st.selectbox(
            "اختر اليوم",
            list(range(1, days_in_month + 1)),
            index=min(datetime.now().day, days_in_month) - 1,
            key="packing_day_pick"
        )
        day_col_pick = f"يوم {day_pick}"

        daily_by_cat = summary.groupby("الفئة").apply(
            lambda g: pd.Series({
                "المسلم بالطن": (g[day_col_pick] * g["وزن الكرتونة (كيلو)"] / 1000).sum(),
                "المسلم بالكرتونة": g[day_col_pick].sum()
            })
        ).reset_index().rename(columns={"الفئة": "اليومي"})

        total_row = pd.DataFrame([{
            "اليومي": "الإجمالي",
            "المسلم بالطن": daily_by_cat["المسلم بالطن"].sum(),
            "المسلم بالكرتونة": daily_by_cat["المسلم بالكرتونة"].sum()
        }])
        daily_by_cat_display = pd.concat([daily_by_cat, total_row], ignore_index=True)

        st.dataframe(daily_by_cat_display, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("#### 🖨️ تقرير الطباعة اليومي")

        print_df = summary[["الصنف"]].copy()
        print_df[f"تعبئة يوم {day_pick}"] = summary[day_col_pick]
        print_df["إجمالي الكراتين"] = summary["إجمالي الكراتين"]
        print_df["المخطط بالكراتين (شهري)"] = summary["المخطط بالكراتين (شهري)"]

        print_df["نسبة التحقيق %"] = summary.apply(
            lambda r: round((r["إجمالي الكراتين"] / r["المخطط بالكراتين (شهري)"] * 100), 1)
            if r["المخطط بالكراتين (شهري)"] > 0 else 0,
            axis=1
        )

        print_df = print_df.fillna(0)

        total_actual_all = print_df["إجمالي الكراتين"].sum()
        total_target_all = print_df["المخطط بالكراتين (شهري)"].sum()
        total_row_print = pd.DataFrame([{
            "الصنف": "الإجمالي",
            f"تعبئة يوم {day_pick}": print_df[f"تعبئة يوم {day_pick}"].sum(),
            "إجمالي الكراتين": total_actual_all,
            "المخطط بالكراتين (شهري)": total_target_all,
            "نسبة التحقيق %": round((total_actual_all / total_target_all * 100), 1) if total_target_all > 0 else 0,
        }])
        print_df = pd.concat([print_df, total_row_print], ignore_index=True)

        # ---------- جدول صغير: إنتاج الخطوط لنفس اليوم (من صفحة Production) ----------
        # بنعرض كل الخطوط المعرّفة دايمًا (حتى لو صفر)، عشان الجدول يفضل ظاهر في التقرير دايمًا
        report_date = pd.Timestamp(year=year, month=month_num, day=day_pick).strftime("%Y-%m-%d")
        all_lines_clean_pm = [str(l).replace("🏭", "").strip() for l in st.session_state.production_lines]
        prod_line_table = pd.DataFrame({
            "الخط": all_lines_clean_pm,
            "المستهدف (KG)": 0,
            "الفعلي (KG)": 0,
        })
        if GSHEETS_ENABLED and gsheet_exists(PRODUCTION_SHEET):
            hist_df_p = read_gsheet(PRODUCTION_SHEET)
            hist_df_p["Date"] = hist_df_p["Date"].astype(str)
            day_hist = hist_df_p[(hist_df_p["Date"] == report_date) & (hist_df_p["Shift"] == "All Shifts")]
            # نستبعد أي صف اسم الخط فيه فاضي عشان اسم الخط يظهر صح في التقرير
            if "Line" in day_hist.columns:
                day_hist = day_hist[day_hist["Line"].astype(str).str.strip() != ""]
            if not day_hist.empty:
                for nc in ["المستهدف (KG)", "الفعلي (KG)"]:
                    day_hist[nc] = pd.to_numeric(day_hist[nc], errors="coerce").fillna(0)
                day_grouped = day_hist.groupby("Line")[["المستهدف (KG)", "الفعلي (KG)"]].sum()
                prod_line_table = day_grouped.reindex(all_lines_clean_pm, fill_value=0).reset_index()
                prod_line_table.columns = ["الخط", "المستهدف (KG)", "الفعلي (KG)"]

        # ---------- جدول صغير: الأعطال لنفس اليوم (من جوجل شيت) ----------
        faults_table = pd.DataFrame(columns=["الخط", "مدة التوقف (دقيقة)"])
        faults_sheet_name = f"faults_monthly_{selected_month}"
        if GSHEETS_ENABLED and gsheet_exists(faults_sheet_name):
            faults_df_p = read_gsheet(faults_sheet_name)
            if day_col_pick in faults_df_p.columns and "الخط" in faults_df_p.columns:
                faults_df_p[day_col_pick] = pd.to_numeric(faults_df_p[day_col_pick], errors="coerce").fillna(0)
                faults_table = faults_df_p[["الخط", day_col_pick]].rename(columns={day_col_pick: "مدة التوقف (دقيقة)"})
                faults_table = faults_table[faults_table["مدة التوقف (دقيقة)"] >= 0]

        # ---------- رسم بياني احترافي: إنتاج الخطوط الفعلي مقابل المستهدف — يتحط جوه التقرير القابل للطباعة ----------
        prod_chart_html = ""
        if not prod_line_table.empty and prod_line_table[["المستهدف (KG)", "الفعلي (KG)"]].sum().sum() > 0:
            fig_prod_chart = build_line_production_chart(
                prod_line_table, line_col="الخط",
                chart_title=f"إنتاج الخطوط — يوم {day_pick}"
            )
            if fig_prod_chart is not None:
                prod_chart_html = (
                    f'<h2>📊 إنتاج الخطوط — الفعلي مقابل المستهدف</h2>'
                    f'{fig_to_base64_img(fig_prod_chart)}'
                )

        printable_html = build_printable_html(
            f"تقرير Packing اليومي — شهر {selected_month}",
            f"يوم {day_pick} — تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            print_df,
            landscape=True,
            extra_tables=[
                (f"📅 تعبئة يوم {day_pick} بالفئات", daily_by_cat_display),
                ("🏭 إنتاج الخطوط لنفس اليوم", prod_line_table),
                ("⚠ الأعطال لنفس اليوم", faults_table),
            ],
            extra_html=prod_chart_html or None,
        )
        st.download_button(
            "🖨️ تحميل نسخة قابلة للطباعة (PDF) — للإدارة",
            data=printable_html.encode("utf-8"),
            file_name=f"packing_{selected_month}_day{day_pick}.html",
            mime="text/html",
            help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' عشان تحوله PDF أو تطبعه"
        )

        # ==========================
        # تقرير تاني مخصوص لمدير الإنتاج — بطاقات KPI + جدول ملوّن بالحالة + جدول فئات ملوّن + جدول للمقصّرين
        # ==========================
        st.divider()
        st.markdown("#### 🖨️ تقرير مدير الإنتاج")

        PACKING_SETTINGS_SHEET = "packing_settings"

        def load_planned_days(month_str, default_days):
            if GSHEETS_ENABLED and gsheet_exists(PACKING_SETTINGS_SHEET):
                settings_df = read_gsheet(PACKING_SETTINGS_SHEET)
                match = settings_df[settings_df["الشهر"] == month_str]
                if not match.empty:
                    val = pd.to_numeric(match.iloc[0]["أيام العمل المخططة"], errors="coerce")
                    if pd.notna(val) and val > 0:
                        return int(val)
            return default_days

        def save_planned_days(month_str, value):
            if GSHEETS_ENABLED:
                if gsheet_exists(PACKING_SETTINGS_SHEET):
                    settings_df = read_gsheet(PACKING_SETTINGS_SHEET)
                    settings_df = settings_df[settings_df["الشهر"] != month_str]
                else:
                    settings_df = pd.DataFrame(columns=["الشهر", "أيام العمل المخططة"])
                new_row = pd.DataFrame([{"الشهر": month_str, "أيام العمل المخططة": value}])
                settings_df = pd.concat([settings_df, new_row], ignore_index=True)
                write_gsheet(PACKING_SETTINGS_SHEET, settings_df)

        saved_planned_days = load_planned_days(selected_month, days_in_month)
        pdc1, pdc2 = st.columns([2, 1])
        with pdc1:
            total_month_days = st.number_input(
                f"📅 عدد أيام العمل المخططة لشهر {selected_month} (تقدر تعدّلها، مش لازم تبقى كل أيام الشهر)",
                min_value=1, max_value=31, value=int(saved_planned_days), step=1,
                key=f"planned_days_{selected_month}"
            )
        with pdc2:
            st.write("")
            st.write("")
            if st.button("💾 حفظ عدد الأيام", key="save_planned_days_btn"):
                save_planned_days(selected_month, total_month_days)
                st.success("اتحفظ ✔")

        # عدد أيام العمل الفعلية = عدد الأيام (من أول الشهر لحد اليوم المختار) اللي فيها تعبئة حقيقية
        working_days_upto = [f"يوم {d}" for d in range(1, day_pick + 1)]
        actual_working_days = sum(1 for dc in working_days_upto if summary[dc].sum() > 0)
        day_ratio = (actual_working_days / total_month_days) if total_month_days > 0 else 0

        pm_df = summary[["الصنف", day_col_pick, "المخطط بالكراتين (شهري)", "إجمالي الكراتين",
                          "وزن الكرتونة (كيلو)"]].copy()
        pm_df = pm_df.rename(columns={
            day_col_pick: f"تعبئة يوم {day_pick}",
            "المخطط بالكراتين (شهري)": "إجمالي المخطط (كرتونة)",
            "إجمالي الكراتين": "إجمالي الفعلي (كرتونة)"
        })
        pm_df = pm_df[pm_df["الصنف"].astype(str).str.strip() != ""].reset_index(drop=True)

        # المتوقع تحقيقه حتى الآن = المخطط الشهري × (أيام العمل الفعلية / أيام العمل المخططة)
        pm_df["_متوقع"] = (pm_df["إجمالي المخطط (كرتونة)"] * day_ratio)
        pm_df["نسبة الأداء %"] = pm_df.apply(
            lambda r: round((r["إجمالي الفعلي (كرتونة)"] / r["_متوقع"] * 100), 1)
            if r["_متوقع"] > 0 else None,
            axis=1
        )

        def _pm_status(pct):
            if pct is None or pd.isna(pct):
                return "➖ بدون خطة", "#6b7280", "#f3f4f6"
            if pct >= 90:
                return "⬆ تحقق المستهدف", "#16a34a", "#eafaf0"
            elif pct >= 70:
                return "⚠ قريب من المخطط", "#d97706", "#fff7e6"
            else:
                return "⬇ أداء منخفض", "#dc2626", "#fde2e1"

        status_labels, row_bg_colors = [], []
        for pct in pm_df["نسبة الأداء %"]:
            label, color, bg = _pm_status(pct)
            status_labels.append(f'<span style="color:{color}; font-weight:800;">{label}</span>')
            row_bg_colors.append(bg)
        pm_df["حالة الأداء"] = status_labels

        # الترتيب المطلوب: الصنف، تعبئة اليوم، الإجمالي، المخطط، نسبة الأداء، حالة الأداء
        pm_df = pm_df[[
            "الصنف", f"تعبئة يوم {day_pick}", "إجمالي الفعلي (كرتونة)",
            "إجمالي المخطط (كرتونة)", "نسبة الأداء %", "حالة الأداء"
        ]]

        # ---------- بطاقات KPI ----------
        total_target_pm = summary["المخطط بالكراتين (شهري)"].sum()
        total_actual_pm = summary["إجمالي الكراتين"].sum()
        total_today_pm = summary[day_col_pick].sum()
        total_expected_pm = (total_target_pm * day_ratio)
        avg_perf_pm = (total_actual_pm / total_expected_pm * 100) if total_expected_pm > 0 else 0
        full_plan_pct_pm = (total_actual_pm / total_target_pm * 100) if total_target_pm > 0 else 0
        items_count_pm = len(pm_df[pm_df["إجمالي المخطط (كرتونة)"] > 0])
        low_items_count_pm = sum(
            1 for pct in pm_df["نسبة الأداء %"] if pd.notna(pct) and pct < 90
        )

        # نفس القيم بالوزن (كيلو)
        total_target_kg = (summary["المخطط بالكراتين (شهري)"] * summary["وزن الكرتونة (كيلو)"]).sum()
        total_actual_kg = (summary["إجمالي الكراتين"] * summary["وزن الكرتونة (كيلو)"]).sum()
        total_today_kg = (summary[day_col_pick] * summary["وزن الكرتونة (كيلو)"]).sum()

        def kpi_card(icon, value, label, color):
            return f"""
            <div style="flex:1; background:#fff; border:1px solid #e5e7eb; border-right:5px solid {color};
                        border-radius:8px; padding:10px 8px; text-align:center;">
                <div style="font-size:18px;">{icon}</div>
                <div style="font-size:18px; font-weight:800; color:#0b1f3a;">{value}</div>
                <div style="font-size:10px; color:#6b7280; font-weight:700;">{label}</div>
            </div>
            """

        pm_top_html = (
            '<div style="display:flex; gap:8px; margin:8px 0 8px;">' + "".join([
                kpi_card("📅", f"{total_month_days} يوم", "أيام العمل المخططة", "#2563eb"),
                kpi_card("✅", f"{actual_working_days} يوم", "أيام العمل الفعلية", "#16a34a"),
                kpi_card("📦", f"{total_today_pm:,.0f}", f"تعبئة يوم {day_pick} (كرتونة)", "#0891b2"),
                kpi_card("🎯", f"{total_target_pm:,.0f}", "إجمالي المخطط (كرتونة)", "#2563eb"),
                kpi_card("📈", f"{total_actual_pm:,.0f}", "إجمالي الفعلي (كرتونة)", "#16a34a"),
                kpi_card("📊", f"{avg_perf_pm:.1f}%", "متوسط الأداء (من المتوقع)", "#7c3aed"),
                kpi_card("🔻", f"{low_items_count_pm} من {items_count_pm}", "أصناف أقل من المتوقع", "#dc2626"),
            ]) + "</div>"
            + '<div style="display:flex; gap:8px; margin:0 0 12px;">' + "".join([
                kpi_card("⚖️", f"{total_target_kg:,.0f} كجم", "إجمالي المخطط بالوزن", "#2563eb"),
                kpi_card("⚖️", f"{total_actual_kg:,.0f} كجم", "إجمالي الفعلي بالوزن", "#16a34a"),
                kpi_card("⚖️", f"{total_today_kg:,.0f} كجم", f"تعبئة يوم {day_pick} بالوزن", "#0891b2"),
                kpi_card("🏁", f"{full_plan_pct_pm:.1f}%", "نسبة تحقيق الخطة الشهرية الكاملة", "#f59e0b"),
            ]) + "</div>"
        )

        st.dataframe(
            pm_df.assign(**{
                "حالة الأداء": [s.split(">")[1].split("<")[0] for s in status_labels],
                "نسبة الأداء %": pm_df["نسبة الأداء %"].apply(lambda v: f"{v:.1f} ٪" if pd.notna(v) else "-"),
            }),
            use_container_width=True, hide_index=True
        )

        # ---------- جدول ملوّن: تعبئة اليوم بالفئات (هارد كاندي / طوفي / اكلير / فورية) ----------
        CATEGORY_COLORS = {
            "هارد كاندي": "#e0f2fe",
            "طوفي": "#fef3c7",
            "اكلير": "#fce7f3",
            "فورية": "#dcfce7",
        }
        cat_row_colors = [CATEGORY_COLORS.get(str(v), "#f3f4f6") for v in daily_by_cat_display["اليومي"]]
        cat_row_colors[-1] = "#e5e7eb"  # صف الإجمالي
        cat_table_html = _df_to_html_highlighted(daily_by_cat_display, None, row_colors=cat_row_colors)

        st.markdown(f"##### 📅 تعبئة يوم {day_pick} بالفئات")
        st.dataframe(daily_by_cat_display, use_container_width=True, hide_index=True)

        # ---------- جدول تحت: الأصناف اللي أداؤها أقل من المتوقع ----------
        pm_low_df = pm_df[pd.to_numeric(pm_df["نسبة الأداء %"], errors="coerce") < 90].copy()
        pm_low_df = pm_low_df.sort_values("نسبة الأداء %").reset_index(drop=True)
        low_row_colors_sorted = [_pm_status(p)[2] for p in pm_low_df["نسبة الأداء %"]]
        pm_low_df["نسبة الأداء %"] = pm_low_df["نسبة الأداء %"].apply(lambda v: f"{v:.1f} ٪" if pd.notna(v) else "-")

        pm_bottom_table_html = _df_to_html_highlighted(pm_low_df, None, row_colors=low_row_colors_sorted) if not pm_low_df.empty else \
            "<p style='font-size:12px; color:#6b7280;'>كل الأصناف حققت 90% أو أكتر من المتوقع 🎉</p>"

        # الجدول الرئيسي بيتبعت زي ما هو لـ build_printable_html تحت (كـ pm_df) — نضيف علامة % جنب الرقم دلوقتي
        # بعد ما خلصنا كل الاستخدامات الرقمية اللي محتاجة الرقم الخام (فلترة/ترتيب pm_low_df فوق)
        pm_df["نسبة الأداء %"] = pm_df["نسبة الأداء %"].apply(lambda v: f"{v:.1f} ٪" if pd.notna(v) else "-")

        # ---------- اتجاه الإنتاج آخر 7 أيام بالوزن (كجم) + خط التارجت — مشترك: بيتحط في تقرير مدير الإنتاج وتقرير التخطيط ----------
        trend_days = [d for d in range(max(1, day_pick - 6), day_pick + 1)]
        trend_cols = [f"يوم {d}" for d in trend_days]
        trend_weights = [
            (summary[c] * summary["وزن الكرتونة (كيلو)"]).sum() if c in summary.columns else 0
            for c in trend_cols
        ]
        # التارجت اليومي بالوزن = (المخطط الشهري بالكراتين ÷ أيام الشهر) × وزن الكرتونة، مجمّع على كل الأصناف
        daily_target_weight = (
            (summary["المخطط بالكراتين (شهري)"] / total_month_days * summary["وزن الكرتونة (كيلو)"]).sum()
            if total_month_days > 0 else 0
        )
        target_weights = [daily_target_weight] * len(trend_days)

        def _build_trend_fig(figsize=(7.2, 3.2), title_size=12):
            fig_t, ax_t = plt.subplots(figsize=figsize)
            fig_t.patch.set_facecolor("#ffffff")
            ax_t.plot(trend_days, trend_weights, marker="o", linewidth=2.4, color=BRAND_GREEN,
                      markerfacecolor="#ffffff", markeredgecolor=BRAND_GREEN, markeredgewidth=2,
                      markersize=7, zorder=3, label=ar_text("الفعلي (كجم)"))
            ax_t.fill_between(trend_days, trend_weights, color=BRAND_GREEN, alpha=0.08, zorder=2)
            ax_t.plot(trend_days, target_weights, linewidth=2, color="#dc2626", linestyle="--",
                      zorder=2, label=ar_text("التارجت اليومي (كجم)"))
            for x, y in zip(trend_days, trend_weights):
                ax_t.annotate(f"{y:,.0f}", xy=(x, y), xytext=(0, 8), textcoords="offset points",
                               ha="center", fontsize=8, fontweight="bold", color="#1a1d21")
            ax_t.set_xticks(trend_days)
            ax_t.set_xticklabels([ar_text(f"يوم {d}") for d in trend_days], fontsize=9, fontweight="bold")
            ax_t.tick_params(axis="y", labelsize=9, colors="#4b5563")
            ax_t.spines["top"].set_visible(False)
            ax_t.spines["right"].set_visible(False)
            ax_t.grid(axis="y", linestyle="--", alpha=0.4, color="#c9cfd6", zorder=0)
            ax_t.set_axisbelow(True)
            ax_t.legend(fontsize=8, loc="upper left", frameon=False)
            ax_t.set_title(ar_text("اتجاه الإنتاج — آخر 7 أيام (إجمالي الوزن كجم)"),
                            fontsize=title_size, fontweight="bold", color=BRAND_GREEN, pad=10)
            fig_t.tight_layout()
            return fig_t

        trend_chart_img_html = fig_to_base64_img(_build_trend_fig())
        trend_chart_section_html = f"""
        <div style="margin-top:10px; page-break-inside:avoid;">
            <h2 style="background:{BRAND_GREEN}; color:#fff; padding:6px 10px; border-radius:6px; margin-bottom:6px;">
                📈 اتجاه الإنتاج — آخر 7 أيام (بالوزن)
            </h2>
            {trend_chart_img_html}
        </div>
        """

        # ---------- جدول إنتاج الخطوط لنفس اليوم — يتحط جوه تقرير مدير الإنتاج كمان (بيظهر دايمًا حتى لو كله صفر) ----------
        prod_line_total_row = pd.DataFrame([{
            "الخط": "الإجمالي",
            "المستهدف (KG)": prod_line_table["المستهدف (KG)"].sum(),
            "الفعلي (KG)": prod_line_table["الفعلي (KG)"].sum(),
        }])
        prod_line_table_display = pd.concat([prod_line_table, prod_line_total_row], ignore_index=True)
        prod_line_table_html = prod_line_table_display.to_html(index=False, border=0, justify="center", na_rep="-")
        pm_prod_line_section = f"""
        <div style="margin-top:10px; page-break-inside:avoid;">
            <h2 style="background:#2563eb; color:#fff; padding:6px 10px; border-radius:6px; margin-bottom:6px;">
                🏭 إنتاج الخطوط لنفس اليوم {day_pick}
            </h2>
            {prod_line_table_html}
        </div>
        """

        pm_extra_html = f"""
        <div style="margin-top:10px; page-break-inside:avoid;">
            <h2 style="background:#0891b2; color:#fff; padding:6px 10px; border-radius:6px; margin-bottom:6px;">
                📅 تعبئة يوم {day_pick} بالفئات
            </h2>
            {cat_table_html}
        </div>
        {pm_prod_line_section}
        <div style="margin-top:10px;">
            <h2 style="background:#dc2626; color:#fff; padding:6px 10px; border-radius:6px; margin-bottom:6px;">
                🔻 الأصناف اللي أداؤها أقل من المتوقع (حسب أيام العمل الفعلية)
            </h2>
            {pm_bottom_table_html}
        </div>
        <p style="font-size:9px; color:#6b7280; margin-top:10px;">
            ℹ️ يتم احتساب "المتوقع" و"نسبة الأداء" بناءً على عدد أيام العمل الفعلية
            ({actual_working_days} يوم) من إجمالي أيام العمل المخططة ({total_month_days} يوم).
        </p>
        {trend_chart_section_html}
        """

        pm_single_page = st.checkbox(
            "📄 نسخة صفحة واحدة متصلة (للإرسال أونلاين فقط — مش مقاس ورق طابعة عادي)",
            value=False,
            key="pm_single_page_toggle",
            help="لو مفعّل: هيطلع PDF بصفحة واحدة طويلة بدون تقسيم، مناسب للإرسال بالإيميل/واتساب بس. "
                 "لو عايز تطبعه فعليًا على ورق A4، سيبه مطفي."
        )

        single_page_height_mm = None
        if pm_single_page:
            # تقدير ارتفاع الصفحة المطلوب بناءً على عدد الصفوف الفعلي في كل جدول، عشان الصفحة متبقاش فاضية
            main_rows = len(pm_df)
            cat_rows = len(daily_by_cat_display)
            prod_line_rows = len(prod_line_table)
            low_rows = max(len(pm_low_df), 1)
            single_page_height_mm = 95 + (main_rows * 9) + (cat_rows * 6) + (prod_line_rows * 6) + (low_rows * 7) + 35 + 75

        pm_html = build_printable_html(
            "تقرير متابعة الإنتاج — لمدير الإنتاج (Packing)",
            f"شهر {selected_month} — يوم {day_pick} — تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            pm_df,
            landscape=True,
            base_font_size=15,
            bold=True,
            row_padding="10px 8px",
            top_html=pm_top_html,
            row_colors=row_bg_colors,
            extra_html=pm_extra_html,
            single_page_height_mm=single_page_height_mm
        )

        st.download_button(
            "🖨️ تحميل تقرير مدير الإنتاج (خط كبير)",
            data=pm_html.encode("utf-8"),
            file_name=f"packing_pm_{selected_month}_day{day_pick}.html",
            mime="text/html",
            help="تقرير بطاقات + جدول ملوّن بالحالة + جدول فئات — افتحه ودوس Ctrl+P واختار 'Save as PDF'"
        )

        # ==========================
        # تقرير تالت: تقرير التخطيط — الأصناف اللي اتعبأت النهاردة بس، وتمثل قد ايه من الخطة الشهرية
        # ==========================
        st.divider()
        st.markdown("#### 🗓️ تقرير التخطيط — تعبئة اليوم")
        st.caption(
            f"تقرير مخصوص للأصناف اللي اتعبأت يوم {day_pick} بس، وبيوضح كل صنف ده بيمثل قد ايه من خطته الشهرية"
        )

        planning_df = summary[summary[day_col_pick] > 0][[
            "الصنف", "الفئة", day_col_pick, "وزن الكرتونة (كيلو)",
            "إجمالي الكراتين", "المخطط بالكراتين (شهري)"
        ]].copy()

        if planning_df.empty:
            st.info(f"مفيش أي صنف اتعبأ يوم {day_pick} لغاية دلوقتي 📭")
        else:
            planning_df = planning_df.rename(columns={day_col_pick: "تعبئة اليوم (كرتونة)"})
            planning_df["وزن اليوم (كجم)"] = (
                planning_df["تعبئة اليوم (كرتونة)"] * planning_df["وزن الكرتونة (كيلو)"]
            ).round(1)
            planning_df["نسبة من الخطة الشهرية %"] = planning_df.apply(
                lambda r: round((r["تعبئة اليوم (كرتونة)"] / r["المخطط بالكراتين (شهري)"] * 100), 1)
                if r["المخطط بالكراتين (شهري)"] > 0 else None,
                axis=1
            )
            planning_df = planning_df.sort_values("تعبئة اليوم (كرتونة)", ascending=False).reset_index(drop=True)

            # نسخة كاملة (فيها الفئة) تُستخدم لحساب الرسم الدائري فقط
            planning_df_full = planning_df.copy()

            # نسخة العرض والجدول: من غير عمود الفئة
            planning_df = planning_df[[
                "الصنف", "تعبئة اليوم (كرتونة)", "إجمالي الكراتين", "وزن اليوم (كجم)",
                "المخطط بالكراتين (شهري)", "نسبة من الخطة الشهرية %"
            ]]

            # ---------- بطاقات KPI للتخطيط ----------
            items_packed_today = len(planning_df)
            total_qty_today = planning_df["تعبئة اليوم (كرتونة)"].sum()
            total_weight_today = planning_df["وزن اليوم (كجم)"].sum()
            monthly_plan_total = summary["المخطط بالكراتين (شهري)"].sum()
            today_share_of_plan = (total_qty_today / monthly_plan_total * 100) if monthly_plan_total > 0 else 0
            top_item_row = planning_df.iloc[0]
            items_hit_plan_today = int(
                (pd.to_numeric(planning_df["نسبة من الخطة الشهرية %"], errors="coerce") >= 100).sum()
            )

            planning_top_html = (
                '<div style="display:flex; gap:8px; margin:8px 0 8px;">' + "".join([
                    kpi_card("📋", f"{items_packed_today}", "عدد الأصناف المعبأة اليوم", "#2563eb"),
                    kpi_card("📦", f"{total_qty_today:,.0f}", "إجمالي كراتين اليوم", "#0d6b5c"),
                    kpi_card("⚖️", f"{total_weight_today:,.0f} كجم", "إجمالي وزن اليوم", "#0891b2"),
                    kpi_card("🎯", f"{today_share_of_plan:.1f}%", "نسبة تعبئة اليوم من إجمالي الخطة الشهرية", "#e0a92e"),
                    kpi_card("🏆", str(top_item_row["الصنف"])[:18],
                             f"أعلى صنف ({top_item_row['تعبئة اليوم (كرتونة)']:,.0f} كرتونة)", "#7c3aed"),
                    kpi_card("✅", f"{items_hit_plan_today} صنف", "حققوا 100% من خطتهم الشهرية في يوم واحد", "#16a34a"),
                ]) + "</div>"
            )
            st.markdown(_flat_html(planning_top_html), unsafe_allow_html=True)

            st.dataframe(planning_df, use_container_width=True, hide_index=True)

            # ---------- رسمين بيانيين: اتجاه الإنتاج آخر 7 أيام + دائرة توزيع اليوم بالفئات ----------
            cat_today_totals = planning_df_full.groupby("الفئة")["تعبئة اليوم (كرتونة)"].sum()

            st.caption("📈 اتجاه الإنتاج — آخر 7 أيام (إجمالي الكراتين)")
            st.pyplot(_build_trend_fig())

            st.caption("🥧 توزيع تعبئة اليوم بالفئات")
            fig_plan_pie, ax_plan_pie = plt.subplots()
            fig_plan_pie.patch.set_facecolor("#ffffff")
            wedges_p, texts_p, autotexts_p = ax_plan_pie.pie(
                cat_today_totals.values, labels=[ar_text(l) for l in cat_today_totals.index],
                autopct="%1.1f%%", startangle=90, colors=BRAND_PALETTE,
                textprops={"fontsize": 9, "fontweight": "bold", "color": "#1a1d21"},
                wedgeprops={"edgecolor": "#ffffff", "linewidth": 1.5}
            )
            for at in autotexts_p:
                at.set_color("#ffffff")
            ax_plan_pie.axis("equal")
            st.pyplot(fig_plan_pie)

            # ---------- نفس الرسمين بجودة طباعة، يتحطوا جوه تقرير الـ PDF (فوق بعض عشان الصفحة بالطول) ----------
            fig_plan_pie_print, ax_plan_pie_print = plt.subplots(figsize=(4.6, 4.2))
            fig_plan_pie_print.patch.set_facecolor("#ffffff")
            wedges_pp, texts_pp, autotexts_pp = ax_plan_pie_print.pie(
                cat_today_totals.values, labels=[ar_text(l) for l in cat_today_totals.index],
                autopct="%1.1f%%", startangle=90, colors=BRAND_PALETTE,
                textprops={"fontsize": 9, "fontweight": "bold", "color": "#1a1d21"},
                wedgeprops={"edgecolor": "#ffffff", "linewidth": 1.5}
            )
            for at in autotexts_pp:
                at.set_color("#ffffff")
            ax_plan_pie_print.axis("equal")
            ax_plan_pie_print.set_title(ar_text("توزيع تعبئة اليوم بالفئات"),
                                         fontsize=12, fontweight="bold", color=BRAND_GREEN, pad=10)

            planning_charts_html = f"""
            <div style="margin-top:8px; page-break-inside:avoid;">
                {fig_to_base64_img(_build_trend_fig())}
            </div>
            <div style="margin-top:8px; page-break-inside:avoid; text-align:center;">
                {fig_to_base64_img(fig_plan_pie_print, style="width:65%; max-width:420px; display:block; margin:6px auto;")}
            </div>
            """

            # ارتفاع الصفحة بيتحسب حسب عدد صفوف الجدول عشان التقرير يطلع صفحة واحدة بالطول، مظبوطة ومش مقصوصة
            planning_single_page_height_mm = 150 + (len(planning_df) * 7) + 210

            planning_html = build_printable_html(
                f"تقرير التخطيط — تعبئة يوم {day_pick}",
                f"شهر {selected_month} — الأصناف اللي اتعبأت النهاردة فقط — "
                f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                planning_df,
                landscape=False,
                base_font_size=13,
                bold=True,
                row_padding="8px 6px",
                top_html=planning_top_html,
                extra_html=planning_charts_html,
                single_page_height_mm=planning_single_page_height_mm,
            )

            st.download_button(
                "🖨️ تحميل تقرير التخطيط (صفحة واحدة)",
                data=planning_html.encode("utf-8"),
                file_name=f"packing_planning_{selected_month}_day{day_pick}.html",
                mime="text/html",
                help="تقرير صفحة واحدة بالأصناف اللي اتعبأت النهاردة بس + بطاقات + رسوم بيانية — "
                     "افتحه ودوس Ctrl+P واختار 'Save as PDF'"
            )

        st.divider()
        st.subheader("📈 الرسوم البيانية")

        category_totals = summary.groupby("الفئة")["إجمالي الكراتين"].sum()
        cat_c1, cat_c2 = st.columns([1, 1])
        with cat_c1:
            st.caption("توزيع الإنتاج بين الفئات الثلاثة")
            fig1, ax1 = plt.subplots()
            fig1.patch.set_facecolor("#ffffff")
            wedges1, texts1, autotexts1 = ax1.pie(
                category_totals.values, labels=[ar_text(l) for l in category_totals.index],
                autopct="%1.1f%%", startangle=90, colors=BRAND_PALETTE,
                textprops={"fontsize": 9, "fontweight": "bold", "color": "#1a1d21"},
                wedgeprops={"edgecolor": "#ffffff", "linewidth": 1.5}
            )
            for at in autotexts1:
                at.set_color("#ffffff")
            ax1.axis("equal")
            st.pyplot(fig1)
        with cat_c2:
            st.caption("إجمالي الكراتين لكل فئة")
            st.bar_chart(category_totals)

        st.markdown("#### 🔍 تفاصيل فئة معينة")
        category_choice = st.selectbox(
            "اختر الفئة",
            ["هارد كاندي", "طوفي", "اكلير", "أخرى"],
            key="packing_category_filter"
        )
        cat_df = summary[summary["الفئة"] == category_choice]

        if cat_df.empty:
            st.info("مفيش أصناف مسجلة في الفئة دي")
        else:
            st.caption(f"المخطط مقابل الفعلي لكل صنف في فئة {category_choice}")
            compare_df = cat_df.set_index("الصنف")[["المخطط بالكراتين (شهري)", "إجمالي الكراتين"]]
            st.bar_chart(compare_df)

            st.caption(f"اتجاه الإنتاج اليومي على مدار الشهر لفئة {category_choice}")
            daily_trend = cat_df[day_cols].sum(axis=0)
            daily_trend.index = range(1, len(day_cols) + 1)
            st.line_chart(daily_trend)


elif page == "التصدير":
    page_banner("🚢", "التصدير", "تسجيل ومتابعة طلبيات التصدير لكل بلد وشركة")

    EXPORT_PASSWORD = "pack2026"  # نفس باسورد صفحة Packing بالظبط
    if "export_unlocked" not in st.session_state:
        st.session_state.export_unlocked = False

    if not st.session_state.export_unlocked:
        st.subheader("🔒 صفحة محمية")
        st.caption("نفس باسورد صفحة Packing")
        pw_input_ex = st.text_input("كلمة مرور الصفحة", type="password", key="export_page_pw")
        if st.button("دخول", key="export_page_unlock_btn"):
            if pw_input_ex == EXPORT_PASSWORD:
                st.session_state.export_unlocked = True
                st.rerun()
            else:
                st.error("كلمة المرور غلط")
        st.stop()

    if not GSHEETS_ENABLED:
        st.error(
            "⚠ البيانات دي مربوطة بجوجل شيت، ومحتاجة إعداد Secrets صح على Streamlit Cloud "
            "(gcp_service_account + gsheets sheet_id). راجع الإعداد وحاول تاني."
        )
        st.stop()

    today_ex = datetime.now().date()
    month_options_ex = []
    for i in range(-6, 7):
        y = today_ex.year + (today_ex.month - 1 + i) // 12
        m = (today_ex.month - 1 + i) % 12 + 1
        month_options_ex.append(f"{y}-{m:02d}")
    default_index_ex = month_options_ex.index(today_ex.strftime("%Y-%m"))
    selected_month_ex = st.selectbox("📅 اختر الشهر", month_options_ex, index=default_index_ex, key="export_month_select")

    year_ex, month_num_ex = map(int, selected_month_ex.split("-"))
    days_in_month_ex = calendar.monthrange(year_ex, month_num_ex)[1]
    day_cols_ex = [f"يوم {d}" for d in range(1, days_in_month_ex + 1)]

    EXPORT_SHEET = f"export_monthly_{selected_month_ex}"
    id_cols_ex = ["الصنف", "اسم البلد", "الشركة"]
    base_cols_ex = id_cols_ex + ["الكمية المطلوبة (KG)"] + day_cols_ex

    grid_raw_ex = read_gsheet_strict(EXPORT_SHEET)
    if grid_raw_ex is None:
        st.error(
            "⚠️ تعذّر الاتصال بجوجل شيت دلوقتي (زحمة مؤقتة على الـ API). "
            "بياناتك آمنة ومتأثرتش، بس معرفناش نجيبها. جرب تحدّث الصفحة بعد كام ثانية."
        )
        st.stop()

    if grid_raw_ex.empty:
        month_grid_ex = pd.DataFrame([{
            "الصنف": "", "اسم البلد": "", "الشركة": "", "الكمية المطلوبة (KG)": 0,
            **{dc: 0 for dc in day_cols_ex}
        }])
    else:
        month_grid_ex = grid_raw_ex
        for c in base_cols_ex:
            if c not in month_grid_ex.columns:
                month_grid_ex[c] = "" if c in id_cols_ex else 0
        month_grid_ex = month_grid_ex[base_cols_ex]

    for c in id_cols_ex:
        month_grid_ex[c] = month_grid_ex[c].astype(str).str.strip()
    month_grid_ex["الكمية المطلوبة (KG)"] = pd.to_numeric(month_grid_ex["الكمية المطلوبة (KG)"], errors="coerce").fillna(0)
    for dc in day_cols_ex:
        month_grid_ex[dc] = pd.to_numeric(month_grid_ex[dc], errors="coerce").fillna(0)

    st.caption(
        "📌 سجّل كل طلبية تصدير في صف: الصنف، اسم البلد، الشركة، والكمية المطلوبة (KG). "
        "بعدين سجّل الكمية المُصدَّرة فعليًا كل يوم في عموده. تقدر تضيف طلبيات جديدة أو تمسح صفوف من آخر الجدول مباشرة."
    )

    edited_ex = st.data_editor(
        month_grid_ex,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"export_editor_{selected_month_ex}",
        column_config={
            "الصنف": st.column_config.TextColumn("📦 الصنف", width="medium"),
            "اسم البلد": st.column_config.TextColumn("🌍 اسم البلد", width="medium"),
            "الشركة": st.column_config.TextColumn("🏢 الشركة", width="medium"),
            "الكمية المطلوبة (KG)": st.column_config.NumberColumn("🎯 الكمية المطلوبة (KG)", format="%.0f", min_value=0),
            **{dc: st.column_config.NumberColumn(dc, format="%.0f", min_value=0) for dc in day_cols_ex},
        }
    )

    if st.button("💾 حفظ بيانات التصدير", key="export_save_btn"):
        to_save_ex = edited_ex.copy()
        for c in id_cols_ex:
            to_save_ex[c] = to_save_ex[c].astype(str).str.strip()
        # نتجاهل الصفوف الفاضية تمامًا (من غير صنف ولا بلد) قبل الحفظ
        to_save_ex = to_save_ex[(to_save_ex["الصنف"] != "") | (to_save_ex["اسم البلد"] != "")].reset_index(drop=True)
        try:
            write_gsheet(EXPORT_SHEET, to_save_ex)
        except Exception as e:
            st.error(f"❌ فشل الحفظ — جرب تاني بعد شوية. (تفاصيل: {e})")
            st.stop()
        st.success(f"اتحفظت بيانات تصدير شهر {selected_month_ex} ✔")
        st.rerun()

    st.divider()

    # ---------- حساب الفعلي حتى الآن ونسبة التحقيق لكل طلبية ----------
    report_grid_ex = edited_ex.copy()
    for c in id_cols_ex:
        report_grid_ex[c] = report_grid_ex[c].astype(str).str.strip()
    report_grid_ex = report_grid_ex[(report_grid_ex["الصنف"] != "") | (report_grid_ex["اسم البلد"] != "")].reset_index(drop=True)
    report_grid_ex["الفعلي حتى الآن (KG)"] = report_grid_ex[day_cols_ex].sum(axis=1)
    report_grid_ex["نسبة التحقيق %"] = report_grid_ex.apply(
        lambda r: round((r["الفعلي حتى الآن (KG)"] / r["الكمية المطلوبة (KG)"] * 100), 1)
        if r["الكمية المطلوبة (KG)"] > 0 else 0,
        axis=1
    )
    report_grid_ex["المتبقي (KG)"] = (report_grid_ex["الكمية المطلوبة (KG)"] - report_grid_ex["الفعلي حتى الآن (KG)"]).clip(lower=0)

    # ---------- نسبة الوقت المنقضي من الشهر — عشان نعرف الطلبية ماشية على المسار الصح ولا متأخرة ----------
    if (year_ex, month_num_ex) < (today_ex.year, today_ex.month):
        day_ratio_ex = 1.0
    elif (year_ex, month_num_ex) > (today_ex.year, today_ex.month):
        day_ratio_ex = 0.0
    else:
        day_ratio_ex = today_ex.day / days_in_month_ex

    report_grid_ex["المتوقع حتى الآن (KG)"] = (report_grid_ex["الكمية المطلوبة (KG)"] * day_ratio_ex).round(0)
    report_grid_ex["حالة الطلبية"] = report_grid_ex.apply(
        lambda r: "✅ مكتملة" if r["نسبة التحقيق %"] >= 100
        else ("🟢 على المسار" if r["الفعلي حتى الآن (KG)"] >= r["المتوقع حتى الآن (KG)"]
              else "🔴 متأخرة"),
        axis=1
    )

    total_target_ex = report_grid_ex["الكمية المطلوبة (KG)"].sum()
    total_actual_ex = report_grid_ex["الفعلي حتى الآن (KG)"].sum()
    total_pct_ex = round((total_actual_ex / total_target_ex * 100), 1) if total_target_ex > 0 else 0
    total_remaining_ex = report_grid_ex["المتبقي (KG)"].sum()
    n_countries_ex = report_grid_ex["اسم البلد"].replace("", pd.NA).dropna().nunique()
    n_companies_ex = report_grid_ex["الشركة"].replace("", pd.NA).dropna().nunique()
    n_delayed_ex = int((report_grid_ex["حالة الطلبية"] == "🔴 متأخرة").sum())
    n_completed_ex = int((report_grid_ex["حالة الطلبية"] == "✅ مكتملة").sum())

    kpi_row([
        {"icon": "📋", "label": "عدد الطلبيات", "value": f"{len(report_grid_ex)}", "color": "#2563eb"},
        {"icon": "🎯", "label": "إجمالي الكمية المطلوبة", "value": f"{total_target_ex:,.0f} KG", "color": "#e0a92e"},
        {"icon": "📦", "label": "إجمالي الفعلي حتى الآن", "value": f"{total_actual_ex:,.0f} KG", "color": "#0d6b5c"},
        {"icon": "🥇", "label": "نسبة التحقيق الإجمالية", "value": f"{total_pct_ex}%", "color": "#7c3aed"},
    ])
    kpi_row([
        {"icon": "⏳", "label": "المتبقي لإتمام كل الطلبيات", "value": f"{total_remaining_ex:,.0f} KG", "color": "#ea580c"},
        {"icon": "🌍", "label": "عدد البلاد", "value": f"{n_countries_ex}", "color": "#0891b2"},
        {"icon": "🏢", "label": "عدد الشركات", "value": f"{n_companies_ex}", "color": "#4338ca"},
        {"icon": "🔴", "label": "طلبيات متأخرة عن المسار", "value": f"{n_delayed_ex}", "color": "#dc2626"},
        {"icon": "✅", "label": "طلبيات مكتملة", "value": f"{n_completed_ex}", "color": "#16a34a"},
    ])

    # ==========================
    # تقرير لكل بلد
    # ==========================
    st.divider()
    st.subheader("🌍 تقرير التصدير لكل بلد")

    if report_grid_ex.empty:
        st.info("لسه مفيش طلبيات تصدير مسجلة للشهر ده")
    else:
        country_summary_ex = report_grid_ex.groupby("اسم البلد", sort=False).agg(
            **{
                "عدد الطلبيات": ("الصنف", "count"),
                "الكمية المطلوبة (KG)": ("الكمية المطلوبة (KG)", "sum"),
                "الفعلي حتى الآن (KG)": ("الفعلي حتى الآن (KG)", "sum"),
            }
        ).reset_index()
        country_summary_ex["نسبة التحقيق %"] = country_summary_ex.apply(
            lambda r: round((r["الفعلي حتى الآن (KG)"] / r["الكمية المطلوبة (KG)"] * 100), 1)
            if r["الكمية المطلوبة (KG)"] > 0 else 0,
            axis=1
        )
        country_summary_ex = country_summary_ex.sort_values("الكمية المطلوبة (KG)", ascending=False).reset_index(drop=True)

        st.dataframe(country_summary_ex, use_container_width=True, hide_index=True)
        st.bar_chart(country_summary_ex.set_index("اسم البلد")[["الكمية المطلوبة (KG)", "الفعلي حتى الآن (KG)"]])

        country_report_html = build_printable_html(
            f"تقرير التصدير لكل بلد — شهر {selected_month_ex}",
            f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')} — إجمالي نسبة التحقيق: {total_pct_ex}%",
            country_summary_ex,
            landscape=False,
        )
        st.download_button(
            "🖨️ تحميل تقرير كل بلد (PDF)",
            data=country_report_html.encode("utf-8"),
            file_name=f"export_by_country_{selected_month_ex}.html",
            mime="text/html",
            help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF'",
            key="export_country_report_btn"
        )

    # ==========================
    # تقرير لكل شركة
    # ==========================
    st.divider()
    st.subheader("🏢 تقرير التصدير لكل شركة")

    if report_grid_ex.empty:
        st.info("لسه مفيش طلبيات تصدير مسجلة للشهر ده")
    else:
        company_summary_ex = report_grid_ex.groupby("الشركة", sort=False).agg(
            **{
                "عدد الطلبيات": ("الصنف", "count"),
                "الكمية المطلوبة (KG)": ("الكمية المطلوبة (KG)", "sum"),
                "الفعلي حتى الآن (KG)": ("الفعلي حتى الآن (KG)", "sum"),
            }
        ).reset_index()
        company_summary_ex["نسبة التحقيق %"] = company_summary_ex.apply(
            lambda r: round((r["الفعلي حتى الآن (KG)"] / r["الكمية المطلوبة (KG)"] * 100), 1)
            if r["الكمية المطلوبة (KG)"] > 0 else 0,
            axis=1
        )
        company_summary_ex = company_summary_ex.sort_values("الكمية المطلوبة (KG)", ascending=False).reset_index(drop=True)
        st.dataframe(company_summary_ex, use_container_width=True, hide_index=True)
        st.bar_chart(company_summary_ex.set_index("الشركة")[["الكمية المطلوبة (KG)", "الفعلي حتى الآن (KG)"]])

    # ==========================
    # رسومات إضافية تفيد التخطيط
    # ==========================
    st.divider()
    st.subheader("📊 رسومات تفيد التخطيط")

    if not report_grid_ex.empty:
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.caption("🏆 أعلى 10 أصناف من حيث الكمية المطلوبة (KG)")
            top_items_ex = (
                report_grid_ex.groupby("الصنف")["الكمية المطلوبة (KG)"].sum()
                .sort_values(ascending=False).head(10)
            )
            if not top_items_ex.empty:
                st.bar_chart(top_items_ex)
            else:
                st.info("لا توجد بيانات كافية")

        with chart_col2:
            st.caption("📈 اتجاه إجمالي الكمية المُصدَّرة يوميًا على مدار الشهر (KG)")
            daily_trend_ex = report_grid_ex[day_cols_ex].sum(axis=0)
            daily_trend_ex.index = range(1, len(day_cols_ex) + 1)
            st.line_chart(daily_trend_ex)

        st.caption("🚦 توزيع الطلبيات حسب حالة المسار (متأخرة / على المسار / مكتملة)")
        status_counts_ex = report_grid_ex["حالة الطلبية"].value_counts()
        st.bar_chart(status_counts_ex)

    # ==========================
    # التقرير المفصل لكل طلبيات التصدير
    # ==========================
    st.divider()
    st.subheader("📋 التقرير المفصل لكل طلبيات التصدير")

    if report_grid_ex.empty:
        st.info("لسه مفيش طلبيات تصدير مسجلة للشهر ده")
    else:
        detail_cols_ex = [
            "الصنف", "اسم البلد", "الشركة", "الكمية المطلوبة (KG)", "الفعلي حتى الآن (KG)",
            "المتبقي (KG)", "المتوقع حتى الآن (KG)", "نسبة التحقيق %", "حالة الطلبية"
        ]
        detail_df_ex = report_grid_ex[detail_cols_ex].sort_values("نسبة التحقيق %").reset_index(drop=True)
        st.dataframe(detail_df_ex, use_container_width=True, hide_index=True)

        detail_report_html = build_printable_html(
            f"التقرير المفصل للتصدير — شهر {selected_month_ex}",
            f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')} — عدد الطلبيات: {len(detail_df_ex)} — "
            f"متأخرة: {n_delayed_ex} — مكتملة: {n_completed_ex}",
            detail_df_ex,
            landscape=True,
        )
        st.download_button(
            "🖨️ تحميل التقرير المفصل (PDF)",
            data=detail_report_html.encode("utf-8"),
            file_name=f"export_detailed_{selected_month_ex}.html",
            mime="text/html",
            help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF'",
            key="export_detailed_report_btn"
        )


elif page == "الأعطال":
    page_banner("⚠️", "الأعطال", "تسجيل ومتابعة أعطال وتوقفات خطوط الإنتاج")

    if not GSHEETS_ENABLED:
        st.error(
            "⚠ البيانات دي مربوطة بجوجل شيت، ومحتاجة إعداد Secrets صح على Streamlit Cloud "
            "(gcp_service_account + gsheets sheet_id). راجع الإعداد وحاول تاني."
        )
        st.stop()

    # خطوط الأعطال وكلمة مرور كل خط
    fault_line_passwords = {
        "الاكلير ص٣": "1111",
        "المستمر": "2222",
        "الإيطالي": "3333",
        "الاكلير ص١": "4444",
        "الطوفي": "5555",
        "الترانسلاب": "6666",
        "خط ويفر ١": "7171",
        "خط ويفر ٢": "7272",
        "خط ويفر ٣": "7373",
        "المطحنة": "7474",
    }

    # تقسيم المصانع: كل مصنع له خطوطه ومدير الصيانة بتاعه (باسورد + اسم يظهر كتوقيع في التقارير)
    FACTORY_CONFIG = {
        "مصنع 1": {
            "lines": ["الاكلير ص٣", "المستمر", "الإيطالي", "الاكلير ص١", "الطوفي", "الترانسلاب"],
            "maint_password": "8899",
            "maint_name": "م. هشام كامل",
        },
        "مصنع 2": {
            "lines": ["خط ويفر ١", "خط ويفر ٢", "خط ويفر ٣", "المطحنة"],
            "maint_password": "9988",
            "maint_name": "م. عبدالرحمن",
        },
    }

    factory_pick = st.radio("🏭 اختار المصنع", list(FACTORY_CONFIG.keys()), horizontal=True, key="faults_factory_pick")
    fault_lines = FACTORY_CONFIG[factory_pick]["lines"]
    ALL_FAULT_LINES = FACTORY_CONFIG["مصنع 1"]["lines"] + FACTORY_CONFIG["مصنع 2"]["lines"]
    st.divider()

    SHIFT_OPTIONS_F = ["الوردية الأولى", "الوردية الثانية", "الوردية الثالثة"]

    today_f = datetime.now().date()
    month_options_f = []
    for i in range(-2, 3):
        y = today_f.year + (today_f.month - 1 + i) // 12
        m = (today_f.month - 1 + i) % 12 + 1
        month_options_f.append(f"{y}-{m:02d}")
    default_index_f = month_options_f.index(today_f.strftime("%Y-%m"))
    selected_month_f = st.selectbox("📅 اختر الشهر (للعرض)", month_options_f, index=default_index_f, key="faults_month_select")

    year_f, month_num_f = map(int, selected_month_f.split("-"))
    days_in_month_f = calendar.monthrange(year_f, month_num_f)[1]
    day_cols_f = [f"يوم {d}" for d in range(1, days_in_month_f + 1)]
    base_cols_f = ["الخط", "سبب/ملاحظات"] + day_cols_f

    def load_faults_grid(month_str, lines_for_default):
        """الجدول الشهري التجميعي: إجمالي دقائق التوقف لكل خط في كل يوم.
        بيرجع None في المكان الأول لو فشل الاتصال بجوجل شيت فعلاً، عشان أي كود بيستخدم الدالة
        دي يقدر يوقف بدل ما يكمل بجدول فاضي (أصفار) ويكتبه فوق البيانات الحقيقية بالغلط."""
        f_year, f_month = map(int, month_str.split("-"))
        f_days = calendar.monthrange(f_year, f_month)[1]
        f_day_cols = [f"يوم {d}" for d in range(1, f_days + 1)]
        f_cols = ["الخط", "سبب/ملاحظات"] + f_day_cols
        f_path = f"faults_monthly_{month_str}"

        grid_raw = read_gsheet_strict(f_path)
        if grid_raw is None:
            return None, f_path, f_day_cols

        if grid_raw.empty:
            grid = pd.DataFrame([
                {"الخط": line, "سبب/ملاحظات": "", **{dc: 0 for dc in f_day_cols}}
                for line in lines_for_default
            ])
        else:
            grid = grid_raw
            for c in f_cols:
                if c not in grid.columns:
                    grid[c] = 0 if c in f_day_cols else ""
            grid = grid[f_cols]

        # تنظيف: نشيل أي صفوف بأسماء خطوط قديمة/ملغاة (زي أسماء خطوط اتغيرت قبل كده)
        # ونضمن إن كل الخطوط الحالية موجودة بالترتيب الصح
        grid = grid[grid["الخط"].isin(lines_for_default)].reset_index(drop=True)
        missing_lines = [l for l in lines_for_default if l not in grid["الخط"].values]
        if missing_lines:
            grid = pd.concat([
                grid,
                pd.DataFrame([{"الخط": l, "سبب/ملاحظات": "", **{dc: 0 for dc in f_day_cols}} for l in missing_lines])
            ], ignore_index=True)
        grid["__order"] = grid["الخط"].apply(lambda l: lines_for_default.index(l))
        grid = grid.sort_values("__order").drop(columns="__order").reset_index(drop=True)

        return grid, f_path, f_day_cols

    DAILY_LOG_SHEET = "faults_daily_log"
    DAILY_LOG_COLS = [
        "معرف العطل", "التاريخ", "الخط", "اسم الماكينة", "الوردية", "من الساعة", "إلى الساعة",
        "مدة العطل (دقيقة)", "سبب العطل",
        "الحالة", "تكلفة الصيانة (جنيه)", "معتمد بواسطة", "تاريخ الاعتماد",
    ]
    STATUS_PENDING = "قيد مراجعة الصيانة"
    STATUS_APPROVED = "معتمد"

    def load_daily_log():
        """السجل التفصيلي: كل عطل بصف لوحده (خط / ماكينة / وردية / من - إلى / مدة / سبب / حالة الاعتماد وتكلفته).
        بيستخدم القراءة "الصارمة" ومبيكتبش فوق الشيت (مايجراش أي Migration تلقائي) إلا لو القراءة
        نجحت فعلاً — عشان أي فشل اتصال مؤقت متخليش البرنامج يفتكر إن الشيت فاضي ويمسح بيانات حقيقية."""
        log_df_raw = read_gsheet_strict(DAILY_LOG_SHEET)

        if log_df_raw is None:
            # فشل الاتصال — نرجع جدول فاضي مؤقتًا للعرض بس من غير ما نلمس الشيت خالص
            st.warning(
                "⚠ تعذّر الاتصال بجوجل شيت مؤقتًا وإحنا بنجيب سجل الأعطال. "
                "البيانات الفعلية آمنة ومتأثرتش، بس ممكن تظهرلك الصفحة فاضية دلوقتي. جرب تحدّث الصفحة بعد كام ثانية."
            )
            return pd.DataFrame(columns=DAILY_LOG_COLS)

        log_df = log_df_raw
        needs_migration = False
        if log_df.empty:
            log_df = pd.DataFrame(columns=DAILY_LOG_COLS)
        else:
            for c in DAILY_LOG_COLS:
                if c not in log_df.columns:
                    needs_migration = True
                    if c == "مدة العطل (دقيقة)":
                        log_df[c] = 0
                    elif c == "تكلفة الصيانة (جنيه)":
                        log_df[c] = 0.0
                    elif c == "الحالة":
                        # سجلات قديمة اتسجلت قبل ما يتفعل نظام الاعتماد — نعتبرها معتمدة تلقائي
                        # عشان متتراكمش في قايمة "محتاج اعتماد" لمدير الصيانة بالغلط
                        log_df[c] = STATUS_APPROVED
                    elif c == "معتمد بواسطة":
                        log_df[c] = "بيانات قديمة (قبل نظام الاعتماد)"
                    else:
                        log_df[c] = ""
            log_df = log_df[DAILY_LOG_COLS]
            log_df["مدة العطل (دقيقة)"] = pd.to_numeric(log_df["مدة العطل (دقيقة)"], errors="coerce").fillna(0)
            log_df["تكلفة الصيانة (جنيه)"] = pd.to_numeric(log_df["تكلفة الصيانة (جنيه)"], errors="coerce").fillna(0.0)
            log_df["الحالة"] = log_df["الحالة"].replace("", STATUS_APPROVED).fillna(STATUS_APPROVED)

            # نولّد معرف فريد لأي صف قديم من غير معرف (مرة واحدة بس) عشان الاعتماد يقدر يحدّد كل عطل بدقة
            missing_id_mask = log_df["معرف العطل"].astype(str).str.strip().isin(["", "nan"])
            if missing_id_mask.any():
                needs_migration = True
                log_df.loc[missing_id_mask, "معرف العطل"] = [
                    f"F-{uuid.uuid4().hex[:10]}" for _ in range(missing_id_mask.sum())
                ]

        # بنكتب فوق الشيت بس لو القراءة الأصلية نجحت فعلاً (log_df_raw مش None) — الشرط ده أهم حاجة هنا
        if needs_migration and not log_df.empty:
            write_gsheet(DAILY_LOG_SHEET, log_df)
        return log_df

    def sync_month_grid_from_log(line, month_str, daily_log_df):
        """بيعيد بناء صف الخط في الجدول الشهري (دقايق كل يوم + الملاحظات) من السجل التفصيلي
        من الأول — كده أي إضافة أو حذف في السجل بتتظبط تلقائي في الجدول من غير ما نحتاج نحسب
        فرق يدوي، وده بيمنع أي خطأ تراكمي."""
        grid, f_path, f_day_cols = load_faults_grid(month_str, fault_lines)
        if grid is None:
            # فشل قراءة الجدول الشهري — نوقف من غير ما نكتب أي حاجة، عشان منمسحش بيانات باقي
            # الخطوط بالغلط بجدول فاضي. السجل التفصيلي نفسه (المصدر الأساسي) اتحفظ صح برضو.
            st.warning(
                "⚠️ اتسجلت البيانات في السجل التفصيلي، لكن تعذّر تحديث الجدول الشهري المجمّع دلوقتي "
                "(زحمة مؤقتة على الاتصال بجوجل شيت). جرب تحدّث الصفحة بعد كام ثانية عشان يتزامن."
            )
            return None
        if line not in grid["الخط"].values:
            new_row = {"الخط": line, "سبب/ملاحظات": "", **{dc: 0 for dc in f_day_cols}}
            grid = pd.concat([grid, pd.DataFrame([new_row])], ignore_index=True)
        row_idx = grid[grid["الخط"] == line].index[0]

        month_line_log = daily_log_df[
            (daily_log_df["الخط"] == line) & (daily_log_df["التاريخ"].astype(str).str.startswith(month_str))
        ].copy()
        month_line_log["مدة العطل (دقيقة)"] = pd.to_numeric(month_line_log["مدة العطل (دقيقة)"], errors="coerce").fillna(0)

        for dc in f_day_cols:
            day_num = int(dc.replace("يوم ", ""))
            day_str = f"{month_str}-{day_num:02d}"
            grid.at[row_idx, dc] = month_line_log[month_line_log["التاريخ"] == day_str]["مدة العطل (دقيقة)"].sum()

        notes_parts = []
        for _, r in month_line_log.sort_values(["التاريخ", "من الساعة"]).iterrows():
            if str(r["سبب العطل"]).strip():
                time_part = f" ({r['من الساعة']}-{r['إلى الساعة']})" if r["مدة العطل (دقيقة)"] > 0 else ""
                notes_parts.append(f"{r['التاريخ']}{time_part}: {r['سبب العطل']}")
        grid.at[row_idx, "سبب/ملاحظات"] = " | ".join(notes_parts)

        write_gsheet(f_path, grid)
        return grid

    # ==========================
    # تسجيل عطل خط المهندس بس — محتاج باسورد الخط بتاعه
    # ==========================
    st.subheader("🔒 تسجيل عطل خطي")

    my_line = st.selectbox("اختر خطك", fault_lines, key="faults_my_line")
    my_pass = st.text_input("كلمة مرور الخط", type="password", key="faults_my_pass")
    allow_log = my_pass == fault_line_passwords[my_line]

    if allow_log:
        st.success(f"تم التحقق ✔ — تقدر تسجل عطل خط {my_line} بس")
    else:
        st.warning("لازم تدخل كلمة مرور خطك الصحيحة عشان تقدر تسجل عطل")

    if allow_log:
        log_date = st.date_input("📅 التاريخ", value=today_f, key="fault_log_date_single")
        mc1, mc2 = st.columns(2)
        with mc1:
            machine_name = st.text_input("🔧 اسم الماكينة", key="fault_machine_single")
        with mc2:
            shift_pick = st.selectbox("👷 الوردية", SHIFT_OPTIONS_F, key="fault_shift_single")
        lc1, lc2 = st.columns(2)
        with lc1:
            from_t = st.time_input("⏱ من الساعة", key="fault_from_single")
        with lc2:
            to_t = st.time_input("⏱ إلى الساعة", key="fault_to_single")
        duration = st.number_input("⏰ مدة العطل (دقيقة)", min_value=0, step=1, key="fault_duration_single")
        reason = st.text_input("📝 سبب العطل", key="fault_reason_single")

        if st.button("💾 تسجيل عطل خطي اليوم"):
            log_month_str = log_date.strftime("%Y-%m")
            daily_log = load_daily_log()
            new_log_row = pd.DataFrame([{
                "معرف العطل": f"F-{uuid.uuid4().hex[:10]}",
                "التاريخ": log_date.strftime("%Y-%m-%d"),
                "الخط": my_line,
                "اسم الماكينة": machine_name.strip(),
                "الوردية": shift_pick,
                "من الساعة": from_t.strftime("%H:%M"),
                "إلى الساعة": to_t.strftime("%H:%M"),
                "مدة العطل (دقيقة)": duration,
                "سبب العطل": reason.strip(),
                "الحالة": STATUS_PENDING,
                "تكلفة الصيانة (جنيه)": 0.0,
                "معتمد بواسطة": "",
                "تاريخ الاعتماد": "",
            }])
            daily_log = pd.concat([daily_log, new_log_row], ignore_index=True)
            write_gsheet(DAILY_LOG_SHEET, daily_log)

            # الجدول الشهري بيتبني تلقائي من السجل التفصيلي عشان يفضل متطابق معاه دايمًا
            sync_month_grid_from_log(my_line, log_month_str, daily_log)

            st.success(f"اتسجل عطل خط {my_line} ليوم {log_date.strftime('%Y-%m-%d')} ✔ — دلوقتي مستني اعتماد مدير الصيانة")
            st.rerun()

        # ==========================
        # حذف عطل اتسجل غلط — بيمسح من السجل التفصيلي وبيحدّث الجدول الشهري تلقائي
        # ==========================
        st.markdown(f"##### 🗑️ حذف عطل مسجّل غلط (خط {my_line} بس)")
        del_date = st.date_input("📅 يوم العطل اللي عايز تحذفه", value=today_f, key="fault_delete_date")
        del_date_str = del_date.strftime("%Y-%m-%d")

        daily_log_del = load_daily_log()
        my_day_incidents = daily_log_del[
            (daily_log_del["الخط"] == my_line) & (daily_log_del["التاريخ"].astype(str) == del_date_str)
        ].reset_index(drop=True)

        if my_day_incidents.empty:
            # ممكن يكون العطل ده اتسجل قبل ما "السجل التفصيلي" يتفعل، فمش هيلاقيه هنا —
            # نتأكد لو فيه بيانات قديمة في الجدول الشهري نفسه ليوم ده ونديله وسيلة يمسحها مباشرة
            del_month_str = del_date.strftime("%Y-%m")
            legacy_grid, legacy_path, legacy_day_cols = load_faults_grid(del_month_str, fault_lines)
            if legacy_grid is None:
                st.warning("⚠ تعذّر الاتصال بجوجل شيت مؤقتًا وإحنا بندوّر على بيانات قديمة. جرب تاني بعد شوية.")
                legacy_row = pd.DataFrame()
                legacy_val = 0
            else:
                legacy_day_col = f"يوم {del_date.day}"
                legacy_row = legacy_grid[legacy_grid["الخط"] == my_line]

                legacy_val = 0
                if not legacy_row.empty and legacy_day_col in legacy_grid.columns:
                    legacy_val = pd.to_numeric(legacy_row.iloc[0][legacy_day_col], errors="coerce")
                    legacy_val = 0 if pd.isna(legacy_val) else legacy_val

            if legacy_val and legacy_val > 0:
                st.warning(
                    f"⚠ مفيش سجل تفصيلي للعطل ده (يبدو إنه اتسجل قبل تفعيل السجل التفصيلي)، "
                    f"بس لقيت **{legacy_val:,.0f} دقيقة** مسجلة في الجدول الشهري ليوم {del_date_str}."
                )
                notes_preview = str(legacy_row.iloc[0]["سبب/ملاحظات"])
                if notes_preview and notes_preview != "nan":
                    st.caption(f"الملاحظة المرتبطة: {notes_preview}")
                if st.button("🧹 امسح بيانات هذا اليوم من الجدول مباشرة (بيانات قديمة)", key="fault_delete_legacy_btn"):
                    row_idx = legacy_row.index[0]
                    legacy_grid.at[row_idx, legacy_day_col] = 0
                    # نشيل بس الأجزاء اللي بتاريخ اليوم ده من الملاحظات، ونسيب باقي الشهر زي ما هو
                    parts = [p.strip() for p in notes_preview.split(" | ")] if notes_preview and notes_preview != "nan" else []
                    kept_parts = [p for p in parts if not p.startswith(del_date_str)]
                    legacy_grid.at[row_idx, "سبب/ملاحظات"] = " | ".join(kept_parts)
                    write_gsheet(legacy_path, legacy_grid)
                    st.success("اتمسحت بيانات اليوم ده من الجدول ✔")
                    st.rerun()
            else:
                st.caption("مفيش أي عطل مسجل على خطك في اليوم ده")
        else:
            options_map = {}
            for i, row in my_day_incidents.iterrows():
                label = f"{row['من الساعة']}–{row['إلى الساعة']} | {row['مدة العطل (دقيقة)']:.0f} دقيقة | {row['سبب العطل'] or 'بدون سبب'}"
                options_map[label] = i
            picked_label = st.selectbox("اختر العطل اللي عايز تحذفه", list(options_map.keys()), key="fault_delete_pick")

            if st.button("🗑️ احذف العطل ده نهائيًا", key="fault_delete_confirm_btn"):
                picked_idx = options_map[picked_label]
                row_to_remove = my_day_incidents.iloc[picked_idx]

                full_log = load_daily_log()
                if "معرف العطل" in row_to_remove.index and str(row_to_remove["معرف العطل"]).strip():
                    match_mask = full_log["معرف العطل"] == row_to_remove["معرف العطل"]
                else:
                    match_mask = (
                        (full_log["الخط"] == row_to_remove["الخط"]) &
                        (full_log["التاريخ"].astype(str) == str(row_to_remove["التاريخ"])) &
                        (full_log["من الساعة"] == row_to_remove["من الساعة"]) &
                        (full_log["إلى الساعة"] == row_to_remove["إلى الساعة"]) &
                        (full_log["سبب العطل"] == row_to_remove["سبب العطل"]) &
                        (full_log["مدة العطل (دقيقة)"] == row_to_remove["مدة العطل (دقيقة)"])
                    )
                match_idx = full_log[match_mask].index
                if len(match_idx) > 0:
                    # نمسح أول تطابق بس، حتى لو فيه أكتر من عطل شبه بعضه بالظبط في نفس اليوم
                    full_log = full_log.drop(index=match_idx[0]).reset_index(drop=True)
                    write_gsheet(DAILY_LOG_SHEET, full_log)
                    sync_month_grid_from_log(my_line, del_date.strftime("%Y-%m"), full_log)
                    st.success("اتمسح العطل، والجدول الشهري اتحدّث تلقائي ✔")
                    st.rerun()
                else:
                    st.error("معلش، مقدرتش ألاقي العطل ده — جرب تحدّث الصفحة وحاول تاني")

    st.divider()

    # ==========================
    # اعتماد الأعطال وتكلفة الصيانة (مدير صيانة المصنع المختار بس)
    # ==========================
    st.subheader(f"🛠️ اعتماد أعطال {factory_pick} (مدير الصيانة)")
    maint_conf = FACTORY_CONFIG[factory_pick]
    maint_pass = st.text_input(
        f"🔒 كلمة مرور مدير صيانة {factory_pick}", type="password", key="maint_approval_pass"
    )

    if maint_pass and maint_pass != maint_conf["maint_password"]:
        st.warning("كلمة مرور مدير الصيانة غلط")
    elif maint_pass == maint_conf["maint_password"]:
        st.success(f"تم التحقق ✔ — {maint_conf['maint_name']}، تقدر تعتمد أعطال {factory_pick} وتحدد تكلفة الصيانة")

        HAS_DIALOG = hasattr(st, "dialog")
        approver_signature = maint_conf["maint_name"]

        def _save_fault_approval(fault_id, no_cost, cost_val):
            full_log_now = load_daily_log()
            idx_match = full_log_now[full_log_now["معرف العطل"] == fault_id].index
            if len(idx_match) == 0:
                st.error("معلش، العطل ده مش موجود دلوقتي (يمكن اتعتمد أو اتحذف من مكان تاني)")
                return
            full_log_now.loc[idx_match[0], "الحالة"] = STATUS_APPROVED
            full_log_now.loc[idx_match[0], "تكلفة الصيانة (جنيه)"] = 0.0 if no_cost else float(cost_val)
            full_log_now.loc[idx_match[0], "معتمد بواسطة"] = f"اعتماد مدير صيانة {factory_pick}: {approver_signature}"
            full_log_now.loc[idx_match[0], "تاريخ الاعتماد"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            write_gsheet(DAILY_LOG_SHEET, full_log_now)

            line_for_sync = full_log_now.loc[idx_match[0], "الخط"]
            month_for_sync = str(full_log_now.loc[idx_match[0], "التاريخ"])[:7]
            sync_month_grid_from_log(line_for_sync, month_for_sync, full_log_now)

            st.success("تم اعتماد العطل ✔")
            st.rerun()

        def _render_approval_form(row, key_prefix):
            no_cost = st.checkbox("☐ لا توجد تكلفة مادية", key=f"{key_prefix}_no_cost")
            cost_val = 0.0
            if not no_cost:
                cost_val = st.number_input(
                    "💰 قيمة التكلفة (جنيه)", min_value=0.0, step=1.0, key=f"{key_prefix}_cost"
                )
            st.caption(f"هيتسجل توقيع الاعتماد باسم: **{approver_signature}**")
            if st.button("💾 حفظ الاعتماد", key=f"{key_prefix}_save"):
                _save_fault_approval(row["معرف العطل"], no_cost, cost_val)

        maint_review_date = st.date_input(
            "📅 اختار تاريخ الأعطال اللي عايز تراجعها وتعتمدها",
            value=datetime.now().date(), key=f"maint_review_date_{factory_pick}"
        )
        maint_review_date_str = maint_review_date.strftime("%Y-%m-%d")

        full_log_appr = load_daily_log()
        pending_df = full_log_appr[
            (full_log_appr["الحالة"] == STATUS_PENDING) & (full_log_appr["الخط"].isin(fault_lines)) &
            (full_log_appr["التاريخ"] == maint_review_date_str)
        ].copy()

        if pending_df.empty:
            st.info(f"مفيش أي أعطال محتاجة اعتماد في {factory_pick} ليوم {maint_review_date_str} ✅")
        else:
            st.caption(f"فيه {len(pending_df)} عطل مستني اعتماد في {factory_pick} ليوم {maint_review_date_str}")
            for _, prow in pending_df.sort_values("التاريخ", ascending=False).iterrows():
                fid = prow["معرف العطل"]
                with st.container(border=True):
                    st.markdown(
                        f"**⚠️ {prow['الخط']}** — {prow['التاريخ']} | {prow['الوردية']} | "
                        f"{prow['من الساعة']}–{prow['إلى الساعة']} | ⏰ {prow['مدة العطل (دقيقة)']:.0f} دقيقة  \n"
                        f"سبب العطل: {prow['سبب العطل'] or '—'}"
                    )
                    if HAS_DIALOG:
                        if st.button("✅ اعتماد", key=f"approve_btn_{fid}"):
                            @st.dialog(f"اعتماد عطل خط {prow['الخط']}")
                            def _approval_dialog(row=prow, kp=fid):
                                st.write(
                                    f"📅 {row['التاريخ']} | ⏰ {row['مدة العطل (دقيقة)']:.0f} دقيقة | "
                                    f"سبب: {row['سبب العطل'] or '—'}"
                                )
                                _render_approval_form(row, f"dlg_{kp}")
                            _approval_dialog()
                    else:
                        with st.expander("✅ اعتماد هذا العطل وتحديد التكلفة"):
                            _render_approval_form(prow, f"exp_{fid}")

    # ==========================
    # الجدول التجميعي الشهري (DataFrame) — عرض بس، متاح لأي حد يشوفه
    # ==========================
    faults_grid, FAULTS_FILE, _ = load_faults_grid(selected_month_f, fault_lines)

    if faults_grid is None:
        st.error(
            "⚠️ تعذّر الاتصال بجوجل شيت دلوقتي (زحمة مؤقتة على الـ API). "
            "بياناتك القديمة آمنة ومتأثرتش، بس معرفناش نجيبها عشان نعرضها. "
            "استنى كام ثانية واعمل تحديث للصفحة (F5) وجرب تاني."
        )
        st.stop()

    for dc in day_cols_f:
        faults_grid[dc] = pd.to_numeric(faults_grid[dc], errors="coerce").fillna(0)

    # ==========================
    # 🍬 تقرير تفصيلي — مصنع الكاندي (بنفس شكل ملف الإكسيل اللي بيتسجل بيه يدوي كل يوم)
    # ==========================
    st.divider()
    st.subheader("🍬 تقرير تفصيلي — مصنع الكاندي")
    st.caption("سجّل بيانات النهاردة زي ما بتسجلها في الإكسيل بالظبط، واطبعها بنفس الشكل جاهزة للإدارة")

    # نفس القوائم والترتيب اللي في الملف الأصلي بالظبط، من غير أي تعديل أو حذف تكرار
    CANDY_LINES = ["الخط المستمر", "الخط الايطالي", "الخط البوليمكس", "خط اكلير (3)"]
    CANDY_TOFFEE = ["الطباخ", "ماكينة صيني 1", "ماكينة صيني 2", "ماكينة صيني 2",
                     "ماكينة ناجيما 1", "ماكينة ناجيما 2", "ماكينة ناجيما 3"]
    CANDY_WRAPPING = ["فلوباك 3", ""]
    CANDY_FILLING = ["ماكينة الاشيدا", "ماكينة C1", "ماكينة C2", "ماكينة C3",
                       "ماكينة C4", "ماكينة C4", "ماكينة C5", "ماكينة C6", "ماكينة C7"]
    CANDY_FAULT_COLS = ["الوردية", "وقت العطل", "وقت الإصلاح", "مدة العطل (دقيقة)", "سبب العطل"]

    def _candy_default_rows(names):
        return pd.DataFrame([
            {"الماكينة": n, "الوردية": "", "وقت العطل": "", "وقت الإصلاح": "", "مدة العطل (دقيقة)": "", "سبب العطل": "لا يوجد أعطال"}
            for n in names
        ])

    candy_date = st.date_input("📅 تاريخ التقرير", value=today_f, key="candy_report_date")
    candy_date_str = candy_date.strftime("%Y-%m-%d")
    CANDY_SHEET = f"candy_faults_{candy_date_str}"

    candy_raw = read_gsheet_strict(CANDY_SHEET)
    if candy_raw is None:
        st.error(
            "⚠️ تعذّر الاتصال بجوجل شيت دلوقتي (زحمة مؤقتة على الـ API). "
            "بياناتك آمنة ومتأثرتش، بس معرفناش نجيبها. جرب تحدّث الصفحة بعد كام ثانية."
        )
        st.stop()

    candy_all_cols = ["القسم", "الماكينة"] + CANDY_FAULT_COLS
    if candy_raw.empty:
        candy_default = pd.concat([
            _candy_default_rows(CANDY_LINES).assign(القسم="الخطوط"),
            _candy_default_rows(CANDY_TOFFEE).assign(القسم="الطوفي"),
            _candy_default_rows(CANDY_WRAPPING).assign(القسم="التغليف"),
            _candy_default_rows(CANDY_FILLING).assign(القسم="التعبئة"),
        ], ignore_index=True)[candy_all_cols]
        candy_grid = candy_default
    else:
        candy_grid = candy_raw
        for c in candy_all_cols:
            if c not in candy_grid.columns:
                candy_grid[c] = ""
        candy_grid = candy_grid[candy_all_cols]

    edited_candy = st.data_editor(
        candy_grid,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key=f"candy_editor_{candy_date_str}",
        disabled=["القسم", "الماكينة"],
        column_config={
            "القسم": st.column_config.TextColumn("القسم", pinned=True),
            "الماكينة": st.column_config.TextColumn("الماكينة / الخط", pinned=True, width="medium"),
            "الوردية": st.column_config.TextColumn("الوردية"),
            "وقت العطل": st.column_config.TextColumn("وقت العطل"),
            "وقت الإصلاح": st.column_config.TextColumn("وقت الإصلاح"),
            "مدة العطل (دقيقة)": st.column_config.TextColumn("مدة العطل (دقيقة)"),
            "سبب العطل": st.column_config.TextColumn("سبب العطل"),
        }
    )

    if st.button("💾 حفظ تقرير الكاندي", key="candy_save_btn"):
        try:
            write_gsheet(CANDY_SHEET, edited_candy)
        except Exception as e:
            st.error(f"❌ فشل الحفظ — جرب تاني بعد شوية. (تفاصيل: {e})")
            st.stop()
        st.success(f"اتحفظ تقرير الكاندي ليوم {candy_date_str} ✔")
        st.rerun()

    # ---------- بناء التقرير القابل للطباعة بنفس شكل الإكسيل بالظبط ----------
    def _candy_section_table_html(df_section):
        return df_section[["الماكينة"] + CANDY_FAULT_COLS].rename(
            columns={"الماكينة": "الخط / الماكينة"}
        ).to_html(index=False, border=0, justify="center")

    candy_lines_df = edited_candy[edited_candy["القسم"] == "الخطوط"]
    candy_toffee_df = edited_candy[edited_candy["القسم"] == "الطوفي"]
    candy_wrapping_df = edited_candy[edited_candy["القسم"] == "التغليف"]
    candy_filling_df = edited_candy[edited_candy["القسم"] == "التعبئة"]

    candy_extra_html = f"""
    <div style="margin-top:10px;">
        <h2 style="margin-top:0; font-size:12px; color:{BRAND_GREEN};">🍬 الطوفي</h2>
        {_candy_section_table_html(candy_toffee_df)}
    </div>
    <div style="margin-top:14px;">
        <h2 style="margin-top:0; font-size:12px; color:{BRAND_GREEN};">📦 التغليف</h2>
        {_candy_section_table_html(candy_wrapping_df)}
    </div>
    <div style="margin-top:14px;">
        <h2 style="margin-top:0; font-size:12px; color:{BRAND_GREEN};">📥 التعبئة</h2>
        {_candy_section_table_html(candy_filling_df)}
    </div>
    """

    candy_report_html = build_printable_html(
        "اعطال مصنع الكاندي",
        f"تاريخ: {candy_date_str} — تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        candy_lines_df[["الماكينة"] + CANDY_FAULT_COLS].rename(columns={"الماكينة": "الخط"}),
        landscape=False,
        compact=True,
        extra_html=candy_extra_html,
    )

    st.download_button(
        "🖨️ تحميل تقرير مصنع الكاندي (PDF)",
        data=candy_report_html.encode("utf-8"),
        file_name=f"candy_faults_{candy_date_str}.html",
        mime="text/html",
        help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' أو اطبعه مباشرة",
        key="candy_report_print_btn"
    )

    # ==========================
    # دخول الأدمن — هو بس اللي يقدر يشوف التقارير والرسوم البيانية ويطبعها
    # ==========================
    st.divider()
    st.markdown("### 👑 دخول الأدمن (لعرض التقارير والرسوم البيانية والطباعة)")
    ADMIN_PASSWORD = "9999"
    admin_pass_input = st.text_input("🔒 كلمة مرور الأدمن", type="password", key="faults_admin_pass")
    admin_ok = (admin_pass_input == ADMIN_PASSWORD)
    if admin_pass_input and not admin_ok:
        st.warning("كلمة مرور الأدمن غلط")

    if admin_ok:
        with st.expander("🔄 الأرقام مش متطابقة مع السجل التفصيلي؟ اضغط هنا تصلحها"):
            st.caption(
                "لو فيه عطل ظاهر في السجل التفصيلي بس الجدول أو التقرير بيوريه صفر (زي لو العطل اتسجل "
                "بنسخة قديمة من النظام)، الزرار ده بيعيد بناء الجدول الشهري بالكامل لكل الخطوط من السجل "
                "التفصيلي من الأول، عشان يبقوا متطابقين مع بعض."
            )
            if st.button(f"🔄 إعادة مزامنة جدول شهر {selected_month_f} بالكامل", key="faults_full_resync_btn"):
                resync_log = load_daily_log()
                progress = st.progress(0, text="بدء المزامنة...")
                for i, _line in enumerate(fault_lines):
                    sync_month_grid_from_log(_line, selected_month_f, resync_log)
                    progress.progress((i + 1) / len(fault_lines), text=f"اتزامن خط {_line} ✔")
                    if i < len(fault_lines) - 1:
                        time.sleep(1.2)
                st.success("اتظبطت المزامنة لكل الخطوط ✔")
                st.rerun()

        st.subheader(f"📋 الجدول التجميعي لأعطال شهر {selected_month_f}")
        st.caption("لو خط مسجلش أي عطل في يوم معين، بيظهر 'لا يوجد أعطال' بدل الصفر")

        display_grid_view = faults_grid.copy()
        for dc in day_cols_f:
            display_grid_view[dc] = display_grid_view[dc].apply(lambda v: "لا يوجد أعطال" if v == 0 else v)
        st.dataframe(display_grid_view, use_container_width=True, hide_index=True)

        # ==========================
        # ملخص تراكمي: الخط اتعطل لحد يوم كام قد ايه
        # ==========================
        st.divider()
        st.subheader("📊 ملخص تراكمي (من أول الشهر لحد يوم معين)")

        default_ref_day = min(today_f.day, days_in_month_f) if selected_month_f == today_f.strftime("%Y-%m") else days_in_month_f
        ref_day = st.slider("لحد يوم", 1, days_in_month_f, default_ref_day, key="faults_ref_day")

        cols_up_to = [f"يوم {d}" for d in range(1, ref_day + 1)]
        cumulative = faults_grid[["الخط"] + cols_up_to].copy()
        cumulative["إجمالي حتى الآن (دقيقة)"] = cumulative[cols_up_to].sum(axis=1)
        cumulative["إجمالي حتى الآن (ساعة)"] = (cumulative["إجمالي حتى الآن (دقيقة)"] / 60).round(2)

        cum_display = cumulative[["الخط", "إجمالي حتى الآن (دقيقة)", "إجمالي حتى الآن (ساعة)"]].copy()
        cum_display["الحالة"] = cum_display["إجمالي حتى الآن (دقيقة)"].apply(
            lambda v: "لا يوجد أعطال" if v == 0 else f"{v:,.0f} دقيقة توقف"
        )
        st.dataframe(cum_display, use_container_width=True, hide_index=True)

        cumulative_report_html = build_printable_html(
            f"تقرير إجمالي الأعطال الشهري (حتى يوم {ref_day})",
            f"شهر {selected_month_f} — من يوم 1 حتى يوم {ref_day} — تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            cum_display
        )
        st.download_button(
            "🖨️ تحميل تقرير الإجمالي التراكمي (للإدارة)",
            data=cumulative_report_html.encode("utf-8"),
            file_name=f"faults_cumulative_{selected_month_f}_upto_day{ref_day}.html",
            mime="text/html",
            help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' — جاهز يتبعت للإدارة",
            key="faults_cumulative_print_btn"
        )

        # ==========================
        # التقرير اليومي — تجميع أعطال يوم معين بشكل احترافي (من السجل التفصيلي)
        # ==========================
        st.divider()
        st.subheader("📄 التقرير اليومي للأعطال")
        st.caption("تقرير جاهز للطباعة والعرض على الإدارة — لكل المصنعين مع بعض، وكل خط ماسجلش عطل بيظهر جنبه 'لا يوجد عطل'")

        print_format_choice = st.radio(
            "🖨️ نوع النسخة القابلة للطباعة",
            ["📄 صفحة واحدة متصلة (Online / Email)", "🖨️ ورق A4 عادي (تلقائي متعدد الصفحات)"],
            horizontal=True, key="faults_daily_print_format"
        )

        daily_report_date = st.date_input("📅 اختر يوم التقرير", value=today_f, key="faults_daily_report_date")
        daily_report_date_str = daily_report_date.strftime("%Y-%m-%d")

        daily_log_all = load_daily_log()
        day_incidents = daily_log_all[
            (daily_log_all["التاريخ"] == daily_report_date_str) & (daily_log_all["الخط"].isin(ALL_FAULT_LINES))
        ].copy()

        # الخطوط اللي مسجلتش أي عطل اليوم ده — تظهر بصف "لا يوجد عطل" (لكل خطوط المصنعين مع بعض)
        lines_with_incident = set(day_incidents["الخط"])
        no_fault_rows = pd.DataFrame([
            {"التاريخ": daily_report_date_str, "الخط": l, "اسم الماكينة": "-", "الوردية": "-",
             "من الساعة": "-", "إلى الساعة": "-", "مدة العطل (دقيقة)": 0, "سبب العطل": "لا يوجد عطل",
             "الحالة": "-", "تكلفة الصيانة (جنيه)": 0, "معتمد بواسطة": "-"}
            for l in ALL_FAULT_LINES if l not in lines_with_incident
        ])

        # نحدد فعلاً أي مصنع اتعمله اعتماد النهاردة (من عمود الحالة قبل ما نشيله من جدول العرض)
        approved_today = day_incidents[day_incidents["الحالة"] == STATUS_APPROVED]
        factories_approved_today = [
            f_name for f_name, f_conf in FACTORY_CONFIG.items()
            if approved_today["الخط"].isin(f_conf["lines"]).any()
        ]

        daily_report_df = pd.concat([day_incidents, no_fault_rows], ignore_index=True)
        daily_report_df["تكلفة الصيانة (جنيه)"] = pd.to_numeric(
            daily_report_df["تكلفة الصيانة (جنيه)"], errors="coerce"
        ).fillna(0)
        # الحالة والاعتماد مش بيتحطوا كخانة لكل عطل في التقرير — بدالهم إمضاء واحد في آخر التقرير
        # لكل مدير صيانة، وهو ده اللي بيبقى ضامن لكل الأعطال المسجلة في اليوم ده
        daily_report_df = daily_report_df[[
            "الخط", "اسم الماكينة", "الوردية", "من الساعة", "إلى الساعة", "مدة العطل (دقيقة)", "سبب العطل",
            "تكلفة الصيانة (جنيه)",
        ]]
        daily_report_df = daily_report_df.sort_values("الخط").reset_index(drop=True)

        # الخطوط اللي فعلاً اتعطلت اليوم ده — هتتلوّن صفوفها بالأصفر في تقرير الطباعة
        daily_highlight_mask = (daily_report_df["سبب العطل"] != "لا يوجد عطل").tolist()

        total_day_minutes = daily_report_df["مدة العطل (دقيقة)"].sum()
        lines_with_faults = len(lines_with_incident)
        total_incidents_today = len(day_incidents)

        if not day_incidents.empty:
            _durations = pd.to_numeric(day_incidents["مدة العطل (دقيقة)"], errors="coerce").fillna(0)
            _max_idx = _durations.idxmax()
            max_downtime_val = _durations.loc[_max_idx]
            max_downtime_line = day_incidents.loc[_max_idx, "الخط"]
            avg_downtime_val = total_day_minutes / total_incidents_today
        else:
            max_downtime_val, max_downtime_line, avg_downtime_val = 0, "-", 0
        fault_ratio_pct = (total_day_minutes / (len(ALL_FAULT_LINES) * 24 * 60)) * 100

        st.markdown("#### 🔎 ملخص سريع لليوم")
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("⚠ إجمالي الأعطال", f"{total_incidents_today} عطل")
        k2.metric("⏱ إجمالي مدة التوقف", f"{total_day_minutes:,.0f} دقيقة")
        k3.metric("⏳ بالساعة", f"{(total_day_minutes/60):,.2f} ساعة")
        k4.metric("🔺 أعلى توقف لعطل واحد", f"{max_downtime_val:,.0f} دقيقة", help=f"خط {max_downtime_line}" if max_downtime_line != "-" else None)
        k5.metric("🕐 متوسط التوقف للعطل", f"{avg_downtime_val:,.1f} دقيقة")
        k6.metric("📊 نسبة التوقف من التشغيل", f"{fault_ratio_pct:.1f}%")

        st.dataframe(daily_report_df, use_container_width=True, hide_index=True)

        def _build_signature_block(font_size_label, font_size_name, margin_top, extra_style=""):
            if not factories_approved_today:
                return f"""
                <div style="margin-top:{margin_top}px; padding:10px 16px; background:#fef3c7;
                            border-right:4px solid #d97706; border-radius:8px; {extra_style}">
                    <div style="font-size:{font_size_label}px; color:#92400e;">⏳ لسه مفيش اعتماد من مدير الصيانة على أعطال اليوم ده</div>
                </div>
                """
            names_line = " &nbsp;&amp;&nbsp; ".join(
                FACTORY_CONFIG[f]["maint_name"] for f in factories_approved_today
            )
            label = (
                f"✅ تم الاعتماد من قبل مدير صيانة {factories_approved_today[0]}"
                if len(factories_approved_today) == 1
                else "✅ تم الاعتماد من قبل مديري صيانة مصنع 1 و 2"
            )
            return f"""
            <div style="margin-top:{margin_top}px; padding:10px 16px; background:linear-gradient(90deg,#f8fafc,#eef2f7);
                        border-right:4px solid #16a34a; border-radius:8px; {extra_style}">
                <div style="font-size:{font_size_label}px; color:#374151;">{label}</div>
                <div style="font-family:'Segoe Script','Brush Script MT',cursive; font-style:italic; font-size:{font_size_name}px;
                            color:#0b1f3a; margin-top:3px; letter-spacing:0.5px;">
                    {names_line}
                </div>
            </div>
            """

        st.markdown(_build_signature_block(13, 22, 8), unsafe_allow_html=True)

        # ================= تفاصيل كل مصنع لوحده: الترتيب + التوقف الشهري + الرسوم البيانية =================
        report_month_str = daily_report_date.strftime("%Y-%m")
        date_from_str = f"{report_month_str}-01"
        month_log_upto = daily_log_all[
            (daily_log_all["التاريخ"] >= date_from_str) & (daily_log_all["التاريخ"] <= daily_report_date_str)
        ]

        # ---- MTTR (متوسط زمن إصلاح العطل) و MTBF (متوسط الزمن بين الأعطال) — من أول الشهر حتى اليوم ----
        # MTTR = متوسط مدة إصلاح العطل الواحد (زي ما هو مسجل)
        # MTBF = متوسط الوقت الفاصل بين نهاية عطل وبداية اللي بعده على نفس الخط (بيتحسب لكل خط لوحده
        # من التاريخ + الأوقات الفعلية المسجلة، وبعدين بناخد متوسط كل الخطوط)
        def _mttr_mtbf(log_slice, lines_list):
            durations = pd.to_numeric(log_slice["مدة العطل (دقيقة)"], errors="coerce").fillna(0)
            mttr = float(durations.mean()) if len(durations) > 0 else 0.0

            def _parse_dt(date_str, time_str):
                try:
                    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                except Exception:
                    return None

            line_mtbfs = []
            for ln in lines_list:
                line_log = log_slice[log_slice["الخط"] == ln].copy()
                if len(line_log) < 2:
                    continue
                line_log["start_dt"] = line_log.apply(lambda r: _parse_dt(r["التاريخ"], r["من الساعة"]), axis=1)
                line_log["end_dt"] = line_log.apply(lambda r: _parse_dt(r["التاريخ"], r["إلى الساعة"]), axis=1)
                line_log = line_log.dropna(subset=["start_dt", "end_dt"]).sort_values("start_dt")
                if len(line_log) < 2:
                    continue
                # لو وقت النهاية قبل وقت البداية، يبقى العطل عدى نص الليل لليوم اللي بعده
                line_log["end_dt"] = line_log.apply(
                    lambda r: r["end_dt"] + timedelta(days=1) if r["end_dt"] < r["start_dt"] else r["end_dt"], axis=1
                )
                gaps = []
                rows = line_log.to_dict("records")
                for i in range(1, len(rows)):
                    gap_min = (rows[i]["start_dt"] - rows[i - 1]["end_dt"]).total_seconds() / 60
                    if gap_min >= 0:
                        gaps.append(gap_min)
                if gaps:
                    line_mtbfs.append(sum(gaps) / len(gaps))

            mtbf = (sum(line_mtbfs) / len(line_mtbfs)) if line_mtbfs else 0.0
            return mttr, mtbf

        all_month_log = month_log_upto[month_log_upto["الخط"].isin(ALL_FAULT_LINES)]
        mttr_today, mtbf_today = _mttr_mtbf(all_month_log, ALL_FAULT_LINES)

        yesterday_log = all_month_log[all_month_log["التاريخ"] < daily_report_date_str]
        mttr_yday, mtbf_yday = _mttr_mtbf(yesterday_log, ALL_FAULT_LINES)

        mttr_trend = ((mttr_today - mttr_yday) / mttr_yday * 100) if mttr_yday > 0 else None
        mtbf_trend = ((mtbf_today - mtbf_yday) / mtbf_yday * 100) if mtbf_yday > 0 else None
        # في MTBF الأعلى أفضل (توقف أقل)، فعكسنا اتجاه اللون بالنسبة لـ MTTR
        mtbf_trend_display = -mtbf_trend if mtbf_trend is not None else None

        # تكلفة الصيانة المعتمدة اليوم بس (مش تراكمي الشهر) — التكلفة الفعلية اللي اتصرفت النهاردة
        today_maint_cost = pd.to_numeric(
            day_incidents.loc[day_incidents["الحالة"] == STATUS_APPROVED, "تكلفة الصيانة (جنيه)"],
            errors="coerce"
        ).fillna(0).sum()

        st.markdown("#### 🔧 مؤشرات الصيانة الهندسية (من أول الشهر حتى اليوم)")
        km1, km2, km3 = st.columns(3)
        km1.metric(
            "🔧 MTTR — متوسط زمن الإصلاح", f"{mttr_today:,.0f} دقيقة",
            delta=(f"{mttr_trend:+.0f}% عن أمس" if mttr_trend is not None else None), delta_color="inverse"
        )
        km2.metric(
            "⏳ MTBF — متوسط الزمن بين الأعطال", f"{mtbf_today/60:,.1f} ساعة",
            delta=(f"{mtbf_trend:+.0f}% عن أمس" if mtbf_trend is not None else None), delta_color="normal"
        )
        km3.metric("💰 Maintenance Cost — إجمالي اليوم", f"{today_maint_cost:,.0f} جنيه")

        trend_days_n = 7
        trend_day_list = [(daily_report_date - timedelta(days=i)) for i in range(trend_days_n - 1, -1, -1)]
        trend_day_strs = [d.strftime("%Y-%m-%d") for d in trend_day_list]

        def _build_factory_detail(f_name, f_lines):
            # ملحوظة مهمة: كل الأرقام هنا (عدد، توقف، تكلفة) بتتحسب من "السجل التفصيلي" (daily_log)
            # نفسه عشان الجداول والرسومات تفضل متطابقة دايمًا من غير أي تعارض
            f_month_log = month_log_upto[month_log_upto["الخط"].isin(f_lines)].copy()
            f_month_log["مدة العطل (دقيقة)"] = pd.to_numeric(f_month_log["مدة العطل (دقيقة)"], errors="coerce").fillna(0)

            f_cost_log = f_month_log[f_month_log["الحالة"] == STATUS_APPROVED].copy()
            f_cost_log["تكلفة الصيانة (جنيه)"] = pd.to_numeric(f_cost_log["تكلفة الصيانة (جنيه)"], errors="coerce").fillna(0)
            f_cost = f_cost_log.groupby("الخط")["تكلفة الصيانة (جنيه)"].sum().reindex(f_lines).fillna(0)

            f_agg = f_month_log.groupby("الخط").agg(
                **{"عدد الأعطال": ("مدة العطل (دقيقة)", "count"), "إجمالي التوقف (دقيقة)": ("مدة العطل (دقيقة)", "sum")}
            ).reindex(f_lines).fillna(0)
            f_agg["عدد الأعطال"] = f_agg["عدد الأعطال"].astype(int)
            f_agg["إجمالي التوقف (ساعة)"] = (f_agg["إجمالي التوقف (دقيقة)"] / 60).round(2)
            f_agg["متوسط زمن الإصلاح (دقيقة)"] = f_agg.apply(
                lambda r: round(r["إجمالي التوقف (دقيقة)"] / r["عدد الأعطال"], 1) if r["عدد الأعطال"] > 0 else 0, axis=1
            )
            f_agg["تكلفة الصيانة (جنيه)"] = f_cost.reindex(f_lines).fillna(0).values
            f_agg = f_agg.reset_index().rename(columns={"index": "الخط"})
            f_agg = f_agg[[
                "الخط", "عدد الأعطال", "إجمالي التوقف (دقيقة)", "إجمالي التوقف (ساعة)",
                "متوسط زمن الإصلاح (دقيقة)", "تكلفة الصيانة (جنيه)"
            ]]
            f_agg_sorted = f_agg.sort_values("إجمالي التوقف (دقيقة)", ascending=False).reset_index(drop=True)

            total_faults_n = int(f_agg_sorted["عدد الأعطال"].sum())
            total_downtime_min = float(f_agg_sorted["إجمالي التوقف (دقيقة)"].sum())
            total_row = pd.DataFrame([{
                "الخط": "الإجمالي",
                "عدد الأعطال": total_faults_n,
                "إجمالي التوقف (دقيقة)": total_downtime_min,
                "إجمالي التوقف (ساعة)": round(total_downtime_min / 60, 2),
                "متوسط زمن الإصلاح (دقيقة)": round(total_downtime_min / total_faults_n, 1) if total_faults_n > 0 else 0,
                "تكلفة الصيانة (جنيه)": float(f_agg_sorted["تكلفة الصيانة (جنيه)"].sum()),
            }])
            f_summary = pd.concat([f_agg_sorted, total_row], ignore_index=True)

            # رسم Pareto: أعمدة التوقف بالدقيقة (تنازلي) + خط النسبة التراكمية %
            fig_b, ax_b = plt.subplots(figsize=(4.4, 2.3))
            fig_b.patch.set_facecolor("#ffffff")
            bar_values = f_agg_sorted["إجمالي التوقف (دقيقة)"].tolist()
            bar_labels = [ar_text(l) for l in f_agg_sorted["الخط"].tolist()]
            cum_minutes = f_agg_sorted["إجمالي التوقف (دقيقة)"].cumsum()
            cum_pct = (cum_minutes / total_downtime_min * 100) if total_downtime_min > 0 else cum_minutes * 0

            bars = ax_b.bar(bar_labels, bar_values, color="#2f6fed", edgecolor="#0b1f3a", linewidth=0.6, zorder=2)
            ax_b.set_ylabel(ar_text("دقيقة"), fontsize=8, fontweight="bold")
            ax_b.set_title(ar_text(f"{f_name} — إجمالي التوقف لكل خط حتى {daily_report_date_str}"), fontsize=9.5, fontweight="bold", color=BRAND_GREEN, pad=8)
            ax_b.spines["top"].set_visible(False)
            ax_b.grid(axis="y", linestyle="--", alpha=0.3)
            ax_b.set_axisbelow(True)
            max_bar_val = max(bar_values) if bar_values and max(bar_values) > 0 else 1
            for b in bars:
                h = b.get_height()
                ax_b.text(b.get_x() + b.get_width() / 2, h + max_bar_val * 0.02, f"{h:,.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", color="#0b1f3a")

            ax_b2 = ax_b.twinx()
            ax_b2.plot(bar_labels, cum_pct.tolist(), color="#dc2626", marker="o", markersize=4, linewidth=1.8, zorder=3)
            ax_b2.set_ylim(0, 110)
            ax_b2.set_ylabel(ar_text("النسبة التراكمية %"), fontsize=8, fontweight="bold", color="#dc2626")
            ax_b2.spines["top"].set_visible(False)
            ax_b2.tick_params(axis="y", colors="#dc2626")
            for x, y in zip(bar_labels, cum_pct.tolist()):
                ax_b2.text(x, y + 3, f"{y:.0f}%", ha="center", va="bottom", fontsize=6.5, fontweight="bold", color="#dc2626")

            plt.setp(ax_b.get_xticklabels(), rotation=20, ha="right", fontsize=7, fontweight="bold")
            fig_b.tight_layout()
            bar_buf = io.BytesIO()
            fig_b.savefig(bar_buf, format="png", dpi=150, bbox_inches="tight")
            bar_b64 = base64.b64encode(bar_buf.getvalue()).decode()

            # ترتيب حسب عدد الأعطال
            f_counts_sorted = f_agg.set_index("الخط")["عدد الأعطال"].sort_values(ascending=False)
            max_count = max(int(f_counts_sorted.max()), 1)
            f_rank_html = ""
            for line_name, cnt in f_counts_sorted.items():
                pct = (int(cnt) / max_count) * 100
                f_rank_html += f"""
                <div class="rank-row">
                    <div class="rank-header"><span class="rank-label">{line_name}</span><span class="rank-num">{int(cnt)}</span></div>
                    <div class="rank-track"><div class="rank-fill" style="width:{pct:.0f}%;"></div></div>
                </div>
                """

            # تطور الأعطال اليومي آخر 7 أيام
            f_trend_log = daily_log_all[daily_log_all["التاريخ"].isin(trend_day_strs) & daily_log_all["الخط"].isin(f_lines)]
            f_trend_counts = f_trend_log.groupby(["التاريخ", "الخط"]).size().unstack(fill_value=0)
            f_trend_counts = f_trend_counts.reindex(index=trend_day_strs, columns=f_lines, fill_value=0)

            fig_t, ax_t = plt.subplots(figsize=(4.2, 2.1))
            fig_t.patch.set_facecolor("#ffffff")
            trend_colors = [BRAND_PALETTE[i % len(BRAND_PALETTE)] for i in range(len(f_lines))]
            x_positions = range(len(trend_day_strs))
            for i, line_name in enumerate(f_lines):
                ax_t.plot(x_positions, f_trend_counts[line_name].values, marker="o", markersize=3,
                          linewidth=1.6, label=ar_text(line_name), color=trend_colors[i])
            ax_t.set_xticks(list(x_positions))
            ax_t.set_xticklabels([d[5:] for d in trend_day_strs], fontsize=7, fontweight="bold")
            ax_t.set_ylabel(ar_text("عدد الأعطال"), fontsize=8, fontweight="bold")
            ax_t.set_title(ar_text(f"{f_name} — تطور الأعطال اليومي"), fontsize=9.5, fontweight="bold", color=BRAND_GREEN, pad=8)
            ax_t.spines["top"].set_visible(False)
            ax_t.spines["right"].set_visible(False)
            ax_t.grid(axis="y", linestyle="--", alpha=0.3)
            ax_t.set_axisbelow(True)
            ax_t.legend(fontsize=6, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.28), frameon=False)
            fig_t.tight_layout()
            trend_buf = io.BytesIO()
            fig_t.savefig(trend_buf, format="png", dpi=150, bbox_inches="tight")
            trend_b64 = base64.b64encode(trend_buf.getvalue()).decode()

            plt.close(fig_b)
            plt.close(fig_t)

            # تكلفة الصيانة (f_cost) اتحسبت فوق قبل الجدول المجمّع — بنعيد استخدامها هنا للرسم التقدمي
            f_cost_sorted = f_cost.sort_values(ascending=False)
            f_cost_total = float(f_cost.sum())

            # نفس شكل رسم "ترتيب الخطوط حسب عدد الأعطال" بالظبط — صفوف بار تقدمي (Progress bar)
            max_cost_val = max(float(f_cost_sorted.max()), 1) if len(f_cost_sorted) else 1
            f_cost_rank_html = ""
            for line_name, val in f_cost_sorted.items():
                pct = (float(val) / max_cost_val) * 100
                f_cost_rank_html += f"""
                <div class="rank-row">
                    <div class="rank-header"><span class="rank-label">{line_name}</span><span class="rank-num">{val:,.0f} ج</span></div>
                    <div class="rank-track"><div class="rank-fill" style="width:{pct:.0f}%;"></div></div>
                </div>
                """

            return {
                "summary": f_summary, "bar_b64": bar_b64, "rank_html": f_rank_html,
                "counts_sorted": f_counts_sorted, "trend_counts": f_trend_counts, "trend_b64": trend_b64,
                "cost_sorted": f_cost_sorted, "cost_rank_html": f_cost_rank_html, "cost_total": f_cost_total,
            }

        FACTORY_ACCENTS = {"مصنع 1": "#2563eb", "مصنع 2": "#7c3aed"}
        factory_details = {}
        for f_name in FACTORY_CONFIG.keys():
            f_lines_iter = FACTORY_CONFIG[f_name]["lines"]
            result = _build_factory_detail(f_name, f_lines_iter)
            factory_details[f_name] = result

            st.markdown(f"### 📍 تفاصيل {f_name}")
            st.markdown(f"#### 🏆 ترتيب خطوط {f_name} حسب عدد الأعطال (من أول شهر {report_month_str} حتى اليوم)")
            st.bar_chart(result["counts_sorted"])
            st.markdown(f"#### 📊 إجمالي التوقف الشهري لكل خط — {f_name} (من أول شهر {report_month_str} حتى يوم {daily_report_date.day})")
            st.dataframe(result["summary"], use_container_width=True, hide_index=True)
            st.markdown(f"#### 📈 تطور الأعطال اليومي — {f_name} (آخر 7 أيام)")
            st.line_chart(result["trend_counts"])
            st.markdown(f"#### 💰 تكلفة الصيانة حسب الخط — {f_name} (تراكمي من أول شهر {report_month_str} حتى اليوم)")
            st.caption(f"إجمالي تكلفة الصيانة (المعتمدة) لـ {f_name} حتى الآن: **{result['cost_total']:,.0f} جنيه**")
            st.bar_chart(result["cost_sorted"])
            st.divider()

        # ---- أكثر أسباب الأعطال اليوم ----
        if not day_incidents.empty:
            reasons_df = day_incidents.groupby("سبب العطل").size().reset_index(name="عدد الأعطال")
            reasons_df["النسبة %"] = (reasons_df["عدد الأعطال"] / total_incidents_today * 100).round(1)
            reasons_df = reasons_df.sort_values("عدد الأعطال", ascending=False).reset_index(drop=True)
        else:
            reasons_df = pd.DataFrame(columns=["سبب العطل", "عدد الأعطال", "النسبة %"])

        st.markdown("#### 🧾 أكثر أسباب الأعطال اليوم")
        if reasons_df.empty:
            st.info("مفيش أي عطل مسجل اليوم ✅")
        else:
            st.dataframe(reasons_df, use_container_width=True, hide_index=True)

        # ---- ملاحظات تلقائية مختصرة ----
        notes_list = []
        if not day_incidents.empty:
            notes_list.append(f"أعلى مدة توقف اليوم كانت على خط {max_downtime_line} بمقدار {max_downtime_val:,.0f} دقيقة.")
            top_reason_row = reasons_df.iloc[0]
            notes_list.append(
                f"السبب الأكثر تكرارًا اليوم: {top_reason_row['سبب العطل']} "
                f"({int(top_reason_row['عدد الأعطال'])} من {total_incidents_today} عطل)."
            )
        else:
            notes_list.append("مفيش أي عطل مسجل على أي خط اليوم ✅")

        # ================= بناء نسخة الطباعة =================
        def _hex_to_rgba(hex_color, alpha):
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r},{g},{b},{alpha})"

        def kpi_card_html(icon, value, label, color, trend_pct=None):
            trend_html = ""
            if trend_pct is not None:
                t_color = "#16a34a" if trend_pct <= 0 else "#dc2626"
                t_arrow = "▼" if trend_pct <= 0 else "▲"
                trend_html = f'<div style="font-size:9px; font-weight:700; color:{t_color}; margin-top:2px;">{t_arrow} {abs(trend_pct):.0f}%</div>'
            bg_tint = _hex_to_rgba(color, 0.08)
            return f"""
            <div style="flex:1; background:{bg_tint}; border:1px solid {_hex_to_rgba(color, 0.35)}; border-right:4px solid {color};
                        border-radius:6px; padding:6px 8px; text-align:center;">
                <div style="font-size:14px;">{icon}</div>
                <div style="font-size:14px; font-weight:800; color:#0b1f3a;">{value}</div>
                <div style="font-size:8px; color:#374151; font-weight:600;">{label}</div>
                {trend_html}
            </div>
            """

        # تكلفة الصيانة اليوم (today_maint_cost) اتحسبت فوق قبل قسم مؤشرات الصيانة — بنعيد استخدامها هنا
        # MTTR/MTBF واتجاهاتهم اتحسبوا فوق قبل تفاصيل المصانع — بنعيد استخدامهم هنا في كروت الطباعة
        kpi_html = (
            '<div style="display:flex; gap:8px; margin:8px 0;">' + "".join([
                kpi_card_html("⚠", f"{total_incidents_today} عطل", "إجمالي الأعطال اليوم", "#dc2626"),
                kpi_card_html("⏱", f"{total_day_minutes:,.0f} دقيقة", "إجمالي مدة التوقف", "#2563eb"),
                kpi_card_html("🔺", f"{max_downtime_val:,.0f} دقيقة" + (f" ({max_downtime_line})" if max_downtime_line != "-" else ""), "أعلى توقف لعطل واحد", "#16a34a"),
                kpi_card_html("🕐", f"{avg_downtime_val:,.1f} دقيقة", "متوسط التوقف لكل عطل", "#7c3aed"),
            ]) + "</div>"
            + '<div style="display:flex; gap:8px; margin:8px 0;">' + "".join([
                kpi_card_html("📊", f"{fault_ratio_pct:.1f}%", "نسبة التوقف من إجمالي التشغيل", "#ea580c"),
                kpi_card_html("🔧", f"{mttr_today:,.0f} دقيقة", "MTTR — متوسط زمن الإصلاح", "#b91c1c", trend_pct=mttr_trend),
                kpi_card_html("⏳", f"{mtbf_today/60:,.1f} ساعة", "MTBF — متوسط الزمن بين الأعطال", "#0f766e", trend_pct=mtbf_trend_display),
                kpi_card_html("💰", f"{today_maint_cost:,.0f} جنيه", "Maintenance Cost — إجمالي اليوم", "#c026d3"),
            ]) + "</div>"
        )

        reasons_html_table = (
            reasons_df.to_html(index=False, border=0, justify="center")
            if not reasons_df.empty else "<p style='font-size:9px; color:#6b7280;'>مفيش أي عطل مسجل اليوم ✅</p>"
        )
        notes_html = "".join(f"<li style='margin-bottom:3px;'>{n}</li>" for n in notes_list)

        signature_html = _build_signature_block(11, 18, 10, extra_style="page-break-inside:avoid;")

        def _factory_block_html(f_name, det, accent):
            summary_html = det["summary"].to_html(index=False, border=0, justify="center")
            return f"""
            <div style="margin-top:12px; border:1px solid #e5e7eb; border-right:5px solid {accent};
                        border-radius:8px; padding:10px 12px; background:#fff;">
                <h2 style="margin-top:0; font-size:12px; color:{accent};">📍 تفاصيل {f_name}</h2>
                <div style="display:flex; gap:12px;">
                    <div class="side-small" style="flex:1;">
                        <h2 style="margin-top:0; font-size:10.5px;">🏆 ترتيب الخطوط حسب عدد الأعطال</h2>
                        <div class="rank-list">{det['rank_html']}</div>
                    </div>
                    <div class="side-small" style="flex:1;">
                        <h2 style="margin-top:0; font-size:10.5px;">📊 تفاصيل التوقف حسب الخط</h2>
                        {summary_html}
                    </div>
                </div>
                <div style="display:flex; gap:12px; margin-top:8px;">
                    <div style="flex:1;">
                        <img src="data:image/png;base64,{det['bar_b64']}" style="width:100%; max-width:320px;">
                    </div>
                    <div style="flex:1;">
                        <img src="data:image/png;base64,{det['trend_b64']}" style="width:100%; max-width:320px;">
                    </div>
                </div>
                <div style="margin-top:8px;">
                    <h2 style="margin-top:0; font-size:10.5px;">💰 تكلفة الصيانة حسب الخط (تراكمي، معتمدة) — إجمالي {f_name}: {det['cost_total']:,.0f} جنيه</h2>
                    <div class="rank-list">{det['cost_rank_html']}</div>
                </div>
            </div>
            """

        factory_blocks_html = "".join(
            _factory_block_html(f_name, factory_details[f_name], FACTORY_ACCENTS[f_name])
            for f_name in FACTORY_CONFIG.keys()
        )

        daily_extra_html = f"""
        <style>
            .rank-row {{ margin-bottom: 5px; }}
            .rank-header {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:2px; }}
            .rank-label {{ font-weight:700; font-size:9px; color:#1a1d21; }}
            .rank-num {{ font-weight:800; font-size:10px; color:#0b1f3a; }}
            .rank-track {{ background:#e9edf3; border-radius:6px; height:6px; overflow:hidden; display:flex; flex-direction:row-reverse; }}
            .rank-fill {{ height:100%; border-radius:6px; background:linear-gradient(270deg,#2f6fed,#7aa6ff); }}
            .side-small {{ font-size:9px; }}
            .side-small table {{ font-size:9px; }}
            .bottom-col ul {{ margin:4px 0 0; padding-inline-start:16px; font-size:9px; color:#1a1d21; }}
        </style>
        {signature_html}
        {factory_blocks_html}
        <div style="margin-top:10px; display:flex; gap:12px;">
            <div class="bottom-col side-small" style="flex:1.2;">
                <h2 style="margin-top:0; font-size:11px;">🧾 أكثر أسباب الأعطال اليوم</h2>
                {reasons_html_table}
            </div>
            <div class="bottom-col" style="flex:1;">
                <h2 style="margin-top:0; font-size:11px;">📝 ملاحظات</h2>
                <ul>{notes_html}</ul>
            </div>
        </div>
        """

        # ---- ارتفاع الصفحة عشان نسخة "صفحة واحدة متصلة" تطلع من غير تقطيع (مش مستخدم في نسخة A4) ----
        daily_single_page_height_mm = (
            190
            + (len(daily_report_df) * 7)
            + sum(max(len(FACTORY_CONFIG[fn]["lines"]), 1) * 6 for fn in FACTORY_CONFIG)  # الترتيب لكل مصنع
            + sum(len(factory_details[fn]["summary"]) * 6 for fn in FACTORY_CONFIG)       # جداول التوقف لكل مصنع
            + (280 * len(FACTORY_CONFIG))  # صور الرسوم البيانية (باريتو + ترند لكل مصنع)
            + sum(max(len(FACTORY_CONFIG[fn]["lines"]), 1) * 6 for fn in FACTORY_CONFIG)  # صفوف تكلفة الصيانة لكل مصنع
            + (len(reasons_df) * 6)
            + (len(notes_list) * 6)
            + 50  # الإمضاء
        )

        is_a4_mode = print_format_choice.startswith("🖨️")

        daily_report_html = build_printable_html(
            f"التقرير اليومي للأعطال — {daily_report_date_str}",
            f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')} — إجمالي التوقف: {total_day_minutes:,.0f} دقيقة",
            daily_report_df,
            landscape=False,
            compact=True,
            base_font_size=14 if not is_a4_mode else 11,
            highlight_mask=daily_highlight_mask,
            top_html=kpi_html,
            extra_html=daily_extra_html,
            # نسخة A4 من غير single_page_height_mm عشان تتقسم تلقائي على ورق A4 عادي بعدد الصفحات اللي يلزمها
            single_page_height_mm=None if is_a4_mode else daily_single_page_height_mm,
        )

        btn_label = (
            "🖨️ تحميل النسخة القابلة للطباعة (ورق A4 — كل حاجة كاملة)"
            if is_a4_mode else
            "🖨️ تحميل التقرير اليومي (للإدارة PDF — صفحة واحدة متصلة)"
        )
        btn_help = (
            "افتح الملف بعد التحميل، ودوس Ctrl+P واطبعها مباشرة على ورق A4 — ممكن تطلع 2 أو 3 صفحات وده طبيعي"
            if is_a4_mode else
            "افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' — جاهز يتبعت للإدارة"
        )
        file_suffix = "A4" if is_a4_mode else "online"

        st.download_button(
            btn_label,
            data=daily_report_html.encode("utf-8"),
            file_name=f"faults_daily_{file_suffix}_{daily_report_date.strftime('%Y-%m-%d')}.html",
            mime="text/html",
            help=btn_help,
            key="faults_daily_report_print_btn"
        )

    st.divider()
    st.subheader(f"📋 الشيت التفصيلي لأعطال شهر {selected_month_f}")
    st.caption("الجدول ده بيتحدث تلقائي من التسجيل اللي فوق، وتقدر كمان تعدل فيه يدوي مباشرة (لأي صلاحية إدارية)")

    edited_faults = st.data_editor(
        faults_grid,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"faults_monthly_editor_{selected_month_f}"
    )

    if st.button("💾 حفظ التعديلات اليدوية"):
        to_save_f = edited_faults.copy()
        to_save_f = to_save_f[to_save_f["الخط"].astype(str).str.strip() != ""]
        if to_save_f.empty:
            st.warning("اكتب اسم خط واحد على الأقل قبل الحفظ ⚠")
        else:
            write_gsheet(FAULTS_FILE, to_save_f)
            st.success(f"اتحفظت بيانات أعطال شهر {selected_month_f} ✔")

    st.divider()
    if admin_ok:
        st.subheader(f"📊 ملخص أعطال شهر {selected_month_f}")

        summary_f = edited_faults.copy()
        summary_f = summary_f[summary_f["الخط"].astype(str).str.strip() != ""]

        if summary_f.empty:
            st.info("سجل بيانات خط واحد على الأقل عشان يظهر الملخص")
        else:
            for dc in day_cols_f:
                summary_f[dc] = pd.to_numeric(summary_f[dc], errors="coerce").fillna(0)

            summary_f["إجمالي وقت التوقف (دقيقة)"] = summary_f[day_cols_f].sum(axis=1)
            summary_f["إجمالي وقت التوقف (ساعة)"] = (summary_f["إجمالي وقت التوقف (دقيقة)"] / 60).round(2)

            display_f = summary_f[["الخط", "سبب/ملاحظات", "إجمالي وقت التوقف (دقيقة)", "إجمالي وقت التوقف (ساعة)"]]
            st.dataframe(display_f, use_container_width=True, hide_index=True)

            c1, c2 = st.columns(2)
            c1.metric("⏰ إجمالي وقت التوقف", f"{summary_f['إجمالي وقت التوقف (دقيقة)'].sum():,.0f} دقيقة")
            c2.metric("⏱ بالساعات", f"{summary_f['إجمالي وقت التوقف (ساعة)'].sum():,.1f} ساعة")

            st.download_button(
                "⬇ تحميل بيانات الشهر CSV",
                data=summary_f.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"faults_{selected_month_f}.csv",
                mime="text/csv"
            )

            printable_html_f = build_printable_html(
                f"تقرير الأعطال — شهر {selected_month_f}",
                f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                display_f
            )
            st.download_button(
                "🖨️ تحميل نسخة قابلة للطباعة (PDF)",
                data=printable_html_f.encode("utf-8"),
                file_name=f"faults_{selected_month_f}.html",
                mime="text/html",
                help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' عشان تحوله PDF أو تطبعه"
            )

            st.divider()
            st.subheader("📈 الرسوم البيانية")

            line_totals = summary_f.set_index("الخط")["إجمالي وقت التوقف (دقيقة)"]

            st.caption("توزيع وقت التوقف بين الخطوط (دقيقة)")
            fig_f_tree = build_treemap_chart(line_totals, unit=" د")
            if fig_f_tree is not None:
                st.pyplot(fig_f_tree)

            st.markdown("#### 🔍 اتجاه التوقف اليومي")
            line_choice_f = st.selectbox("اختر الخط", summary_f["الخط"].unique(), key="faults_line_filter")
            line_row = summary_f[summary_f["الخط"] == line_choice_f]
            daily_trend_f = line_row[day_cols_f].sum(axis=0)
            daily_trend_f.index = range(1, len(day_cols_f) + 1)
            st.line_chart(daily_trend_f)

            # ---- رسوم إضافية من السجل التفصيلي: حسب الوردية وحسب الماكينة ----
            month_log = daily_log_all[daily_log_all["التاريخ"].str.startswith(selected_month_f)].copy()
            if not month_log.empty:
                st.markdown("#### 👷 التوقف حسب الوردية والماكينة (من السجل التفصيلي)")
                chart_c3, chart_c4 = st.columns(2)
                with chart_c3:
                    shift_totals = month_log[month_log["الوردية"].astype(str).str.strip() != ""].groupby("الوردية")["مدة العطل (دقيقة)"].sum()
                    if not shift_totals.empty:
                        st.caption("إجمالي دقائق التوقف حسب الوردية")
                        st.bar_chart(shift_totals)
                    else:
                        st.info("لا توجد بيانات وردية مسجلة لهذا الشهر")
                with chart_c4:
                    machine_totals = month_log[month_log["اسم الماكينة"].astype(str).str.strip() != ""].groupby("اسم الماكينة")["مدة العطل (دقيقة)"].sum().sort_values(ascending=False).head(10)
                    if not machine_totals.empty:
                        st.caption("أكثر 10 ماكينات توقفًا (دقيقة)")
                        st.bar_chart(machine_totals)
                    else:
                        st.info("لا توجد أسماء ماكينات مسجلة لهذا الشهر")
            else:
                st.caption("لسه مفيش سجل تفصيلي (بماكينة ووردية) لهذا الشهر عشان تظهر رسوم إضافية")



elif page == "الكسر":
    page_banner("🔨", "الكسر", "تسجيل الكسر الداخل والخارج لكل خط بنظام الرصيد (أول المدة → آخر المدة)")

    BREAKAGE_SHEET = "breakage_history"

    breakage_date = st.date_input("📅 اختر اليوم", value=datetime.now(), key="breakage_date_pick")
    breakage_date_str = breakage_date.strftime("%Y-%m-%d")

    all_lines_clean_b = [str(l).replace("🏭", "").strip() for l in st.session_state.production_lines]

    # ---------- هات إنتاج كل خط لنفس اليوم من صفحة Production (لاستخدامه في حساب نسبة الكسر %) ----------
    day_production = {ln: 0.0 for ln in all_lines_clean_b}
    daily_prod_totals_b = {}  # إجمالي إنتاج كل الخطوط لكل يوم (مطلوب لحساب اتجاه نسبة الكسر لآخر 7 أيام)
    if GSHEETS_ENABLED and gsheet_exists(PRODUCTION_SHEET):
        hist_df_b = read_gsheet(PRODUCTION_SHEET)
        hist_df_b["Date"] = hist_df_b["Date"].astype(str)
        all_shifts_b = hist_df_b[hist_df_b["Shift"] == "All Shifts"].copy()
        all_shifts_b["الفعلي (KG)"] = pd.to_numeric(all_shifts_b["الفعلي (KG)"], errors="coerce").fillna(0)
        daily_prod_totals_b = all_shifts_b.groupby("Date")["الفعلي (KG)"].sum().to_dict()

        day_hist_b = all_shifts_b[all_shifts_b["Date"] == breakage_date_str].copy()
        if not day_hist_b.empty:
            day_hist_b["Line"] = day_hist_b["Line"].astype(str).str.strip()
            prod_by_line_day = day_hist_b.groupby("Line")["الفعلي (KG)"].sum()
            for ln in all_lines_clean_b:
                if ln in prod_by_line_day.index:
                    day_production[ln] = float(prod_by_line_day[ln])

    # ---------- هات "متبقي الرصيد" آخر مرة اتسجلت لكل خط (قبل اليوم المختار) عشان يبقى "رصيد أول المدة" النهاردة ----------
    carry_forward = {ln: 0.0 for ln in all_lines_clean_b}
    breakage_log_all = pd.DataFrame()
    if GSHEETS_ENABLED and gsheet_exists(BREAKAGE_SHEET):
        breakage_log_all = read_gsheet(BREAKAGE_SHEET)
        needed_cols = {"Date", "الخط", "رصيد أول المدة (KG)", "كسر خارج (KG)", "كسر داخل (KG)"}
        if needed_cols.issubset(set(breakage_log_all.columns)):
            breakage_log_all["Date"] = breakage_log_all["Date"].astype(str)
            for nc in ["رصيد أول المدة (KG)", "كسر خارج (KG)", "كسر داخل (KG)"]:
                breakage_log_all[nc] = pd.to_numeric(breakage_log_all[nc], errors="coerce").fillna(0)
            breakage_log_all["الخط"] = breakage_log_all["الخط"].astype(str).str.strip()
            breakage_log_all["متبقي الرصيد (KG)"] = (
                breakage_log_all["رصيد أول المدة (KG)"] + breakage_log_all["كسر خارج (KG)"] - breakage_log_all["كسر داخل (KG)"]
            )
            prior = breakage_log_all[breakage_log_all["Date"] < breakage_date_str]
            if not prior.empty:
                last_per_line = prior.sort_values("Date").groupby("الخط").tail(1).set_index("الخط")["متبقي الرصيد (KG)"]
                for ln in all_lines_clean_b:
                    if ln in last_per_line.index:
                        carry_forward[ln] = float(last_per_line[ln])
        else:
            breakage_log_all = pd.DataFrame()

    # ================= تسجيل الكسر =================
    st.markdown(f"##### 📝 تسجيل الكسر — {breakage_date_str}")
    st.caption("رصيد أول المدة بييجي تلقائي من متبقي رصيد آخر يوم سجّلت فيه، وتقدر تعدّله يدوي لو حابب")

    entry_rows = [
        {"الخط": ln, "رصيد أول المدة (KG)": carry_forward[ln], "كسر خارج (KG)": 0, "كسر داخل (KG)": 0}
        for ln in all_lines_clean_b
    ]
    entry_df = pd.DataFrame(entry_rows)

    edited_entry = st.data_editor(
        entry_df,
        column_config={
            "الخط": st.column_config.TextColumn(disabled=True),
            "رصيد أول المدة (KG)": st.column_config.NumberColumn(min_value=0, step=1),
            "كسر خارج (KG)": st.column_config.NumberColumn(min_value=0, step=1),
            "كسر داخل (KG)": st.column_config.NumberColumn(min_value=0, step=1),
        },
        use_container_width=True,
        hide_index=True,
        key="breakage_entry_editor"
    )

    if st.button("💾 حفظ بيانات الكسر", type="primary"):
        to_save_b = edited_entry.copy()
        to_save_b = to_save_b[
            (to_save_b["رصيد أول المدة (KG)"] != 0) |
            (to_save_b["كسر خارج (KG)"] != 0) |
            (to_save_b["كسر داخل (KG)"] != 0)
        ]
        if to_save_b.empty:
            st.warning("مفيش بيانات كسر اتدخلت عشان تتحفظ ⚠")
        else:
            to_save_b.insert(0, "Date", breakage_date_str)
            to_save_b.insert(1, "Saved At", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            append_gsheet(BREAKAGE_SHEET, to_save_b)
            st.success(f"بيانات الكسر اتحفظت ✔ ({len(to_save_b)} صف)")
            st.rerun()

    # ================= السجل التفصيلي — قابل للتعديل والحذف =================
    st.divider()
    st.markdown("### 📋 سجل الكسر التفصيلي (تقدر تعدّل فيه أو تمسح صفوف)")

    if breakage_log_all.empty:
        st.info("لسه مفيش بيانات كسر محفوظة")
    else:
        display_log = breakage_log_all.drop(columns=["متبقي الرصيد (KG)"], errors="ignore").copy()
        edited_log = st.data_editor(
            display_log,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="breakage_log_editor"
        )
        if st.button("💾 حفظ التعديلات على السجل"):
            write_gsheet(BREAKAGE_SHEET, edited_log)
            st.success("اتحفظ التعديل على السجل ✔ (تعديل/حذف الصفوف اتطبق)")
            st.rerun()

    # ================= التقرير الاحترافي =================
    st.divider()
    st.markdown("### 📊 تقرير تحليل الكسر")

    if breakage_log_all.empty:
        st.info("لسه مفيش بيانات كسر محفوظة عشان يظهر التقرير")
    else:
        day_b = breakage_log_all[breakage_log_all["Date"] == breakage_date_str].copy()
        if day_b.empty:
            st.info("لسه مفيش بيانات كسر محفوظة لنفس اليوم")
        else:
            day_b_grouped = day_b.groupby("الخط")[["رصيد أول المدة (KG)", "كسر خارج (KG)", "كسر داخل (KG)"]].sum()
            day_b_grouped = day_b_grouped.reindex(all_lines_clean_b, fill_value=0)

            line_rows_b = []
            total_prod_day = sum(day_production.values())
            for ln in all_lines_clean_b:
                opening = day_b_grouped.loc[ln, "رصيد أول المدة (KG)"]
                out_v = day_b_grouped.loc[ln, "كسر خارج (KG)"]
                in_v = day_b_grouped.loc[ln, "كسر داخل (KG)"]
                total_v = opening + out_v
                remaining_v = total_v - in_v
                prod_v = day_production.get(ln, 0)
                # نسبة الكسر بتتحسب من الكسر الخارج بس (مش الداخل)
                pct_v = (out_v / prod_v * 100) if prod_v > 0 else 0
                line_rows_b.append({
                    "name": ln, "opening": opening, "out": out_v, "in": in_v,
                    "total": total_v, "remaining": remaining_v, "pct": pct_v
                })

            tot_opening = sum(r["opening"] for r in line_rows_b)
            tot_out = sum(r["out"] for r in line_rows_b)
            tot_in = sum(r["in"] for r in line_rows_b)
            tot_total = sum(r["total"] for r in line_rows_b)
            tot_remaining = sum(r["remaining"] for r in line_rows_b)
            # نسبة الكسر الإجمالية بتتحسب من الكسر الخارج بس (مش الداخل)
            tot_break_pct = (tot_out / total_prod_day * 100) if total_prod_day > 0 else 0
            tot_out_pct = (tot_out / total_prod_day * 100) if total_prod_day > 0 else 0
            tot_in_pct = (tot_in / total_prod_day * 100) if total_prod_day > 0 else 0
            tot_out_kgton = (tot_out / total_prod_day * 1000) if total_prod_day > 0 else 0
            tot_in_kgton = (tot_in / total_prod_day * 1000) if total_prod_day > 0 else 0
            tot_efficiency = max(0, 100 - tot_break_pct)

            totals_b = {
                "out": tot_out, "out_pct": tot_out_pct, "out_kgton": tot_out_kgton,
                "in": tot_in, "in_pct": tot_in_pct, "in_kgton": tot_in_kgton,
                "remaining": tot_remaining, "production": total_prod_day,
                "break_pct": tot_break_pct, "efficiency": tot_efficiency,
            }

            # ---------- اتجاه نسبة الكسر (داخل/خارج) آخر 7 أيام ----------
            trend_dates_b = [(breakage_date - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
            trend_out_pct_b, trend_in_pct_b = [], []
            daily_totals_b = breakage_log_all.groupby("Date")[["كسر خارج (KG)", "كسر داخل (KG)"]].sum()
            for d in trend_dates_b:
                d_prod = daily_prod_totals_b.get(d, 0)
                if d in daily_totals_b.index and d_prod > 0:
                    trend_out_pct_b.append(round(float(daily_totals_b.loc[d, "كسر خارج (KG)"]) / d_prod * 100, 2))
                    trend_in_pct_b.append(round(float(daily_totals_b.loc[d, "كسر داخل (KG)"]) / d_prod * 100, 2))
                else:
                    trend_out_pct_b.append(0.0)
                    trend_in_pct_b.append(0.0)

            # ---------- تقدير ارتفاع الصفحة المناسب للمحتوى (صفحة واحدة متصلة عند الطباعة/PDF) ----------
            num_lines_b = len(line_rows_b)
            breakage_page_height_mm = 130 + (num_lines_b * 8) + 90 + 75 + 30

            breakage_html = build_breakage_report_html(
                totals_b, line_rows_b, trend_dates_b, trend_out_pct_b, trend_in_pct_b,
                breakage_date_str, page_height_mm=breakage_page_height_mm
            )
            components.html(breakage_html, height=1200, scrolling=False)

            st.download_button(
                "🖨️ تحميل التقرير (HTML) — يتفتح ويتطبع أو يتحفظ PDF",
                data=breakage_html.encode("utf-8"),
                file_name=f"breakage_report_{breakage_date_str}.html",
                mime="text/html",
                help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' عشان تحوله PDF أو تطبعه"
            )

elif page == "Inventory":
    page_banner("🗃️", "Inventory", "متابعة أرصدة المواد الخام والجرد الدفتري والفعلي")
    st.subheader("جرد الاكلير (ص٣)")

    INV_LOG_FILE = "inventory_eclair_log.csv"
    # ==========================================================
    # الجرد الدفتري والفعلي للمواد الخام
    # ==========================================================

    st.header("📒 الجرد الدفتري مقابل الجرد الفعلي")

    RECIPES_FILE = "recipes_master.csv"
    RAW_FILE = "raw_inventory.csv"
    BATCH_FILE = "recipe_batches.csv"

    recipe_columns = [
        "الريسبي",
        "النوع",
        "المادة الخام",
        "الكمية للوحدة"
    ]

    raw_columns = [
        "Date",
        "المادة الخام",
        "رصيد اول المدة",
        "الوارد",
        "المرتجع",
        "الهالك",
        "المستخدم",
        "الجرد الدفتري",
        "الجرد الفعلي",
        "الفرق"
    ]

    batch_columns = [
        "Date",
        "الريسبي",
        "عدد الطبخات"
    ]

    # -----------------------------
    # تحميل الريسبيات
    # -----------------------------

    if os.path.exists(RECIPES_FILE):

        recipes_df = pd.read_csv(
            RECIPES_FILE,
            encoding="utf-8-sig"
        )

    else:

        recipes_df = pd.DataFrame(
            columns=recipe_columns
        )

    for c in recipe_columns:

        if c not in recipes_df.columns:

            recipes_df[c] = ""

    recipes_df["الكمية للوحدة"] = pd.to_numeric(
        recipes_df["الكمية للوحدة"],
        errors="coerce"
    ).fillna(0)

    recipes_df["الريسبي"] = (
        recipes_df["الريسبي"]
        .astype(str)
        .str.strip()
    )

    recipes_df["المادة الخام"] = (
        recipes_df["المادة الخام"]
        .astype(str)
        .str.strip()
    )

    st.subheader("📒 الريسبيات")

    recipes_editor = st.data_editor(

        recipes_df,

        hide_index=True,

        use_container_width=True,

        num_rows="dynamic",

        key="recipes_editor",

        column_config={

            "النوع": st.column_config.SelectboxColumn(

                "النوع",

                options=[
                    "طبخة",
                    "حشو"
                ]

            ),

            "الكمية للوحدة": st.column_config.NumberColumn(

                "الكمية للوحدة",

                format="%.3f",

                step=0.001

            )

        }

    )

    if st.button("💾 حفظ الريسبيات"):

        recipes_editor.to_csv(

            RECIPES_FILE,

            index=False,

            encoding="utf-8-sig"

        )

        st.success("تم حفظ الريسبيات")

        st.rerun()

    recipe_names = sorted(

        recipes_editor["الريسبي"]

        .dropna()

        .astype(str)

        .str.strip()

        .unique()

    )

    materials = sorted(

        recipes_editor["المادة الخام"]

        .dropna()

        .astype(str)

        .str.strip()

        .unique()

    )

    st.divider()
    # ==========================================================
    # اختيار التاريخ + عدد الطبخات + حساب المستخدم
    # ==========================================================

    st.subheader("🍳 عدد الطبخات")

    inventory_date = st.date_input(
        "📅 تاريخ الجرد",
        value=datetime.now().date(),
        key="inventory_date"
    )

    today = inventory_date.strftime("%Y-%m-%d")

    # -----------------------------
    # تحميل عدد الطبخات
    # -----------------------------

    if os.path.exists(BATCH_FILE):

        batch_log = pd.read_csv(
            BATCH_FILE,
            encoding="utf-8-sig"
        )

        batch_log["Date"] = batch_log["Date"].astype(str)

    else:

        batch_log = pd.DataFrame(
            columns=batch_columns
        )

    today_batch = batch_log[
        batch_log["Date"] == today
    ]

    rows = []

    for recipe in recipe_names:

        if recipe in today_batch["الريسبي"].values:

            value = float(

                today_batch.loc[
                    today_batch["الريسبي"] == recipe,
                    "عدد الطبخات"
                ].iloc[0]

            )

        else:

            value = 0.0

        rows.append({

            "الريسبي": recipe,

            "عدد الطبخات": value

        })

    batch_df = pd.DataFrame(rows)

    batch_editor = st.data_editor(

        batch_df,

        hide_index=True,

        use_container_width=True,

        num_rows="fixed",

        key=f"batch_editor_{today}",

        column_config={

            "الريسبي":

                st.column_config.TextColumn(

                    disabled=True

                ),

            "عدد الطبخات":

                st.column_config.NumberColumn(

                    format="%.2f",

                    step=0.5,

                    min_value=0.0

                )

        }

    )

    batch_editor["عدد الطبخات"] = pd.to_numeric(

        batch_editor["عدد الطبخات"],

        errors="coerce"

    ).fillna(0)

    batch_map = {}

    for _, row in batch_editor.iterrows():

        batch_map[str(row["الريسبي"]).strip()] = float(

            row["عدد الطبخات"]

        )

    # ==========================================================
    # حساب المستخدم لكل خامة
    # ==========================================================

    usage_dict = {}

    for _, row in recipes_editor.iterrows():

        recipe = str(row["الريسبي"]).strip()

        material = str(row["المادة الخام"]).strip()

        qty = float(row["الكمية للوحدة"])

        batches = batch_map.get(recipe, 0)

        used = qty * batches

        usage_dict[material] = usage_dict.get(material, 0) + used

    usage_table = pd.DataFrame(

        [

            {

                "المادة الخام": k,

                "المستخدم": round(v,3)

            }

            for k,v in usage_dict.items()

        ]

    )

    st.subheader("📦 المستخدم المحسوب تلقائياً")

    if usage_table.empty:

        st.info("لا يوجد استهلاك.")

    else:

        st.dataframe(

            usage_table.sort_values("المادة الخام"),

            hide_index=True,

            use_container_width=True

        )

    st.divider()
    # ==========================================================
    # الجرد الدفتري والفعلي
    # ==========================================================

    st.subheader("📦 الجرد الدفتري والفعلي")

    # -----------------------------
    # تحميل الجرد السابق
    # -----------------------------

    if os.path.exists(RAW_FILE):

        raw_log = pd.read_csv(
            RAW_FILE,
            encoding="utf-8-sig"
        )

        raw_log["Date"] = raw_log["Date"].astype(str)

    else:

        raw_log = pd.DataFrame(columns=raw_columns)

    rows = []

    for material in materials:

        today_row = raw_log[
            (raw_log["Date"] == today)
            &
            (raw_log["المادة الخام"] == material)
        ]

        if not today_row.empty:

            opening = float(today_row.iloc[0]["رصيد اول المدة"])
            incoming = float(today_row.iloc[0]["الوارد"])
            returned = float(today_row.iloc[0]["المرتجع"])
            waste = float(today_row.iloc[0]["الهالك"])
            actual = float(today_row.iloc[0]["الجرد الفعلي"])

        else:

            history = raw_log[
                (raw_log["المادة الخام"] == material)
                &
                (raw_log["Date"] < today)
            ]

            if history.empty:

                opening = 0

            else:

                history = history.sort_values("Date")

                opening = float(
                    history.iloc[-1]["الجرد الدفتري"]
                )

            incoming = 0
            returned = 0
            waste = 0
            actual = 0

        rows.append({

            "المادة الخام": material,

            "رصيد اول المدة": opening,

            "الوارد": incoming,

            "المرتجع": returned,

            "الهالك": waste,

            "الجرد الفعلي": actual

        })

    raw_df = pd.DataFrame(rows)

    edited_raw = st.data_editor(

        raw_df,

        hide_index=True,

        use_container_width=True,

        num_rows="fixed",

        key=f"raw_editor_{today}",

        column_config={

            "رصيد اول المدة": st.column_config.NumberColumn(
                format="%.3f",
                step=0.001
            ),

            "الوارد": st.column_config.NumberColumn(
                format="%.3f",
                step=0.001
            ),

            "المرتجع": st.column_config.NumberColumn(
                format="%.3f",
                step=0.001
            ),

            "الهالك": st.column_config.NumberColumn(
                format="%.3f",
                step=0.001
            ),

            "الجرد الفعلي": st.column_config.NumberColumn(
                format="%.3f",
                step=0.001
            )

        }

    )

    # -----------------------------
    # الحسابات
    # -----------------------------

    calc = edited_raw.copy()

    numeric_cols = [

        "رصيد اول المدة",

        "الوارد",

        "المرتجع",

        "الهالك",

        "الجرد الفعلي"

    ]

    for col in numeric_cols:

        calc[col] = pd.to_numeric(
            calc[col],
            errors="coerce"
        ).fillna(0)

    calc["المستخدم"] = calc["المادة الخام"].map(
        usage_dict
    ).fillna(0)

    calc["الجرد الدفتري"] = (

        calc["رصيد اول المدة"]

        +

        calc["الوارد"]

        -

        calc["المرتجع"]

        -

        calc["الهالك"]

        -

        calc["المستخدم"]

    )

    calc["الفرق"] = (

        calc["الجرد الفعلي"]

        -

        calc["الجرد الدفتري"]

    )

    calc["الحالة"] = calc["الفرق"].apply(

        lambda x:

        "✔ مطابق"

        if abs(x) < 0.001

        else (

            f"⚠ عجز {abs(x):.3f}"

            if x < 0

            else f"✅ زيادة {x:.3f}"

        )

    )

    st.dataframe(

        calc[

            [

                "المادة الخام",

                "رصيد اول المدة",

                "الوارد",

                "المرتجع",

                "الهالك",

                "المستخدم",

                "الجرد الدفتري",

                "الجرد الفعلي",

                "الفرق",

                "الحالة"

            ]

        ],

        hide_index=True,

        use_container_width=True

    )

    st.metric(
        "إجمالي المستخدم",
        f"{calc['المستخدم'].sum():.3f}"
    )

    st.metric(
        "إجمالي الفرق",
        f"{calc['الفرق'].sum():.3f}"
    )

    st.divider()
    # ==========================================================
    # حفظ الجرد + حفظ عدد الطبخات
    # ==========================================================

    if st.button("💾 حفظ الجرد", use_container_width=True):

        # --------------------------
        # حفظ عدد الطبخات
        # --------------------------

        save_batches = batch_editor.copy()

        save_batches["Date"] = today

        save_batches = save_batches[
            [
                "Date",
                "الريسبي",
                "عدد الطبخات"
            ]
        ]

        if os.path.exists(BATCH_FILE):

            old_batches = pd.read_csv(
                BATCH_FILE,
                encoding="utf-8-sig"
            )

            old_batches["Date"] = old_batches["Date"].astype(str)

            old_batches = old_batches[
                old_batches["Date"] != today
            ]

        else:

            old_batches = pd.DataFrame(
                columns=batch_columns
            )

        old_batches = pd.concat(
            [
                old_batches,
                save_batches
            ],
            ignore_index=True
        )

        old_batches.to_csv(
            BATCH_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        # --------------------------
        # حفظ الجرد
        # --------------------------

        save_inventory = calc.copy()

        save_inventory["Date"] = today

        save_inventory = save_inventory[
            [
                "Date",
                "المادة الخام",
                "رصيد اول المدة",
                "الوارد",
                "المرتجع",
                "الهالك",
                "المستخدم",
                "الجرد الدفتري",
                "الجرد الفعلي",
                "الفرق"
            ]
        ]

        if os.path.exists(RAW_FILE):

            old_inventory = pd.read_csv(
                RAW_FILE,
                encoding="utf-8-sig"
            )

            old_inventory["Date"] = old_inventory["Date"].astype(str)

            old_inventory = old_inventory[
                old_inventory["Date"] != today
            ]

        else:

            old_inventory = pd.DataFrame(
                columns=raw_columns
            )

        old_inventory = pd.concat(
            [
                old_inventory,
                save_inventory
            ],
            ignore_index=True
        )

        old_inventory.to_csv(
            RAW_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        st.success("✅ تم حفظ الجرد بنجاح")

        st.rerun()


    # ==========================================================
    # تقرير الجرد
    # ==========================================================

    if not calc.empty:

        report = calc[
            [
                "المادة الخام",
                "رصيد اول المدة",
                "الوارد",
                "المرتجع",
                "الهالك",
                "المستخدم",
                "الجرد الدفتري",
                "الجرد الفعلي",
                "الفرق",
                "الحالة"
            ]
        ]

        html = build_printable_html(
            "جرد المواد الخام",
            f"تاريخ الجرد : {today}",
            report
        )

        st.download_button(
            "🖨️ تحميل تقرير الجرد",
            data=html.encode("utf-8"),
            file_name=f"Raw_Inventory_{today}.html",
            mime="text/html"
        )

    
elif page == "Workers":
    # ==============================
    # إدارة العمال
    # ==============================

    page_banner("👷", "إدارة العمال", "متابعة بيانات وحضور العمال")

    if not GSHEETS_ENABLED:
        st.error(
            "⚠ البيانات دي مربوطة بجوجل شيت، ومحتاجة إعداد Secrets صح على Streamlit Cloud "
            "(gcp_service_account + gsheets sheet_id). راجع الإعداد وحاول تاني."
        )
        st.stop()

    # ملفات كل خط
    worker_files = {
        "الإيطالي": "workers_italy.csv",
        "المستمر": "workers_continuous.csv",
        "اللفافات": "workers_rolls.csv",
        "الترانسلاب": "workers_translab.csv",
        "الطوفي": "workers_toffee.csv",
        "السولا": "workers_sola.csv",
        "الجودة": "workers_quality.csv",
    }

    selected_line = st.selectbox(
        "اختر الخط",
        list(worker_files.keys())
    )

    file_name = worker_files[selected_line]
    cache_key = f"workers_df_cache_{selected_line}"

    # القراءة من جوجل شيت مرة واحدة بس (أول ما تفتح الخط ده)، مش في كل حرف بتكتبه
    if cache_key not in st.session_state:
        if gsheet_exists(file_name):
            loaded_df = read_gsheet(file_name).astype(str).fillna("")
            for c in ["الاسم", "الشيفت", "الكود", "خط السير"]:
                if c not in loaded_df.columns:
                    loaded_df[c] = ""
            loaded_df = loaded_df[["الاسم", "الشيفت", "الكود", "خط السير"]]
        else:
            loaded_df = pd.DataFrame(columns=["الاسم", "الشيفت", "الكود", "خط السير"])

        # تنظيف أي أحرف \n أو أسطر جديدة اتسربت في الأسماء قديمًا
        for c in ["الاسم", "الشيفت", "الكود", "خط السير"]:
            loaded_df[c] = (
                loaded_df[c].astype(str)
                .str.replace(r"\\n", " ", regex=True)
                .str.replace("\n", " ", regex=False)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
            )
        st.session_state[cache_key] = loaded_df

    workers_df = st.session_state[cache_key]

    refresh_col1, refresh_col2 = st.columns([4, 1])
    with refresh_col2:
        if st.button("🔄 تحديث من جوجل شيت", key=f"refresh_{selected_line}"):
            st.session_state.pop(cache_key, None)
            st.session_state.pop(f"workers_editor_{selected_line}", None)
            st.rerun()

    # ==========================
    # كلمات مرور الخطوط — لازم تتحقق قبل أي تعديل
    # ==========================
    line_passwords = {
        "الإيطالي": "1111",
        "المستمر": "2222",
        "اللفافات": "3333",
        "الترانسلاب": "4444",
        "الطوفي": "5555",
        "السولا": "6666",
        "الجودة": "8888",
    }

    st.subheader("🔒 دخول المهندس المسؤول")
    password = st.text_input("كلمة المرور", type="password", key=f"line_pass_{selected_line}")
    allow_edit = password == line_passwords[selected_line]

    if allow_edit:
        st.success("تم فتح صلاحية تعديل الشيفت فقط ✔ — الاسم والكود وخط السير محجوزين لصلاحية المدير")
    else:
        st.warning("لازم تدخل كلمة مرور الخط الصحيحة عشان تقدر تغيّر الشيفت — تقدر تشوف البيانات بس دلوقتي")

    # عرض الجدول — المهندس يقدر يغيّر "الشيفت" بس، وباقي الأعمدة مقفولة عليه
    if allow_edit:
        edited_df = st.data_editor(
            workers_df,
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            key=f"workers_editor_{selected_line}",
            column_config={
                "الاسم": st.column_config.TextColumn(
                    "الاسم", disabled=True
                ),

                "الشيفت": st.column_config.SelectboxColumn(
                    "الشيفت",
                    options=["", "1", "2", "3"]
                ),

                "الكود": st.column_config.TextColumn(
                    "الكود", disabled=True
                ),

                "خط السير": st.column_config.TextColumn(
                    "خط السير", disabled=True
                ),
            },
        )
    else:
        st.dataframe(workers_df, use_container_width=True, hide_index=True)
        edited_df = workers_df
    # ==========================
    # أزرار التحكم — تظهر بس لو الباسورد صح
    # ==========================

    if allow_edit:
        col1, col2, col3 = st.columns(3)

        with col1:
            save_btn = st.button("💾 حفظ", use_container_width=True)

        with col2:
            clear_btn = st.button("🧹 مسح جميع الشيفتات", use_container_width=True)

        with col3:
            reload_btn = st.button("🔄 إعادة تحميل", use_container_width=True)
    else:
        save_btn = clear_btn = reload_btn = False

    # ==========================
    # مسح الشيفتات
    # ==========================

    if clear_btn:
        edited_df["الشيفت"] = ""
        write_gsheet(file_name, edited_df)
        st.session_state[cache_key] = edited_df
        st.success("تم مسح جميع الشيفتات")
        st.rerun()

    # ==========================
    # حفظ البيانات
    # ==========================

    if save_btn:

        write_gsheet(file_name, edited_df)
        st.session_state[cache_key] = edited_df

        st.success("✅ تم حفظ البيانات")

        st.divider()

        st.subheader(f"📋 توزيع عمال خط {selected_line}")

        shift1 = edited_df[edited_df["الشيفت"].astype(str)=="1"]
        shift2 = edited_df[edited_df["الشيفت"].astype(str)=="2"]
        shift3 = edited_df[edited_df["الشيفت"].astype(str)=="3"]

        st.info(
            f"""
    إجمالي العمال : {len(edited_df)}

    الشيفت الأول : {len(shift1)}

    الشيفت الثاني : {len(shift2)}

    الشيفت الثالث : {len(shift3)}
    """
        )

        st.markdown("## 🟢 الشيفت الأول")
        st.dataframe(
            shift1[["الاسم","الكود","خط السير"]],
            use_container_width=True,
            hide_index=True
        )

        st.markdown("## 🟡 الشيفت الثاني")
        st.dataframe(
            shift2[["الاسم","الكود","خط السير"]],
            use_container_width=True,
            hide_index=True
        )

        st.markdown("## 🔵 الشيفت الثالث")
        st.dataframe(
            shift3[["الاسم","الكود","خط السير"]],
            use_container_width=True,
            hide_index=True
        )

    # ===================================
    # لوحة المدير
    # ===================================

    st.divider()

    manager_pass = "admin123"

    with st.expander("⚙️ لوحة المدير"):

        admin_password = st.text_input(
            "كلمة مرور المدير",
            type="password",
            key="admin_pass"
        )

        if admin_password == manager_pass:

            st.success("تم تسجيل دخول المدير")

            st.subheader("➕ إضافة عامل واحد")

            new_name = st.text_input("الاسم")

            new_code = st.text_input("الكود")

            new_route = st.text_input("خط السير")

            if st.button("إضافة العامل"):

                workers_df.loc[len(workers_df)] = [
                    new_name,
                    "",
                    new_code,
                    new_route
                ]

                write_gsheet(file_name, workers_df)
                st.session_state[cache_key] = workers_df
                st.session_state.pop(f"workers_editor_{selected_line}", None)

                st.success("تم إضافة العامل")
                st.rerun()

            st.divider()

            st.subheader("➕ إضافة عمال دفعة واحدة (الصق قائمة كاملة)")
            st.caption(
                "الصق كل عامل في سطر لوحده. لو عندك كود أو خط سير كمان، اكتبهم في نفس السطر بينهم فاصلة (,) بالترتيب: "
                "الاسم, الكود, خط السير — مش لازم تكتب الكود والخط سير، ينفع تسيبهم فاضيين وتكمل بعدين من الجدول"
            )
            st.code("مثال:\nأحمد محمد علي, 101, قرية 1\nمحمود سعيد, 102\nخالد إبراهيم", language=None)
            bulk_names = st.text_area("قائمة العمال", key=f"bulk_names_{selected_line}", height=180)
            if st.button("➕ إضافة العمال دول", key=f"bulk_add_btn_{selected_line}"):
                lines_in = [ln.strip() for ln in bulk_names.splitlines() if ln.strip()]
                if not lines_in:
                    st.warning("الصق بيانات عامل واحد على الأقل قبل الإضافة ⚠")
                else:
                    new_rows_list = []
                    for ln in lines_in:
                        parts = [p.strip() for p in ln.split(",")]
                        name_part = parts[0] if len(parts) > 0 else ""
                        code_part = parts[1] if len(parts) > 1 else ""
                        route_part = parts[2] if len(parts) > 2 else ""
                        if name_part:
                            new_rows_list.append({
                                "الاسم": name_part, "الشيفت": "",
                                "الكود": code_part, "خط السير": route_part
                            })
                    new_rows = pd.DataFrame(new_rows_list)
                    workers_df = pd.concat([workers_df, new_rows], ignore_index=True)
                    write_gsheet(file_name, workers_df)
                    st.session_state[cache_key] = workers_df
                    st.session_state.pop(f"workers_editor_{selected_line}", None)
                    st.success(f"اتضاف {len(new_rows)} عامل ✔")
                    st.rerun()

            st.divider()

            st.subheader("🗑️ حذف عامل")

            delete_worker = st.selectbox(
                "اختر العامل",
                workers_df["الاسم"]
            )

            if st.button("حذف العامل"):

                workers_df = workers_df[
                    workers_df["الاسم"] != delete_worker
                ]

                write_gsheet(file_name, workers_df)
                st.session_state[cache_key] = workers_df
                st.session_state.pop(f"workers_editor_{selected_line}", None)

                st.success("تم حذف العامل")
                st.rerun()

            st.divider()

            st.subheader("✏️ تعديل بيانات عامل")

            selected = st.selectbox(
                "العامل",
                workers_df["الاسم"],
                key="edit_worker"
            )

            row = workers_df[
                workers_df["الاسم"] == selected
            ].index[0]

            edit_name = st.text_input(
                "الاسم الجديد",
                workers_df.loc[row,"الاسم"]
            )

            edit_code = st.text_input(
                "الكود الجديد",
                workers_df.loc[row,"الكود"]
            )

            edit_route = st.text_input(
                "خط السير الجديد",
                workers_df.loc[row,"خط السير"]
            )

            if st.button("حفظ التعديل"):

                workers_df.loc[row,"الاسم"] = edit_name
                workers_df.loc[row,"الكود"] = edit_code
                workers_df.loc[row,"خط السير"] = edit_route

                write_gsheet(file_name, workers_df)
                st.session_state[cache_key] = workers_df
                st.session_state.pop(f"workers_editor_{selected_line}", None)

                st.success("تم حفظ التعديل")
                st.rerun()

        elif admin_password != "":
            st.error("كلمة مرور المدير غير صحيحة")

    # ==========================
    # إنشاء تقرير للطباعة
    # ==========================

    report_html = f"""
    <html>
    <head>
    <meta charset="UTF-8">
    <style>

    body {{
    font-family: Arial;
    direction: rtl;
    margin:40px;
    }}

    h1,h2,h3 {{
    text-align:center;
    }}

    table {{

    width:100%;
    border-collapse:collapse;
    margin-bottom:25px;

    }}

    th,td {{

    border:1px solid black;
    padding:8px;
    text-align:center;

    }}

    .page-break {{
    display:block;
    page-break-after:always;
    }}

    </style>
    </head>

    <body>

    <h1>تقرير توزيع العمال</h1>

    <h2>{selected_line}</h2>

    <h3>{pd.Timestamp.today().strftime("%Y-%m-%d")}</h3>

    """

    for i, shift in enumerate(["1", "2", "3"]):

        report_html += f"<h1>بيان بأسماء العاملين بالشيفت {shift}</h1>"

        temp = edited_df[
            edited_df["الشيفت"].astype(str)==shift
        ][["الاسم","الكود","خط السير"]]

        report_html += temp.to_html(index=False)

        if i < 2:
            report_html += '<div class="page-break"></div>'

    report_html += "</body></html>"

    b64 = base64.b64encode(
        report_html.encode("utf-8")
    ).decode()

    href = f"""
    <a download="report_{selected_line}.html"
    href="data:text/html;base64,{b64}">
    📄 تحميل التقرير للطباعة
    </a>
    """

    st.markdown(href, unsafe_allow_html=True)

    st.download_button(
        "📊 تحميل CSV",
        edited_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{selected_line}.csv",
        mime="text/csv"
    )

    # ==========================
    # تقرير موحّد لكل الخطوط حسب الشيفت
    # ==========================

    st.divider()
    st.subheader("🖨️ تقرير موحّد لكل الخطوط حسب الشيفت")
    st.caption("بيان بأسماء العاملين في كل الخطوط مع بعض، كل خط في عمود، مقسّم حسب الشيفت — زي بيان الإكسيل")

    if st.button("🧾 توليد التقرير الموحّد"):
        all_lines_data = {}
        for line_name, fpath in worker_files.items():
            if gsheet_exists(fpath):
                df_line = read_gsheet(fpath).astype(str).fillna("")
            else:
                df_line = pd.DataFrame(columns=["الاسم", "الشيفت", "الكود", "خط السير"])
            for c in ["الاسم", "الشيفت"]:
                df_line[c] = (
                    df_line[c].astype(str)
                    .str.replace(r"\\n", " ", regex=True)
                    .str.replace("\n", " ", regex=False)
                    .str.replace(r"\s+", " ", regex=True)
                    .str.strip()
                )
            all_lines_data[line_name] = df_line

        combined_html = f"""
        <html>
        <head>
        <meta charset="UTF-8">
        <style>
        @page {{ size: A4 landscape; margin: 8mm; }}
        body {{ font-family: Arial; direction: rtl; margin:0; padding:6px; }}
        h1 {{ text-align:center; font-size:16px; margin:2px 0; }}
        h3 {{ text-align:center; font-size:11px; margin:2px 0 8px; color:#555; }}
        table {{ width:100%; border-collapse:collapse; }}
        th,td {{ border:1px solid black; padding:3px 4px; text-align:center; font-size:10px; }}
        th {{ background-color:#f4b183; }}
        .page-break {{ display:block; page-break-after:always; }}
        </style>
        </head>
        <body>
        """

        for i, shift in enumerate(["1", "2", "3"]):
            st.markdown(f"### بيان بأسماء العاملين بالشيفت {shift}")
            col_data = {}
            max_len = 0
            for line_name, df_line in all_lines_data.items():
                # خط السولا شيفت واحد بس، فمش بيظهر في شيفت 2 و3
                if line_name == "السولا" and shift != "1":
                    continue
                names = df_line[df_line["الشيفت"].astype(str) == shift]["الاسم"].tolist()
                col_data[line_name] = names
                max_len = max(max_len, len(names))
            for line_name in col_data:
                col_data[line_name] = col_data[line_name] + [""] * (max_len - len(col_data[line_name]))

            shift_columns = [l for l in worker_files.keys() if not (l == "السولا" and shift != "1")]
            shift_df = pd.DataFrame(col_data) if max_len > 0 else pd.DataFrame(columns=shift_columns)
            st.dataframe(shift_df, use_container_width=True, hide_index=True)

            combined_html += f"<h1>بيان بأسماء العاملين بالشيفت {shift}</h1>"
            combined_html += f"<h3>{pd.Timestamp.today().strftime('%Y-%m-%d')}</h3>"
            combined_html += shift_df.to_html(index=False)
            if i < 2:
                combined_html += '<div class="page-break"></div>'

        combined_html += "</body></html>"

        b64_all = base64.b64encode(combined_html.encode("utf-8")).decode()
        href_all = f"""
        <a download="report_all_lines_by_shift.html"
        href="data:text/html;base64,{b64_all}">
        📄 تحميل التقرير الموحّد للطباعة
        </a>
        """
        st.markdown(href_all, unsafe_allow_html=True)

    # ==========================
    # شيت الشؤون (Excel) — منفصل تمامًا عن الطباعة
    # ==========================

    st.divider()
    st.subheader("🗂️ شيت الشؤون (Excel)")
    st.caption("ملف Excel لقسم الشؤون: تجميع العمال حسب الشيفت (الاسم، الكود، الخط) + عدد العمال في كل خط")

    if st.button("📊 توليد شيت الشؤون"):
        all_lines_hr = {}
        for line_name, fpath in worker_files.items():
            if gsheet_exists(fpath):
                df_line = read_gsheet(fpath).astype(str).fillna("")
            else:
                df_line = pd.DataFrame(columns=["الاسم", "الشيفت", "الكود", "خط السير"])
            for c in ["الاسم", "الشيفت", "الكود", "خط السير"]:
                df_line[c] = (
                    df_line[c].astype(str)
                    .str.replace(r"\\n", " ", regex=True)
                    .str.replace("\n", " ", regex=False)
                    .str.replace(r"\s+", " ", regex=True)
                    .str.strip()
                )
            all_lines_hr[line_name] = df_line

        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:

            # ---- شيت لكل شيفت: الاسم، الكود، القسم، خط السير ----
            for shift in ["1", "2", "3"]:
                rows = []
                for line_name, df_line in all_lines_hr.items():
                    shift_rows = df_line[df_line["الشيفت"] == shift]
                    for _, r in shift_rows.iterrows():
                        rows.append({
                            "الاسم": r["الاسم"],
                            "الكود": r["الكود"],
                            "القسم": line_name,
                            "خط السير": r.get("خط السير", "")
                        })
                shift_sheet = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["الاسم", "الكود", "القسم", "خط السير"])
                shift_sheet.to_excel(writer, sheet_name=f"الشيفت {shift}", index=False)

            # ---- شيت ملخص الأعداد لكل خط ----
            summary_rows = []
            for line_name, df_line in all_lines_hr.items():
                total = len(df_line[df_line["الاسم"].str.strip() != ""])
                s1 = len(df_line[df_line["الشيفت"] == "1"])
                s2 = len(df_line[df_line["الشيفت"] == "2"])
                s3 = len(df_line[df_line["الشيفت"] == "3"])
                summary_rows.append({
                    "الخط": line_name, "الإجمالي": total,
                    "الشيفت 1": s1, "الشيفت 2": s2, "الشيفت 3": s3
                })
            summary_df = pd.DataFrame(summary_rows)
            summary_df.loc[len(summary_df)] = {
                "الخط": "الإجمالي الكلي",
                "الإجمالي": summary_df["الإجمالي"].sum(),
                "الشيفت 1": summary_df["الشيفت 1"].sum(),
                "الشيفت 2": summary_df["الشيفت 2"].sum(),
                "الشيفت 3": summary_df["الشيفت 3"].sum(),
            }
            summary_df.to_excel(writer, sheet_name="ملخص الأعداد", index=False)

            # ---- شيت ملخص عدد العمال من كل بلد/خط سير في كل شيفت ----
            all_workers_hr = pd.concat(all_lines_hr.values(), ignore_index=True)
            all_workers_hr = all_workers_hr[all_workers_hr["الاسم"].str.strip() != ""]
            all_workers_hr["خط السير"] = all_workers_hr["خط السير"].replace("", "غير محدد")

            routes = sorted(all_workers_hr["خط السير"].unique())
            route_rows = []
            for route in routes:
                route_df = all_workers_hr[all_workers_hr["خط السير"] == route]
                total = len(route_df)
                s1 = len(route_df[route_df["الشيفت"] == "1"])
                s2 = len(route_df[route_df["الشيفت"] == "2"])
                s3 = len(route_df[route_df["الشيفت"] == "3"])
                route_rows.append({
                    "خط السير (البلد)": route, "الإجمالي": total,
                    "الشيفت 1": s1, "الشيفت 2": s2, "الشيفت 3": s3
                })
            routes_summary_df = pd.DataFrame(route_rows) if route_rows else pd.DataFrame(
                columns=["خط السير (البلد)", "الإجمالي", "الشيفت 1", "الشيفت 2", "الشيفت 3"]
            )
            if not routes_summary_df.empty:
                routes_summary_df.loc[len(routes_summary_df)] = {
                    "خط السير (البلد)": "الإجمالي الكلي",
                    "الإجمالي": routes_summary_df["الإجمالي"].sum(),
                    "الشيفت 1": routes_summary_df["الشيفت 1"].sum(),
                    "الشيفت 2": routes_summary_df["الشيفت 2"].sum(),
                    "الشيفت 3": routes_summary_df["الشيفت 3"].sum(),
                }
            routes_summary_df.to_excel(writer, sheet_name="ملخص البلاد بالشيفت", index=False)

        st.success("اتعمل شيت الشؤون ✔")
        st.subheader("📋 ملخص الأعداد لكل خط")
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        st.subheader("📋 ملخص عدد العمال من كل بلد حسب الشيفت")
        st.dataframe(routes_summary_df, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇ تحميل شيت الشؤون (Excel)",
            data=excel_buffer.getvalue(),
            file_name="workers_hr_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )



elif page == "الكابستي":
    page_banner("📈", "كابستي الخطوط", "إنتاجية العمالة بالوزن والكراتين — KG/Worker، KG/Labor Hour، Cartons/Worker وغيرهم")

    if not GSHEETS_ENABLED:
        st.error(
            "⚠ البيانات دي مربوطة بجوجل شيت، ومحتاجة إعداد Secrets صح على Streamlit Cloud "
            "(gcp_service_account + gsheets sheet_id). راجع الإعداد وحاول تاني."
        )
        st.stop()

    st.caption(
        "الجودة مش خط إنتاج فمش ظاهرة هنا خالص. العمالة بتتحسب حي من صفحة Workers، والإنتاج من صفحة "
        "Production والباكينج. المؤشرات بتتحسب تراكمي على مستوى الشهر اللي تختاره."
    )

    worker_files_cap = {
        "الإيطالي": "workers_italy.csv",
        "المستمر": "workers_continuous.csv",
        "اللفافات": "workers_rolls.csv",
        "الترانسلاب": "workers_translab.csv",
        "الطوفي": "workers_toffee.csv",
        "السولا": "workers_sola.csv",
        # "الجودة" مستبعدة عمدًا — مش خط إنتاج
    }
    CAPACITY_SHIFTS = ["1", "2", "3"]

    # ---------- ساعات الشيفت (رقم واحد بيتحفظ ويتعدل) ----------
    CAPACITY_SETTINGS_SHEET = "capacity_settings"

    def load_shift_hours():
        if gsheet_exists(CAPACITY_SETTINGS_SHEET):
            df = read_gsheet(CAPACITY_SETTINGS_SHEET)
            if not df.empty and "ساعات الشيفت" in df.columns:
                try:
                    return float(df["ساعات الشيفت"].iloc[0])
                except (ValueError, TypeError):
                    pass
        return 8.0

    top1, top2 = st.columns([2, 1])
    with top1:
        today_cap = datetime.now().date()
        month_options_cap = []
        for i in range(-6, 1):
            y = today_cap.year + (today_cap.month - 1 + i) // 12
            m = (today_cap.month - 1 + i) % 12 + 1
            month_options_cap.append(f"{y}-{m:02d}")
        default_index_cap = month_options_cap.index(today_cap.strftime("%Y-%m"))
        selected_month_cap = st.selectbox("📅 اختر الشهر", month_options_cap, index=default_index_cap, key="capacity_month")
    with top2:
        shift_hours_cap = st.number_input(
            "⏱️ عدد ساعات الشيفت", min_value=1.0, max_value=24.0,
            value=load_shift_hours(), step=0.5, key="capacity_shift_hours_input"
        )
        if st.button("💾 حفظ عدد الساعات", key="capacity_save_hours_btn"):
            write_gsheet(CAPACITY_SETTINGS_SHEET, pd.DataFrame([{"ساعات الشيفت": shift_hours_cap}]))
            st.success("اتحفظ ✔")
            st.rerun()

    # ---------- العمالة الحالية — حي من صفحة Workers، لكل قسم وشيفت ----------
    current_counts = {}
    dept_total_workers = {}
    for dept, fpath in worker_files_cap.items():
        if gsheet_exists(fpath):
            wdf = read_gsheet(fpath).astype(str).fillna("")
            if "الاسم" not in wdf.columns:
                wdf["الاسم"] = ""
            if "الشيفت" not in wdf.columns:
                wdf["الشيفت"] = ""
            wdf = wdf[wdf["الاسم"].str.strip() != ""]
        else:
            wdf = pd.DataFrame(columns=["الاسم", "الشيفت"])
        for sh in CAPACITY_SHIFTS:
            current_counts[(dept, sh)] = int((wdf["الشيفت"].astype(str).str.strip() == sh).sum())
        dept_total_workers[dept] = len(wdf)

    # ---------- إنتاج الخطوط بالكيلو من صفحة Production ----------
    # "الإيطالي" في صفحة Workers = قوة الطباخات المشتركة اللي بتغذي 3 خطوط (الإيطالي + الاكلير ص1 + الاكلير ص3)
    KG_LINES = {
        "الإيطالي": ["الإيطالي", "الاكلير ص١", "الاكلير ص٣"],
        "المستمر": ["المستمر"],
        "الطوفي": ["الطوفي"],
    }

    month_totals_cap = pd.Series(dtype=float)
    shift_totals_cap = pd.DataFrame(columns=["Line", "Shift", "الفعلي (KG)"])
    days_active_cap = {}  # (line) -> عدد الأيام اللي فيها إنتاج فعلي مسجل هذا الشهر

    if gsheet_exists(PRODUCTION_SHEET):
        hist_cap = read_gsheet(PRODUCTION_SHEET)
        hist_cap["Date"] = hist_cap["Date"].astype(str)
        hist_cap["Line"] = hist_cap["Line"].astype(str).str.strip()
        hist_cap["الفعلي (KG)"] = pd.to_numeric(hist_cap["الفعلي (KG)"], errors="coerce").fillna(0)
        hist_month_cap = hist_cap[hist_cap["Date"].str.startswith(selected_month_cap)]

        all_shifts_hist = hist_month_cap[hist_month_cap["Shift"] == "All Shifts"]
        month_totals_cap = all_shifts_hist.groupby("Line")["الفعلي (KG)"].sum()

        active_days_df = all_shifts_hist[all_shifts_hist["الفعلي (KG)"] > 0]
        days_active_cap = active_days_df.groupby("Line")["Date"].nunique().to_dict()

        shift_only_hist = hist_month_cap[hist_month_cap["Shift"] != "All Shifts"]
        shift_totals_cap = shift_only_hist.groupby(["Line", "Shift"])["الفعلي (KG)"].sum().reset_index()

    # ================= جدول 1: كابستي خطوط الإنتاج بالوزن =================
    st.markdown("### ⚖️ كابستي خطوط الإنتاج بالوزن (KG)")

    kg_rows = []
    for dept, prod_lines in KG_LINES.items():
        month_kg = float(sum(month_totals_cap.get(pl, 0) for pl in prod_lines))
        worker_count = dept_total_workers.get(dept, 0)
        days_op = max(sum(days_active_cap.get(pl, 0) for pl in prod_lines), 0)
        # نفادي ازدواج عدد الأيام لو الخط أكتر من خط فرعي (زي الإيطالي) بناخد أكبر عدد أيام تشغيل مسجل من ضمن خطوطه الفرعية
        days_op = max([days_active_cap.get(pl, 0) for pl in prod_lines], default=0)
        labor_hours = worker_count * shift_hours_cap * days_op

        kg_per_worker = (month_kg / worker_count) if worker_count > 0 else 0
        kg_per_hour = (month_kg / labor_hours) if labor_hours > 0 else 0

        lines_label = ", ".join(pl.replace("الاكلير ص١", "اكلير ص1").replace("الاكلير ص٣", "اكلير ص3") for pl in prod_lines)
        kg_rows.append({
            "القسم / الخط": f"{dept} ({lines_label})" if len(prod_lines) > 1 else dept,
            "إنتاج الشهر (KG)": round(month_kg, 0),
            "عدد العمال": worker_count,
            "أيام تشغيل مسجلة": days_op,
            "إجمالي ساعات العمل": round(labor_hours, 0),
            "KG / Worker": round(kg_per_worker, 1),
            "KG / Labor Hour": round(kg_per_hour, 2),
        })

    kg_df = pd.DataFrame(kg_rows)
    if kg_df.empty or kg_df["إنتاج الشهر (KG)"].sum() == 0:
        st.info("لسه مفيش إنتاج مسجل لشهر ده في صفحة Production عشان نحسب كابستي الوزن")
    else:
        st.dataframe(kg_df, use_container_width=True, hide_index=True)
        st.bar_chart(kg_df.set_index("القسم / الخط")["KG / Worker"])

    # ================= جدول 2: KG / Worker / Shift =================
    st.markdown("### 👷 كابستي كل شيفت لوحده (KG / Worker / Shift)")

    shift_rows = []
    for dept, prod_lines in KG_LINES.items():
        for sh in CAPACITY_SHIFTS:
            shift_kg = float(shift_totals_cap[
                (shift_totals_cap["Line"].isin(prod_lines)) & (shift_totals_cap["Shift"] == SHIFTS[int(sh) - 1])
            ]["الفعلي (KG)"].sum()) if not shift_totals_cap.empty else 0.0
            shift_workers = current_counts.get((dept, sh), 0)
            kg_per_worker_shift = (shift_kg / shift_workers) if shift_workers > 0 else 0
            shift_rows.append({
                "القسم / الخط": dept,
                "الشيفت": sh,
                "إنتاج الشيفت الشهري (KG)": round(shift_kg, 0),
                "عدد عمال الشيفت": shift_workers,
                "KG / Worker / Shift": round(kg_per_worker_shift, 1),
            })

    shift_kg_df = pd.DataFrame(shift_rows)
    if shift_kg_df.empty or shift_kg_df["إنتاج الشيفت الشهري (KG)"].sum() == 0:
        st.info("لسه مفيش إنتاج مسجل بالشيفت (مش 'الكل') لشهر ده عشان نحسب KG / Worker / Shift")
    else:
        st.dataframe(shift_kg_df, use_container_width=True, hide_index=True)

    # ================= جدول 3: كابستي التعبئة بالكراتين =================
    st.markdown("### 📦 كابستي التعبئة بالكراتين")
    st.caption(
        "إجمالي الكراتين مأخوذ من كل الأصناف المسجلة في صفحة الباكينج لشهر ده (مفيش تقسيم دقيق للكراتين بين "
        "اللفافات والترانسلاب، فكل قسم بيتحسب برقم الكراتين الكلي مقسوم على عماله هو بس)."
    )

    pack_sheet_cap = f"packing_monthly_{selected_month_cap}"
    total_cartons_cap = 0.0
    days_pack_active_cap = 0
    if gsheet_exists(pack_sheet_cap):
        pack_df_cap = read_gsheet(pack_sheet_cap)
        day_cols_cap = [c for c in pack_df_cap.columns if str(c).startswith("يوم")]
        for dc in day_cols_cap:
            pack_df_cap[dc] = pd.to_numeric(pack_df_cap[dc], errors="coerce").fillna(0)
        if day_cols_cap:
            total_cartons_cap = float(pack_df_cap[day_cols_cap].sum().sum())
            daily_totals_cap = pack_df_cap[day_cols_cap].sum()
            days_pack_active_cap = int((daily_totals_cap > 0).sum())

    carton_rows = []
    for dept in ["اللفافات", "الترانسلاب"]:
        worker_count = dept_total_workers.get(dept, 0)
        labor_hours = worker_count * shift_hours_cap * days_pack_active_cap
        cartons_per_worker = (total_cartons_cap / worker_count) if worker_count > 0 else 0
        cartons_per_hour = (total_cartons_cap / labor_hours) if labor_hours > 0 else 0
        carton_rows.append({
            "القسم": dept,
            "كراتين الشهر (إجمالي المصنع)": round(total_cartons_cap, 0),
            "عدد العمال": worker_count,
            "أيام تعبئة مسجلة": days_pack_active_cap,
            "إجمالي ساعات العمل": round(labor_hours, 0),
            "Cartons / Worker": round(cartons_per_worker, 1),
            "Cartons / Labor Hour": round(cartons_per_hour, 2),
        })

    carton_df = pd.DataFrame(carton_rows)
    if total_cartons_cap == 0:
        st.info("لسه مفيش كراتين مسجلة في صفحة الباكينج لشهر ده عشان نحسب كابستي التعبئة")
    else:
        st.dataframe(carton_df, use_container_width=True, hide_index=True)
        st.bar_chart(carton_df.set_index("القسم")["Cartons / Worker"])

elif page == "Reports":
    page_banner("📑", "Reports", "تقارير شهرية احترافية عن الباكينج والبرودكشن والكسر والأعطال")

    if not GSHEETS_ENABLED:
        st.error(
            "⚠ البيانات دي مربوطة بجوجل شيت، ومحتاجة إعداد Secrets صح على Streamlit Cloud "
            "(gcp_service_account + gsheets sheet_id). راجع الإعداد وحاول تاني."
        )
        st.stop()

    st.markdown("### 📊 التقارير الشهرية الاحترافية")
    st.caption(
        "كل تقرير هنا بيتحمّل بتصميم لوحة تحكم احترافية (كروت KPI + رسوم بيانية + جدول) — "
        "الملف الناتج صفحة HTML مستقلة تقدر تنشرها على أي موقع ويب زي ما هي، أو تفتحها وتدوس "
        "Ctrl+P وتحفظها PDF"
    )

    today_r = datetime.now().date()
    month_options_r = []
    for i in range(-5, 1):
        y = today_r.year + (today_r.month - 1 + i) // 12
        m = (today_r.month - 1 + i) % 12 + 1
        month_options_r.append(f"{y}-{m:02d}")
    default_index_r = month_options_r.index(today_r.strftime("%Y-%m"))
    selected_month_r = st.selectbox(
        "📅 اختر الشهر للتقارير", month_options_r, index=default_index_r, key="reports_month_select"
    )
    year_r, month_num_r = map(int, selected_month_r.split("-"))
    days_in_month_r = calendar.monthrange(year_r, month_num_r)[1]
    month_label_r = f"شهر {selected_month_r}"

    prev_year_r = year_r if month_num_r > 1 else year_r - 1
    prev_month_num_r = month_num_r - 1 if month_num_r > 1 else 12
    prev_month_str_r = f"{prev_year_r}-{prev_month_num_r:02d}"

    def _delta_pack(current_val, prev_val):
        """بيحسب نسبة التغيير عن الشهر اللي فات، وبيرجع (نص جاهز, هل التغيير إيجابي) — أو None لو مفيش بيانات سابقة"""
        if prev_val is None or prev_val == 0:
            return None, None
        pct = (current_val - prev_val) / abs(prev_val) * 100
        return f"{pct:+.1f}% عن الشهر اللي فات", pct >= 0

    def _report_kpi_card(icon, value, label, color):
        """كارت KPI بستايل inline بسيط — للعرض السريع جوه الـ Streamlit نفسه بس"""
        return f"""
        <div style="flex:1; background:#fff; border:1px solid #e5e7eb; border-right:5px solid {color};
                    border-radius:8px; padding:10px 8px; text-align:center;">
            <div style="font-size:18px;">{icon}</div>
            <div style="font-size:18px; font-weight:800; color:#0b1f3a;">{value}</div>
            <div style="font-size:10px; color:#6b7280; font-weight:700;">{label}</div>
        </div>
        """

    def _trend_line_fig(x_vals, y_vals, title, color, xtick_step=5):
        fig, ax = plt.subplots(figsize=(4.6, 2.1), dpi=140)
        fig.patch.set_facecolor("#ffffff")
        ax.plot(x_vals, y_vals, marker="o", linewidth=1.8, color=color,
                markerfacecolor="#ffffff", markeredgecolor=color, markeredgewidth=1.4, markersize=3.5, zorder=3)
        ax.fill_between(x_vals, y_vals, color=color, alpha=0.10, zorder=2)
        ticks = sorted({v for v in x_vals if (v == x_vals[0] or v % xtick_step == 0 or v == x_vals[-1])})
        ax.set_xticks(ticks)
        ax.tick_params(axis="both", labelsize=6.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", linestyle="--", alpha=0.4, color="#c9cfd6", zorder=0, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_title(ar_text(title), fontsize=8.5, fontweight="bold", color=BRAND_GREEN, pad=6)
        fig.tight_layout(pad=0.6)
        return fig

    def _donut_fig(labels, values, title, center_text=None):
        fig, ax = plt.subplots(figsize=(3.4, 2.8), dpi=140)
        fig.patch.set_facecolor("#ffffff")
        w_, t_, at_ = ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90,
                              colors=BRAND_PALETTE, textprops={"fontsize": 6.5, "fontweight": "bold"},
                              wedgeprops={"edgecolor": "#ffffff", "linewidth": 1.2, "width": 0.55})
        for a in at_:
            a.set_color("#1a1d21")
            a.set_fontsize(6.5)
        if center_text:
            ax.text(0, 0, ar_text(center_text), ha="center", va="center",
                    fontsize=9.5, fontweight="bold", color=BRAND_GREEN)
        ax.axis("equal")
        ax.set_title(ar_text(title), fontsize=8.5, fontweight="bold", color=BRAND_GREEN, pad=6)
        fig.tight_layout(pad=0.6)
        return fig

    def _bar_fig(labels, values, title, color):
        fig, ax = plt.subplots(figsize=(4.6, 2.2), dpi=140)
        fig.patch.set_facecolor("#ffffff")
        bars = ax.bar(labels, values, color=color, edgecolor="#00201c", linewidth=0.5, zorder=3)
        for b in bars:
            h = b.get_height()
            ax.annotate(f"{h:,.0f}", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", fontsize=6, fontweight="bold")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=6.5, fontweight="bold")
        ax.tick_params(axis="y", labelsize=6.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", linestyle="--", alpha=0.4, color="#c9cfd6", zorder=0, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_title(ar_text(title), fontsize=8.5, fontweight="bold", color=BRAND_GREEN, pad=6)
        fig.tight_layout(pad=0.6)
        return fig

    def _grouped_bar_fig(categories, series1_vals, series2_vals, title,
                          series_labels=("الفعلي", "المخطط"), colors=(BRAND_GREEN, "#9ca3af")):
        categories = list(categories)
        x = np.arange(len(categories))
        width = 0.35
        fig, ax = plt.subplots(figsize=(4.6, 2.2), dpi=140)
        fig.patch.set_facecolor("#ffffff")
        b1 = ax.bar(x - width / 2, series1_vals, width, label=ar_text(series_labels[0]), color=colors[0],
                    edgecolor="#00201c", linewidth=0.5, zorder=3)
        b2 = ax.bar(x + width / 2, series2_vals, width, label=ar_text(series_labels[1]), color=colors[1],
                    edgecolor="#4b5563", linewidth=0.5, zorder=3)
        for bars in (b1, b2):
            for b in bars:
                h = b.get_height()
                ax.annotate(f"{h:,.0f}", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 2),
                            textcoords="offset points", ha="center", fontsize=5.5, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([ar_text(c) for c in categories], fontsize=6.5, fontweight="bold")
        ax.tick_params(axis="y", labelsize=6.5)
        ax.legend(fontsize=6, loc="upper right")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", linestyle="--", alpha=0.4, color="#c9cfd6", zorder=0, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_title(ar_text(title), fontsize=8.5, fontweight="bold", color=BRAND_GREEN, pad=6)
        fig.tight_layout(pad=0.6)
        return fig

    def _dual_line_trend_fig(days, top_series, bottom_series, top_title, bottom_title,
                              top_color_top=None, bottom_neg_color="#dc2626", figsize=(4.6, 3.6)):
        """رسم احترافي مكوّن من لوحتين فوق بعض بنفس محور الأيام: فوق سلسلة (زي الإنتاج) وتحت سلسلة تانية
        (زي الأعطال/الكسر) — كل واحدة بخط لكل خط إنتاج، عشان نربط بين الاتجاهين بصريًا بسهولة"""
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=figsize, dpi=140, sharex=True, gridspec_kw={"height_ratios": [1, 1], "hspace": 0.45}
        )
        fig.patch.set_facecolor("#ffffff")
        palette = BRAND_PALETTE

        for i, (name, vals) in enumerate(top_series.items()):
            ax1.plot(days, vals, marker="o", markersize=2.4, linewidth=1.5,
                     color=palette[i % len(palette)], label=ar_text(str(name)))
        ax1.set_title(ar_text(top_title), fontsize=8, fontweight="bold", color=BRAND_GREEN, pad=4)
        ax1.tick_params(axis="both", labelsize=5.5)
        ax1.spines["top"].set_visible(False)
        ax1.spines["right"].set_visible(False)
        ax1.grid(axis="y", linestyle="--", alpha=0.4, linewidth=0.5, color="#c9cfd6")
        ax1.legend(fontsize=5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.42), frameon=False)

        for i, (name, vals) in enumerate(bottom_series.items()):
            ax2.plot(days, vals, marker="s", markersize=2.4, linewidth=1.5, linestyle="--",
                     color=palette[i % len(palette)], label=ar_text(str(name)))
        ax2.set_title(ar_text(bottom_title), fontsize=8, fontweight="bold", color=bottom_neg_color, pad=4)
        ax2.tick_params(axis="both", labelsize=5.5)
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)
        ax2.grid(axis="y", linestyle="--", alpha=0.4, linewidth=0.5, color="#c9cfd6")

        fig.tight_layout(pad=0.8)
        return fig

    report_parts = {}  # بنخزن هنا أجزاء كل تقرير (بتصميم الداشبورد) عشان نقدر نجمعهم في البورتفوليو
    report_totals = {}  # بنخزن هنا أهم الأرقام لكل تقرير عشان نبني منها صفحة "النظرة العامة" الأولى

    # ==========================
    # 1) تقرير الباكينج الشهري — بالوزن (على مستوى الفئات: هارد كاندي / طوفي / إكلير / فورية... إلخ)
    # ==========================
    with st.expander("📦 تقرير الباكينج الشهري — بالوزن", expanded=False):
        packing_sheet_r = f"packing_monthly_{selected_month_r}"
        if not gsheet_exists(packing_sheet_r):
            st.info("مفيش بيانات باكينج مسجلة للشهر ده")
        else:
            pgrid_r = read_gsheet(packing_sheet_r)
            day_cols_r_pack = [f"يوم {d}" for d in range(1, days_in_month_r + 1)]
            for c in ["الصنف", "الفئة", "وزن الكرتونة (كيلو)", "المخطط بالكراتين (شهري)"] + day_cols_r_pack:
                if c not in pgrid_r.columns:
                    pgrid_r[c] = 0 if c not in ["الصنف", "الفئة"] else ""
            for dc in day_cols_r_pack:
                pgrid_r[dc] = pd.to_numeric(pgrid_r[dc], errors="coerce").fillna(0)
            pgrid_r["وزن الكرتونة (كيلو)"] = pd.to_numeric(pgrid_r["وزن الكرتونة (كيلو)"], errors="coerce").fillna(0.0)
            pgrid_r["المخطط بالكراتين (شهري)"] = pd.to_numeric(
                pgrid_r["المخطط بالكراتين (شهري)"], errors="coerce"
            ).fillna(0)
            pgrid_r["الفئة"] = pgrid_r["الفئة"].astype(str).str.strip()

            pgrid_r["إجمالي الكراتين"] = pgrid_r[day_cols_r_pack].sum(axis=1)
            pgrid_r["الوزن الفعلي (كجم)"] = pgrid_r["إجمالي الكراتين"] * pgrid_r["وزن الكرتونة (كيلو)"]
            pgrid_r["الوزن المخطط (كجم)"] = pgrid_r["المخطط بالكراتين (شهري)"] * pgrid_r["وزن الكرتونة (كيلو)"]

            cat_summary_r = pgrid_r[pgrid_r["الفئة"] != ""].groupby("الفئة", sort=False)[
                ["الوزن المخطط (كجم)", "الوزن الفعلي (كجم)"]
            ].sum().reset_index()
            cat_summary_r = cat_summary_r[
                (cat_summary_r["الوزن المخطط (كجم)"] > 0) | (cat_summary_r["الوزن الفعلي (كجم)"] > 0)
            ].copy()
            cat_summary_r["الوزن المخطط (كجم)"] = cat_summary_r["الوزن المخطط (كجم)"].round(0)
            cat_summary_r["الوزن الفعلي (كجم)"] = cat_summary_r["الوزن الفعلي (كجم)"].round(0)
            cat_summary_r["نسبة التحقيق %"] = cat_summary_r.apply(
                lambda r: round((r["الوزن الفعلي (كجم)"] / r["الوزن المخطط (كجم)"] * 100), 1)
                if r["الوزن المخطط (كجم)"] > 0 else None,
                axis=1
            )
            cat_summary_r = cat_summary_r.sort_values("الوزن الفعلي (كجم)", ascending=False).reset_index(drop=True)

            if cat_summary_r.empty:
                st.info("لسه مفيش أي تعبئة اتسجلت للشهر ده")
            else:
                total_actual_w = cat_summary_r["الوزن الفعلي (كجم)"].sum()
                total_target_w = cat_summary_r["الوزن المخطط (كجم)"].sum()
                achievement_w = (total_actual_w / total_target_w * 100) if total_target_w > 0 else 0
                best_cat_w = cat_summary_r.iloc[0]

                # ---------- إجماليات بالكراتين (بالإضافة للوزن) ----------
                total_actual_cartons_w = pgrid_r["إجمالي الكراتين"].sum()
                total_target_cartons_w = pgrid_r["المخطط بالكراتين (شهري)"].sum()
                achievement_cartons_w = (
                    (total_actual_cartons_w / total_target_cartons_w * 100) if total_target_cartons_w > 0 else 0
                )

                # ---------- مقارنة بالشهر اللي فات ----------
                prev_actual_w, prev_achv_w = None, None
                prev_pack_sheet = f"packing_monthly_{prev_month_str_r}"
                if gsheet_exists(prev_pack_sheet):
                    pgrid_prev = read_gsheet(prev_pack_sheet)
                    prev_days_in_month = calendar.monthrange(prev_year_r, prev_month_num_r)[1]
                    prev_day_cols = [f"يوم {d}" for d in range(1, prev_days_in_month + 1)]
                    for c in ["وزن الكرتونة (كيلو)", "المخطط بالكراتين (شهري)"] + prev_day_cols:
                        if c not in pgrid_prev.columns:
                            pgrid_prev[c] = 0
                    for dc in prev_day_cols:
                        pgrid_prev[dc] = pd.to_numeric(pgrid_prev[dc], errors="coerce").fillna(0)
                    pgrid_prev["وزن الكرتونة (كيلو)"] = pd.to_numeric(
                        pgrid_prev["وزن الكرتونة (كيلو)"], errors="coerce"
                    ).fillna(0.0)
                    pgrid_prev["المخطط بالكراتين (شهري)"] = pd.to_numeric(
                        pgrid_prev["المخطط بالكراتين (شهري)"], errors="coerce"
                    ).fillna(0)
                    prev_actual_w = (pgrid_prev[prev_day_cols].sum(axis=1) * pgrid_prev["وزن الكرتونة (كيلو)"]).sum()
                    prev_target_w = (pgrid_prev["المخطط بالكراتين (شهري)"] * pgrid_prev["وزن الكرتونة (كيلو)"]).sum()
                    prev_achv_w = (prev_actual_w / prev_target_w * 100) if prev_target_w > 0 else None

                delta_actual_w, delta_actual_w_pos = _delta_pack(total_actual_w, prev_actual_w)
                delta_achv_w, delta_achv_w_pos = _delta_pack(achievement_w, prev_achv_w)

                pack_kpi_defs = [
                    ("⚖️", f"{total_actual_w:,.0f} كجم", "إجمالي الوزن الفعلي", "#16a34a",
                     delta_actual_w, delta_actual_w_pos),
                    ("🎯", f"{total_target_w:,.0f} كجم", "إجمالي الوزن المخطط", "#e0a92e", None, None),
                    ("📈", f"{achievement_w:.1f}%", "نسبة التحقيق (بالوزن)", "#7c3aed", delta_achv_w, delta_achv_w_pos),
                    ("📦", f"{total_target_cartons_w:,.0f} كرتونة", "إجمالي المستهدف (كراتين)", "#2563eb", None, None),
                    ("📊", f"{achievement_cartons_w:.1f}%", "نسبة التحقيق (كراتين)", "#0891b2", None, None),
                    ("🏆", str(best_cat_w["الفئة"])[:16],
                     f"أعلى فئة ({best_cat_w['الوزن الفعلي (كجم)']:,.0f} كجم)", "#0d6b5c", None, None),
                ]
                pack_top_html = '<div style="display:flex; gap:8px; margin:8px 0 8px; flex-wrap:wrap;">' + "".join(
                    _report_kpi_card(d[0], d[1], d[2], d[3]) for d in pack_kpi_defs
                ) + "</div>"
                pack_kpi_html = "".join(dash_kpi_card(*d) for d in pack_kpi_defs)

                st.markdown(_flat_html(pack_top_html), unsafe_allow_html=True)
                st.dataframe(cat_summary_r, use_container_width=True, hide_index=True)

                # ---------- اتجاه الباكينج بالوزن خلال الشهر ----------
                daily_weight_r = pgrid_r[day_cols_r_pack].multiply(pgrid_r["وزن الكرتونة (كيلو)"], axis=0).sum(axis=0)
                trend_days_pack = list(range(1, days_in_month_r + 1))
                trend_values_pack = [float(daily_weight_r.get(f"يوم {d}", 0)) for d in trend_days_pack]

                st.caption("📈 اتجاه الباكينج بالوزن خلال الشهر (كجم)")
                st.pyplot(_trend_line_fig(trend_days_pack, trend_values_pack, "اتجاه الباكينج بالوزن (كجم)", BRAND_GREEN))

                st.caption("📊 المخطط مقابل الفعلي لكل فئة (كجم)")
                st.pyplot(_grouped_bar_fig(
                    cat_summary_r["الفئة"], cat_summary_r["الوزن الفعلي (كجم)"], cat_summary_r["الوزن المخطط (كجم)"],
                    "المخطط مقابل الفعلي لكل فئة (كجم)"
                ))

                st.caption("🥧 توزيع الوزن الفعلي بالفئات")
                st.pyplot(_donut_fig(
                    [ar_text(c) for c in cat_summary_r["الفئة"]], cat_summary_r["الوزن الفعلي (كجم)"],
                    "توزيع الوزن الفعلي بالفئات", center_text=f"{total_actual_w:,.0f}\nكجم"
                ))

                pack_chart_html = "".join([
                    dash_chart_card("📈 اتجاه الباكينج بالوزن خلال الشهر", fig_to_base64_img(
                        _trend_line_fig(trend_days_pack, trend_values_pack, "اتجاه الباكينج بالوزن (كجم)", BRAND_GREEN)
                    )),
                    dash_chart_card("📊 المخطط مقابل الفعلي لكل فئة (كجم)", fig_to_base64_img(
                        _grouped_bar_fig(cat_summary_r["الفئة"], cat_summary_r["الوزن الفعلي (كجم)"],
                                          cat_summary_r["الوزن المخطط (كجم)"], "المخطط مقابل الفعلي لكل فئة")
                    )),
                    dash_chart_card("🥧 توزيع الوزن الفعلي بالفئات", fig_to_base64_img(
                        _donut_fig([ar_text(c) for c in cat_summary_r["الفئة"]], cat_summary_r["الوزن الفعلي (كجم)"],
                                    "توزيع الوزن الفعلي بالفئات", center_text=f"{total_actual_w:,.0f}\nكجم")
                    )),
                ])

                report_parts["packing"] = {
                    "key": "packing",
                    "title": "الباكينج",
                    "subtitle": f"Monthly Report - {month_label_r} — بالوزن",
                    "kpi_html": pack_kpi_html,
                    "chart_html": pack_chart_html,
                    "table_title": "المخطط مقابل الفعلي ونسبة التحقيق لكل فئة",
                    "table_df": cat_summary_r,
                }
                report_totals["packing"] = {
                    "actual_weight": total_actual_w, "target_weight": total_target_w,
                    "achievement": achievement_w, "cat_df": cat_summary_r,
                    "trend_days": trend_days_pack, "trend_values": trend_values_pack,
                }

                pack_doc_html = build_dashboard_document(
                    "تقرير الباكينج الشهري (بالوزن)", month_label_r, [report_parts["packing"]]
                )
                st.download_button(
                    "🖨️ تحميل تقرير الباكينج بالوزن (تصميم احترافي)", data=pack_doc_html.encode("utf-8"),
                    file_name=f"packing_weight_report_{selected_month_r}.html", mime="text/html",
                    key="dl_pack_weight_report"
                )

    # ==========================
    # 2) تقرير البرودكشن الشهري
    # ==========================
    with st.expander("🏭 تقرير البرودكشن الشهري", expanded=False):
        if not gsheet_exists(PRODUCTION_SHEET):
            st.info("لسه مفيش بيانات إنتاج مسجلة")
        else:
            prod_hist_r = read_gsheet(PRODUCTION_SHEET)
            prod_hist_r["Date"] = prod_hist_r["Date"].astype(str)
            prod_month_r = prod_hist_r[
                (prod_hist_r["Date"].str.startswith(selected_month_r)) & (prod_hist_r["Shift"] == "All Shifts")
            ].copy()

            if prod_month_r.empty:
                st.info("لسه مفيش بيانات إنتاج مسجلة للشهر ده")
            else:
                prod_month_r["المستهدف (KG)"] = pd.to_numeric(prod_month_r["المستهدف (KG)"], errors="coerce").fillna(0)
                prod_month_r["الفعلي (KG)"] = pd.to_numeric(prod_month_r["الفعلي (KG)"], errors="coerce").fillna(0)
                prod_month_r["الخط"] = prod_month_r["Line"].astype(str).str.replace("🏭", "", regex=False).str.strip()

                prod_line_summary_r = prod_month_r.groupby("الخط", sort=False)[
                    ["المستهدف (KG)", "الفعلي (KG)"]
                ].sum().reset_index()
                prod_line_summary_r["نسبة التحقيق %"] = prod_line_summary_r.apply(
                    lambda r: round((r["الفعلي (KG)"] / r["المستهدف (KG)"] * 100), 1) if r["المستهدف (KG)"] > 0 else 0,
                    axis=1
                )
                prod_line_summary_r = prod_line_summary_r.sort_values("الفعلي (KG)", ascending=False).reset_index(drop=True)

                total_target_r = prod_line_summary_r["المستهدف (KG)"].sum()
                total_actual_r = prod_line_summary_r["الفعلي (KG)"].sum()
                achievement_r = (total_actual_r / total_target_r * 100) if total_target_r > 0 else 0
                best_line_r = prod_line_summary_r.iloc[0] if not prod_line_summary_r.empty else None

                # ---------- مقارنة بالشهر اللي فات ----------
                prev_actual_r, prev_achv_r = None, None
                if gsheet_exists(PRODUCTION_SHEET):
                    prod_prev_full = read_gsheet(PRODUCTION_SHEET)
                    prod_prev_full["Date"] = prod_prev_full["Date"].astype(str)
                    prod_prev_m = prod_prev_full[
                        (prod_prev_full["Date"].str.startswith(prev_month_str_r))
                        & (prod_prev_full["Shift"] == "All Shifts")
                    ].copy()
                    if not prod_prev_m.empty:
                        prod_prev_m["المستهدف (KG)"] = pd.to_numeric(prod_prev_m["المستهدف (KG)"], errors="coerce").fillna(0)
                        prod_prev_m["الفعلي (KG)"] = pd.to_numeric(prod_prev_m["الفعلي (KG)"], errors="coerce").fillna(0)
                        prev_actual_r = prod_prev_m["الفعلي (KG)"].sum()
                        prev_target_r = prod_prev_m["المستهدف (KG)"].sum()
                        prev_achv_r = (prev_actual_r / prev_target_r * 100) if prev_target_r > 0 else None

                delta_actual_r, delta_actual_r_pos = _delta_pack(total_actual_r, prev_actual_r)
                delta_achv_r, delta_achv_r_pos = _delta_pack(achievement_r, prev_achv_r)

                # ---------- كروت: إجماليات + كارت لكل خط (فعلي + نسبة تحقيق) ----------
                prod_kpi_defs = [
                    ("🎯", f"{total_target_r:,.0f} KG", "إجمالي المستهدف", "#e0a92e", None, None),
                    ("📦", f"{total_actual_r:,.0f} KG", "إجمالي الفعلي", "#0d6b5c", delta_actual_r, delta_actual_r_pos),
                    ("📈", f"{achievement_r:.1f}%", "نسبة التحقيق الإجمالية", "#7c3aed", delta_achv_r, delta_achv_r_pos),
                ]
                for _i, _row in prod_line_summary_r.iterrows():
                    _line_color = BRAND_PALETTE[_i % len(BRAND_PALETTE)]
                    prod_kpi_defs.append((
                        "🏭", f"{_row['الفعلي (KG)']:,.0f} KG",
                        f"{_row['الخط']} — {_row['نسبة التحقيق %']:.1f}%", _line_color, None, None
                    ))

                prod_top_html = '<div style="display:flex; gap:8px; margin:8px 0 8px; flex-wrap:wrap;">' + "".join(
                    _report_kpi_card(d[0], d[1], d[2], d[3]) for d in prod_kpi_defs
                ) + "</div>"
                prod_kpi_html = "".join(dash_kpi_card(*d) for d in prod_kpi_defs)

                st.markdown(_flat_html(prod_top_html), unsafe_allow_html=True)
                st.dataframe(prod_line_summary_r, use_container_width=True, hide_index=True)

                fig_prod_r = build_line_production_chart(prod_line_summary_r)
                if fig_prod_r is not None:
                    st.pyplot(fig_prod_r)

                daily_prod_totals_r = prod_month_r.groupby("Date")["الفعلي (KG)"].sum().sort_index()
                days_x = [int(d.split("-")[-1]) for d in daily_prod_totals_r.index]
                has_trend_prod = len(daily_prod_totals_r) > 1
                if has_trend_prod:
                    st.caption("📈 اتجاه الإنتاج اليومي خلال الشهر (KG)")
                    st.pyplot(_trend_line_fig(days_x, daily_prod_totals_r.values, "اتجاه الإنتاج اليومي (KG)", "#2563eb"))

                line_actual_series_r = prod_line_summary_r.set_index("الخط")["الفعلي (KG)"]
                st.caption("🥧 توزيع الإنتاج الفعلي بين الخطوط")
                st.pyplot(_donut_fig(
                    [ar_text(l) for l in line_actual_series_r.index], line_actual_series_r.values,
                    "توزيع الإنتاج الفعلي بين الخطوط", center_text=f"{total_actual_r:,.0f}\nKG"
                ))

                # ---------- رسم احترافي يربط اتجاه الإنتاج باتجاه الأعطال لكل خط في نفس الرسمة ----------
                prod_month_r["_day"] = prod_month_r["Date"].str.split("-").str[-1].astype(int)
                daily_line_actual_pivot = prod_month_r.pivot_table(
                    index="_day", columns="الخط", values="الفعلي (KG)", aggfunc="sum"
                ).fillna(0).sort_index()

                daily_line_downtime_pivot = None
                if gsheet_exists("faults_daily_log"):
                    faults_for_prod_r = read_gsheet("faults_daily_log")
                    faults_for_prod_r["التاريخ"] = faults_for_prod_r["التاريخ"].astype(str)
                    faults_for_prod_m = faults_for_prod_r[
                        faults_for_prod_r["التاريخ"].str.startswith(selected_month_r)
                    ].copy()
                    if not faults_for_prod_m.empty:
                        faults_for_prod_m["مدة العطل (دقيقة)"] = pd.to_numeric(
                            faults_for_prod_m["مدة العطل (دقيقة)"], errors="coerce"
                        ).fillna(0)
                        faults_for_prod_m["_day"] = faults_for_prod_m["التاريخ"].str.split("-").str[-1].astype(int)
                        daily_line_downtime_pivot = faults_for_prod_m.pivot_table(
                            index="_day", columns="الخط", values="مدة العطل (دقيقة)", aggfunc="sum"
                        ).fillna(0)

                has_combo_prod_faults = (
                    daily_line_downtime_pivot is not None and not daily_line_downtime_pivot.empty
                    and not daily_line_actual_pivot.empty
                )
                if has_combo_prod_faults:
                    combo_days = sorted(set(daily_line_actual_pivot.index) | set(daily_line_downtime_pivot.index))
                    actual_pivot_r = daily_line_actual_pivot.reindex(combo_days, fill_value=0)
                    downtime_pivot_r = daily_line_downtime_pivot.reindex(combo_days, fill_value=0)
                    top_series_prod = {c: actual_pivot_r[c].tolist() for c in actual_pivot_r.columns}
                    bottom_series_faults = {c: downtime_pivot_r[c].tolist() for c in downtime_pivot_r.columns}

                    st.caption("📈⚠️ اتجاه الإنتاج مقابل اتجاه الأعطال لكل خط خلال الشهر")
                    st.pyplot(_dual_line_trend_fig(
                        combo_days, top_series_prod, bottom_series_faults,
                        "اتجاه الإنتاج لكل خط (KG)", "اتجاه الأعطال لكل خط (دقيقة)"
                    ))

                prod_chart_parts = []
                fig_prod_r_p = build_line_production_chart(prod_line_summary_r)
                if fig_prod_r_p is not None:
                    prod_chart_parts.append(
                        dash_chart_card("📊 المستهدف مقابل الفعلي لكل خط", fig_to_base64_img(fig_prod_r_p))
                    )
                if has_trend_prod:
                    prod_chart_parts.append(dash_chart_card("📈 اتجاه الإنتاج اليومي خلال الشهر", fig_to_base64_img(
                        _trend_line_fig(days_x, daily_prod_totals_r.values, "اتجاه الإنتاج اليومي (KG)", "#2563eb")
                    )))
                prod_chart_parts.append(dash_chart_card("🥧 توزيع الإنتاج الفعلي بين الخطوط", fig_to_base64_img(
                    _donut_fig([ar_text(l) for l in line_actual_series_r.index], line_actual_series_r.values,
                                "توزيع الإنتاج الفعلي بين الخطوط", center_text=f"{total_actual_r:,.0f}\nKG")
                )))
                if has_combo_prod_faults:
                    prod_chart_parts.append(dash_chart_card("📈⚠️ الإنتاج مقابل الأعطال لكل خط", fig_to_base64_img(
                        _dual_line_trend_fig(
                            combo_days, top_series_prod, bottom_series_faults,
                            "اتجاه الإنتاج لكل خط (KG)", "اتجاه الأعطال لكل خط (دقيقة)"
                        )
                    )))

                # ---- رسم تفاعلي لكل خط بالفلتر (Select) + خط التارجت اليومي — نفس فكرة الفلتر المطلوبة ----
                if not daily_line_actual_pivot.empty:
                    target_by_line_r = (
                        prod_line_summary_r.set_index("الخط")["المستهدف (KG)"]
                        if "الخط" in prod_line_summary_r.columns and "المستهدف (KG)" in prod_line_summary_r.columns
                        else pd.Series(dtype=float)
                    )

                    def _build_per_line_filter_chart(pivot_df, target_series, days_total, uid, chart_title):
                        line_names_list = list(pivot_df.columns)
                        imgs_by_line = {}
                        for ln in line_names_list:
                            fig_l, ax_l = plt.subplots(figsize=(5.2, 2.6))
                            fig_l.patch.set_facecolor("#1e293b")
                            ax_l.set_facecolor("#1e293b")
                            days_idx = pivot_df.index.tolist()
                            vals = pivot_df[ln].tolist()
                            ax_l.plot(days_idx, vals, marker="o", markersize=4, linewidth=2,
                                      color="#38bdf8", label=ar_text("الفعلي"))
                            if ln in target_series.index and pd.notna(target_series[ln]) and target_series[ln] > 0 and days_total > 0:
                                daily_t = target_series[ln] / days_total
                                ax_l.axhline(daily_t, color="#f87171", linestyle="--", linewidth=1.6, label=ar_text("التارجت"))
                            ax_l.set_title(ar_text(ln), fontsize=10, fontweight="bold", color="#f1f5f9")
                            ax_l.tick_params(colors="#cbd5e1", labelsize=7)
                            for spine in ax_l.spines.values():
                                spine.set_color("#475569")
                            ax_l.legend(fontsize=7, facecolor="#1e293b", labelcolor="#e5e7eb", frameon=False)
                            ax_l.grid(alpha=0.15, color="#64748b")
                            fig_l.tight_layout()
                            imgs_by_line[ln] = fig_to_base64_img(fig_l)
                            plt.close(fig_l)

                        options_html = "".join(
                            f'<option value="{i}">{ar_text(l)}</option>' for i, l in enumerate(imgs_by_line.keys())
                        )
                        divs_html = "".join(
                            f'<div class="{uid}-item" id="{uid}-{i}" style="display:{"block" if i == 0 else "none"};">{img}</div>'
                            for i, (l, img) in enumerate(imgs_by_line.items())
                        )
                        return f"""
                        <div class="chart-card" style="flex:2 1 100%; min-width:320px;">
                            <div class="chart-card-title">{chart_title}</div>
                            <select onchange="document.querySelectorAll('.{uid}-item').forEach(function(el){{el.style.display='none';}}); document.getElementById('{uid}-'+this.value).style.display='block';">
                                {options_html}
                            </select>
                            {divs_html}
                        </div>
                        """

                    prod_chart_parts.append(_build_per_line_filter_chart(
                        daily_line_actual_pivot, target_by_line_r, days_in_month_r,
                        "prodlinefilter", "📈 Daily Production per Line (Actual vs Target)"
                    ))

                prod_chart_html = "".join(prod_chart_parts)

                report_parts["production"] = {
                    "key": "production",
                    "title": "انتاج الخطوط",
                    "subtitle": f"Monthly Report - {month_label_r}",
                    "kpi_html": prod_kpi_html,
                    "chart_html": prod_chart_html,
                    "table_title": "ملخص الإنتاج لكل خط",
                    "table_df": prod_line_summary_r,
                }
                report_totals["production"] = {
                    "actual": total_actual_r, "target": total_target_r, "achievement": achievement_r,
                    "line_df": prod_line_summary_r,
                    "trend_days": days_x if has_trend_prod else None,
                    "trend_values": list(daily_prod_totals_r.values) if has_trend_prod else None,
                }

                prod_doc_html = build_dashboard_document(
                    "تقرير البرودكشن الشهري", month_label_r, [report_parts["production"]]
                )
                st.download_button(
                    "🖨️ تحميل تقرير البرودكشن الشهري (تصميم احترافي)", data=prod_doc_html.encode("utf-8"),
                    file_name=f"production_report_{selected_month_r}.html", mime="text/html",
                    key="dl_prod_report"
                )

    # ==========================
    # 3) تقرير الكسر الشهري
    # ==========================
    with st.expander("🔨 تقرير الكسر الشهري", expanded=False):
        if not gsheet_exists("breakage_history"):
            st.info("لسه مفيش بيانات كسر مسجلة")
        else:
            break_hist_r = read_gsheet("breakage_history")
            break_hist_r["Date"] = break_hist_r["Date"].astype(str)
            break_month_r = break_hist_r[break_hist_r["Date"].str.startswith(selected_month_r)].copy()

            if break_month_r.empty:
                st.info("لسه مفيش بيانات كسر مسجلة للشهر ده")
            else:
                for c in ["رصيد أول المدة (KG)", "كسر خارج (KG)", "كسر داخل (KG)"]:
                    break_month_r[c] = pd.to_numeric(break_month_r[c], errors="coerce").fillna(0)
                break_month_r["الخط"] = break_month_r["الخط"].astype(str).str.strip()

                break_line_summary_r = break_month_r.groupby("الخط", sort=False)[
                    ["كسر خارج (KG)", "كسر داخل (KG)"]
                ].sum().reset_index()
                break_line_summary_r["إجمالي الكسر (KG)"] = (
                    break_line_summary_r["كسر خارج (KG)"] + break_line_summary_r["كسر داخل (KG)"]
                )
                break_line_summary_r = break_line_summary_r.sort_values(
                    "كسر خارج (KG)", ascending=False
                ).reset_index(drop=True)

                total_out_r = break_line_summary_r["كسر خارج (KG)"].sum()
                total_in_r = break_line_summary_r["كسر داخل (KG)"].sum()
                total_gross_r = total_out_r + total_in_r
                worst_line_break_r = break_line_summary_r.iloc[0] if not break_line_summary_r.empty else None

                # ---------- إنتاج كل خط لنفس الشهر — عشان نحسب نسبة الكسر من إنتاج كل خط بالظبط ----------
                prod_line_actual_map = {}
                total_prod_month_r = 0
                if gsheet_exists(PRODUCTION_SHEET):
                    prod_for_ratio = read_gsheet(PRODUCTION_SHEET)
                    prod_for_ratio["Date"] = prod_for_ratio["Date"].astype(str)
                    prod_for_ratio_m = prod_for_ratio[
                        (prod_for_ratio["Date"].str.startswith(selected_month_r))
                        & (prod_for_ratio["Shift"] == "All Shifts")
                    ].copy()
                    if not prod_for_ratio_m.empty:
                        prod_for_ratio_m["الفعلي (KG)"] = pd.to_numeric(
                            prod_for_ratio_m["الفعلي (KG)"], errors="coerce"
                        ).fillna(0)
                        prod_for_ratio_m["الخط"] = prod_for_ratio_m["Line"].astype(str).str.replace(
                            "🏭", "", regex=False
                        ).str.strip()
                        prod_line_actual_map = prod_for_ratio_m.groupby("الخط")["الفعلي (KG)"].sum().to_dict()
                        total_prod_month_r = prod_for_ratio_m["الفعلي (KG)"].sum()

                # ---------- نسبة كسر كل خط من إنتاج نفس الخط (مش من إجمالي إنتاج المصنع) ----------
                break_line_summary_r["كسر خارج % من إنتاج الخط"] = break_line_summary_r.apply(
                    lambda r: round(r["كسر خارج (KG)"] / prod_line_actual_map[r["الخط"]] * 100, 2)
                    if prod_line_actual_map.get(r["الخط"], 0) > 0 else None, axis=1
                )
                break_line_summary_r["كسر داخل % من إنتاج الخط"] = break_line_summary_r.apply(
                    lambda r: round(r["كسر داخل (KG)"] / prod_line_actual_map[r["الخط"]] * 100, 2)
                    if prod_line_actual_map.get(r["الخط"], 0) > 0 else None, axis=1
                )

                # نسبة إجمالية لكل من الخارج والداخل، محسوبة بس على إنتاج الخطوط اللي عندها بيانات كسر (مش كل المصنع)
                matched_prod_total = sum(
                    prod_line_actual_map.get(ln, 0) for ln in break_line_summary_r["الخط"]
                )
                ratio_out_txt = f"{(total_out_r / matched_prod_total * 100):.2f}% من إنتاج نفس الخطوط" \
                    if matched_prod_total > 0 else "لا توجد بيانات إنتاج مطابقة"
                ratio_in_txt = f"{(total_in_r / matched_prod_total * 100):.2f}% من إنتاج نفس الخطوط" \
                    if matched_prod_total > 0 else "لا توجد بيانات إنتاج مطابقة"

                # ---------- مقارنة بالشهر اللي فات ----------
                prev_out_break, prev_in_break = None, None
                if gsheet_exists("breakage_history"):
                    break_prev_full = read_gsheet("breakage_history")
                    break_prev_full["Date"] = break_prev_full["Date"].astype(str)
                    break_prev_m = break_prev_full[break_prev_full["Date"].str.startswith(prev_month_str_r)].copy()
                    if not break_prev_m.empty:
                        break_prev_m["كسر خارج (KG)"] = pd.to_numeric(
                            break_prev_m["كسر خارج (KG)"], errors="coerce"
                        ).fillna(0)
                        break_prev_m["كسر داخل (KG)"] = pd.to_numeric(
                            break_prev_m["كسر داخل (KG)"], errors="coerce"
                        ).fillna(0)
                        prev_out_break = break_prev_m["كسر خارج (KG)"].sum()
                        prev_in_break = break_prev_m["كسر داخل (KG)"].sum()

                delta_out_break, delta_out_break_pos = _delta_pack(total_out_r, prev_out_break)
                delta_in_break, delta_in_break_pos = _delta_pack(total_in_r, prev_in_break)
                # الكسر: انخفاض القيمة يعتبر تحسّن، فالسهم بيتعكس (نزول = أخضر، زيادة = أحمر)
                if delta_out_break_pos is not None:
                    delta_out_break_pos = not delta_out_break_pos
                if delta_in_break_pos is not None:
                    delta_in_break_pos = not delta_in_break_pos

                break_kpi_defs = [
                    ("📤", f"{total_out_r:,.0f} كجم", f"إجمالي الكسر خارج — {ratio_out_txt}", "#dc2626",
                     delta_out_break, delta_out_break_pos),
                    ("📥", f"{total_in_r:,.0f} كجم", f"إجمالي الكسر داخل — {ratio_in_txt}", "#f97316",
                     delta_in_break, delta_in_break_pos),
                    ("📦", f"{total_gross_r:,.0f} كجم", "إجمالي الكسر (خارج + داخل)", "#e0a92e", None, None),
                    ("🔻", str(worst_line_break_r["الخط"])[:16] if worst_line_break_r is not None else "-",
                     f"أعلى خط كسر خارج ({worst_line_break_r['كسر خارج (KG)']:,.0f} كجم)"
                     if worst_line_break_r is not None else "-", "#2563eb", None, None),
                ]
                break_top_html = '<div style="display:flex; gap:8px; margin:8px 0 8px; flex-wrap:wrap;">' + "".join(
                    _report_kpi_card(d[0], d[1], d[2], d[3]) for d in break_kpi_defs
                ) + "</div>"
                break_kpi_html = "".join(dash_kpi_card(*d) for d in break_kpi_defs)

                st.markdown(_flat_html(break_top_html), unsafe_allow_html=True)
                st.dataframe(break_line_summary_r, use_container_width=True, hide_index=True)

                st.caption("📊 كسر خارج مقابل كسر داخل لكل خط (كجم)")
                st.pyplot(_grouped_bar_fig(
                    break_line_summary_r["الخط"], break_line_summary_r["كسر خارج (KG)"],
                    break_line_summary_r["كسر داخل (KG)"], "كسر خارج مقابل كسر داخل لكل خط (كجم)",
                    series_labels=("كسر خارج", "كسر داخل"), colors=("#dc2626", "#f97316")
                ))

                pie_vals_b = break_line_summary_r["إجمالي الكسر (KG)"].clip(lower=0)
                has_pie_break = pie_vals_b.sum() > 0
                if has_pie_break:
                    st.caption("🥧 نسبة كل خط من إجمالي الكسر")
                    st.pyplot(_donut_fig([ar_text(n) for n in break_line_summary_r["الخط"]], pie_vals_b.values,
                                          "نسبة كل خط من إجمالي الكسر", center_text=f"{total_gross_r:,.0f}\nكجم"))

                # ---------- اتجاه الكسر لكل خط خلال الشهر، ومقارنته باتجاه الإنتاج في نفس الرسمة ----------
                break_month_r["_day"] = break_month_r["Date"].str.split("-").str[-1].astype(int)
                daily_line_break_pivot = break_month_r.pivot_table(
                    index="_day", columns="الخط", values="كسر خارج (KG)", aggfunc="sum"
                ).fillna(0).sort_index()

                has_break_trend = not daily_line_break_pivot.empty
                if has_break_trend:
                    break_trend_days = list(daily_line_break_pivot.index)
                    break_trend_series = {c: daily_line_break_pivot[c].tolist() for c in daily_line_break_pivot.columns}
                    st.caption("📈 اتجاه الكسر (خارج) لكل خط على مدار الشهر")
                    fig_break_trend_only, ax_bt = plt.subplots(figsize=(4.6, 2.1), dpi=140)
                    fig_break_trend_only.patch.set_facecolor("#ffffff")
                    for i, (name, vals) in enumerate(break_trend_series.items()):
                        ax_bt.plot(break_trend_days, vals, marker="o", markersize=2.4, linewidth=1.5,
                                   color=BRAND_PALETTE[i % len(BRAND_PALETTE)], label=ar_text(str(name)))
                    ax_bt.set_title(ar_text("اتجاه الكسر (خارج) لكل خط"), fontsize=8.5, fontweight="bold",
                                     color="#dc2626", pad=6)
                    ax_bt.tick_params(axis="both", labelsize=6)
                    ax_bt.spines["top"].set_visible(False)
                    ax_bt.spines["right"].set_visible(False)
                    ax_bt.grid(axis="y", linestyle="--", alpha=0.4, linewidth=0.5, color="#c9cfd6")
                    ax_bt.legend(fontsize=5.5, ncol=2, loc="upper right")
                    fig_break_trend_only.tight_layout(pad=0.6)
                    st.pyplot(fig_break_trend_only)

                # مصفوفة الإنتاج اليومي لكل خط لنفس الشهر (مستقلة عن قسم البرودكشن) عشان نربطها بالكسر
                daily_line_prod_for_break = None
                if gsheet_exists(PRODUCTION_SHEET):
                    prod_for_break_trend = read_gsheet(PRODUCTION_SHEET)
                    prod_for_break_trend["Date"] = prod_for_break_trend["Date"].astype(str)
                    prod_for_break_trend_m = prod_for_break_trend[
                        (prod_for_break_trend["Date"].str.startswith(selected_month_r))
                        & (prod_for_break_trend["Shift"] == "All Shifts")
                    ].copy()
                    if not prod_for_break_trend_m.empty:
                        prod_for_break_trend_m["الفعلي (KG)"] = pd.to_numeric(
                            prod_for_break_trend_m["الفعلي (KG)"], errors="coerce"
                        ).fillna(0)
                        prod_for_break_trend_m["الخط"] = prod_for_break_trend_m["Line"].astype(str).str.replace(
                            "🏭", "", regex=False
                        ).str.strip()
                        prod_for_break_trend_m["_day"] = prod_for_break_trend_m["Date"].str.split("-").str[-1].astype(int)
                        daily_line_prod_for_break = prod_for_break_trend_m.pivot_table(
                            index="_day", columns="الخط", values="الفعلي (KG)", aggfunc="sum"
                        ).fillna(0)

                has_combo_prod_break = (
                    has_break_trend and daily_line_prod_for_break is not None and not daily_line_prod_for_break.empty
                )
                if has_combo_prod_break:
                    combo_days_b = sorted(set(daily_line_prod_for_break.index) | set(daily_line_break_pivot.index))
                    prod_pivot_b = daily_line_prod_for_break.reindex(combo_days_b, fill_value=0)
                    break_pivot_b = daily_line_break_pivot.reindex(combo_days_b, fill_value=0)
                    top_series_prod_b = {c: prod_pivot_b[c].tolist() for c in prod_pivot_b.columns}
                    bottom_series_break_b = {c: break_pivot_b[c].tolist() for c in break_pivot_b.columns}

                    st.caption("📈🔨 اتجاه الإنتاج مقابل اتجاه الكسر لكل خط خلال الشهر")
                    st.pyplot(_dual_line_trend_fig(
                        combo_days_b, top_series_prod_b, bottom_series_break_b,
                        "اتجاه الإنتاج لكل خط (KG)", "اتجاه الكسر (خارج) لكل خط (KG)"
                    ))

                break_chart_parts = [
                    dash_chart_card("📊 كسر خارج مقابل كسر داخل لكل خط", fig_to_base64_img(
                        _grouped_bar_fig(
                            break_line_summary_r["الخط"], break_line_summary_r["كسر خارج (KG)"],
                            break_line_summary_r["كسر داخل (KG)"], "كسر خارج مقابل كسر داخل لكل خط (كجم)",
                            series_labels=("كسر خارج", "كسر داخل"), colors=("#dc2626", "#f97316")
                        )
                    ))
                ]
                if has_pie_break:
                    break_chart_parts.append(dash_chart_card("🥧 نسبة كل خط من إجمالي الكسر", fig_to_base64_img(
                        _donut_fig([ar_text(n) for n in break_line_summary_r["الخط"]], pie_vals_b.values,
                                    "نسبة كل خط من إجمالي الكسر", center_text=f"{total_gross_r:,.0f}\nكجم")
                    )))
                if has_break_trend:
                    fig_break_trend_p, ax_btp = plt.subplots(figsize=(4.6, 2.1), dpi=140)
                    fig_break_trend_p.patch.set_facecolor("#ffffff")
                    for i, (name, vals) in enumerate(break_trend_series.items()):
                        ax_btp.plot(break_trend_days, vals, marker="o", markersize=2.4, linewidth=1.5,
                                    color=BRAND_PALETTE[i % len(BRAND_PALETTE)], label=ar_text(str(name)))
                    ax_btp.set_title(ar_text("اتجاه الكسر (خارج) لكل خط"), fontsize=8.5, fontweight="bold",
                                      color="#dc2626", pad=6)
                    ax_btp.tick_params(axis="both", labelsize=6)
                    ax_btp.spines["top"].set_visible(False)
                    ax_btp.spines["right"].set_visible(False)
                    ax_btp.grid(axis="y", linestyle="--", alpha=0.4, linewidth=0.5, color="#c9cfd6")
                    ax_btp.legend(fontsize=5.5, ncol=2, loc="upper right")
                    fig_break_trend_p.tight_layout(pad=0.6)
                    break_chart_parts.append(dash_chart_card("📈 اتجاه الكسر لكل خط", fig_to_base64_img(fig_break_trend_p)))
                if has_combo_prod_break:
                    break_chart_parts.append(dash_chart_card("📈🔨 الإنتاج مقابل الكسر لكل خط", fig_to_base64_img(
                        _dual_line_trend_fig(
                            combo_days_b, top_series_prod_b, bottom_series_break_b,
                            "اتجاه الإنتاج لكل خط (KG)", "اتجاه الكسر (خارج) لكل خط (KG)"
                        )
                    )))
                break_chart_html = "".join(break_chart_parts)

                report_parts["breakage"] = {
                    "key": "breakage",
                    "title": "الكسر",
                    "subtitle": f"Monthly Report - {month_label_r}",
                    "kpi_html": break_kpi_html,
                    "chart_html": break_chart_html,
                    "table_title": "ملخص الكسر لكل خط (وزن + نسبة من إنتاج نفس الخط)",
                    "table_df": break_line_summary_r,
                }
                report_totals["breakage"] = {
                    "net": total_gross_r, "out": total_out_r, "in": total_in_r,
                    "line_df": break_line_summary_r,
                }

                break_doc_html = build_dashboard_document(
                    "تقرير الكسر الشهري", month_label_r, [report_parts["breakage"]]
                )
                st.download_button(
                    "🖨️ تحميل تقرير الكسر الشهري (تصميم احترافي)", data=break_doc_html.encode("utf-8"),
                    file_name=f"breakage_report_{selected_month_r}.html", mime="text/html",
                    key="dl_break_report"
                )

    # ==========================
    # 4) تقرير الأعطال الشهري
    # ==========================
    with st.expander("⚠️ تقرير الأعطال الشهري", expanded=False):
        if not gsheet_exists("faults_daily_log"):
            st.info("لسه مفيش بيانات أعطال مسجلة")
        else:
            faults_hist_r = read_gsheet("faults_daily_log")
            faults_hist_r["التاريخ"] = faults_hist_r["التاريخ"].astype(str)
            faults_month_r = faults_hist_r[faults_hist_r["التاريخ"].str.startswith(selected_month_r)].copy()

            if faults_month_r.empty:
                st.info("لسه مفيش بيانات أعطال مسجلة للشهر ده")
            else:
                faults_month_r["مدة العطل (دقيقة)"] = pd.to_numeric(
                    faults_month_r["مدة العطل (دقيقة)"], errors="coerce"
                ).fillna(0)
                if "تكلفة الصيانة (جنيه)" in faults_month_r.columns:
                    faults_month_r["تكلفة الصيانة (جنيه)"] = pd.to_numeric(
                        faults_month_r["تكلفة الصيانة (جنيه)"], errors="coerce"
                    ).fillna(0)
                else:
                    faults_month_r["تكلفة الصيانة (جنيه)"] = 0.0

                faults_line_summary_r = faults_month_r.groupby("الخط", sort=False).agg(
                    **{
                        "عدد الأعطال": ("مدة العطل (دقيقة)", "count"),
                        "إجمالي دقائق التوقف": ("مدة العطل (دقيقة)", "sum"),
                        "إجمالي تكلفة الصيانة (جنيه)": ("تكلفة الصيانة (جنيه)", "sum"),
                    }
                ).reset_index()
                faults_line_summary_r = faults_line_summary_r.sort_values(
                    "إجمالي دقائق التوقف", ascending=False
                ).reset_index(drop=True)

                total_downtime_r = faults_line_summary_r["إجمالي دقائق التوقف"].sum()
                total_faults_count_r = faults_line_summary_r["عدد الأعطال"].sum()
                total_maint_cost_r = faults_line_summary_r["إجمالي تكلفة الصيانة (جنيه)"].sum()
                avg_fault_duration_r = (total_downtime_r / total_faults_count_r) if total_faults_count_r > 0 else 0
                worst_line_fault_r = faults_line_summary_r.iloc[0] if not faults_line_summary_r.empty else None

                # ---------- مقارنة بالشهر اللي فات ----------
                prev_downtime = None
                if gsheet_exists("faults_daily_log"):
                    faults_prev_full = read_gsheet("faults_daily_log")
                    faults_prev_full["التاريخ"] = faults_prev_full["التاريخ"].astype(str)
                    faults_prev_m = faults_prev_full[
                        faults_prev_full["التاريخ"].str.startswith(prev_month_str_r)
                    ].copy()
                    if not faults_prev_m.empty:
                        faults_prev_m["مدة العطل (دقيقة)"] = pd.to_numeric(
                            faults_prev_m["مدة العطل (دقيقة)"], errors="coerce"
                        ).fillna(0)
                        prev_downtime = faults_prev_m["مدة العطل (دقيقة)"].sum()

                delta_downtime, delta_downtime_pos = _delta_pack(total_downtime_r, prev_downtime)
                # الأعطال: انخفاض دقائق التوقف يعتبر تحسّن، فالسهم بيتعكس (نزول = أخضر، زيادة = أحمر)
                if delta_downtime_pos is not None:
                    delta_downtime_pos = not delta_downtime_pos

                faults_kpi_defs = [
                    ("⏱️", f"{total_downtime_r:,.0f} د", "إجمالي دقائق التوقف", "#dc2626",
                     delta_downtime, delta_downtime_pos),
                    ("🛠️", f"{total_faults_count_r:,.0f}", "عدد الأعطال المسجلة", "#2563eb", None, None),
                    ("📊", f"{avg_fault_duration_r:,.0f} د", "متوسط مدة العطل", "#e0a92e", None, None),
                    ("⏳", f"{(total_downtime_r / 60):,.1f} س", "إجمالي التوقف بالساعات", "#7c3aed", None, None),
                    ("🔻", str(worst_line_fault_r["الخط"])[:16] if worst_line_fault_r is not None else "-",
                     f"أكتر خط توقف ({worst_line_fault_r['إجمالي دقائق التوقف']:,.0f} د)"
                     if worst_line_fault_r is not None else "-", "#16a34a", None, None),
                    ("💰", f"{total_maint_cost_r:,.0f} ج", "إجمالي تكلفة الصيانة (المعتمدة)", "#dc2626", None, None),
                ]
                faults_top_html = '<div style="display:flex; gap:8px; margin:8px 0 8px;">' + "".join(
                    _report_kpi_card(d[0], d[1], d[2], d[3]) for d in faults_kpi_defs
                ) + "</div>"
                faults_kpi_html = "".join(dash_kpi_card(*d) for d in faults_kpi_defs)

                st.markdown(_flat_html(faults_top_html), unsafe_allow_html=True)
                st.dataframe(faults_line_summary_r, use_container_width=True, hide_index=True)

                st.caption("📊 إجمالي دقائق التوقف لكل خط")
                st.pyplot(_bar_fig([ar_text(n) for n in faults_line_summary_r["الخط"]],
                                    faults_line_summary_r["إجمالي دقائق التوقف"], "إجمالي دقائق التوقف لكل خط", "#dc2626"))

                cause_totals_r = faults_month_r.groupby("سبب العطل")["مدة العطل (دقيقة)"].sum().sort_values(
                    ascending=False
                )
                cause_totals_r = cause_totals_r[cause_totals_r.index.astype(str).str.strip() != ""]
                top_causes_r = cause_totals_r.head(6)
                has_causes = not top_causes_r.empty

                if has_causes:
                    st.caption("🥧 أكتر أسباب الأعطال (دقائق)")
                    st.pyplot(_donut_fig([ar_text(l) for l in top_causes_r.index], top_causes_r.values,
                                          "أكتر أسباب الأعطال (دقائق)", center_text=f"{total_downtime_r:,.0f}\nدقيقة"))

                # ---------- اتجاه الأعطال على مدار الشهر: إجمالي يومي + تفصيل لكل خط ----------
                faults_month_r["_day"] = faults_month_r["التاريخ"].str.split("-").str[-1].astype(int)
                daily_downtime_totals_r = faults_month_r.groupby("_day")["مدة العطل (دقيقة)"].sum().sort_index()
                has_faults_trend = len(daily_downtime_totals_r) > 1

                if has_faults_trend:
                    st.caption("📈 اتجاه إجمالي دقائق التوقف على مدار الشهر")
                    st.pyplot(_trend_line_fig(
                        list(daily_downtime_totals_r.index), daily_downtime_totals_r.values,
                        "اتجاه إجمالي دقائق التوقف", "#dc2626"
                    ))

                daily_line_downtime_pivot_f = faults_month_r.pivot_table(
                    index="_day", columns="الخط", values="مدة العطل (دقيقة)", aggfunc="sum"
                ).fillna(0).sort_index()
                has_faults_line_trend = not daily_line_downtime_pivot_f.empty and len(daily_line_downtime_pivot_f.columns) > 1

                def _build_faults_line_trend_fig():
                    fig_flt, ax_flt = plt.subplots(figsize=(4.6, 2.1), dpi=140)
                    fig_flt.patch.set_facecolor("#ffffff")
                    for i, col in enumerate(daily_line_downtime_pivot_f.columns):
                        ax_flt.plot(
                            list(daily_line_downtime_pivot_f.index), daily_line_downtime_pivot_f[col].tolist(),
                            marker="o", markersize=2.4, linewidth=1.5,
                            color=BRAND_PALETTE[i % len(BRAND_PALETTE)], label=ar_text(str(col))
                        )
                    ax_flt.set_title(ar_text("اتجاه التوقف لكل خط (دقيقة)"), fontsize=8.5, fontweight="bold",
                                      color="#dc2626", pad=6)
                    ax_flt.tick_params(axis="both", labelsize=6)
                    ax_flt.spines["top"].set_visible(False)
                    ax_flt.spines["right"].set_visible(False)
                    ax_flt.grid(axis="y", linestyle="--", alpha=0.4, linewidth=0.5, color="#c9cfd6")
                    ax_flt.legend(fontsize=5.5, ncol=2, loc="upper right")
                    fig_flt.tight_layout(pad=0.6)
                    return fig_flt

                if has_faults_line_trend:
                    st.caption("📈 اتجاه التوقف لكل خط على مدار الشهر")
                    st.pyplot(_build_faults_line_trend_fig())

                faults_chart_parts = [
                    dash_chart_card("📊 إجمالي دقائق التوقف لكل خط", fig_to_base64_img(
                        _bar_fig([ar_text(n) for n in faults_line_summary_r["الخط"]],
                                 faults_line_summary_r["إجمالي دقائق التوقف"], "إجمالي دقائق التوقف لكل خط", "#dc2626")
                    ))
                ]
                if has_causes:
                    faults_chart_parts.append(dash_chart_card("🥧 أكتر أسباب الأعطال (دقائق)", fig_to_base64_img(
                        _donut_fig([ar_text(l) for l in top_causes_r.index], top_causes_r.values,
                                    "أكتر أسباب الأعطال (دقائق)", center_text=f"{total_downtime_r:,.0f}\nدقيقة")
                    )))
                if has_faults_trend:
                    faults_chart_parts.append(dash_chart_card("📈 اتجاه إجمالي دقائق التوقف خلال الشهر", fig_to_base64_img(
                        _trend_line_fig(
                            list(daily_downtime_totals_r.index), daily_downtime_totals_r.values,
                            "اتجاه إجمالي دقائق التوقف", "#dc2626"
                        )
                    )))
                if has_faults_line_trend:
                    faults_chart_parts.append(
                        dash_chart_card("📈 اتجاه التوقف لكل خط", fig_to_base64_img(_build_faults_line_trend_fig()))
                    )
                faults_chart_html = "".join(faults_chart_parts)

                report_parts["faults"] = {
                    "key": "faults",
                    "title": "الأعطال",
                    "subtitle": f"Monthly Report - {month_label_r}",
                    "kpi_html": faults_kpi_html,
                    "chart_html": faults_chart_html,
                    "table_title": "ملخص الأعطال لكل خط",
                    "table_df": faults_line_summary_r,
                }
                report_totals["faults"] = {
                    "downtime_min": total_downtime_r, "count": total_faults_count_r,
                    "line_df": faults_line_summary_r,
                    "causes": top_causes_r if has_causes else None,
                }

                faults_doc_html = build_dashboard_document(
                    "تقرير الأعطال الشهري", month_label_r, [report_parts["faults"]]
                )
                st.download_button(
                    "🖨️ تحميل تقرير الأعطال الشهري (تصميم احترافي)", data=faults_doc_html.encode("utf-8"),
                    file_name=f"faults_report_{selected_month_r}.html", mime="text/html",
                    key="dl_faults_report"
                )

    # ==========================
    # 🏠 صفحة النظرة العامة (Overview) — ملخص شامل بكروت ورسوم بيانية وجداول، بتتحط أول صفحة في البورتفوليو
    # ==========================
    overview_section = None
    if report_totals:
        ov_kpi_defs = []
        if "production" in report_totals:
            t = report_totals["production"]
            ov_kpi_defs.append(("🏭", f"{t['actual']:,.0f} KG", "إجمالي الإنتاج الفعلي", "#2563eb"))
            ov_kpi_defs.append(("📈", f"{t['achievement']:.1f}%", "نسبة تحقيق الإنتاج", "#1e3a8a"))
        if "packing" in report_totals:
            t = report_totals["packing"]
            ov_kpi_defs.append(("📦", f"{t['actual_weight']:,.0f} كجم", "إجمالي الباكينج بالوزن", "#16a34a"))
            ov_kpi_defs.append(("🎯", f"{t['achievement']:.1f}%", "نسبة تحقيق الباكينج", "#065f46"))
        if "breakage" in report_totals:
            t = report_totals["breakage"]
            ov_kpi_defs.append(("🔨", f"{t['net']:,.0f} كجم", "إجمالي الكسر (خارج + داخل)", "#ea580c"))
        if "faults" in report_totals:
            t = report_totals["faults"]
            ov_kpi_defs.append(("⚠️", f"{t['downtime_min']:,.0f} د", "إجمالي دقائق التوقف", "#dc2626"))
            ov_kpi_defs.append(("🛠️", f"{t['count']:,.0f}", "عدد الأعطال", "#7f1d1d"))

        ov_kpi_html = "".join(dash_kpi_card(*d) for d in ov_kpi_defs)

        # ---------- جدول 1: ملخص الأداء العام لكل الأقسام ----------
        ov_rows = []
        if "production" in report_totals:
            t = report_totals["production"]
            ov_rows.append({
                "القسم": "الإنتاج", "المخطط": f"{t['target']:,.0f} KG", "الفعلي": f"{t['actual']:,.0f} KG",
                "نسبة التحقيق %": round(t["achievement"], 1)
            })
        if "packing" in report_totals:
            t = report_totals["packing"]
            ov_rows.append({
                "القسم": "الباكينج (بالوزن)", "المخطط": f"{t['target_weight']:,.0f} كجم",
                "الفعلي": f"{t['actual_weight']:,.0f} كجم", "نسبة التحقيق %": round(t["achievement"], 1)
            })
        if "breakage" in report_totals:
            t = report_totals["breakage"]
            ov_rows.append({
                "القسم": "الكسر", "المخطط": "-", "الفعلي": f"{t['net']:,.0f} كجم (خارج+داخل)", "نسبة التحقيق %": None
            })
        if "faults" in report_totals:
            t = report_totals["faults"]
            ov_rows.append({
                "القسم": "الأعطال", "المخطط": "-", "الفعلي": f"{t['downtime_min']:,.0f} دقيقة",
                "نسبة التحقيق %": None
            })
        ov_table_df = pd.DataFrame(ov_rows)

        # ---------- جدول 2: أبرز المؤشرات للإدارة (Highlights) ----------
        ov_highlights = []
        if "production" in report_totals and report_totals["production"].get("line_df") is not None \
                and not report_totals["production"]["line_df"].empty:
            top_prod_line = report_totals["production"]["line_df"].iloc[0]
            ov_highlights.append({"البند": "🏆 أعلى خط إنتاج", "التفاصيل": f"{top_prod_line['الخط']} — {top_prod_line['الفعلي (KG)']:,.0f} KG"})
        if "packing" in report_totals and report_totals["packing"].get("cat_df") is not None \
                and not report_totals["packing"]["cat_df"].empty:
            top_cat = report_totals["packing"]["cat_df"].iloc[0]
            ov_highlights.append({"البند": "📦 أعلى فئة باكينج", "التفاصيل": f"{top_cat['الفئة']} — {top_cat['الوزن الفعلي (كجم)']:,.0f} كجم"})
        if "breakage" in report_totals and report_totals["breakage"].get("line_df") is not None \
                and not report_totals["breakage"]["line_df"].empty:
            top_break_line = report_totals["breakage"]["line_df"].iloc[0]
            ov_highlights.append({"البند": "🔻 أعلى خط كسر (خارج)", "التفاصيل": f"{top_break_line['الخط']} — {top_break_line['كسر خارج (KG)']:,.0f} كجم"})
        if "faults" in report_totals and report_totals["faults"].get("line_df") is not None \
                and not report_totals["faults"]["line_df"].empty:
            top_fault_line = report_totals["faults"]["line_df"].iloc[0]
            ov_highlights.append({"البند": "⏱️ أكتر خط توقف", "التفاصيل": f"{top_fault_line['الخط']} — {top_fault_line['إجمالي دقائق التوقف']:,.0f} دقيقة"})
        if "faults" in report_totals and report_totals["faults"].get("causes") is not None:
            causes_s = report_totals["faults"]["causes"]
            if not causes_s.empty:
                ov_highlights.append({"البند": "⚠️ أكتر سبب عطل", "التفاصيل": f"{causes_s.index[0]} — {causes_s.values[0]:,.0f} دقيقة"})
        ov_highlights_df = pd.DataFrame(ov_highlights) if ov_highlights else None

        # ---------- الرسوم البيانية ----------
        ov_chart_parts = []

        if "production" in report_totals and report_totals["production"].get("line_df") is not None \
                and not report_totals["production"]["line_df"].empty:
            prod_ldf = report_totals["production"]["line_df"]
            ov_chart_parts.append(dash_chart_card("🥧 توزيع الإنتاج حسب الخط", fig_to_base64_img(
                _donut_fig([ar_text(l) for l in prod_ldf["الخط"]], prod_ldf["الفعلي (KG)"],
                           "توزيع الإنتاج حسب الخط", center_text=f"{report_totals['production']['actual']:,.0f}\nKG")
            )))
            ov_chart_parts.append(dash_chart_card("📊 المستهدف مقابل الفعلي لكل خط", fig_to_base64_img(
                _grouped_bar_fig(prod_ldf["الخط"], prod_ldf["الفعلي (KG)"], prod_ldf["المستهدف (KG)"],
                                 "المستهدف مقابل الفعلي لكل خط")
            )))

        if "production" in report_totals and report_totals["production"].get("trend_values"):
            t = report_totals["production"]
            ov_chart_parts.append(dash_chart_card("📈 اتجاه الإنتاج اليومي (KG)", fig_to_base64_img(
                _trend_line_fig(t["trend_days"], t["trend_values"], "اتجاه الإنتاج اليومي (KG)", "#2563eb")
            )))

        if "packing" in report_totals and report_totals["packing"].get("cat_df") is not None \
                and not report_totals["packing"]["cat_df"].empty:
            pack_cdf = report_totals["packing"]["cat_df"]
            ov_chart_parts.append(dash_chart_card("🥧 توزيع الباكينج حسب الفئة", fig_to_base64_img(
                _donut_fig([ar_text(c) for c in pack_cdf["الفئة"]], pack_cdf["الوزن الفعلي (كجم)"],
                           "توزيع الباكينج حسب الفئة", center_text=f"{report_totals['packing']['actual_weight']:,.0f}\nكجم")
            )))

        if "packing" in report_totals and report_totals["packing"].get("trend_values"):
            t = report_totals["packing"]
            ov_chart_parts.append(dash_chart_card("📈 اتجاه الباكينج اليومي بالوزن (كجم)", fig_to_base64_img(
                _trend_line_fig(t["trend_days"], t["trend_values"], "اتجاه الباكينج اليومي (كجم)", "#16a34a")
            )))

        if "breakage" in report_totals and report_totals["breakage"].get("line_df") is not None \
                and not report_totals["breakage"]["line_df"].empty:
            break_ldf = report_totals["breakage"]["line_df"]
            ov_chart_parts.append(dash_chart_card("📊 كسر خارج لكل خط (كجم)", fig_to_base64_img(
                _bar_fig([ar_text(n) for n in break_ldf["الخط"]], break_ldf["كسر خارج (KG)"],
                         "كسر خارج لكل خط (كجم)", "#dc2626")
            )))

        if "faults" in report_totals and report_totals["faults"].get("line_df") is not None \
                and not report_totals["faults"]["line_df"].empty:
            faults_ldf = report_totals["faults"]["line_df"]
            ov_chart_parts.append(dash_chart_card("📊 دقائق التوقف لكل خط", fig_to_base64_img(
                _bar_fig([ar_text(n) for n in faults_ldf["الخط"]], faults_ldf["إجمالي دقائق التوقف"],
                         "دقائق التوقف لكل خط", "#ea580c")
            )))

        if "faults" in report_totals and report_totals["faults"].get("causes") is not None \
                and not report_totals["faults"]["causes"].empty:
            causes_s = report_totals["faults"]["causes"]
            ov_chart_parts.append(dash_chart_card("🥧 أكتر أسباب الأعطال (دقائق)", fig_to_base64_img(
                _donut_fig([ar_text(l) for l in causes_s.index], causes_s.values,
                           "أكتر أسباب الأعطال (دقائق)", center_text=f"{report_totals['faults']['downtime_min']:,.0f}\nدقيقة")
            )))

        achievement_labels, achievement_vals = [], []
        if "production" in report_totals:
            achievement_labels.append("الإنتاج")
            achievement_vals.append(report_totals["production"]["achievement"])
        if "packing" in report_totals:
            achievement_labels.append("الباكينج")
            achievement_vals.append(report_totals["packing"]["achievement"])
        if achievement_labels:
            ov_chart_parts.append(dash_chart_card("📈 مقارنة نسب التحقيق", fig_to_base64_img(
                _bar_fig([ar_text(l) for l in achievement_labels], achievement_vals,
                         "مقارنة نسب التحقيق %", "#7a5b0e")
            )))

        ov_chart_html = "".join(ov_chart_parts)

        # ---------- تجميع جدولين في التقرير: الملخص العام + المؤشرات البارزة ----------
        ov_extra_html = ""
        if ov_highlights_df is not None:
            ov_highlights_table_html = ov_highlights_df.to_html(index=False, border=0, justify="center", na_rep="-")
            ov_extra_html = f"""
            <div class="table-card">
                <div class="table-card-header" style="background:#7a5b0e;">أبرز المؤشرات للإدارة</div>
                {ov_highlights_table_html}
            </div>
            """

        overview_section = {
            "key": "overview",
            "title": "اوفر فيو",
            "subtitle": f"نظرة عامة — ملخص شامل لكل الأقسام - {month_label_r}",
            "kpi_html": ov_kpi_html,
            "chart_html": ov_chart_html,
            "table_title": "ملخص الأداء العام لكل الأقسام",
            "table_df": ov_table_df,
            "extra_html": ov_extra_html,
        }

    # ==========================
    # 🗂️ التقرير الشهري الشامل — تجميع كل التقارير في ملف واحد بتصميم احترافي
    # ==========================
    st.divider()
    st.markdown("### 🗂️ التقرير الشهري الشامل — تجميع كل التقارير في ملف واحد")
    st.caption(
        "الصفحة الأولى بتبقى 'اوفر فيو' فيها ملخص كل الأقسام، وبعدها كل تقرير بالتفصيل في صفحة لوحده — "
        "زي داشبورد احترافي حقيقي. الملف HTML مستقل تمامًا: تقدر تنشره كصفحة ويب زي ما هو، "
        "أو تفتحه وتدوس Ctrl+P وتحفظه PDF"
    )

    if not report_parts:
        st.info("مفيش تقارير اتولدت لسه — لازم يكون فيه بيانات مسجلة للشهر المختار عشان تقدر تجمعها")
    else:
        labels_map_r = {
            "production": "🏭 انتاج الخطوط",
            "packing": "📦 الباكينج",
            "faults": "⚠️ الأعطال",
            "breakage": "🔨 الكسر",
        }
        available_keys_r = [k for k in ["production", "packing", "faults", "breakage"] if k in report_parts]
        chosen_keys_r = st.multiselect(
            "اختار التقارير اللي عايز تجمعها",
            options=available_keys_r,
            default=available_keys_r,
            format_func=lambda k: labels_map_r.get(k, k),
            key="portfolio_report_select"
        )
        include_overview_r = True
        if overview_section is not None:
            include_overview_r = st.checkbox(
                "🏠 ضيف صفحة 'اوفر فيو' في الأول (ملخص شامل لكل الأقسام)", value=True, key="portfolio_include_overview"
            )
        if chosen_keys_r:
            portfolio_sections_r = [report_parts[k] for k in chosen_keys_r]
            if overview_section is not None and include_overview_r:
                portfolio_sections_r = [overview_section] + portfolio_sections_r
            portfolio_html_r = build_dashboard_document(
                "التقرير الشهري الشامل", month_label_r, portfolio_sections_r
            )
            st.download_button(
                "🖨️ تحميل التقرير الشهري الشامل (HTML / PDF)",
                data=portfolio_html_r.encode("utf-8"),
                file_name=f"monthly_report_{selected_month_r}.html",
                mime="text/html",
                help="ملف HTML واحد بتصميم لوحة تحكم احترافية — اوفر فيو أول صفحة، وبعدها كل تقرير بالتفصيل "
                     "في صفحة لوحده — تقدر تنشره على أي موقع أو تفتحه وتدوس Ctrl+P وتحفظه PDF. "
                     "⚠️ لو الطباعة طلعت صفحة فاضية أو الشكل غريب، تأكد إنك اخترت 'اتجاه الصفحة: أفقي / Landscape' "
                     "من إعدادات الطباعة",
                key="dl_portfolio"
            )
        else:
            st.info("اختار تقرير واحد على الأقل")

    # ==========================
    # 🔍 فلترة بيانات الإنتاج الخام (تفصيلي)
    # ==========================
    st.divider()
    st.subheader("🔍 فلترة بيانات الإنتاج الخام (تفصيلي)")

    if GSHEETS_ENABLED and gsheet_exists(PRODUCTION_SHEET):
        history_df = read_gsheet(PRODUCTION_SHEET)

        f1, f2 = st.columns(2)
        with f1:
            date_filter = st.multiselect(
                "اختر التاريخ",
                options=sorted(history_df["Date"].unique(), reverse=True)
            )
        with f2:
            line_filter = st.multiselect(
                "اختر الخط",
                options=sorted({str(l) for l in history_df["Line"].dropna() if str(l).strip() != ""})
            )

        filtered = history_df.copy()
        if date_filter:
            filtered = filtered[filtered["Date"].isin(date_filter)]
        if line_filter:
            filtered = filtered[filtered["Line"].isin(line_filter)]

        st.dataframe(filtered, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇ تحميل كل البيانات CSV",
            data=history_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="production_history.csv",
            mime="text/csv"
        )
    else:
        st.info("لسه مفيش تقارير. سجل بيانات إنتاج الأول من صفحة Production.")

elif page == "Settings":
    page_banner("⚙️", "Settings", "إعدادات عامة للبرنامج وخطوط الإنتاج")
    st.subheader("🏭 Production Lines Management")
    new_line = st.text_input("Add New Production Line")
    if st.button("➕ Add Line"):
        clean_line = new_line.strip()
        if not clean_line:
            st.warning("اكتب اسم الخط الأول ⚠")
        elif clean_line in st.session_state.production_lines:
            st.warning("الخط ده موجود بالفعل ⚠")
        else:
            st.session_state.production_lines.append(clean_line)
            st.success("Line Added Successfully")

    st.write("Current Production Lines:")
    for line in st.session_state.production_lines:
        c1, c2 = st.columns([4, 1])
        c1.write(f"🔹 {line}")
        if c2.button("🗑", key=f"del_{line}"):
            st.session_state.production_lines.remove(line)
            st.rerun()
