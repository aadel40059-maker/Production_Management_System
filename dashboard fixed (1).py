import streamlit as st
import pandas as pd
import os
import calendar
import matplotlib.pyplot as plt
import numpy as np
import base64
import io
import time
from datetime import datetime, time as dtime

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


def _gspread_retry(func, *args, max_attempts=4, **kwargs):
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
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def _get_worksheet(sheet_name):
    client = _get_gsheet_client()
    spreadsheet = _gspread_retry(client.open_by_key, st.secrets["gsheets"]["sheet_id"])
    safe_name = sheet_name[:99]  # حد أقصى لاسم التاب في جوجل شيت
    try:
        ws = _gspread_retry(spreadsheet.worksheet, safe_name)
    except gspread.WorksheetNotFound:
        ws = _gspread_retry(spreadsheet.add_worksheet, title=safe_name, rows=2000, cols=60)
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


@st.cache_data(ttl=20, show_spinner=False)
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


def write_gsheet(sheet_name, df):
    ws = _get_worksheet(sheet_name)
    if df.empty:
        _gspread_retry(ws.clear)
        _gspread_retry(ws.update, [df.columns.tolist()])
        _read_gsheet_cached.clear()
        return

    # نكتب البيانات الجديدة الأول (من غير ما نمسح حاجة) عشان الشيت مايفضلش فاضي لحظة واحدة
    values = [df.columns.tolist()] + df.astype(str).values.tolist()
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
    existing = _gspread_retry(ws.get_all_values)
    if not existing:
        _gspread_retry(ws.append_row, df_rows.columns.tolist())
    _gspread_retry(ws.append_rows, df_rows.astype(str).values.tolist())
    _read_gsheet_cached.clear()



st.set_page_config(
    page_title="Production by eng/ahmed adel",
    page_icon="🏭",
    layout="wide"
)

# ---------- زرار تبديل نهاري / ليلي ----------
if "app_theme" not in st.session_state:
    st.session_state.app_theme = "light"

theme_pick = st.sidebar.radio(
    "🎨 الوضع", ["🌞 نهاري", "🌙 ليلي"],
    index=0 if st.session_state.app_theme == "light" else 1,
    horizontal=True, key="theme_toggle"
)
st.session_state.app_theme = "light" if theme_pick == "🌞 نهاري" else "dark"

if st.session_state.app_theme == "light":
    theme_css = """
    <style>
    [data-testid="stSidebar"] { background-color: #0b1f3a; }
    [data-testid="stSidebar"] * { color: #ffffff !important; }

    .stButton>button, .stDownloadButton>button {
        background-color: #2f6fed; color: #ffffff; border: none;
        border-radius: 8px; font-weight: 600; padding: 8px 18px;
    }
    .stButton>button:hover, .stDownloadButton>button:hover { filter: brightness(0.92); color:#ffffff; }

    [data-testid="stMetric"] {
        background-color: #f4f7fb; border: 1px solid #dbe4f0;
        border-radius: 12px; padding: 14px 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    h1, h2, h3 { font-weight: 700; letter-spacing: -0.3px; color: #0b1f3a; }
    p, span, label, div, li { font-weight: 500; }

    /* قائمة الصفحات كمربعات كاملة قابلة للاختيار */
    [data-testid="stSidebar"] [data-testid="stRadio"] > div {
        gap: 6px;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label {
        display: flex;
        width: 100%;
        padding: 10px 14px;
        border-radius: 8px;
        background-color: rgba(255,255,255,0.07);
        margin-bottom: 4px;
        font-weight: 700;
        cursor: pointer;
        transition: background-color 0.15s;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
        background-color: rgba(255,255,255,0.18);
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
        background-color: #2f6fed;
    }
    </style>
    """
