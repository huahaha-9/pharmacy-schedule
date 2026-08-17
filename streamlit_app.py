import streamlit as st
from datetime import date, timedelta
from supabase import create_client

from backend.models import ScheduleRequest
from backend.scheduler import solve_schedule


# ============================================================
# Supabase 連線
# ============================================================

@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SECRET_KEY"],
    )

supabase = get_supabase()
# ============================================================
# 從 Supabase 讀取員工
# ============================================================

def load_employees():

    response = (
        supabase
        .table("employees")
        .select("*")
        .eq("is_active", True)
        .order("employee_id")
        .execute()
    )

    employees = []

    for row in response.data:

        employees.append({
            "id": row["employee_id"],
            "name": row["name"],
            "employee_type": row["employment_type"],
            "is_pharmacist": row["is_pharmacist"],
            "is_senior": row["is_senior"],
            "reducible": row["is_reducible"],
            "work_days": row["work_days"],
            "hours_per_day": float(row["hours_per_day"]),
            "can_morning": row["can_morning"],
            "can_night": row["can_night"],
            "preferred_shift": row["preferred_shift"],
            "prefer_consecutive_off": row["prefer_consecutive_off"],
        })

    return employees
# ============================================================
# Supabase 連線測試
# ============================================================

try:
    employee_test = (
        supabase
        .table("employees")
        .select("employee_id,name")
        .limit(5)
        .execute()
    )

    st.success("✅ Supabase 連線成功")

except Exception as error:
    st.error("❌ Supabase 連線失敗")
    st.exception(error)


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
# 員工排假
# ============================================================

st.header("🗓️ 員工排假")

employee_rows = load_employees()

employee_name_map = {
    employee["id"]: employee["name"]
    for employee in employee_rows
}

employee_id = st.selectbox(
    "我是",
    options=list(employee_name_map.keys()),
    format_func=lambda x: employee_name_map[x],
    key="leave_employee_id",
)

min_leave_date = date.today() + timedelta(days=10)
max_leave_date = date.today() + timedelta(days=183)

leave_date = st.date_input(
    "排假日期",
    min_value=min_leave_date,
    max_value=max_leave_date,
    value=min_leave_date,
    key="leave_date",
)

request_label = st.selectbox(
    "排假 / 指定班",
    [
        "休假",
        "指定早班",
        "指定中班",
        "指定晚班",
    ],
    key="leave_request_type",
)

request_type_map = {
    "休假": "OFF",
    "指定早班": "MORNING",
    "指定中班": "MIDDLE",
    "指定晚班": "NIGHT",
}

request_type = request_type_map[request_label]

start_time_value = None
end_time_value = None

half_hour_options = [
    f"{hour:02d}:{minute:02d}"
    for hour in range(24)
    for minute in (0, 30)
]

if request_type == "MORNING":
    use_early_leave = st.checkbox(
        "需要提早下班",
        key="use_early_leave",
    )

    if use_early_leave:
        end_time_value = st.selectbox(
            "提早下班時間",
            options=half_hour_options,
            index=half_hour_options.index("15:00"),
            key="leave_end_time",
        )

elif request_type == "NIGHT":
    use_late_start = st.checkbox(
        "需要延後上班",
        key="use_late_start",
    )

    if use_late_start:
        start_time_value = st.selectbox(
            "延後上班時間",
            options=half_hour_options,
            index=half_hour_options.index("18:00"),
            key="leave_start_time",
        )

if st.button(
    "💾 儲存送出",
    key="submit_leave_request",
    use_container_width=True,
):
    try:
        payload = {
            "employee_id": employee_id,
            "request_date": leave_date.isoformat(),
            "request_type": request_type,
            "start_time": start_time_value,
            "end_time": end_time_value,
        }

        supabase.table("leave_requests").upsert(
            payload,
            on_conflict="employee_id,request_date",
        ).execute()

        st.success("✅ 排假已儲存")

    except Exception as error:
        st.error("❌ 排假儲存失敗")
        st.exception(error)

st.divider()
# ============================================================
# 我的排假紀錄
# ============================================================

st.subheader("📋 我的排假紀錄")

request_type_display = {
    "OFF": "休假",
    "MORNING": "早班",
    "MIDDLE": "中班",
    "NIGHT": "晚班",
}

try:
    my_requests_response = (
        supabase
        .table("leave_requests")
        .select("*")
        .eq("employee_id", employee_id)
        .order("request_date")
        .execute()
    )

    my_requests = my_requests_response.data

except Exception as error:
    my_requests = []
    st.error("❌ 無法讀取排假紀錄")
    st.exception(error)


if not my_requests:
    st.info("目前沒有排假紀錄。")


