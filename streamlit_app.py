import streamlit as st
from datetime import date, timedelta

from backend.models import ScheduleRequest
from backend.scheduler import solve_schedule


st.set_page_config(
    page_title="藥局自動排班",
    page_icon="💊",
    layout="wide",
)

st.title("💊 藥局自動排班系統")
st.caption("設定人員、營業時間與排班條件後，自動產生班表")


# ============================================================
# 預設員工
# ============================================================

DEFAULT_EMPLOYEES = [
    {
        "id": "F1",
        "name": "F1",
        "employee_type": "FT",
        "is_pharmacist": True,
        "is_senior": True,
        "reducible": False,
        "work_days": 5,
        "hours_per_day": 8.0,
    },
    {
        "id": "F2",
        "name": "F2",
        "employee_type": "FT",
        "is_pharmacist": True,
        "is_senior": True,
        "reducible": False,
        "work_days": 5,
        "hours_per_day": 8.0,
    },
    {
        "id": "F3",
        "name": "F3",
        "employee_type": "FT",
        "is_pharmacist": False,
        "is_senior": True,
        "reducible": False,
        "work_days": 5,
        "hours_per_day": 8.0,
    },
    {
        "id": "F4",
        "name": "F4",
        "employee_type": "FT",
        "is_pharmacist": False,
        "is_senior": False,
        "reducible": False,
        "work_days": 5,
        "hours_per_day": 8.0,
    },
    {
        "id": "P1",
        "name": "P1",
        "employee_type": "PT",
        "is_pharmacist": False,
        "is_senior": True,
        "reducible": True,
        "work_days": 4,
        "hours_per_day": 7.0,
    },
    {
        "id": "P2",
        "name": "P2",
        "employee_type": "PT",
        "is_pharmacist": False,
        "is_senior": True,
        "reducible": True,
        "work_days": 4,
        "hours_per_day": 7.0,
    },
    {
        "id": "P3",
        "name": "P3",
        "employee_type": "PT",
        "is_pharmacist": False,
        "is_senior": False,
        "reducible": False,
        "work_days": 4,
        "hours_per_day": 7.0,
    },
    {
        "id": "P4",
        "name": "P4",
        "employee_type": "PT",
        "is_pharmacist": False,
        "is_senior": False,
        "reducible": False,
        "work_days": 4,
        "hours_per_day": 7.0,
    },
    {
        "id": "P5",
        "name": "P5",
        "employee_type": "PT",
        "is_pharmacist": False,
        "is_senior": False,
        "reducible": False,
        "work_days": 4,
        "hours_per_day": 7.0,
    },
]


if "employees" not in st.session_state:
    st.session_state.employees = DEFAULT_EMPLOYEES


# ============================================================
# 排班週期
# ============================================================

st.header("📅 排班週期")

start_date = st.date_input(
    "排班開始日期",
    value=date.today(),
)

end_date = start_date + timedelta(days=6)

st.info(
    f"本次排班：{start_date} ～ {end_date}"
)


# ============================================================
# 人員設定
# ============================================================

st.header("👥 人員設定")

st.caption(
    "姓名、FT/PT、藥師、成熟人力、可減班、上班天數與每日工時都可以修改"
)

employees = []

for index, employee in enumerate(
    st.session_state.employees
):

    with st.expander(
        f"{employee['id']}｜{employee['name']}",
        expanded=False,
    ):

        name = st.text_input(
            "姓名",
            value=employee["name"],
            key=f"name_{index}",
        )

        employee_type = st.radio(
            "人員類型",
            ["FT", "PT"],
            index=(
                0
                if employee["employee_type"] == "FT"
                else 1
            ),
            horizontal=True,
            key=f"type_{index}",
        )

        col1, col2, col3 = st.columns(3)

        with col1:
            is_pharmacist = st.checkbox(
                "藥師",
                value=employee["is_pharmacist"],
                key=f"pharmacist_{index}",
            )

        with col2:
            is_senior = st.checkbox(
                "成熟人力",
                value=employee["is_senior"],
                key=f"senior_{index}",
            )

        with col3:
            reducible = st.checkbox(
                "可減班",
                value=employee["reducible"],
                key=f"reducible_{index}",
            )

        col4, col5 = st.columns(2)

        with col4:
            work_days = st.number_input(
                "每週上班天數",
                min_value=0,
                max_value=7,
                value=employee["work_days"],
                step=1,
                key=f"days_{index}",
            )

        with col5:
            hours_per_day = st.number_input(
                "一班工時",
                min_value=0.5,
                max_value=16.0,
                value=float(
                    employee["hours_per_day"]
                ),
                step=0.5,
                key=f"hours_{index}",
            )

        employees.append({
            "id": employee["id"],
            "name": name,
            "employee_type": employee_type,
            "is_pharmacist": is_pharmacist,
            "is_senior": is_senior,
            "reducible": reducible,
            "work_days": int(work_days),
            "hours_per_day": float(hours_per_day),
        })


# ============================================================
# 營業時間
# ============================================================

st.header("🕘 營業時間")

TIME_OPTIONS = [
    f"{hour:02d}:{minute:02d}"
    for hour in range(24)
    for minute in (0, 30)
]

col1, col2 = st.columns(2)

with col1:

    st.subheader("週一～週五")

    weekday_start = st.selectbox(
        "開始營業",
        TIME_OPTIONS,
        index=TIME_OPTIONS.index("09:00"),
        key="weekday_start",
    )

    weekday_end = st.selectbox(
        "結束營業",
        TIME_OPTIONS,
        index=TIME_OPTIONS.index("22:00"),
        key="weekday_end",
    )


with col2:

    st.subheader("週六、週日")

    weekend_start = st.selectbox(
        "開始營業 ",
        TIME_OPTIONS,
        index=TIME_OPTIONS.index("09:00"),
        key="weekend_start",
    )

    weekend_end = st.selectbox(
        "結束營業 ",
        TIME_OPTIONS,
        index=TIME_OPTIONS.index("22:30"),
        key="weekend_end",
    )


# ============================================================
# 班別需求
# ============================================================

st.header("🧑‍⚕️ 每班人力")

col1, col2, col3 = st.columns(3)

with col1:

    morning_demand = st.number_input(
        "早班人數",
        min_value=0,
        value=2,
        step=1,
    )

with col2:

    middle_demand = st.number_input(
        "中班人數",
        min_value=0,
        value=0,
        step=1,
    )

with col3:

    night_demand = st.number_input(
        "晚班人數",
        min_value=0,
        value=3,
        step=1,
    )


middle_start = st.selectbox(
    "中班開始時間",
    TIME_OPTIONS,
    index=TIME_OPTIONS.index("12:00"),
)


# ============================================================
# 班別時間說明
# ============================================================

with st.expander("班別時間規則"):

    st.write(
        "早班：營業開始時間 → 完成該員工設定工時"
    )

    st.write(
        "晚班：營業結束時間 → 往前回推該員工設定工時"
    )

    st.write(
        "中班：中班設定時間 → 完成該員工設定工時"
    )


# ============================================================
# 下一階段提示
# ============================================================

st.divider()

st.info(
    "下一階段會加入：會議、固定班、排假、指定上下班時間與個人偏好。"
)

st.caption(
    "目前先確認基本設定畫面與人員資料可以正常操作。"
)
