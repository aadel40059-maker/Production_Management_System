import streamlit as st
import pandas as pd
import os
import calendar
import matplotlib.pyplot as plt
import numpy as np
import base64
from datetime import datetime, time as dtime

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


def build_printable_html(title, subtitle, df, extra_title=None, extra_df=None):
    """يبني صفحة HTML جاهزة للطباعة/تحويل PDF من المتصفح (Ctrl+P > Save as PDF)"""
    table_html = df.to_html(index=False, border=0, justify="center", na_rep="-")

    if extra_df is not None:
        extra_table_html = extra_df.to_html(index=False, border=0, justify="center", na_rep="-")
        layout_html = f"""
        <table class="layout-wrapper" width="100%">
        <tr>
            <td class="main-cell" valign="top">{table_html}</td>
            <td class="side-cell" valign="top">
                <h2>{extra_title or ""}</h2>
                {extra_table_html}
            </td>
        </tr>
        </table>
        """
    else:
        layout_html = table_html

    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        @page {{ size: A4; margin: 6mm; }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; margin: 0; padding: 6px; color: #1a1d21; }}
        h1 {{ font-size: 16px; margin: 0 0 2px; }}
        h2 {{ color: #0b1f3a; font-size: 11px; margin: 0 0 4px; }}
        p.dev {{ color: #374151; margin: 0 0 4px; font-size: 10px; font-weight: 600; }}
        p.sub {{ color: #6b7280; margin: 0 0 6px; font-size: 9px; }}

        table.layout-wrapper {{ border-collapse: collapse; }}
        table.layout-wrapper > tr > td {{ border: none; padding: 0; }}
        td.main-cell {{ width: 78%; padding-left: 10px !important; }}
        td.side-cell {{ width: 22%; }}

        table:not(.layout-wrapper) {{ border-collapse: collapse; width: 100%; font-size: 10px; }}
        table:not(.layout-wrapper) th, table:not(.layout-wrapper) td {{
            border: 1px solid #d1d5db; padding: 2.5px 4px; text-align: center;
        }}
        table:not(.layout-wrapper) th {{ background-color: #f4f7fb; font-weight: 700; }}
        table:not(.layout-wrapper) tr:nth-child(even) {{ background-color: #fafafa; }}
        table:not(.layout-wrapper) tr:last-child {{ font-weight: 700; background-color: #eef2f7; }}
        .side-cell table {{ font-size: 9.5px; }}

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
    if os.path.exists(DATA_FILE):
        hist_df = pd.read_csv(DATA_FILE)
        hist_df["Date"] = hist_df["Date"].astype(str)
        month_hist = hist_df[hist_df["Date"].str.startswith(current_month_str)]
        month_hist = month_hist[month_hist["Shift"] == "All Shifts"]
        if not month_hist.empty:
            prod_target = month_hist["Target (KG)"].sum()
            prod_actual = month_hist["Actual (KG)"].sum()
            prod_downtime_min = month_hist["DownTime (min)"].sum()
            prod_waste = month_hist["Waste (KG)"].sum()
            prod_by_line = month_hist.groupby("Line")[["Target (KG)", "Actual (KG)"]].sum()

    # ---------- بيانات الباكينج ----------
    pack_target = pack_actual = 0
    pack_by_cat = pd.DataFrame()
    pack_file = f"packing_monthly_{current_month_str}.csv"
    if os.path.exists(pack_file):
        pack_df = pd.read_csv(pack_file)
        day_cols_dash = [c for c in pack_df.columns if c.startswith("يوم")]
        if day_cols_dash:
            for dc in day_cols_dash:
                pack_df[dc] = pd.to_numeric(pack_df[dc], errors="coerce").fillna(0)
            pack_df["إجمالي الكراتين"] = pack_df[day_cols_dash].sum(axis=1)
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
            file_exists = os.path.exists(DATA_FILE)
            to_save.to_csv(DATA_FILE, mode="a", header=not file_exists, index=False)
            st.success(f"Production data saved successfully ✔ ({len(to_save)} صف اتحفظ)")

elif page == "Packing":
    st.header("📦 Packing")

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

    MONTHLY_FILE = f"packing_monthly_{selected_month}.csv"
    base_cols = ["الصنف", "وزن الكرتونة (كيلو)", "المخطط بالكراتين (شهري)"] + day_cols

    if os.path.exists(MONTHLY_FILE):
        month_grid = pd.read_csv(MONTHLY_FILE)
        for c in base_cols:
            if c not in month_grid.columns:
                month_grid[c] = 0
        month_grid = month_grid[base_cols]
    else:
        month_grid = pd.DataFrame([{
            "الصنف": "",
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
                new_row = {"الصنف": clean_name, "وزن الكرتونة (كيلو)": 0.0,
                           "المخطط بالكراتين (شهري)": 0, **{dc: 0 for dc in day_cols}}
                if insert_position == "في الأول":
                    insert_idx = 0
                else:
                    after_name = insert_position.replace("بعد: ", "")
                    insert_idx = month_grid[month_grid["الصنف"] == after_name].index[0] + 1

                top = month_grid.iloc[:insert_idx]
                bottom = month_grid.iloc[insert_idx:]
                month_grid = pd.concat([top, pd.DataFrame([new_row]), bottom], ignore_index=True)
                month_grid.to_csv(MONTHLY_FILE, index=False)
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
            to_save.to_csv(MONTHLY_FILE, index=False)
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
        summary["الفئة"] = summary["الصنف"].apply(categorize_product)

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
        st.markdown("#### 🖨️ إعدادات تقرير الطباعة")
        default_elapsed = min(datetime.now().day, days_in_month) if selected_month == datetime.now().strftime("%Y-%m") else days_in_month

        plan_c1, plan_c2 = st.columns(2)
        with plan_c1:
            plan_total_days = st.number_input(
                "📅 مدة الخطة الكلية (كام يوم)",
                min_value=1, max_value=62, value=days_in_month, step=1,
                key="packing_plan_total_days"
            )
        with plan_c2:
            days_elapsed = st.number_input(
                "📆 عدد الأيام اللي عدت فعلاً من الخطة",
                min_value=1, max_value=int(plan_total_days), value=min(default_elapsed, int(plan_total_days)), step=1,
                key="packing_days_elapsed"
            )

        print_df = summary[["الصنف"]].copy()
        print_df[f"تعبئة يوم {day_pick}"] = summary[day_col_pick]
        print_df["إجمالي الكراتين"] = summary["إجمالي الكراتين"]
        print_df["المخطط بالكراتين (شهري)"] = summary["المخطط بالكراتين (شهري)"]

        print_df["نسبة التحقيق %"] = summary.apply(
            lambda r: round((r["إجمالي الكراتين"] / r["المخطط بالكراتين (شهري)"] * 100), 1)
            if r["المخطط بالكراتين (شهري)"] > 0 else 0,
            axis=1
        )

        print_df["نصيب اليوم (كرتونة)"] = summary.apply(
            lambda r: round(r["المخطط بالكراتين (شهري)"] / plan_total_days, 1) if plan_total_days > 0 else 0,
            axis=1
        )
        print_df["المتوقع حتى الآن (كرتونة)"] = (print_df["نصيب اليوم (كرتونة)"] * days_elapsed).round(1)

        print_df = print_df.fillna(0)

        total_actual_all = print_df["إجمالي الكراتين"].sum()
        total_target_all = print_df["المخطط بالكراتين (شهري)"].sum()
        total_row_print = pd.DataFrame([{
            "الصنف": "الإجمالي",
            f"تعبئة يوم {day_pick}": print_df[f"تعبئة يوم {day_pick}"].sum(),
            "إجمالي الكراتين": total_actual_all,
            "المخطط بالكراتين (شهري)": total_target_all,
            "نسبة التحقيق %": round((total_actual_all / total_target_all * 100), 1) if total_target_all > 0 else 0,
            "نصيب اليوم (كرتونة)": print_df["نصيب اليوم (كرتونة)"].sum(),
            "المتوقع حتى الآن (كرتونة)": print_df["المتوقع حتى الآن (كرتونة)"].sum(),
        }])
        print_df = pd.concat([print_df, total_row_print], ignore_index=True)

        printable_html = build_printable_html(
            f"تقرير Packing — شهر {selected_month}",
            f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')} — الخطة {plan_total_days} يوم، عدى منها {days_elapsed} يوم",
            print_df,
            extra_title=f"📅 ملخص يوم {day_pick} بالفئات (المسلم بالطن والكرتونة)",
            extra_df=daily_by_cat_display
        )
        st.download_button(
            "🖨️ تحميل نسخة قابلة للطباعة (PDF)",
            data=printable_html.encode("utf-8"),
            file_name=f"packing_{selected_month}.html",
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
        f_year, f_month = map(int, month_str.split("-"))
        f_days = calendar.monthrange(f_year, f_month)[1]
        f_day_cols = [f"يوم {d}" for d in range(1, f_days + 1)]
        f_cols = ["الخط", "سبب/ملاحظات"] + f_day_cols
        f_path = f"faults_monthly_{month_str}.csv"
        if os.path.exists(f_path):
            grid = pd.read_csv(f_path)
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

    # ---------- جدول تسجيل الأعطال (كل الخطوط، تكتب الوقت والمدة بإيدك) ----------
    st.subheader("➕ تسجيل عطل جديد")
    st.caption("اختار التاريخ، واكتب من الساعة/إلى الساعة ومدة العطل بالدقيقة بإيدك لكل خط. تقدر تضيف خط جديد بعلامة (+) تحت آخر صف")

    log_date = st.date_input("📅 التاريخ", value=today_f, key="faults_log_date_table")

    if "faults_log_table" not in st.session_state:
        st.session_state.faults_log_table = pd.DataFrame([
            {"الخط": line, "من الساعة": dtime(0, 0), "إلى الساعة": dtime(0, 0),
             "مدة العطل (دقيقة)": 0, "سبب العطل": ""}
            for line in st.session_state.production_lines
        ])

    # نضيف أي خط جديد اتضاف من صفحة الإعدادات لسه مش موجود في جدول التسجيل
    existing_lines_in_log = set(st.session_state.faults_log_table["الخط"])
    missing_lines = [l for l in st.session_state.production_lines if l not in existing_lines_in_log]
    if missing_lines:
        extra_rows = pd.DataFrame([
            {"الخط": l, "من الساعة": dtime(0, 0), "إلى الساعة": dtime(0, 0),
             "مدة العطل (دقيقة)": 0, "سبب العطل": ""} for l in missing_lines
        ])
        st.session_state.faults_log_table = pd.concat(
            [st.session_state.faults_log_table, extra_rows], ignore_index=True
        )

    edited_log = st.data_editor(
        st.session_state.faults_log_table,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="faults_log_editor",
        column_config={
            "من الساعة": st.column_config.TimeColumn("من الساعة"),
            "إلى الساعة": st.column_config.TimeColumn("إلى الساعة"),
            "مدة العطل (دقيقة)": st.column_config.NumberColumn("مدة العطل (دقيقة)", min_value=0, step=1),
        }
    )

    st.session_state.faults_log_table = edited_log

    if st.button("💾 تسجيل في جدول الشهر"):
        log_month_str = log_date.strftime("%Y-%m")
        log_day_col = f"يوم {log_date.day}"
        grid, f_path, f_day_cols = load_faults_grid(log_month_str, st.session_state.production_lines)

        added_count = 0
        for _, r in edited_log.iterrows():
            line_name = str(r["الخط"]).strip()
            duration = pd.to_numeric(r["مدة العطل (دقيقة)"], errors="coerce")
            duration = 0 if pd.isna(duration) else duration
            if not line_name or duration <= 0:
                continue

            if line_name not in grid["الخط"].values:
                new_row = {"الخط": line_name, "سبب/ملاحظات": "", **{dc: 0 for dc in f_day_cols}}
                grid = pd.concat([grid, pd.DataFrame([new_row])], ignore_index=True)

            row_idx = grid[grid["الخط"] == line_name].index[0]
            current_val = pd.to_numeric(grid.at[row_idx, log_day_col], errors="coerce")
            current_val = 0 if pd.isna(current_val) else current_val
            grid.at[row_idx, log_day_col] = current_val + duration

            reason = str(r["سبب العطل"]).strip()
            from_t = r["من الساعة"]
            to_t = r["إلى الساعة"]
            if reason:
                existing_notes = str(grid.at[row_idx, "سبب/ملاحظات"])
                existing_notes = "" if existing_notes == "nan" else existing_notes
                time_part = ""
                if from_t and to_t and not (from_t == to_t == dtime(0, 0)):
                    time_part = f" ({from_t.strftime('%H:%M')}-{to_t.strftime('%H:%M')})"
                note_entry = f"{log_date.strftime('%Y-%m-%d')}{time_part}: {reason}"
                grid.at[row_idx, "سبب/ملاحظات"] = (existing_notes + " | " + note_entry) if existing_notes else note_entry

            added_count += 1

        if added_count == 0:
            st.warning("مفيش أي خط له مدة عطل أكبر من صفر عشان يتسجل ⚠")
        else:
            grid.to_csv(f_path, index=False)
            st.session_state.pop(f"faults_monthly_editor_{log_month_str}", None)
            st.session_state.faults_log_table = pd.DataFrame([
                {"الخط": line, "من الساعة": dtime(0, 0), "إلى الساعة": dtime(0, 0),
                 "مدة العطل (دقيقة)": 0, "سبب العطل": ""}
                for line in st.session_state.production_lines
            ])
            st.success(f"اتسجل عطل {added_count} خط ليوم {log_date.strftime('%Y-%m-%d')} في جدول شهر {log_month_str} ✔")
            st.rerun()

    st.divider()
    daily_print_df = edited_log[edited_log["مدة العطل (دقيقة)"].apply(
        lambda v: pd.to_numeric(v, errors="coerce") if pd.notna(v) else 0
    ) > 0].copy()
    if not daily_print_df.empty:
        daily_print_df["من الساعة"] = daily_print_df["من الساعة"].apply(lambda t: t.strftime("%H:%M") if t else "-")
        daily_print_df["إلى الساعة"] = daily_print_df["إلى الساعة"].apply(lambda t: t.strftime("%H:%M") if t else "-")
        daily_faults_html = build_printable_html(
            f"تقرير الأعطال اليومي — {log_date.strftime('%Y-%m-%d')}",
            f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            daily_print_df[["الخط", "من الساعة", "إلى الساعة", "مدة العطل (دقيقة)", "سبب العطل"]]
        )
        st.download_button(
            "🖨️ تحميل تقرير الأعطال اليومي (PDF)",
            data=daily_faults_html.encode("utf-8"),
            file_name=f"faults_daily_{log_date.strftime('%Y-%m-%d')}.html",
            mime="text/html",
            help="افتح الملف بعد التحميل، ودوس Ctrl+P واختار 'Save as PDF'",
            key="faults_daily_print_btn"
        )
    else:
        st.caption("سجل مدة عطل لخط واحد على الأقل عشان يظهر زرار طباعة اليوم")

    st.divider()

    faults_grid, FAULTS_FILE, _ = load_faults_grid(selected_month_f, st.session_state.production_lines)

    st.subheader(f"📋 جدول أعطال شهر {selected_month_f}")
    st.caption("الجدول ده بيتحدث تلقائي من التسجيل اللي فوق، وتقدر كمان تعدل فيه يدوي مباشرة")

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
            to_save_f.to_csv(FAULTS_FILE, index=False)
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

    # ملفات كل خط
    worker_files = {
        "الإيطالي": "workers_italy.csv",
        "المستمر": "workers_continuous.csv",
        "اللفافات": "workers_rolls.csv",
        "الترانسلاب": "workers_translab.csv",
        "الطوفي": "workers_toffee.csv",
        "السولا": "workers_sola.csv",
        "الطباخات": "workers_cooking.csv",
        "الجودة": "workers_quality.csv",
    }

    selected_line = st.selectbox(
        "اختر الخط",
        list(worker_files.keys())
    )

    file_name = worker_files[selected_line]

    # إنشاء الملف أول مرة
    if not os.path.exists(file_name):
        df = pd.DataFrame(
            columns=[
                "الاسم",
                "الشيفت",
                "الكود",
                "خط السير"
            ]
        )
        df.to_csv(file_name, index=False, encoding="utf-8-sig")

    # قراءة البيانات
    workers_df = pd.read_csv(
    file_name,
    dtype=str
    ).fillna("")

    # تنظيف أي أحرف \n أو أسطر جديدة اتسربت في الأسماء قديمًا
    for c in ["الاسم", "الشيفت", "الكود", "خط السير"]:
        workers_df[c] = (
            workers_df[c].astype(str)
            .str.replace(r"\\n", " ", regex=True)
            .str.replace("\n", " ", regex=False)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )

    # ---------- إضافة أسماء دفعة واحدة (بدل لصق الجدول اللي بيلخبط) ----------
    with st.expander("➕ إضافة أسماء دفعة واحدة (الصق قائمة أسماء)"):
        st.caption("الصق قائمة الأسماء هنا، اسم في كل سطر، وهتتضاف كصفوف جديدة في الجدول تلقائي")
        bulk_names = st.text_area("قائمة الأسماء", key=f"bulk_names_{selected_line}", height=150)
        if st.button("➕ إضافة الأسماء دي", key=f"bulk_add_btn_{selected_line}"):
            new_names = [n.strip() for n in bulk_names.splitlines() if n.strip()]
            if not new_names:
                st.warning("الصق اسم واحد على الأقل قبل الإضافة ⚠")
            else:
                new_rows = pd.DataFrame([
                    {"الاسم": n, "الشيفت": "", "الكود": "", "خط السير": ""} for n in new_names
                ])
                workers_df = pd.concat([workers_df, new_rows], ignore_index=True)
                workers_df.to_csv(file_name, index=False, encoding="utf-8-sig")
                st.success(f"اتضاف {len(new_names)} اسم ✔")
                st.rerun()

    # عرض الجدول
    edited_df = st.data_editor(
        workers_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "الاسم": st.column_config.TextColumn(
                "الاسم"
            ),

            "الشيفت": st.column_config.SelectboxColumn(
                "الشيفت",
                options=["", "1", "2", "3"]
            ),

            "الكود": st.column_config.TextColumn(
                "الكود"
            ),

            "خط السير": st.column_config.TextColumn(
                "خط السير"
            ),
        },
    )
    # ==========================
    # أزرار التحكم
    # ==========================

    col1, col2, col3 = st.columns(3)

    with col1:
        save_btn = st.button("💾 حفظ", use_container_width=True)

    with col2:
        clear_btn = st.button("🧹 مسح جميع الشيفتات", use_container_width=True)

    with col3:
        reload_btn = st.button("🔄 إعادة تحميل", use_container_width=True)

    # ==========================
    # مسح الشيفتات
    # ==========================

    if clear_btn:
        edited_df["الشيفت"] = ""
        edited_df.to_csv(file_name, index=False, encoding="utf-8-sig")
        st.success("تم مسح جميع الشيفتات")

    # ==========================
    # حفظ البيانات
    # ==========================

    if save_btn:

        edited_df.to_csv(
            file_name,
            index=False,
            encoding="utf-8-sig"
        )

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

        # ==========================
    # كلمات مرور الخطوط
    # ==========================

    line_passwords = {
        "الإيطالي": "1111",
        "المستمر": "2222",
        "اللفافات": "3333",
        "الترانسلاب": "4444",
        "الطوفي": "5555",
        "السولا": "6666",
        "الطباخات": "7777",
        "الجودة": "8888",
    }

    st.subheader("🔒 دخول المهندس المسؤول")

    password = st.text_input(
        "كلمة المرور",
        type="password"
    )

    allow_edit = password == line_passwords[selected_line]

    if allow_edit:
        st.success("تم فتح صلاحية التعديل")
    else:
        st.warning("يمكنك مشاهدة البيانات فقط")
    # ===================================
    # لوحة المدير
    # ===================================

    st.divider()

    manager_pass = "ahmed123"

    with st.expander("⚙️ لوحة المدير"):

        admin_password = st.text_input(
            "كلمة مرور المدير",
            type="password",
            key="admin_pass"
        )

        if admin_password == manager_pass:

            st.success("تم تسجيل دخول المدير")

            st.subheader("➕ إضافة عامل")

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

                workers_df.to_csv(
                    file_name,
                    index=False,
                    encoding="utf-8-sig"
                )

                st.success("تم إضافة العامل")

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

                workers_df.to_csv(
                    file_name,
                    index=False,
                    encoding="utf-8-sig"
                )

                st.success("تم حذف العامل")

            st.divider()

            st.subheader("✏️ تعديل بيانات عامل")

            selected = st.selectbox(
                "العامل",
                workers_df["الاسم"],
                key="edit_worker"
            )
            st.write(selected)
            st.write(workers_df["الاسم"]) 
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

                workers_df.to_csv(
                    file_name,
                    index=False,
                    encoding="utf-8-sig"
                )

                st.success("تم حفظ التعديل")

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
            if os.path.exists(fpath):
                df_line = pd.read_csv(fpath, dtype=str).fillna("")
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
        body {{ font-family: Arial; direction: rtl; margin:40px; }}
        h1,h2,h3 {{ text-align:center; }}
        table {{ width:100%; border-collapse:collapse; margin-bottom:25px; }}
        th,td {{ border:1px solid black; padding:8px; text-align:center; }}
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
                names = df_line[df_line["الشيفت"].astype(str) == shift]["الاسم"].tolist()
                col_data[line_name] = names
                max_len = max(max_len, len(names))
            for line_name in col_data:
                col_data[line_name] = col_data[line_name] + [""] * (max_len - len(col_data[line_name]))

            shift_df = pd.DataFrame(col_data) if max_len > 0 else pd.DataFrame(columns=list(worker_files.keys()))
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



elif page == "Reports":
    st.header("📖Reports")

    if os.path.exists(DATA_FILE):
        history_df = pd.read_csv(DATA_FILE)

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