for record in my_requests:

    record_type = record["request_type"]

    title = (
        f"{record['request_date']}｜"
        f"{request_type_display.get(record_type, record_type)}"
    )

    if record_type == "MORNING" and record.get("end_time"):
        title += f"｜{str(record['end_time'])[:5]} 下班"

    elif record_type == "NIGHT" and record.get("start_time"):
        title += f"｜{str(record['start_time'])[:5]} 上班"


    with st.expander(title):

        st.write(
            f"日期：{record['request_date']}"
        )

        st.write(
            f"類型：{request_type_display.get(record_type, record_type)}"
        )

        if record_type == "MORNING" and record.get("end_time"):
            st.write(
                f"提早下班：{str(record['end_time'])[:5]}"
            )

        if record_type == "NIGHT" and record.get("start_time"):
            st.write(
                f"延後上班：{str(record['start_time'])[:5]}"
            )
            st.markdown("#### ✏️ 修改排假")

            edit_date = st.date_input(
                "修改日期",
                value=date.fromisoformat(record["request_date"]),
                min_value=min_leave_date,
                max_value=max_leave_date,
                key=f"edit_date_{record['id']}",
            )
            
            edit_options = [
                "休假",
                "指定早班",
                "指定中班",
                "指定晚班",
            ]
            
            code_to_label = {
                "OFF": "休假",
                "MORNING": "指定早班",
                "MIDDLE": "指定中班",
                "NIGHT": "指定晚班",
            }
            
            edit_label = st.selectbox(
                "修改排假 / 指定班",
                edit_options,
                index=edit_options.index(
                    code_to_label.get(record_type, "休假")
                ),
                key=f"edit_type_{record['id']}",
            )
            
            edit_type = request_type_map[edit_label]
            
            edit_start_time = None
            edit_end_time = None
            
            if edit_type == "MORNING":
            
                old_end_time = (
                    str(record["end_time"])[:5]
                    if record.get("end_time")
                    else "15:00"
                )
            
                use_early_end = st.checkbox(
                    "提早下班",
                    value=record.get("end_time") is not None,
                    key=f"edit_early_{record['id']}",
                )
            
                if use_early_end:
                    edit_end_time = st.selectbox(
                        "新的下班時間",
                        half_hour_options,
                        index=half_hour_options.index(old_end_time),
                        key=f"edit_end_{record['id']}",
                    )
            
            elif edit_type == "NIGHT":
            
                old_start_time = (
                    str(record["start_time"])[:5]
                    if record.get("start_time")
                    else "18:00"
                )
            
                use_late_start = st.checkbox(
                    "延後上班",
                    value=record.get("start_time") is not None,
                    key=f"edit_late_{record['id']}",
                )
            
                if use_late_start:
                    edit_start_time = st.selectbox(
                        "新的上班時間",
                        half_hour_options,
                        index=half_hour_options.index(old_start_time),
                        key=f"edit_start_{record['id']}",
                    )
            
            if st.button(
                "💾 儲存修改",
                key=f"save_edit_{record['id']}",
                use_container_width=True,
            ):
                try:
            
                    supabase.table(
                        "leave_requests"
                    ).update({
                        "request_date": edit_date.isoformat(),
                        "request_type": edit_type,
                        "start_time": edit_start_time,
                        "end_time": edit_end_time,
                    }).eq(
                        "id",
                        record["id"],
                    ).execute()
            
                    st.success("✅ 修改完成")
                    st.rerun()
            
                except Exception as error:
                    st.error("❌ 修改失敗")
                    st.exception(error)


        if st.button(
            "🗑️ 刪除這筆排假",
            key=f"delete_leave_{record['id']}",
            use_container_width=True,
        ):

            try:

                supabase.table(
                    "leave_requests"
                ).delete().eq(
                    "id",
                    record["id"],
                ).execute()

                st.success("✅ 已刪除")
                st.rerun()

            except Exception as error:

                st.error("❌ 刪除失敗")
                st.exception(error)


st.divider()
# ============================================================
# 同一天的排假
# ============================================================

st.subheader("👥 這一天還有誰排假？")

check_date = st.date_input(
    "查看日期",
    value=leave_date,
    min_value=min_leave_date,
    max_value=max_leave_date,
    key="check_same_day_date",
)

try:
    same_day_response = (
        supabase
        .table("leave_requests")
        .select("*")
        .eq("request_date", check_date.isoformat())
        .order("employee_id")
        .execute()
    )

    same_day_requests = same_day_response.data

except Exception as error:
    same_day_requests = []
    st.error("❌ 無法讀取當日排假")
    st.exception(error)


if not same_day_requests:

    st.info("這一天目前沒有人排假。")

else:

    for item in same_day_requests:

        person_name = employee_name_map.get(
            item["employee_id"],
            item["employee_id"],
        )

        type_text = request_type_display.get(
            item["request_type"],
            item["request_type"],
        )

        extra_text = ""

        if (
            item["request_type"] == "MORNING"
            and item.get("end_time")
        ):
            extra_text = (
                f"｜{str(item['end_time'])[:5]} 下班"
            )

        elif (
            item["request_type"] == "NIGHT"
            and item.get("start_time")
        ):
            extra_text = (
                f"｜{str(item['start_time'])[:5]} 上班"
            )

        st.write(
            f"👤 **{person_name}**｜{type_text}{extra_text}"
        )


st.divider()
# ============================================================
# 店長登入
# ============================================================

st.header("🔐 店長專區")

if "manager_logged_in" not in st.session_state:
    st.session_state.manager_logged_in = False

if not st.session_state.manager_logged_in:

    manager_password = st.text_input(
        "店長密碼",
        type="password",
        key="manager_password_input",
    )

    if st.button(
        "登入店長專區",
        key="manager_login_button",
        use_container_width=True,
    ):
        if manager_password == st.secrets["MANAGER_PASSWORD"]:
            st.session_state.manager_logged_in = True
            st.success("✅ 登入成功")
            st.rerun()
        else:
            st.error("❌ 密碼錯誤")