else:
    theme_css = """
    <style>
    .stApp { background-color: #0f172a; color: #e5e7eb; }
    [data-testid="stSidebar"] { background-color: #060c1a; }
    [data-testid="stSidebar"] * { color: #e5e7eb !important; }

    .stButton>button, .stDownloadButton>button {
        background-color: #3b82f6; color: #ffffff; border: none;
        border-radius: 8px; font-weight: 600; padding: 8px 18px;
    }
    .stButton>button:hover, .stDownloadButton>button:hover { filter: brightness(1.1); color:#ffffff; }

    [data-testid="stMetric"] {
        background-color: #1e293b; border: 1px solid #334155;
        border-radius: 12px; padding: 14px 16px;
    }
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"] { color: #e5e7eb; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #e5e7eb !important; }
    p, span, label, div, li { font-weight: 500; }

    /* قائمة الصفحات كمربعات كاملة قابلة للاختيار */
    [data-testid="stSidebar"] [data-testid="stRadio"] > div {
        gap: 6px;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label {
        display: flex;
        width: 100%;
        padding: 10px 14px;
        border-radius: 8px;
        background-color: rgba(255,255,255,0.06);
        margin-bottom: 4px;
        font-weight: 700;
        cursor: pointer;
        transition: background-color 0.15s;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
        background-color: rgba(255,255,255,0.15);
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
        background-color: #3b82f6;
    }
    </style>
    """

st.markdown(theme_css, unsafe_allow_html=True)

DATA_FILE = "production_history.csv"
PRODUCTION_SHEET = "production_history"  # اسم تاب جوجل شيت لبيانات الإنتاج
SHIFTS = ["First Shift", "Second Shift", "Third Shift"]

if "production_lines" not in st.session_state:
    st.session_state.production_lines = [
        "Continuous",
        "Italian",
        "TransLab",
        "Toffee",
        "Eclair",
    ]

logo_path = None
for candidate in ["logo.jpg", "logo.jpeg", "logo.png"]:
    if os.path.exists(candidate):
        logo_path = candidate
        break

if logo_path:
    st.image(logo_path, width=260)

st.title("🏭Production Management System")
st.caption("Developed by Eng/Ahmed Adel")
st.write("Track production, inventory, and performance in one place")
st.write("نظام متابعه و إداره الإنتاج")
st.divider()

st.sidebar.title("📏menu")
page = st.sidebar.radio(
    "choose a page",
    [
        "Dashboard",
        "Production",
        "Packing",
        "الأعطال",
        "Inventory",
        "Workers",
        "Reports",
        "Settings",
    ]
)


def build_production_table():
    """يبني جدول فاضي مبني على قائمة الخطوط الحالية في session_state"""
    data = []
    for line in st.session_state.production_lines:
        data.append({
            "Line": f"🏭 {line}",
            "Shift": "All Shifts",
            "Target (KG)": 0,
            "Actual (KG)": 0,
            "DownTime (min)": 0,
            "Waste (KG)": 0,
            "Remarks": ""
        })
        for shift in SHIFTS:
            data.append({
                "Line": "",
                "Shift": shift,
                "Target (KG)": 0,
                "Actual (KG)": 0,
                "DownTime (min)": 0,
                "Waste (KG)": 0,
                "Remarks": ""
            })
    return pd.DataFrame(data)


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


