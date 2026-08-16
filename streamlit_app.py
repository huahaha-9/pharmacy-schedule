import streamlit as st
from datetime import date, timedelta

from backend.models import ScheduleRequest
from backend.scheduler import solve_schedule


# ============================================================
# 頁面設定
# ============================================================

st.set_page_config(
    page_title="藥局自動排班",
    page_icon="💊",
    layout="wide",
)

st.title("💊 藥局自動排班系統")
st.caption("設定人員、營業時間與排班條件後，自動產生一週班表")


# ============================================================
# 基本常數
# ============================================================

TIME_OPTIONS = [
    f"{hour:02d}:{minute:02d}"
    for hour in range(24)
    for minute in (0, 30)
]

SHIFT_OPTIONS = {
    "休假": "OFF",
    "早班": "MORNING",
    "中班": "MIDDLE",
    "晚班": "NIGHT",
    "會議": "MEETING",
}

SHIFT_DISPLAY = {
    "OFF": "休假",
    "MORNING": "早班",
    "MIDDLE": "中班",
    "NIGHT": "晚班",
    "MEETING": "會議",
}

WEEKDAY_NAMES = [
    "週一",
    "週二",
    "週三",
    "週四",
    "週五",
    "週六",
    "週日",
]

WEEKDAY_MAP = {
    name: index
    for index, name in enumerate(WEEKDAY_NAMES)
}


def safe_index(options, value, default=0):
    try:
        return options.index(value)
    except ValueError:
        return default


def time_to_minutes(value):
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


# ============================================================
# 預設排班週
# ============================================================

today = date.today()

DEFAULT_START = (
    today
    - timedelta(days=today.weekday())
)


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


# ============================================================
# Session State 初始化
# ============================================================

ss = st.session_state

if "employees" not in ss:
    ss.employees = DEFAULT_EMPLOYEES

if "meetings" not in ss:
    ss.meetings = []

if "fixed_shifts" not in ss:
    ss.fixed_shifts = [
        {
            "employee": "P3",
            "shift": "NIGHT",
        }
    ]

if "fixed_days_off" not in ss:
    ss.fixed_days_off = [
        {
            "employee": "P4",
            "weekday": 6,
        }
    ]

if "assignments" not in ss:
    ss.assignments = []

if "preferred_shifts" not in ss:
    ss.preferred_shifts = []

if "preferred_days_off" not in ss:
    ss.preferred_days_off = []

if "consecutive_off" not in ss:
    ss.consecutive_off = ["P1"]

if "different_shift" not in ss:
    ss.different_shift = [
        {
            "employees": ["P3", "P4"]
        }
    ]


# ============================================================
# 1. 排班週期
# ============================================================

st.header("📅 排班週期")

start_date = st.date_input(
    "排班開始日期",
    value=DEFAULT_START,
)

end_date = start_date + timedelta(days=6)

st.info(
    f"本次排班：{start_date} ～ {end_date}"
)


# ============================================================
# 2. 人員設定
# ============================================================

st.header("👥 人員設定")

st.caption(
    "姓名、FT/PT、藥師、成熟人力、可減班、上班天數與工時皆可修改。"
)

employees = []

for i, employee in enumerate(ss.employees):

    with st.expander(
        f"{employee['id']}｜{employee['name']}"
    ):

        name = st.text_input(
            "姓名",
            value=employee["name"],
            key=f"name_{i}",
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
            key=f"type_{i}",
        )

        col1, col2, col3 = st.columns(3)

        with col1:
            is_pharmacist = st.checkbox(
                "藥師",
                value=employee["is_pharmacist"],
                key=f"pharmacist_{i}",
            )

        with col2:
            is_senior = st.checkbox(
                "成熟人力",
                value=employee["is_senior"],
                key=f"senior_{i}",
            )

        with col3:
            reducible = st.checkbox(
                "可減班",
                value=employee["reducible"],
                key=f"reducible_{i}",
            )

        col4, col5 = st.columns(2)

        with col4:
            work_days = st.number_input(
                "每週上班天數",
                min_value=0,
                max_value=7,
                value=int(employee["work_days"]),
                step=1,
                key=f"work_days_{i}",
            )

        with col5:
            hours_per_day = st.number_input(
                "一班工時",
                min_value=0.5,
                max_value=16.0,
                value=float(employee["hours_per_day"]),
                step=0.5,
                key=f"hours_{i}",
            )

        updated_employee = {
            "id": employee["id"],
            "name": name,
            "employee_type": employee_type,
            "is_pharmacist": is_pharmacist,
            "is_senior": is_senior,
            "reducible": reducible,
            "work_days": int(work_days),
            "hours_per_day": float(hours_per_day),
        }

        employees.append(updated_employee)
        ss.employees[i] = updated_employee


employee_ids = [
    employee["id"]
    for employee in employees
]