else:

    st.success("✅ 已登入店長專區")

    if st.button(
        "登出店長專區",
        key="manager_logout_button",
    ):
        st.session_state.manager_logged_in = False
        st.rerun()

    manager_tab1, manager_tab2, manager_tab3 = st.tabs(
    [
        "👥 基本設定",
        "📋 本週總結",
        "🧩 生成班表",
    ]
)

    with manager_tab1:
        st.subheader("👥 基本設定")
    
    with manager_tab2:
        st.subheader("📋 本週總結")
        st.caption("快速確認本週排假、指定班與會議安排。")
    
        summary_start = st.date_input(
            "本週開始日期",
            value=DEFAULT_START,
            key="manager_summary_start",
        )
    
        summary_end = summary_start + timedelta(days=6)
    
        st.info(
            f"📅 查看期間：{summary_start} ～ {summary_end}"
        )
    
        # --------------------------------------------------------
        # 本週員工排假 / 指定班
        # --------------------------------------------------------
    
        st.markdown("### 🏖️ 員工排假 / 指定班")
    
        try:
            summary_leave_response = (
                supabase
                .table("leave_requests")
                .select("*")
                .gte("request_date", summary_start.isoformat())
                .lte("request_date", summary_end.isoformat())
                .order("request_date")
                .execute()
            )
    
            summary_leave_requests = summary_leave_response.data
    
        except Exception as error:
            summary_leave_requests = []
            st.error("❌ 無法讀取本週排假資料")
            st.exception(error)
    
        if not summary_leave_requests:
            st.info("本週目前沒有員工排假或指定班。")
    
        else:
            for item in summary_leave_requests:
    
                employee_name = employee_name_map.get(
                    item["employee_id"],
                    item["employee_id"],
                )
    
                request_text = request_type_display.get(
                    item["request_type"],
                    item["request_type"],
                )
    
                extra_text = ""
    
                if (
                    item["request_type"] == "MORNING"
                    and item.get("end_time")
                ):
                    extra_text = (
                        f"｜{str(item['end_time'])[:5]} 下班"
                    )

                elif (
                    item["request_type"] == "NIGHT"
                    and item.get("start_time")
                ):
                    extra_text = (
                        f"｜{str(item['start_time'])[:5]} 上班"
                    )

                st.write(
                    f"📅 {item['request_date']}｜"
                    f"👤 {employee_name}｜"
                    f"{request_text}{extra_text}"
                )

        st.divider()

        # --------------------------------------------------------
        # 本週會議
        # --------------------------------------------------------

        st.markdown("### 📣 本週會議")

        try:
            summary_meetings = [
                meeting
                for meeting in st.session_state.meetings
                if (
                    summary_start
                    <= meeting["date"]
                    <= summary_end
                )
            ]

        except Exception as error:
            summary_meetings = []
            st.error("❌ 無法讀取本週會議")
            st.exception(error)

        if not summary_meetings:
            st.info("本週目前沒有會議。")

        else:
            summary_meetings = sorted(
                summary_meetings,
                key=lambda meeting: meeting["date"],
            )

            for meeting in summary_meetings:

                meeting_employee_id = meeting["employee"]

                meeting_employee_name = employee_name_map.get(
                    meeting_employee_id,
                    meeting_employee_id,
                )

                st.write(
                    f"📅 {meeting['date']}｜"
                    f"👤 {meeting_employee_name}｜"
                    f"會議"
                )
        st.divider()

        # --------------------------------------------------------
        # 固定班 / 固定休假
        # --------------------------------------------------------

        st.markdown("### 📌 固定班 / 固定休假")

        try:
            fixed_rules_response = (
                supabase
                .table("employee_fixed_rules")
                .select("*")
                .order("employee_id")
                .execute()
            )

            fixed_rules = fixed_rules_response.data

        except Exception as error:
            fixed_rules = []
            st.error("❌ 無法讀取固定規則")
            st.exception(error)

        if not fixed_rules:
            st.info("目前沒有固定班或固定休假設定。")

        else:
            weekday_display = {
                0: "週一",
                1: "週二",
                2: "週三",
                3: "週四",
                4: "週五",
                5: "週六",
                6: "週日",
            }

            shift_display = {
                "MORNING": "早班",
                "MIDDLE": "中班",
                "NIGHT": "晚班",
            }

            for rule in fixed_rules:

                employee_name = employee_name_map.get(
                    rule["employee_id"],
                    rule["employee_id"],
                )

                if rule["rule_type"] == "FIXED_SHIFT":
                    rule_text = (
                        f"固定{shift_display.get(rule['shift'], rule['shift'])}"
                    )

                else:
                    weekday_text = weekday_display.get(
                        rule.get("weekday"),
                        "",
                    )

                    rule_text = (
                        f"固定{weekday_text}休假"
                    )

                st.write(
                    f"👤 {employee_name}｜{rule_text}"
                )
                        st.divider()

        # --------------------------------------------------------
        # 本週人力配置
        # --------------------------------------------------------

        st.markdown("### 👥 本週人力配置")

                staffing_days = [
            (0, "週一"),
            (1, "週二"),
            (2, "週三"),
            (3, "週四"),
            (4, "週五"),
            (5, "週六"),
            (6, "週日"),
        ]

        try:
            staffing_response = (
                supabase
                .table("weekly_staffing")
                .select("*")
                .eq("week_start", summary_start.isoformat())
                .order("weekday")
                .execute()
            )

            staffing_rows = staffing_response.data

        except Exception as error:
            staffing_rows = []
            st.error("❌ 無法讀取本週人力配置")
            st.exception(error)

        staffing_map = {
            int(row["weekday"]): row
            for row in staffing_rows
        }

        weekly_staffing_ui = {}

        for weekday_num, day_name in staffing_days:

            saved = staffing_map.get(weekday_num)

            default_morning = (
                int(saved["morning_required"])
                if saved
                else 2
            )

            default_middle = (
                int(saved["middle_required"])
                if saved
                else 0
            )

            default_night = (
                int(saved["night_required"])
                if saved
                else 3
            )

            st.markdown(f"**{day_name}**")

            col1, col2, col3 = st.columns(3)

            with col1:
                morning_value = st.number_input(
                    "早班",
                    min_value=0,
                    max_value=20,
                    value=default_morning,
                    step=1,
                    key=f"staffing_morning_{weekday_num}",
                )

            with col2:
                middle_value = st.number_input(
                    "中班",
                    min_value=0,
                    max_value=20,
                    value=default_middle,
                    step=1,
                    key=f"staffing_middle_{weekday_num}",
                )

            with col3:
                night_value = st.number_input(
                    "晚班",
                    min_value=0,
                    max_value=20,
                    value=default_night,
                    step=1,
                    key=f"staffing_night_{weekday_num}",
                )

            weekly_staffing_ui[weekday_num] = {
                "morning": int(morning_value),
                "middle": int(middle_value),
                "night": int(night_value),
            }

        if st.button(
            "💾 儲存本週人力配置",
            key="save_weekly_staffing",
            use_container_width=True,
        ):

            try:
                for weekday_num, values in weekly_staffing_ui.items():

                    supabase.table("weekly_staffing").upsert(
                        {
                            "week_start": summary_start.isoformat(),
                            "weekday": weekday_num,
                            "morning_required": values["morning"],
                            "middle_required": values["middle"],
                            "night_required": values["night"],
                        },
                        on_conflict="week_start,weekday",
                    ).execute()

                st.success("✅ 本週人力配置已儲存")

            except Exception as error:
                st.error("❌ 儲存本週人力配置失敗")
                st.exception(error)
    with manager_tab3:
        st.subheader("🧩 生成班表")

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
    ss.employees = load_employees()

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