def build_printable_html(title, subtitle, df, extra_title=None, extra_df=None, extra_tables=None, landscape=False, extra_html=None):
    """يبني صفحة HTML جاهزة للطباعة/تحويل PDF من المتصفح (Ctrl+P > Save as PDF)
    extra_tables: قائمة اختيارية [(عنوان, DataFrame), ...] تتحط كلها جنب الجدول الرئيسي فوق بعض
    extra_html: أي HTML إضافي (زي جدول ملخص أو صورة رسم بياني) يتحط تحت الجدول الرئيسي مباشرة"""
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

    page_size = "A4 landscape" if landscape else "A4"

    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        @page {{ size: {page_size}; margin: 6mm; }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; margin: 0; padding: 6px; color: #1a1d21; }}
        h1 {{ font-size: 16px; margin: 0 0 2px; }}
        h2 {{ color: #0b1f3a; font-size: 11px; margin: 8px 0 4px; }}
        p.dev {{ color: #374151; margin: 0 0 4px; font-size: 10px; font-weight: 600; }}
        p.sub {{ color: #6b7280; margin: 0 0 6px; font-size: 9px; }}

        table.layout-wrapper {{ border-collapse: collapse; }}
        table.layout-wrapper > tr > td {{ border: none; padding: 0; }}
        td.main-cell {{ width: 74%; padding-left: 10px !important; }}
        td.side-cell {{ width: 26%; }}
        .side-block {{ margin-bottom: 10px; }}
        .side-block:first-child h2 {{ margin-top: 0; }}

        table:not(.layout-wrapper) {{ border-collapse: collapse; width: 100%; font-size: 10px; }}
        table:not(.layout-wrapper) th, table:not(.layout-wrapper) td {{
            border: 1px solid #d1d5db; padding: 2.5px 4px; text-align: center;
        }}
        table:not(.layout-wrapper) th {{ background-color: #f4f7fb; font-weight: 700; }}
        table:not(.layout-wrapper) tr:nth-child(even) {{ background-color: #fafafa; }}
        table:not(.layout-wrapper) tr:last-child {{ font-weight: 700; background-color: #eef2f7; }}
        .side-cell table {{ font-size: 9px; }}

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
        {layout_html}
        {extra_html or ''}
    </body>
    </html>
    """
    return html


if page == "Dashboard":
    st.header("🏭 لوحة المتابعة الشاملة")

    current_month_str = datetime.now().strftime("%Y-%m")
    today_day_num = datetime.now().day

    # ---------- بيانات الإنتاج (خطوط) ----------
    prod_target = prod_actual = prod_downtime_min = prod_waste = 0
    prod_by_line = pd.DataFrame()
    if GSHEETS_ENABLED and gsheet_exists(PRODUCTION_SHEET):
        hist_df = read_gsheet(PRODUCTION_SHEET)
        hist_df["Date"] = hist_df["Date"].astype(str)
        month_hist = hist_df[hist_df["Date"].str.startswith(current_month_str)]
        month_hist = month_hist[month_hist["Shift"] == "All Shifts"]
        if not month_hist.empty:
            for nc in ["Target (KG)", "Actual (KG)", "DownTime (min)", "Waste (KG)"]:
                month_hist[nc] = pd.to_numeric(month_hist[nc], errors="coerce").fillna(0)
            prod_target = month_hist["Target (KG)"].sum()
            prod_actual = month_hist["Actual (KG)"].sum()
            prod_downtime_min = month_hist["DownTime (min)"].sum()
            prod_waste = month_hist["Waste (KG)"].sum()
            prod_by_line = month_hist.groupby("Line")[["Target (KG)", "Actual (KG)"]].sum()

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

    # ---------- بيانات الأعطال ----------
    faults_total_min = 0
    faults_by_line = pd.Series(dtype=float)
    faults_file = f"faults_monthly_{current_month_str}.csv"
    if os.path.exists(faults_file):
        faults_df = pd.read_csv(faults_file)
        day_cols_f_dash = [c for c in faults_df.columns if c.startswith("يوم")]
        if day_cols_f_dash:
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
    quality = ((prod_actual - prod_waste) / prod_actual) if prod_actual > 0 else 1
    oee = max(0, min(availability * performance * quality * 100, 100))

    # ---------- رسم مقياس OEE (Gauge) ----------
    gc1, gc2 = st.columns([1, 2])
    with gc1:
        fig_gauge, ax_gauge = plt.subplots(figsize=(4, 2.6), subplot_kw={"projection": None})
        bands = [50, 30, 20]
        colors = ["#e74c3c", "#f39c12", "#2ecc71"]
        start = 180
        for band, color in zip(bands, colors):
            ax_gauge.pie([band, 360 - band], radius=1, colors=[color, "none"],
                         startangle=start, counterclock=False,
                         wedgeprops={"width": 0.3, "edgecolor": "none"})
            start -= band * 1.8

        needle_angle = 180 - (oee / 100 * 180)
        needle_rad = needle_angle * 3.14159 / 180
        ax_gauge.plot([0, 0.75 * np.cos(needle_rad)], [0, 0.75 * np.sin(needle_rad)],
                      color="#1a1d21", linewidth=3)
        ax_gauge.add_artist(plt.Circle((0, 0), 0.05, color="#1a1d21"))
        ax_gauge.text(0, -0.25, f"{oee:.1f}%", ha="center", fontsize=20, fontweight="bold")
        ax_gauge.text(0, -0.45, "OEE التقريبية", ha="center", fontsize=11, color="#6b7280")
        ax_gauge.set_xlim(-1, 1)
        ax_gauge.set_ylim(-0.6, 1)
        ax_gauge.axis("off")
        st.pyplot(fig_gauge)

    with gc2:
        st.markdown("##### 📊 مؤشرات الشهر الحالي")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🎯 إنتاج (فعلي/مخطط)", f"{prod_actual:,.0f} / {prod_target:,.0f} KG")
        m2.metric("📦 باكينج (فعلي/مخطط)", f"{pack_actual:,.0f} / {pack_target:,.0f} كرتونة")
        m3.metric("⏰ إجمالي التوقف", f"{faults_total_min/60:,.1f} ساعة")
        m4.metric("♻ الفاقد", f"{prod_waste:,.0f} KG")

    st.divider()
    st.subheader("📈 تفصيل الأداء")

    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        st.caption("إنتاج الخطوط: فعلي مقابل مخطط")
        if not prod_by_line.empty:
            st.bar_chart(prod_by_line)
        else:
            st.info("لا توجد بيانات إنتاج مسجلة لهذا الشهر")
    with dc2:
        st.caption("الباكينج حسب الفئة (كرتونة)")
        if not pack_by_cat.empty:
            st.bar_chart(pack_by_cat)
        else:
            st.info("لا توجد بيانات باكينج مسجلة لهذا الشهر")
    with dc3:
        st.caption("توزيع وقت التوقف حسب الخط")
        if not faults_by_line.empty:
            fig_f, ax_f = plt.subplots()
            ax_f.pie(faults_by_line.values, labels=faults_by_line.index, autopct="%1.0f%%", startangle=90)
            ax_f.axis("equal")
            st.pyplot(fig_f)
        else:
            st.info("لا توجد أعطال مسجلة لهذا الشهر")

    st.caption("⚠ مؤشر OEE تقريبي مبني على افتراض تشغيل 24 ساعة لكل الخطوط، فهو للاسترشاد فقط وليس رقمًا دقيقًا معتمدًا.")

elif page == "Production":
    st.header("🏭 Production Management")

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

    Production_date = st.date_input("📅 Production Date")

    # لو الخطوط اتغيرت (اتضافت من صفحة Settings) نبني الجدول من جديد
    current_lines_key = ",".join(st.session_state.production_lines)
    if (
        "production_df" not in st.session_state
        or st.session_state.get("production_lines_key") != current_lines_key
    ):
        st.session_state.production_df = build_production_table()
        st.session_state.production_lines_key = current_lines_key

    edited_df = st.data_editor(
        st.session_state.production_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="Production_table"
    )

    st.session_state.production_df = edited_df

    st.divider()

    total_target = edited_df["Target (KG)"].sum()
    total_actual = edited_df["Actual (KG)"].sum()
    total_downtime = edited_df["DownTime (min)"].sum()
    total_waste = edited_df["Waste (KG)"].sum()

    achievement = (total_actual / total_target * 100) if total_target > 0 else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("🎯 Target", f"{total_target:,.0f} KG")
    col2.metric("📦 Actual", f"{total_actual:,.0f} KG")
    col3.metric("🥇 Achievement", f"{achievement:.1f}%")
    col4.metric("⏰ DownTime", f"{total_downtime:,.0f} min")
    col5.metric("♻ Waste", f"{total_waste:,.0f} KG")

    if st.button("💾 Save Production"):
        # نجهز نسخة من الجدول ونضيفلها التاريخ عشان نقدر نجمع بيانات كتير على مر الوقت
        to_save = edited_df.copy()
        to_save.insert(0, "Date", Production_date.strftime("%Y-%m-%d"))
        to_save.insert(1, "Saved At", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # نشيل السطور الفاضية اللي مالهاش قيم حقيقية (اختياري بس بيخلي البيانات أنضف)
        to_save = to_save[
            (to_save["Target (KG)"] != 0) |
            (to_save["Actual (KG)"] != 0) |
            (to_save["DownTime (min)"] != 0) |
            (to_save["Waste (KG)"] != 0) |
            (to_save["Remarks"].astype(str).str.strip() != "")
        ]

        if to_save.empty:
            st.warning("مفيش بيانات حقيقية اتدخلت عشان تتحفظ ⚠")
        else:
            append_gsheet(PRODUCTION_SHEET, to_save)
            st.success(f"Production data saved successfully ✔ ({len(to_save)} صف اتحفظ)")

elif page == "Packing":
    st.header("📦 Packing")

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

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🎯 إجمالي المخطط", f"{summary['المخطط بالكراتين (شهري)'].sum():,.0f} كرتونة")
        c2.metric("📦 إجمالي المُنتج", f"{summary['إجمالي الكراتين'].sum():,.0f} كرتونة")
        total_target_sum = summary["المخطط بالكراتين (شهري)"].sum()
        total_pct = round(
            (summary["إجمالي الكراتين"].sum() / total_target_sum * 100) if total_target_sum > 0 else 0, 1
        )
        c3.metric("🥇 نسبة التحقيق", f"{total_pct}%")
        c4.metric("⚖ الوزن الفعلي", f"{summary['الوزن الفعلي (كيلو)'].sum():,.1f} كجم")

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
        report_date = pd.Timestamp(year=year, month=month_num, day=day_pick).strftime("%Y-%m-%d")
        prod_line_table = pd.DataFrame(columns=["الخط", "المخطط (KG)", "الفعلي (KG)"])
        if GSHEETS_ENABLED and gsheet_exists(PRODUCTION_SHEET):
            hist_df_p = read_gsheet(PRODUCTION_SHEET)
            hist_df_p["Date"] = hist_df_p["Date"].astype(str)
            day_hist = hist_df_p[(hist_df_p["Date"] == report_date) & (hist_df_p["Shift"] == "All Shifts")]
            if not day_hist.empty:
                for nc in ["Target (KG)", "Actual (KG)"]:
                    day_hist[nc] = pd.to_numeric(day_hist[nc], errors="coerce").fillna(0)
                prod_line_table = day_hist.groupby("Line")[["Target (KG)", "Actual (KG)"]].sum().reset_index()
                prod_line_table.columns = ["الخط", "المخطط (KG)", "الفعلي (KG)"]

        # ---------- جدول صغير: الأعطال لنفس اليوم (من جوجل شيت) ----------
        faults_table = pd.DataFrame(columns=["الخط", "مدة التوقف (دقيقة)"])
        faults_sheet_name = f"faults_monthly_{selected_month}"
        if GSHEETS_ENABLED and gsheet_exists(faults_sheet_name):
            faults_df_p = read_gsheet(faults_sheet_name)
            if day_col_pick in faults_df_p.columns and "الخط" in faults_df_p.columns:
                faults_df_p[day_col_pick] = pd.to_numeric(faults_df_p[day_col_pick], errors="coerce").fillna(0)
                faults_table = faults_df_p[["الخط", day_col_pick]].rename(columns={day_col_pick: "مدة التوقف (دقيقة)"})
                faults_table = faults_table[faults_table["مدة التوقف (دقيقة)"] >= 0]

        printable_html = build_printable_html(
            f"تقرير Packing اليومي — شهر {selected_month}",
            f"يوم {day_pick} — تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            print_df,
            landscape=True,
            extra_tables=[
                (f"📅 تعبئة يوم {day_pick} بالفئات", daily_by_cat_display),
                ("🏭 إنتاج الخطوط لنفس اليوم", prod_line_table),
                ("⚠ الأعطال لنفس اليوم", faults_table),
            ]
        )
        st.download_button(
            "🖨️ تحميل نسخة قابلة للطباعة (PDF)",
            data=printable_html.encode("utf-8"),
            file_name=f"packing_{selected_month}_day{day_pick}.html",
            mime="text/html",
            help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' عشان تحوله PDF أو تطبعه"
        )

        st.divider()
        st.subheader("📈 الرسوم البيانية")

        category_totals = summary.groupby("الفئة")["إجمالي الكراتين"].sum()
        cat_c1, cat_c2 = st.columns([1, 1])
        with cat_c1:
            st.caption("توزيع الإنتاج بين الفئات الثلاثة")
            fig1, ax1 = plt.subplots()
            ax1.pie(category_totals.values, labels=category_totals.index, autopct="%1.1f%%", startangle=90)
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


elif page == "الأعطال":
    st.header("⚠ الأعطال")

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
    }
    fault_lines = list(fault_line_passwords.keys())
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
        """الجدول الشهري التجميعي: إجمالي دقائق التوقف لكل خط في كل يوم"""
        f_year, f_month = map(int, month_str.split("-"))
        f_days = calendar.monthrange(f_year, f_month)[1]
        f_day_cols = [f"يوم {d}" for d in range(1, f_days + 1)]
        f_cols = ["الخط", "سبب/ملاحظات"] + f_day_cols
        f_path = f"faults_monthly_{month_str}"
        if gsheet_exists(f_path):
            grid = read_gsheet(f_path)
            for c in f_cols:
                if c not in grid.columns:
                    grid[c] = 0 if c in f_day_cols else ""
            grid = grid[f_cols]
        else:
            grid = pd.DataFrame([
                {"الخط": line, "سبب/ملاحظات": "", **{dc: 0 for dc in f_day_cols}}
                for line in lines_for_default
            ])
        return grid, f_path, f_day_cols

    DAILY_LOG_SHEET = "faults_daily_log"
    DAILY_LOG_COLS = ["التاريخ", "الخط", "اسم الماكينة", "الوردية", "من الساعة", "إلى الساعة", "مدة العطل (دقيقة)", "سبب العطل"]

    def load_daily_log():
        """السجل التفصيلي: كل عطل بصف لوحده (خط / ماكينة / وردية / من - إلى / مدة / سبب)"""
        if gsheet_exists(DAILY_LOG_SHEET):
            log_df = read_gsheet(DAILY_LOG_SHEET)
            for c in DAILY_LOG_COLS:
                if c not in log_df.columns:
                    log_df[c] = 0 if c == "مدة العطل (دقيقة)" else ""
            log_df = log_df[DAILY_LOG_COLS]
            log_df["مدة العطل (دقيقة)"] = pd.to_numeric(log_df["مدة العطل (دقيقة)"], errors="coerce").fillna(0)
        else:
            log_df = pd.DataFrame(columns=DAILY_LOG_COLS)
        return log_df

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
            log_day_col = f"يوم {log_date.day}"
            grid, f_path, f_day_cols = load_faults_grid(log_month_str, fault_lines)

            if my_line not in grid["الخط"].values:
                new_row = {"الخط": my_line, "سبب/ملاحظات": "", **{dc: 0 for dc in f_day_cols}}
                grid = pd.concat([grid, pd.DataFrame([new_row])], ignore_index=True)

            row_idx = grid[grid["الخط"] == my_line].index[0]
            current_val = pd.to_numeric(grid.at[row_idx, log_day_col], errors="coerce")
            current_val = 0 if pd.isna(current_val) else current_val
            grid.at[row_idx, log_day_col] = current_val + duration

            if reason.strip():
                existing_notes = str(grid.at[row_idx, "سبب/ملاحظات"])
                existing_notes = "" if existing_notes == "nan" else existing_notes
                time_part = f" ({from_t.strftime('%H:%M')}-{to_t.strftime('%H:%M')})" if duration > 0 else ""
                note_entry = f"{log_date.strftime('%Y-%m-%d')}{time_part}: {reason.strip()}"
                grid.at[row_idx, "سبب/ملاحظات"] = (existing_notes + " | " + note_entry) if existing_notes else note_entry

            write_gsheet(f_path, grid)

            # ---- سجل تفصيلي منفصل: كل عطل بصف لوحده، ماكينة/وردية/من-إلى واضحين ----
            daily_log = load_daily_log()
            new_log_row = pd.DataFrame([{
                "التاريخ": log_date.strftime("%Y-%m-%d"),
                "الخط": my_line,
                "اسم الماكينة": machine_name.strip(),
                "الوردية": shift_pick,
                "من الساعة": from_t.strftime("%H:%M"),
                "إلى الساعة": to_t.strftime("%H:%M"),
                "مدة العطل (دقيقة)": duration,
                "سبب العطل": reason.strip()
            }])
            daily_log = pd.concat([daily_log, new_log_row], ignore_index=True)
            write_gsheet(DAILY_LOG_SHEET, daily_log)

            st.success(f"اتسجل عطل خط {my_line} ليوم {log_date.strftime('%Y-%m-%d')} ✔")
            st.rerun()

    st.divider()

    # ==========================
    # الجدول التجميعي الشهري (DataFrame) — عرض بس، متاح لأي حد يشوفه
    # ==========================
    faults_grid, FAULTS_FILE, _ = load_faults_grid(selected_month_f, fault_lines)

    for dc in day_cols_f:
        faults_grid[dc] = pd.to_numeric(faults_grid[dc], errors="coerce").fillna(0)

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
    st.caption("تقرير جاهز للطباعة والعرض على الإدارة — كل خط ماسجلش عطل بيظهر جنبه 'لا يوجد عطل'")

    daily_report_date = st.date_input("📅 اختر يوم التقرير", value=today_f, key="faults_daily_report_date")
    daily_report_date_str = daily_report_date.strftime("%Y-%m-%d")

    daily_log_all = load_daily_log()
    day_incidents = daily_log_all[daily_log_all["التاريخ"] == daily_report_date_str].copy()

    # الخطوط اللي مسجلتش أي عطل اليوم ده — تظهر بصف "لا يوجد عطل"
    lines_with_incident = set(day_incidents["الخط"])
    no_fault_rows = pd.DataFrame([
        {"التاريخ": daily_report_date_str, "الخط": l, "اسم الماكينة": "-", "الوردية": "-",
         "من الساعة": "-", "إلى الساعة": "-", "مدة العطل (دقيقة)": 0, "سبب العطل": "لا يوجد عطل"}
        for l in fault_lines if l not in lines_with_incident
    ])

    daily_report_df = pd.concat([day_incidents, no_fault_rows], ignore_index=True)
    daily_report_df = daily_report_df[["الخط", "اسم الماكينة", "الوردية", "من الساعة", "إلى الساعة", "مدة العطل (دقيقة)", "سبب العطل"]]
    daily_report_df = daily_report_df.sort_values("الخط").reset_index(drop=True)

    st.dataframe(daily_report_df, use_container_width=True, hide_index=True)

    total_day_minutes = daily_report_df["مدة العطل (دقيقة)"].sum()
    lines_with_faults = len(lines_with_incident)
    dc1, dc2 = st.columns(2)
    dc1.metric("⏰ إجمالي توقف اليوم", f"{total_day_minutes:,.0f} دقيقة")
    dc2.metric("⚠ عدد الخطوط المتعطلة", f"{lines_with_faults} من {len(fault_lines)}")

    # ---- إجمالي التوقف الشهري التراكمي لكل خط (من أول الشهر لحد تاريخ التقرير) + رسم بياني واحد لكل الخطوط ----
    report_month_str = daily_report_date.strftime("%Y-%m")
    if report_month_str == selected_month_f:
        # نفس الشهر المعروض فوق أصلاً — نستخدم نفس الجدول بدل ما نعمل نداء تاني لجوجل شيت
        report_grid, report_day_cols = faults_grid, day_cols_f
    else:
        report_grid, _, report_day_cols = load_faults_grid(report_month_str, fault_lines)
    for dc in report_day_cols:
        report_grid[dc] = pd.to_numeric(report_grid[dc], errors="coerce").fillna(0)

    cols_up_to_report_day = [f"يوم {d}" for d in range(1, daily_report_date.day + 1) if f"يوم {d}" in report_day_cols]
    line_summary_day = report_grid[["الخط"] + cols_up_to_report_day].copy()
    line_summary_day["إجمالي التوقف (دقيقة)"] = line_summary_day[cols_up_to_report_day].sum(axis=1)
    line_summary_day = line_summary_day[["الخط", "إجمالي التوقف (دقيقة)"]]
    line_summary_day["الخط"] = line_summary_day["الخط"].astype(str)
    line_summary_day = (
        line_summary_day.groupby("الخط")["إجمالي التوقف (دقيقة)"].sum()
        .reindex(fault_lines)
        .fillna(0)
        .reset_index()
    )
    line_summary_day["إجمالي التوقف (ساعة)"] = (line_summary_day["إجمالي التوقف (دقيقة)"] / 60).round(2)
    line_summary_day = line_summary_day[["الخط", "إجمالي التوقف (دقيقة)", "إجمالي التوقف (ساعة)"]]

    st.markdown(f"#### 📊 إجمالي التوقف الشهري لكل خط (من أول شهر {report_month_str} حتى يوم {daily_report_date.day})")
    st.dataframe(line_summary_day, use_container_width=True, hide_index=True)

    fig_daily, ax_daily = plt.subplots(figsize=(7, 3))
    ax_daily.bar(
        line_summary_day["الخط"].tolist(),
        line_summary_day["إجمالي التوقف (دقيقة)"].tolist(),
        color="#2f6fed"
    )
    ax_daily.set_ylabel("دقيقة")
    ax_daily.set_title(f"إجمالي التوقف الشهري لكل خط — حتى {daily_report_date_str}")
    plt.setp(ax_daily.get_xticklabels(), rotation=25, ha="right")
    fig_daily.tight_layout()
    st.pyplot(fig_daily)

    daily_chart_buf = io.BytesIO()
    fig_daily.savefig(daily_chart_buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig_daily)
    daily_chart_b64 = base64.b64encode(daily_chart_buf.getvalue()).decode()

    line_summary_html = line_summary_day.to_html(index=False, border=0, justify="center")
    daily_extra_html = f"""
    <div style="margin-top:14px;">
        <h2>📊 إجمالي التوقف الشهري لكل خط (من أول شهر {report_month_str} حتى يوم {daily_report_date.day})</h2>
        {line_summary_html}
        <img src="data:image/png;base64,{daily_chart_b64}" style="width:100%; max-width:750px; margin-top:8px;">
    </div>
    """

    daily_report_html = build_printable_html(
        f"التقرير اليومي للأعطال — {daily_report_date_str}",
        f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')} — إجمالي التوقف: {total_day_minutes:,.0f} دقيقة",
        daily_report_df,
        landscape=True,
        extra_html=daily_extra_html
    )
    st.download_button(
        "🖨️ تحميل التقرير اليومي (للإدارة PDF)",
        data=daily_report_html.encode("utf-8"),
        file_name=f"faults_daily_{daily_report_date.strftime('%Y-%m-%d')}.html",
        mime="text/html",
        help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF' — جاهز يتبعت للإدارة",
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

        chart_c1, chart_c2 = st.columns(2)
        with chart_c1:
            st.caption("توزيع وقت التوقف بين الخطوط")
            fig_f, ax_f = plt.subplots()
            ax_f.pie(line_totals.values, labels=line_totals.index, autopct="%1.1f%%", startangle=90)
            ax_f.axis("equal")
            st.pyplot(fig_f)
        with chart_c2:
            st.caption("إجمالي دقائق التوقف لكل خط")
            st.bar_chart(line_totals)

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



elif page == "Inventory":
    st.header("📦Inventory")
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

    st.header("👷 إدارة العمال")

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



elif page == "Reports":
    st.header("📖Reports")

    if GSHEETS_ENABLED and gsheet_exists(PRODUCTION_SHEET):
        history_df = read_gsheet(PRODUCTION_SHEET)

        st.subheader("🔍 فلترة البيانات")
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
    st.header("🍬Settings")
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