# ============================================================
# 新增員工
# ============================================================
# ============================================================
# 新增員工
# ============================================================

with st.expander("➕ 新增員工"):
    new_id = st.text_input("員工代號", key="new_id")
    new_name = st.text_input("員工姓名", key="new_name")

    if st.button("新增", key="add_employee"):
        if not new_id.strip() or not new_name.strip():
            st.warning("請填寫員工代號和姓名")
        else:
            try:
                supabase.table("employees").insert({
                    "employee_id": new_id.strip().upper(),
                    "name": new_name.strip(),
                    "employment_type": "PT",
                    "is_pharmacist": False,
                    "is_senior": False,
                    "is_reducible": False,
                    "is_active": True,
                    "work_days": 4,
                    "hours_per_day": 7.0,
                    "can_morning": True,
                    "can_night": True,
                    "preferred_shift": None,
                    "prefer_consecutive_off": False,
                }).execute()

                ss.employees = load_employees()
                st.success("✅ 新增成功")
                st.rerun()

            except Exception as error:
                st.error("❌ 新增失敗")
                st.exception(error)

    
    # ============================================================
# 刪除員工
# ============================================================

with st.expander("🗑️ 刪除員工"):
    delete_employee_id = st.selectbox(
        "選擇要刪除的員工",
        employee_ids,
        key="delete_employee_id",
    )

    delete_employee = next(
        (
            employee
            for employee in employees
            if employee["id"] == delete_employee_id
        ),
        None,
    )

    if delete_employee:

        st.warning(
            f"即將刪除："
            f"{delete_employee['name']} "
            f"({delete_employee_id})"
        )

        st.caption(
            "刪除後，與此員工相關的排假、固定規則、"
            "避免同班偏好及其他已設定為 CASCADE 的資料也會一併刪除。"
        )

        confirm_delete = st.checkbox(
            "我確認要刪除此員工",
            key="confirm_delete_employee",
        )

        if st.button(
            "確定刪除員工",
            disabled=not confirm_delete,
            key="delete_employee_button",
            use_container_width=True,
        ):

            try:

                supabase.table("employees").delete().eq(
                    "employee_id",
                    delete_employee_id,
                ).execute()

                ss.employees = load_employees()

                st.success(
                    f"✅ 已刪除 {delete_employee['name']}"
                )

                st.rerun()

            except Exception as error:

                st.error("❌ 刪除員工失敗")
                st.exception(error)
    
# ============================================================
# 儲存員工設定到 Supabase
# ============================================================

if st.button(
    "💾 儲存員工設定",
    key="save_employee_settings",
    use_container_width=True,
):

    try:

        for employee in employees:

            supabase.table("employees").upsert({
                "employee_id": employee["id"],
                "name": employee["name"],
                "employment_type": employee["employee_type"],
                "is_pharmacist": employee["is_pharmacist"],
                "is_senior": employee["is_senior"],
                "is_reducible": employee["reducible"],
                "is_active": True,
                "work_days": employee["work_days"],
                "hours_per_day": employee["hours_per_day"],
                "can_morning": employee.get("can_morning", True),
                "can_night": employee.get("can_night", True),
                "preferred_shift": employee.get("preferred_shift"),
                "prefer_consecutive_off": employee.get(
                    "prefer_consecutive_off",
                    False,
                ),
            }).execute()

        st.success("✅ 員工設定已儲存")

    except Exception as error:

        st.error("❌ 儲存員工設定失敗")
        st.exception(error)
# ============================================================
# 3. 營業時間
# ============================================================
# ============================================================
# 從 Supabase 讀取營業時間
# ============================================================

try:
    business_hours_response = (
        supabase
        .table("business_hours")
        .select("*")
        .eq("is_active", True)
        .order("weekday")
        .execute()
    )

    business_hours_rows = business_hours_response.data

except Exception as error:
    business_hours_rows = []
    st.error("❌ 無法讀取營業時間設定")
    st.exception(error)


business_hours_map = {
    int(row["weekday"]): row
    for row in business_hours_rows
}
st.header("🕘 營業時間")

# 週一～週日營業時間
business_hours_ui = {}

day_settings = [
    ("monday", "週一", 0, "09:00", "22:00"),
    ("tuesday", "週二", 1, "09:00", "22:30"),
    ("wednesday", "週三", 2, "09:00", "22:00"),
    ("thursday", "週四", 3, "09:00", "22:00"),
    ("friday", "週五", 4, "09:00", "22:00"),
    ("saturday", "週六", 5, "09:00", "22:30"),
    ("sunday", "週日", 6, "09:00", "22:30"),
]

for day_key, day_name, weekday_num, fallback_start, fallback_end in day_settings:

    saved = business_hours_map.get(weekday_num)

    if saved:
        default_start = str(saved["open_time"])[:5]
        default_end = str(saved["close_time"])[:5]
    else:
        default_start = fallback_start
        default_end = fallback_end

    st.subheader(day_name)

    col_start, col_end = st.columns(2)

    with col_start:
        day_start = st.selectbox(
            "開始營業",
            TIME_OPTIONS,
            index=TIME_OPTIONS.index(default_start),
            key=f"{day_key}_start",
        )

    with col_end:
        day_end = st.selectbox(
            "結束營業",
            TIME_OPTIONS,
            index=TIME_OPTIONS.index(default_end),
            key=f"{day_key}_end",
        )

    business_hours_ui[day_key] = {
        "start": day_start,
        "end": day_end,
    }


# ============================================================
# 4. 每班人力
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

saved_middle_start = "12:00"

if business_hours_rows:
    saved_middle_start = str(
        business_hours_rows[0].get("middle_start") or "12:00"
    )[:5]

if saved_middle_start not in TIME_OPTIONS:
    saved_middle_start = "12:00"

middle_start = st.selectbox(
    "中班開始時間",
    TIME_OPTIONS,
    index=TIME_OPTIONS.index(saved_middle_start),
)
if st.button(
    "💾 儲存營業時間",
    key="save_business_hours",
    use_container_width=True,
):
    try:
        day_key_to_weekday = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }

        for day_key, weekday_num in day_key_to_weekday.items():
            day_data = business_hours_ui[day_key]

            supabase.table("business_hours").update({
                "open_time": day_data["start"],
                "close_time": day_data["end"],
                "middle_start": middle_start,
                "is_active": True,
            }).eq(
                "weekday",
                weekday_num,
            ).execute()

        st.success("✅ 營業時間已儲存")

    except Exception as error:
        st.error("❌ 儲存營業時間失敗")
        st.exception(error)
        
with st.expander("班別時間規則"):

    st.write(
        "早班：營業時間開始 → 完成該員工設定工時"
    )

    st.write(
        "中班：設定時間開始 → 完成該員工設定工時"
    )

    st.write(
        "晚班：營業時間結束 → 往前回推滿該員工設定工時"
    )


# ============================================================
# 5. 會議
# ============================================================

st.header("📣 會議")

st.caption(
    "會議算上班。選擇日期與參加會議的人員。"
)

meeting_delete = None

for i, meeting in enumerate(ss.meetings):

    with st.expander(
        f"會議 {i + 1}",
        expanded=True,
    ):

        meeting_date = st.date_input(
            "日期",
            value=meeting["date"],
            key=f"meeting_date_{i}",
        )

        meeting_employee = st.selectbox(
            "會議人員",
            employee_ids,
            index=safe_index(
                employee_ids,
                meeting["employee"],
            ),
            key=f"meeting_employee_{i}",
        )

        ss.meetings[i] = {
            "date": meeting_date,
            "employee": meeting_employee,
        }

        if st.button(
            "🗑️ 刪除此會議",
            key=f"delete_meeting_{i}",
        ):
            meeting_delete = i


if meeting_delete is not None:

    ss.meetings.pop(meeting_delete)

    st.rerun()


if st.button(
    "＋ 新增會議",
    key="add_meeting",
):

    ss.meetings.append({
        "date": start_date,
        "employee": employee_ids[0],
    })

    st.rerun()


# ============================================================
# 6. 固定班
# ============================================================

st.header("🔒 固定班")

st.caption(
    "固定班代表：這位員工如果上班，只能排指定班別，但仍可以正常休假。"
)

fixed_shift_delete = None

for i, rule in enumerate(
    ss.fixed_shifts
):

    with st.expander(
        f"固定班 {i + 1}",
        expanded=True,
    ):

        fixed_employee = st.selectbox(
            "人員",
            employee_ids,
            index=safe_index(
                employee_ids,
                rule["employee"],
            ),
            key=f"fixed_employee_{i}",
        )

        fixed_shift_values = [
            "MORNING",
            "MIDDLE",
            "NIGHT",
        ]

        fixed_shift_labels = [
            "早班",
            "中班",
            "晚班",
        ]

        current_shift_index = safe_index(
            fixed_shift_values,
            rule["shift"],
        )

        fixed_shift_label = st.selectbox(
            "固定班別",
            fixed_shift_labels,
            index=current_shift_index,
            key=f"fixed_shift_{i}",
        )

        fixed_shift_code = SHIFT_OPTIONS[
            fixed_shift_label
        ]

        ss.fixed_shifts[i] = {
            "employee": fixed_employee,
            "shift": fixed_shift_code,
        }

        if st.button(
            "🗑️ 刪除此固定班",
            key=f"delete_fixed_shift_{i}",
        ):
            fixed_shift_delete = i


if fixed_shift_delete is not None:

    ss.fixed_shifts.pop(
        fixed_shift_delete
    )

    st.rerun()


if st.button(
    "＋ 新增固定班",
    key="add_fixed_shift",
):

    ss.fixed_shifts.append({
        "employee": employee_ids[0],
        "shift": "MORNING",
    })

    st.rerun()


# ============================================================
# 7. 固定休假
# ============================================================

st.header("🏖️ 固定休假")

st.caption(
    "例如：P4 固定週日休假。"
)

fixed_off_delete = None

for i, rule in enumerate(
    ss.fixed_days_off
):

    with st.expander(
        f"固定休假 {i + 1}",
        expanded=True,
    ):

        fixed_off_employee = st.selectbox(
            "人員",
            employee_ids,
            index=safe_index(
                employee_ids,
                rule["employee"],
            ),
            key=f"fixed_off_employee_{i}",
        )

        fixed_off_weekday = st.selectbox(
            "固定休星期",
            WEEKDAY_NAMES,
            index=int(rule["weekday"]),
            key=f"fixed_off_weekday_{i}",
        )

        ss.fixed_days_off[i] = {
            "employee": fixed_off_employee,
            "weekday": WEEKDAY_MAP[
                fixed_off_weekday
            ],
        }

        if st.button(
            "🗑️ 刪除此固定休假",
            key=f"delete_fixed_off_{i}",
        ):
            fixed_off_delete = i


if fixed_off_delete is not None:

    ss.fixed_days_off.pop(
        fixed_off_delete
    )

    st.rerun()


if st.button(
    "＋ 新增固定休假",
    key="add_fixed_off",
):

    ss.fixed_days_off.append({
        "employee": employee_ids[0],
        "weekday": 0,
    })

    st.rerun()
    # ============================================================
# 8. 排假 / 指定班
# ============================================================

st.header("📆 排假／指定班")

st.caption(
    "休假不用設定時間；早班可指定提早下班；晚班可指定較晚上班。時間以 30 分鐘為單位。"
)

assignment_delete = None

ASSIGNMENT_SHIFT_LABELS = [
    "休假",
    "早班",
    "中班",
    "晚班",
]

for i, rule in enumerate(
    ss.assignments
):

    with st.expander(
        f"排假／指定班 {i + 1}",
        expanded=False,
    ):

        assignment_employee = st.selectbox(
            "人員",
            employee_ids,
            index=safe_index(
                employee_ids,
                rule["employee"],
            ),
            key=f"assignment_employee_{i}",
        )

        assignment_date = st.date_input(
            "日期",
            value=rule["date"],
            key=f"assignment_date_{i}",
        )

        current_shift_label = SHIFT_DISPLAY[
            rule["shift"]
        ]

        assignment_shift_label = st.selectbox(
            "班別",
            ASSIGNMENT_SHIFT_LABELS,
            index=safe_index(
                ASSIGNMENT_SHIFT_LABELS,
                current_shift_label,
            ),
            key=f"assignment_shift_{i}",
        )

        assignment_shift_code = SHIFT_OPTIONS[
            assignment_shift_label
        ]

        start_time = None
        end_time = None

        # ----------------------------------------------------
        # 早班：可指定提早下班
        # ----------------------------------------------------

        if assignment_shift_code == "MORNING":

            use_early_end = st.checkbox(
                "指定提早下班",
                value=(
                    rule.get("end_time")
                    is not None
                ),
                key=f"use_early_end_{i}",
            )

            if use_early_end:

                default_end = (
                    rule.get("end_time")
                    or "15:00"
                )

                end_time = st.selectbox(
                    "下班時間",
                    TIME_OPTIONS,
                    index=safe_index(
                        TIME_OPTIONS,
                        default_end,
                    ),
                    key=f"morning_end_{i}",
                )

        # ----------------------------------------------------
        # 晚班：可指定較晚上班
        # ----------------------------------------------------

        elif assignment_shift_code == "NIGHT":

            use_late_start = st.checkbox(
                "指定較晚上班",
                value=(
                    rule.get("start_time")
                    is not None
                ),
                key=f"use_late_start_{i}",
            )

            if use_late_start:

                default_start_time = (
                    rule.get("start_time")
                    or "18:00"
                )

                start_time = st.selectbox(
                    "上班時間",
                    TIME_OPTIONS,
                    index=safe_index(
                        TIME_OPTIONS,
                        default_start_time,
                    ),
                    key=f"night_start_{i}",
                )

        ss.assignments[i] = {
            "employee": assignment_employee,
            "date": assignment_date,
            "shift": assignment_shift_code,
            "start_time": start_time,
            "end_time": end_time,
        }

        if st.button(
            "🗑️ 刪除此設定",
            key=f"delete_assignment_{i}",
        ):
            assignment_delete = i


if assignment_delete is not None:

    ss.assignments.pop(
        assignment_delete
    )

    st.rerun()


if st.button(
    "＋ 新增排假／指定班",
    key="add_assignment",
):

    ss.assignments.append({
        "employee": employee_ids[0],
        "date": start_date,
        "shift": "OFF",
        "start_time": None,
        "end_time": None,
    })

    st.rerun()


# ============================================================
# 9. 排班偏好
# ============================================================

st.header("⭐ 排班偏好")


# ============================================================
# 9-1 偏好班別
# ============================================================

st.subheader("偏好班別")

preferred_shift_delete = None

for i, rule in enumerate(
    ss.preferred_shifts
):

    with st.expander(
        f"偏好班別 {i + 1}",
        expanded=False,
    ):

        pref_employee = st.selectbox(
            "人員",
            employee_ids,
            index=safe_index(
                employee_ids,
                rule["employee"],
            ),
            key=f"pref_employee_{i}",
        )

        pref_shift_values = [
            "MORNING",
            "MIDDLE",
            "NIGHT",
        ]

        pref_shift_labels = [
            "早班",
            "中班",
            "晚班",
        ]

        pref_shift_label = st.selectbox(
            "偏好班別",
            pref_shift_labels,
            index=safe_index(
                pref_shift_values,
                rule["shift"],
            ),
            key=f"pref_shift_{i}",
        )

        use_weekday = st.checkbox(
            "限定星期",
            value=(
                rule.get("weekday")
                is not None
            ),
            key=f"pref_use_weekday_{i}",
        )

        weekday = None

        if use_weekday:

            default_weekday = (
                rule["weekday"]
                if rule.get("weekday")
                is not None
                else 0
            )

            weekday_name = st.selectbox(
                "星期",
                WEEKDAY_NAMES,
                index=int(default_weekday),
                key=f"pref_weekday_{i}",
            )

            weekday = WEEKDAY_MAP[
                weekday_name
            ]

        ss.preferred_shifts[i] = {
            "employee": pref_employee,
            "shift": SHIFT_OPTIONS[
                pref_shift_label
            ],
            "weekday": weekday,
        }

        if st.button(
            "🗑️ 刪除此偏好",
            key=f"delete_pref_shift_{i}",
        ):
            preferred_shift_delete = i


if preferred_shift_delete is not None:

    ss.preferred_shifts.pop(
        preferred_shift_delete
    )

    st.rerun()


if st.button(
    "＋ 新增偏好班別",
    key="add_pref_shift",
):

    ss.preferred_shifts.append({
        "employee": employee_ids[0],
        "shift": "MORNING",
        "weekday": None,
    })

    st.rerun()


# ============================================================
# 9-2 偏好休假星期
# ============================================================

st.subheader("偏好休假星期")

preferred_off_delete = None

for i, rule in enumerate(
    ss.preferred_days_off
):

    with st.expander(
        f"偏好休假 {i + 1}",
        expanded=False,
    ):

        pref_off_employee = st.selectbox(
            "人員",
            employee_ids,
            index=safe_index(
                employee_ids,
                rule["employee"],
            ),
            key=f"pref_off_employee_{i}",
        )

        pref_off_weekday = st.selectbox(
            "偏好休星期",
            WEEKDAY_NAMES,
            index=int(
                rule["weekday"]
            ),
            key=f"pref_off_weekday_{i}",
        )

        ss.preferred_days_off[i] = {
            "employee": pref_off_employee,
            "weekday": WEEKDAY_MAP[
                pref_off_weekday
            ],
        }

        if st.button(
            "🗑️ 刪除此偏好",
            key=f"delete_pref_off_{i}",
        ):
            preferred_off_delete = i


if preferred_off_delete is not None:

    ss.preferred_days_off.pop(
        preferred_off_delete
    )

    st.rerun()


if st.button(
    "＋ 新增偏好休假",
    key="add_pref_off",
):

    ss.preferred_days_off.append({
        "employee": employee_ids[0],
        "weekday": 0,
    })

    st.rerun()


# ============================================================
# 9-3 偏好連休
# ============================================================

st.subheader("偏好連休")

selected_consecutive = st.multiselect(
    "偏好連續休假的人員",
    employee_ids,
    default=[
        employee
        for employee in ss.consecutive_off
        if employee in employee_ids
    ],
)

ss.consecutive_off = (
    selected_consecutive
)


# ============================================================
# 9-4 兩人避免同班
# ============================================================

st.subheader("兩人避免同班")

different_delete = None

for i, rule in enumerate(
    ss.different_shift
):

    with st.expander(
        f"不同班組合 {i + 1}",
        expanded=False,
    ):

        employee_a = st.selectbox(
            "人員 A",
            employee_ids,
            index=safe_index(
                employee_ids,
                rule["employees"][0],
            ),
            key=f"different_a_{i}",
        )

        available_b = [
            employee
            for employee in employee_ids
            if employee != employee_a
        ]

        if available_b:

            employee_b = st.selectbox(
                "人員 B",
                available_b,
                index=safe_index(
                    available_b,
                    rule["employees"][1],
                ),
                key=f"different_b_{i}",
            )

            ss.different_shift[i] = {
                "employees": [
                    employee_a,
                    employee_b,
                ]
            }

        else:

            st.warning(
                "至少需要兩位員工。"
            )

        if st.button(
            "🗑️ 刪除此組合",
            key=f"delete_different_{i}",
        ):
            different_delete = i


if different_delete is not None:

    ss.different_shift.pop(
        different_delete
    )

    st.rerun()


if st.button(
    "＋ 新增不同班組合",
    key="add_different",
):

    if len(employee_ids) >= 2:

        ss.different_shift.append({
            "employees": [
                employee_ids[0],
                employee_ids[1],
            ]
        })

        st.rerun()
        # ============================================================
# 10. 自動排班
# ============================================================

st.divider()

st.header("🤖 自動排班")

st.caption(
    "確認上方設定後，按下按鈕產生班表。"
)


if st.button(
    "🚀 開始自動排班",
    type="primary",
    use_container_width=True,
):

    errors = []


    # ========================================================
    # 10-1 檢查營業時間
    # ========================================================

    if (
        time_to_minutes(weekday_end)
        <= time_to_minutes(weekday_start)
    ):
        errors.append(
            "週一～週五的結束營業時間必須晚於開始營業時間。"
        )

    if (
        time_to_minutes(weekend_end)
        <= time_to_minutes(weekend_start)
    ):
        errors.append(
            "週六、週日的結束營業時間必須晚於開始營業時間。"
        )


    # ========================================================
    # 10-2 會議資料
    # ========================================================

    meeting_assignments = []
    meeting_counts = {}
    seen_meetings = set()

    for meeting in ss.meetings:

        meeting_date = meeting["date"]
        meeting_employee = meeting["employee"]

        # 只送本週資料
        if not (
            start_date
            <= meeting_date
            <= end_date
        ):
            continue

        meeting_key = (
            meeting_employee,
            meeting_date,
        )

        # 同一人同一天不要重複加入
        if meeting_key in seen_meetings:
            continue

        seen_meetings.add(
            meeting_key
        )

        date_string = (
            meeting_date.isoformat()
        )

        meeting_counts[
            date_string
        ] = (
            meeting_counts.get(
                date_string,
                0,
            )
            + 1
        )

        meeting_assignments.append({
            "employee":
                meeting_employee,
            "date":
                date_string,
            "shift":
                "MEETING",
            "start_time":
                None,
            "end_time":
                None,
        })


    meetings_payload = [
        {
            "date": meeting_date,
            "staff_count": staff_count,
        }
        for meeting_date, staff_count
        in meeting_counts.items()
    ]


    # ========================================================
    # 10-3 排假 / 指定班
    # ========================================================

    assignments_payload = []

    seen_assignments = set()

    for rule in ss.assignments:

        rule_date = rule["date"]

        # 排班週以外的設定不送入這次模型
        if not (
            start_date
            <= rule_date
            <= end_date
        ):
            continue

        assignment_key = (
            rule["employee"],
            rule_date,
        )

        if assignment_key in seen_assignments:

            errors.append(
                f"{rule['employee']} 在 "
                f"{rule_date} 有重複的排假／指定班設定。"
            )

            continue

        seen_assignments.add(
            assignment_key
        )

        assignments_payload.append({
            "employee":
                rule["employee"],
            "date":
                rule_date.isoformat(),
            "shift":
                rule["shift"],
            "start_time":
                rule.get("start_time"),
            "end_time":
                rule.get("end_time"),
        })


    # ========================================================
    # 10-4 檢查會議與指定班是否撞期
    # ========================================================

    for meeting in meeting_assignments:

        meeting_key = (
            meeting["employee"],
            date.fromisoformat(
                meeting["date"]
            ),
        )

        if meeting_key in seen_assignments:

            errors.append(
                f"{meeting['employee']} 在 "
                f"{meeting['date']} 同時設定了會議"
                "與其他排假／指定班。"
            )


    assignments_payload.extend(
        meeting_assignments
    )


    # ========================================================
    # 10-5 連休偏好
    # ========================================================

    consecutive_payload = [
        {
            "employee": employee
        }
        for employee
        in ss.consecutive_off
    ]


    # ========================================================
    # 10-6 建立要送進後端的參數
    # ========================================================

    payload = {

        "start_date":
            start_date.isoformat(),

        "end_date":
            end_date.isoformat(),

        "employees":
            employees,

        "business_hours": business_hours_ui,

        "shifts": {

            "demand": {
                "morning":
                    int(morning_demand),
                "middle":
                    int(middle_demand),
                "night":
                    int(night_demand),
            },

            "middle_start":
                middle_start,
        },

        "meetings":
            meetings_payload,

        "fixed_shifts":
            ss.fixed_shifts,

        "fixed_days_off":
            ss.fixed_days_off,

        "assignments":
            assignments_payload,

        "preferences": {

            "preferred_shifts":
                ss.preferred_shifts,

            "preferred_days_off":
                ss.preferred_days_off,

            "consecutive_off":
                consecutive_payload,

            "different_shift":
                ss.different_shift,
        },
    }


    # ========================================================
    # 10-7 執行後端 OR-Tools
    # ========================================================

    if errors:

        st.error(
            "目前設定有衝突，請先修正："
        )

        for error in errors:

            st.write(
                f"• {error}"
            )

    else:

        try:

            request = ScheduleRequest(
                **payload
            )

            with st.spinner(
                "正在計算最佳班表..."
            ):

                result = solve_schedule(
                    request
                )

            ss.schedule_result = result

        except Exception as error:

            st.error(
                "無法執行排班。"
            )

            st.exception(
                error
            )


# ============================================================
# 11. 顯示排班結果
# ============================================================

if "schedule_result" in ss:

    result = ss.schedule_result

    st.divider()

    st.header("📋 自動排班結果")


    # ========================================================
    # 排班失敗
    # ========================================================

    if not result.get(
        "success",
        False,
    ):

        st.error(
            result.get(
                "message",
                "找不到符合目前硬性條件的班表。"
            )
        )

        st.warning(
            "可以檢查固定班、固定休假、排假、會議或每週上班天數是否互相衝突。"
        )


    # ========================================================
    # 排班成功
    # ========================================================

    else:

        st.success(
            "✅ 自動排班完成"
        )

        if result.get("status"):

            st.caption(
                f"求解狀態：{result['status']}"
            )


        # ====================================================
        # 11-1 班表
        # ====================================================

        schedule_rows = []

        schedule_data = result.get(
            "schedule",
            [],
        )


        for employee_result in schedule_data:

            employee_name = (
                employee_result.get(
                    "name"
                )
                or employee_result.get(
                    "employee"
                )
                or employee_result.get(
                    "id"
                )
                or "未知"
            )

            row = {
                "人員": employee_name
            }


            for day_data in employee_result.get(
                "days",
                [],
            ):

                current_date = (
                    date.fromisoformat(
                        day_data["date"]
                    )
                )

                weekday_text = [
                    "一",
                    "二",
                    "三",
                    "四",
                    "五",
                    "六",
                    "日",
                ][
                    current_date.weekday()
                ]

                column_name = (
                    current_date.strftime(
                        "%m/%d"
                    )
                    +
                    f"(週{weekday_text})"
                )

                shift_code = (
                    day_data.get(
                        "shift",
                        "OFF",
                    )
                )

                shift_name = (
                    SHIFT_DISPLAY.get(
                        shift_code,
                        shift_code,
                    )
                )

                start_time_value = (
                    day_data.get(
                        "start_time"
                    )
                )

                end_time_value = (
                    day_data.get(
                        "end_time"
                    )
                )


                if (
                    start_time_value
                    and end_time_value
                ):

                    display_value = (
                        f"{shift_name} "
                        f"{start_time_value}"
                        "-"
                        f"{end_time_value}"
                    )

                else:

                    display_value = (
                        shift_name
                    )


                row[
                    column_name
                ] = display_value


            row["上班天數"] = (
                employee_result.get(
                    "work_days",
                    "",
                )
            )

            row["總工時"] = (
                employee_result.get(
                    "total_hours",
                    "",
                )
            )

            schedule_rows.append(
                row
            )


        if schedule_rows:

            st.dataframe(
                schedule_rows,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.warning(
                "後端已回傳成功，但沒有取得班表資料。"
            )


        # ====================================================
        # 11-2 個人統計
        # ====================================================

        if schedule_data:

            st.subheader(
                "👥 個人出勤統計"
            )

            summary_rows = []

            for employee_result in schedule_data:

                employee_name = (
                    employee_result.get(
                        "name"
                    )
                    or employee_result.get(
                        "employee"
                    )
                    or employee_result.get(
                        "id"
                    )
                    or "未知"
                )

                summary_rows.append({
                    "人員":
                        employee_name,

                    "上班天數":
                        employee_result.get(
                            "work_days",
                            "",
                        ),

                    "總工時":
                        employee_result.get(
                            "total_hours",
                            "",
                        ),
                })


            st.dataframe(
                summary_rows,
                use_container_width=True,
                hide_index=True,
            )


        # ====================================================
        # 11-3 人力不足
        # ====================================================

        deficits = result.get(
            "deficits",
            [],
        )


        if deficits:

            st.subheader(
                "⚠️ 人力不足"
            )

            deficit_rows = []

            for deficit in deficits:

                shift_code = (
                    deficit.get(
                        "shift",
                        ""
                    )
                )

                deficit_rows.append({
                    "日期":
                        deficit.get(
                            "date",
                            "",
                        ),

                    "班別":
                        SHIFT_DISPLAY.get(
                            shift_code,
                            shift_code,
                        ),

                    "不足人數":
                        deficit.get(
                            "deficit",
                            0,
                        ),
                })


            st.dataframe(
                deficit_rows,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.success(
                "✅ 所有基礎營業班別人力需求皆已滿足。"
            )
