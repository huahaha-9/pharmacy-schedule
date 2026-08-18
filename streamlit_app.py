import copy
import streamlit as st
from datetime import date, timedelta
from supabase import create_client

from backend.models import ScheduleRequest
from backend.scheduler import solve_schedule, calculate_shift_time


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
    page_title="排班系統",
    page_icon="💊",
    layout="wide",
)

st.title("💊 排班系統")
st.caption("設定人員、營業時間與排班條件後，自動產生一週班表")


if "manager_logged_in" not in st.session_state:
    st.session_state.manager_logged_in = False

# ============================================================
# 共用常數 / 工具
# ============================================================

TIME_OPTIONS = [
    f"{hour:02d}:{minute:02d}"
    for hour in range(24)
    for minute in (0, 30)
]

EARLY_LEAVE_OPTIONS = [
    f"{minutes // 60:02d}:{minutes % 60:02d}"
    for minutes in range(11 * 60, 16 * 60 + 31, 30)
]

LATE_START_OPTIONS = [
    f"{minutes // 60:02d}:{minutes % 60:02d}"
    for minutes in range(14 * 60 + 30, 19 * 60 + 1, 30)
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
# Session State 初始化
# ============================================================

ss = st.session_state

if "employees" not in ss:
    ss.employees = load_employees()

if "meetings" not in ss:
    ss.meetings = []

if "fixed_shifts" not in ss:
    ss.fixed_shifts = []

if "fixed_days_off" not in ss:
    ss.fixed_days_off = []

if "assignments" not in ss:
    ss.assignments = []

if "preferred_shifts" not in ss:
    ss.preferred_shifts = []

if "preferred_days_off" not in ss:
    ss.preferred_days_off = []

if "consecutive_off" not in ss:
    ss.consecutive_off = []

if "different_shift" not in ss:
    ss.different_shift = []

# 共用顯示對照：員工端與店長端都會使用
employee_name_map = {
    employee["id"]: employee["name"]
    for employee in ss.employees
}

request_type_display = {
    "OFF": "休假",
    "MORNING": "早班",
    "MIDDLE": "中班",
    "NIGHT": "晚班",
}


# ============================================================
# 員工排假
# ============================================================

if not st.session_state.manager_logged_in:

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
    
    min_leave_date = date.today() + timedelta(days=15)
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
            "指定晚班",
        ],
        key="leave_request_type",
    )
    
    request_type_map = {
        "休假": "OFF",
        "指定早班": "MORNING",
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
                options=EARLY_LEAVE_OPTIONS,
                index=EARLY_LEAVE_OPTIONS.index("15:00"),
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
                options=LATE_START_OPTIONS,
                index=LATE_START_OPTIONS.index("18:00"),
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

            original_request_date = date.fromisoformat(record["request_date"])

            # 舊紀錄可能早於目前「15 天後」的可排假範圍。
            # 為了讓舊紀錄仍能正常顯示與編輯，date_input 先允許顯示原日期；
            # 真正儲存時再限制：日期若有更動，必須落在 15 天後～半年內。
            edit_input_min = min(original_request_date, min_leave_date)
            edit_input_max = max(original_request_date, max_leave_date)

            edit_date = st.date_input(
                "修改日期",
                value=original_request_date,
                min_value=edit_input_min,
                max_value=edit_input_max,
                key=f"edit_date_{record['id']}",
            )
            
            edit_options = [
                "休假",
                "指定早班",
                "指定晚班",
            ]
            
            code_to_label = {
                "OFF": "休假",
                "MORNING": "指定早班",
                "NIGHT": "指定晚班",
            }

            current_edit_label = code_to_label.get(record_type, "休假")
            if record_type == "MIDDLE":
                st.caption("此筆為舊的指定中班紀錄；指定中班已停用，如需修改請改選休假、指定早班或指定晚班。")
            
            edit_label = st.selectbox(
                "修改排假 / 指定班",
                edit_options,
                index=edit_options.index(current_edit_label),
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
                        EARLY_LEAVE_OPTIONS,
                        index=safe_index(EARLY_LEAVE_OPTIONS, old_end_time, EARLY_LEAVE_OPTIONS.index("15:00")),
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
                        LATE_START_OPTIONS,
                        index=safe_index(LATE_START_OPTIONS, old_start_time, LATE_START_OPTIONS.index("18:00")),
                        key=f"edit_start_{record['id']}",
                    )
            
            if st.button(
                "💾 儲存修改",
                key=f"save_edit_{record['id']}",
                use_container_width=True,
            ):
                try:
                    if (
                        edit_date != original_request_date
                        and not (min_leave_date <= edit_date <= max_leave_date)
                    ):
                        st.error("修改日期必須選在 15 天後到半年內。")
                        st.stop()
            
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
    # ========================================================
    # 店長選擇排班週期
    # ========================================================

    default_week_start = (
        date.today()
        - timedelta(days=date.today().weekday())
    )

    selected_schedule_date = st.date_input(
        "📅 選擇排班週（點該週任一天即可）",
        value=default_week_start,
        key="manager_schedule_start",
    )

    # 無論店長點選星期幾，一律換算成該週星期一作為排班起點。
    start_date = (
        selected_schedule_date
        - timedelta(days=selected_schedule_date.weekday())
    )
    end_date = start_date + timedelta(days=6)

    st.info(
        f"本次排班：{start_date}（週一）～ {end_date}（週日）"
    )

    manager_tab1, manager_tab2, manager_tab3 = st.tabs(
        [
            "👥 基本設定",
            "📋 本週總結",
            "🧩 生成班表",
        ]
    )

    with manager_tab1:
        st.subheader("👥 基本設定")
        # ============================================================
        # 2. 人員設定
        # ============================================================
        
        st.header("👥 人員設定")
        
        st.caption(
            "姓名、FT/PT、藥師、成熟人力、可減班、上班天數與工時皆可修改。"
        )
        
        employees = []
        
        employee_overview_rows = []
        for display_no, overview_employee in enumerate(ss.employees, start=1):
            employee_overview_rows.append({
                "編號": f"{display_no:02d}",
                "姓名": overview_employee["name"],
                "類型": overview_employee["employee_type"],
                "藥師": "✓" if overview_employee["is_pharmacist"] else "",
                "成熟": "✓" if overview_employee["is_senior"] else "",
                "可減班": "✓" if overview_employee["reducible"] else "",
                "天/週": int(overview_employee["work_days"]),
                "時/班": float(overview_employee["hours_per_day"]),
            })

        st.dataframe(
            employee_overview_rows,
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "01/02/03… 為顯示編號；內部 employee_id 不變，"
            "避免排假、固定規則與後端關聯中斷。需要修改再展開員工。"
        )

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

                st.markdown("**排班偏好**")

                current_shift_prefs = {
                    rule.get("shift")
                    for rule in ss.preferred_shifts
                    if rule.get("employee") == employee["id"]
                    and rule.get("weekday") is None
                }

                current_shift_preference = (
                    "偏好早班" if "MORNING" in current_shift_prefs
                    else "偏好晚班" if "NIGHT" in current_shift_prefs
                    else "無"
                )
                shift_preference_label = st.radio(
                    "偏好班別",
                    ["無", "偏好早班", "偏好晚班"],
                    index=["無", "偏好早班", "偏好晚班"].index(current_shift_preference),
                    horizontal=True,
                    key=f"shift_preference_{i}",
                )
                prefer_morning = shift_preference_label == "偏好早班"
                prefer_night = shift_preference_label == "偏好晚班"

                current_off_days = sorted({
                    int(rule["weekday"])
                    for rule in ss.preferred_days_off
                    if rule.get("employee") == employee["id"]
                    and rule.get("weekday") is not None
                })

                preferred_off_names = st.multiselect(
                    "偏好休星期（可複選）",
                    WEEKDAY_NAMES,
                    default=[
                        WEEKDAY_NAMES[weekday]
                        for weekday in current_off_days
                        if 0 <= weekday <= 6
                    ],
                    key=f"preferred_off_days_{i}",
                )

                prefer_consecutive = st.checkbox(
                    "偏好連休",
                    value=employee["id"] in ss.consecutive_off,
                    key=f"prefer_consecutive_{i}",
                )

                ss.preferred_shifts = [
                    rule for rule in ss.preferred_shifts
                    if not (
                        rule.get("employee") == employee["id"]
                        and rule.get("weekday") is None
                    )
                ]
                for shift_code, enabled in [
                    ("MORNING", prefer_morning),
                    ("NIGHT", prefer_night),
                ]:
                    if enabled:
                        ss.preferred_shifts.append({
                            "employee": employee["id"],
                            "shift": shift_code,
                            "weekday": None,
                        })

                ss.preferred_days_off = [
                    rule for rule in ss.preferred_days_off
                    if rule.get("employee") != employee["id"]
                ]
                for weekday_name in preferred_off_names:
                    ss.preferred_days_off.append({
                        "employee": employee["id"],
                        "weekday": WEEKDAY_MAP[weekday_name],
                    })

                ss.consecutive_off = [
                    employee_id for employee_id in ss.consecutive_off
                    if employee_id != employee["id"]
                ]
                if prefer_consecutive:
                    ss.consecutive_off.append(employee["id"])

                updated_employee = {
                    "id": employee["id"],
                    "name": name,
                    "employee_type": employee_type,
                    "is_pharmacist": is_pharmacist,
                    "is_senior": is_senior,
                    "reducible": reducible,
                    "work_days": int(work_days),
                    "hours_per_day": float(hours_per_day),
                    "can_morning": True,
                    "can_night": True,
                    "preferred_shift": employee.get("preferred_shift"),
                    "prefer_consecutive_off": employee.get("prefer_consecutive_off", False),
                }
        
                employees.append(updated_employee)
                ss.employees[i] = updated_employee
        
        
        
        employee_name_map = {
            employee["id"]: employee["name"]
            for employee in employees
        }

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

    with manager_tab2:
        st.subheader("📋 本週總結")
        st.caption("快速確認本週排假、指定班與會議安排。")

        summary_start = start_date
        summary_end = end_date

        st.info(
            f"📅 查看期間：{summary_start} ～ {summary_end}"
        )
        # --------------------------------------------------------
        # 特殊日：國定假日 / 每月 5 號生日活動
        # --------------------------------------------------------

        st.markdown("#### 🎉 特殊日")

        special_days = []

        current_day = summary_start

        while current_day <= summary_end:

            # 每月 5 號生日活動
            if current_day.day == 5:
                special_days.append(
                    f"🎂 {current_day.strftime('%m/%d')} 生日活動"
                )

            # 國定假日：2026 依行政院人事行政總處辦公日曆。
            holidays_2026 = {
                "01-01": "元旦",
                "02-16": "春節假期", "02-17": "春節假期",
                "02-18": "春節假期", "02-19": "春節假期",
                "02-20": "春節假期",
                "02-27": "和平紀念日補假", "02-28": "和平紀念日",
                "04-03": "兒童節補假", "04-04": "兒童節",
                "04-05": "清明節", "04-06": "清明節補假",
                "05-01": "勞動節",
                "06-19": "端午節",
                "09-25": "中秋節",
                "09-28": "孔子誕辰紀念日／教師節",
                "10-09": "國慶日補假", "10-10": "國慶日",
                "10-25": "臺灣光復暨金門古寧頭大捷紀念日",
                "10-26": "光復節補假",
                "12-25": "行憲紀念日",
            }
            fixed_holidays = {
                "01-01": "元旦", "02-28": "和平紀念日",
                "04-04": "兒童節", "05-01": "勞動節",
                "09-28": "孔子誕辰紀念日／教師節",
                "10-10": "國慶日",
                "10-25": "臺灣光復暨金門古寧頭大捷紀念日",
                "12-25": "行憲紀念日",
            }
            holiday_name = (
                holidays_2026.get(current_day.strftime("%m-%d"))
                if current_day.year == 2026
                else fixed_holidays.get(current_day.strftime("%m-%d"))
            )

            if holiday_name:
                special_days.append(
                    f"🇹🇼 {current_day.strftime('%m/%d')} {holiday_name}"
                )

            current_day += timedelta(days=1)

        if special_days:
            for special_day in special_days:
                st.write(special_day)
        else:
            st.info("本週沒有特殊日。")

        st.divider()

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
        with st.expander("📣 會議", expanded=False):
            st.caption("會議算上班。需要新增或修改時再展開。")

            meeting_delete = None

            for i, meeting in enumerate(ss.meetings):
                with st.expander(
                    f"{meeting['date']}｜{employee_name_map.get(meeting['employee'], meeting['employee'])}",
                    expanded=False,
                ):
                    meeting_date = st.date_input(
                        "日期",
                        value=meeting["date"],
                        min_value=start_date,
                        max_value=end_date,
                        key=f"meeting_date_{i}",
                    )
                    meeting_employee = st.selectbox(
                        "會議人員",
                        employee_ids,
                        index=safe_index(
                            employee_ids,
                            meeting["employee"],
                        ),
                        format_func=lambda employee_id: employee_name_map.get(
                            employee_id, employee_id
                        ),
                        key=f"meeting_employee_{i}",
                    )

                    col_save, col_delete = st.columns(2)
                    with col_save:
                        if st.button(
                            "💾 儲存修改",
                            key=f"save_meeting_{i}",
                            use_container_width=True,
                        ):
                            duplicate = any(
                                j != i
                                and item.get("date") == meeting_date
                                and item.get("employee") == meeting_employee
                                for j, item in enumerate(ss.meetings)
                            )
                            if duplicate:
                                st.warning("⚠️ 相同日期、相同員工的會議已存在，不會重複儲存。")
                            else:
                                ss.meetings[i] = {
                                    "date": meeting_date,
                                    "employee": meeting_employee,
                                }
                                st.success("✅ 會議修改已儲存")
                                st.rerun()

                    with col_delete:
                        if st.button(
                            "🗑️ 刪除",
                            key=f"delete_meeting_{i}",
                            use_container_width=True,
                        ):
                            meeting_delete = i

            if meeting_delete is not None:
                ss.meetings.pop(meeting_delete)
                st.rerun()

            with st.expander("＋ 新增會議", expanded=False):
                new_meeting_date = st.date_input(
                    "日期",
                    value=start_date,
                    min_value=start_date,
                    max_value=end_date,
                    key="new_meeting_date",
                )
                new_meeting_employee = st.selectbox(
                    "會議人員",
                    employee_ids,
                    format_func=lambda employee_id: employee_name_map.get(
                        employee_id, employee_id
                    ),
                    key="new_meeting_employee",
                )

                if st.button(
                    "💾 儲存新會議",
                    key="save_new_meeting",
                    use_container_width=True,
                    type="primary",
                ):
                    duplicate = any(
                        item.get("date") == new_meeting_date
                        and item.get("employee") == new_meeting_employee
                        for item in ss.meetings
                    )
                    if duplicate:
                        st.warning("⚠️ 相同日期、相同員工的會議已存在，不會重複新增。")
                    else:
                        ss.meetings.append({
                            "date": new_meeting_date,
                            "employee": new_meeting_employee,
                        })
                        st.success("✅ 新會議已儲存")
                        st.rerun()

        st.divider()
        # ============================================================
        with st.expander("📝 店長排假 / 指定班管理", expanded=False):
            st.caption("店長不受員工端 15 天限制；資料仍使用 leave_requests。")

            try:
                manager_leave_rows = (
                    supabase.table("leave_requests")
                    .select("*")
                    .gte("request_date", summary_start.isoformat())
                    .lte("request_date", summary_end.isoformat())
                    .order("request_date")
                    .execute()
                ).data
            except Exception as error:
                manager_leave_rows = []
                st.error("❌ 無法讀取本週排假")
                st.exception(error)

            delete_leave_id = None
            for item in manager_leave_rows:
                record_id = item.get("id")
                employee_label = employee_name_map.get(
                    item["employee_id"], item["employee_id"]
                )
                request_label = request_type_display.get(
                    item["request_type"], item["request_type"]
                )
                with st.expander(
                    f"{item['request_date']}｜{employee_label}｜{request_label}",
                    expanded=False,
                ):
                    if st.button(
                        "🗑️ 刪除此筆",
                        key=f"manager_delete_leave_{record_id}",
                        use_container_width=True,
                    ):
                        delete_leave_id = record_id

            if delete_leave_id is not None:
                try:
                    supabase.table("leave_requests").delete().eq(
                        "id", delete_leave_id
                    ).execute()
                    st.success("✅ 已刪除排假紀錄")
                    st.rerun()
                except Exception as error:
                    st.error("❌ 刪除排假失敗")
                    st.exception(error)

            st.markdown("**＋ 新增 / 覆蓋排假**")
            manager_leave_employee = st.selectbox(
                "員工",
                employee_ids,
                format_func=lambda employee_id: employee_name_map.get(
                    employee_id, employee_id
                ),
                key="manager_leave_employee",
            )
            manager_leave_date = st.date_input(
                "日期",
                value=summary_start,
                min_value=summary_start,
                max_value=summary_end,
                key="manager_leave_date",
            )
            manager_leave_label = st.selectbox(
                "排假 / 指定班",
                ["休假", "指定早班", "指定晚班"],
                key="manager_leave_type",
            )
            manager_leave_type = {
                "休假": "OFF",
                "指定早班": "MORNING",
                "指定晚班": "NIGHT",
            }[manager_leave_label]

            manager_start_time = None
            manager_end_time = None
            if manager_leave_type == "MORNING":
                if st.checkbox("提早下班", key="manager_use_early_leave"):
                    manager_end_time = st.selectbox(
                        "下班時間", EARLY_LEAVE_OPTIONS,
                        key="manager_early_leave_time",
                    )
            elif manager_leave_type == "NIGHT":
                if st.checkbox("延後上班", key="manager_use_late_start"):
                    manager_start_time = st.selectbox(
                        "上班時間", LATE_START_OPTIONS,
                        key="manager_late_start_time",
                    )

            if st.button(
                "💾 儲存店長排假",
                key="manager_save_leave",
                use_container_width=True,
                type="primary",
            ):
                try:
                    supabase.table("leave_requests").upsert(
                        {
                            "employee_id": manager_leave_employee,
                            "request_date": manager_leave_date.isoformat(),
                            "request_type": manager_leave_type,
                            "start_time": manager_start_time,
                            "end_time": manager_end_time,
                        },
                        on_conflict="employee_id,request_date",
                    ).execute()
                    st.success("✅ 店長排假已儲存")
                    st.rerun()
                except Exception as error:
                    st.error("❌ 店長排假儲存失敗")
                    st.exception(error)

        st.divider()

        # 6. 固定班
        # ============================================================

        st.markdown("#### 🔒 固定班")
        st.caption(
            "固定班代表：這位員工如果上班，只能排指定班別，但仍可以正常休假。"
        )

        # 固定規則以 Supabase 為唯一正式資料來源
        try:
            fixed_rules_response = (
                supabase
                .table("employee_fixed_rules")
                .select("*")
                .order("employee_id")
                .execute()
            )
            fixed_rules_all = fixed_rules_response.data or []
        except Exception as error:
            fixed_rules_all = []
            st.error("❌ 無法讀取固定規則")
            st.exception(error)

        fixed_shift_rows = [
            rule
            for rule in fixed_rules_all
            if rule.get("rule_type") == "FIXED_SHIFT"
        ]

        fixed_off_rows = [
            rule
            for rule in fixed_rules_all
            if rule.get("rule_type") == "FIXED_OFF"
        ]

        shift_label_map = {
            "MORNING": "早班",
            "MIDDLE": "中班",
            "NIGHT": "晚班",
        }
        shift_code_map = {
            "早班": "MORNING",
            "中班": "MIDDLE",
            "晚班": "NIGHT",
        }

        if fixed_shift_rows:
            for i, rule in enumerate(fixed_shift_rows):
                employee_name = employee_name_map.get(
                    rule["employee_id"],
                    rule["employee_id"],
                )

                col1, col2 = st.columns([4, 1])

                with col1:
                    st.write(
                        f"👤 {employee_name}｜"
                        f"固定{shift_label_map.get(rule.get('shift'), rule.get('shift'))}"
                    )

                with col2:
                    if st.button(
                        "刪除",
                        key=f"delete_fixed_shift_db_{i}",
                    ):
                        try:
                            (
                                supabase
                                .table("employee_fixed_rules")
                                .delete()
                                .eq("employee_id", rule["employee_id"])
                                .eq("rule_type", "FIXED_SHIFT")
                                .eq("shift", rule["shift"])
                                .execute()
                            )
                            st.success("✅ 已刪除固定班")
                            st.rerun()
                        except Exception as error:
                            st.error("❌ 刪除固定班失敗")
                            st.exception(error)
        else:
            st.info("目前沒有固定班。")

        with st.expander("＋ 新增 / 修改固定班"):
            new_fixed_employee = st.selectbox(
                "人員",
                employee_ids,
                key="new_fixed_shift_employee",
            )

            new_fixed_shift_label = st.selectbox(
                "固定班別",
                ["早班", "中班", "晚班"],
                key="new_fixed_shift_value",
            )

            if st.button(
                "💾 儲存固定班",
                key="save_fixed_shift_db",
                use_container_width=True,
            ):
                try:
                    new_fixed_shift = shift_code_map[new_fixed_shift_label]

                    existing_shift = next(
                        (
                            rule
                            for rule in fixed_shift_rows
                            if rule.get("employee_id") == new_fixed_employee
                        ),
                        None,
                    )

                    if existing_shift:
                        (
                            supabase
                            .table("employee_fixed_rules")
                            .update({
                                "shift": new_fixed_shift,
                                "weekday": None,
                            })
                            .eq("employee_id", new_fixed_employee)
                            .eq("rule_type", "FIXED_SHIFT")
                            .execute()
                        )
                        st.success("✅ 固定班已更新")
                    else:
                        (
                            supabase
                            .table("employee_fixed_rules")
                            .insert({
                                "employee_id": new_fixed_employee,
                                "rule_type": "FIXED_SHIFT",
                                "shift": new_fixed_shift,
                                "weekday": None,
                            })
                            .execute()
                        )
                        st.success("✅ 固定班已新增")

                    st.rerun()

                except Exception as error:
                    st.error("❌ 儲存固定班失敗")
                    st.exception(error)


        # ============================================================
        # 7. 固定休假
        # ============================================================

        st.markdown("#### 🏖️ 固定休假")
        st.caption("設定員工固定星期幾休假。")

        weekday_label_map = {
            0: "週一",
            1: "週二",
            2: "週三",
            3: "週四",
            4: "週五",
            5: "週六",
            6: "週日",
        }

        if fixed_off_rows:
            for i, rule in enumerate(fixed_off_rows):
                employee_name = employee_name_map.get(
                    rule["employee_id"],
                    rule["employee_id"],
                )
                weekday_value = int(rule["weekday"])

                col1, col2 = st.columns([4, 1])

                with col1:
                    st.write(
                        f"👤 {employee_name}｜"
                        f"固定{weekday_label_map.get(weekday_value, weekday_value)}休假"
                    )

                with col2:
                    if st.button(
                        "刪除",
                        key=f"delete_fixed_off_db_{i}",
                    ):
                        try:
                            (
                                supabase
                                .table("employee_fixed_rules")
                                .delete()
                                .eq("employee_id", rule["employee_id"])
                                .eq("rule_type", "FIXED_OFF")
                                .eq("weekday", weekday_value)
                                .execute()
                            )
                            st.success("✅ 已刪除固定休假")
                            st.rerun()
                        except Exception as error:
                            st.error("❌ 刪除固定休假失敗")
                            st.exception(error)
        else:
            st.info("目前沒有固定休假。")

        with st.expander("＋ 新增固定休假"):
            new_fixed_off_employee = st.selectbox(
                "人員",
                employee_ids,
                key="new_fixed_off_employee_db",
            )

            new_fixed_off_weekday_label = st.selectbox(
                "固定休星期",
                WEEKDAY_NAMES,
                key="new_fixed_off_weekday_db",
            )

            if st.button(
                "💾 儲存固定休假",
                key="save_fixed_off_db",
                use_container_width=True,
            ):
                try:
                    new_weekday = WEEKDAY_MAP[
                        new_fixed_off_weekday_label
                    ]

                    duplicate_off = any(
                        (
                            rule.get("employee_id") == new_fixed_off_employee
                            and int(rule.get("weekday")) == new_weekday
                        )
                        for rule in fixed_off_rows
                        if rule.get("weekday") is not None
                    )

                    if duplicate_off:
                        st.warning("⚠️ 這筆固定休假已經存在，不會重複新增。")
                    else:
                        (
                            supabase
                            .table("employee_fixed_rules")
                            .insert({
                                "employee_id": new_fixed_off_employee,
                                "rule_type": "FIXED_OFF",
                                "shift": None,
                                "weekday": new_weekday,
                            })
                            .execute()
                        )
                        st.success("✅ 固定休假已新增")
                        st.rerun()

                except Exception as error:
                    st.error("❌ 儲存固定休假失敗")
                    st.exception(error)



        # 舊的 session_state「排假 / 指定班」編輯器已移除。
        # 正式排假資料以 Supabase leave_requests 為唯一資料來源，
        # 本週排假已在本週總結上方顯示。

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
if not st.session_state.manager_logged_in:
    st.stop()

# ============================================================
# 店長三大區塊（舊 UI 已收回對應 Tab）
# ============================================================


with manager_tab1:
    st.divider()
    # ============================================================
    # 9. 排班偏好
    # ============================================================

    st.header("👥 其他排班規則")
    st.caption("員工個人的班別、休假星期與連休偏好，已整合到上方員工資料卡。")


    # 9-4 兩人避免同班
    # ============================================================

    st.caption("↔️ 兩人避免同班（設定後會自動縮起）")

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



with manager_tab3:
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

        day_name_map = {
            "monday": "週一",
            "tuesday": "週二",
            "wednesday": "週三",
            "thursday": "週四",
            "friday": "週五",
            "saturday": "週六",
            "sunday": "週日",
        }

        for day_key, day_name in day_name_map.items():

            day_hours = business_hours_ui[day_key]

            if (
                time_to_minutes(day_hours["end"])
                <= time_to_minutes(day_hours["start"])
            ):
                errors.append(
                    f"{day_name}的結束營業時間必須晚於開始營業時間。"
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

        # 員工端已儲存在 Supabase 的排假／指定班，直接帶入本週排班模型
        try:
            leave_response_for_schedule = (
                supabase
                .table("leave_requests")
                .select("*")
                .gte("request_date", start_date.isoformat())
                .lte("request_date", end_date.isoformat())
                .order("request_date")
                .execute()
            )
            leave_rows_for_schedule = leave_response_for_schedule.data or []
        except Exception as error:
            leave_rows_for_schedule = []
            errors.append(f"無法讀取本週員工排假資料：{error}")

        for row in leave_rows_for_schedule:
            row_date = date.fromisoformat(row["request_date"])
            assignment_key = (row["employee_id"], row_date)
            if assignment_key in seen_assignments:
                continue
            seen_assignments.add(assignment_key)
            assignments_payload.append({
                "employee": row["employee_id"],
                "date": row["request_date"],
                "shift": row["request_type"],
                "start_time": (str(row["start_time"])[:5] if row.get("start_time") else None),
                "end_time": (str(row["end_time"])[:5] if row.get("end_time") else None),
            })

        # 店長在本頁手動新增的設定也一起送入；若與員工排假撞同人同日則提示
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

           # 讀取本週人力需求
        staffing_response = (
            supabase
            .table("weekly_staffing")
            .select("*")
            .eq("week_start", start_date.isoformat())
            .order("weekday")
            .execute()
        )

        staffing_rows_for_schedule = staffing_response.data or []

        staffing_map_for_schedule = {
            int(row["weekday"]): row
            for row in staffing_rows_for_schedule
        }

        weekly_staffing_for_schedule = {}

        for weekday_num in range(7):
            saved_staffing = staffing_map_for_schedule.get(weekday_num)

            weekly_staffing_for_schedule[weekday_num] = {
                "morning": (
                    int(saved_staffing["morning_required"])
                    if saved_staffing
                    else 2
                ),
                "middle": (
                    int(saved_staffing["middle_required"])
                    if saved_staffing
                    else 0
                ),
                "night": (
                    int(saved_staffing["night_required"])
                    if saved_staffing
                    else 3
                ),
            }

        # ========================================================
        # 從 Supabase 讀取固定班 / 固定休假，作為 solver 唯一資料來源
        # ========================================================
        try:
            solver_fixed_rules_response = (
                supabase
                .table("employee_fixed_rules")
                .select("*")
                .order("employee_id")
                .execute()
            )
            solver_fixed_rules = solver_fixed_rules_response.data
        except Exception as error:
            solver_fixed_rules = []
            errors.append(f"無法讀取固定班 / 固定休假：{error}")

        fixed_shifts_payload = []
        fixed_days_off_payload = []

        for rule in solver_fixed_rules:
            if rule.get("rule_type") == "FIXED_SHIFT":
                if rule.get("shift") in {"MORNING", "MIDDLE", "NIGHT"}:
                    fixed_shifts_payload.append({
                        "employee": rule["employee_id"],
                        "shift": rule["shift"],
                    })
            elif rule.get("rule_type") == "FIXED_OFF":
                if rule.get("weekday") is not None:
                    fixed_days_off_payload.append({
                        "employee": rule["employee_id"],
                        "weekday": int(rule["weekday"]),
                    })

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
                    "monday": {
                        "morning": weekly_staffing_for_schedule[0]["morning"],
                        "middle": weekly_staffing_for_schedule[0]["middle"],
                        "night": weekly_staffing_for_schedule[0]["night"],
                    },
                    "tuesday": {
                        "morning": weekly_staffing_for_schedule[1]["morning"],
                        "middle": weekly_staffing_for_schedule[1]["middle"],
                        "night": weekly_staffing_for_schedule[1]["night"],
                    },
                    "wednesday": {
                        "morning": weekly_staffing_for_schedule[2]["morning"],
                        "middle": weekly_staffing_for_schedule[2]["middle"],
                        "night": weekly_staffing_for_schedule[2]["night"],
                    },
                    "thursday": {
                        "morning": weekly_staffing_for_schedule[3]["morning"],
                        "middle": weekly_staffing_for_schedule[3]["middle"],
                        "night": weekly_staffing_for_schedule[3]["night"],
                    },
                    "friday": {
                        "morning": weekly_staffing_for_schedule[4]["morning"],
                        "middle": weekly_staffing_for_schedule[4]["middle"],
                        "night": weekly_staffing_for_schedule[4]["night"],
                    },
                    "saturday": {
                        "morning": weekly_staffing_for_schedule[5]["morning"],
                        "middle": weekly_staffing_for_schedule[5]["middle"],
                        "night": weekly_staffing_for_schedule[5]["night"],
                    },
                    "sunday": {
                        "morning": weekly_staffing_for_schedule[6]["morning"],
                        "middle": weekly_staffing_for_schedule[6]["middle"],
                        "night": weekly_staffing_for_schedule[6]["night"],
                    },
                },

                "middle_start": middle_start,
            },


            "meetings":
                meetings_payload,

            "fixed_shifts": fixed_shifts_payload,

            "fixed_days_off": fixed_days_off_payload,

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

                if result.get("success"):
                    ss.manual_schedule = copy.deepcopy(
                        result.get("schedule", [])
                    )
                    ss.schedule_requirements = {
                        weekday_num: dict(values)
                        for weekday_num, values
                        in weekly_staffing_for_schedule.items()
                    }

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

            schedule_data = ss.get(
                "manual_schedule",
                result.get("schedule", []),
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

                st.caption(
                    "手動調整後按「💾 儲存本日修改」，"
                    "七天總表會立即重新整理顯示修改後的班別與時間。"
                )

            else:

                st.warning(
                    "後端已回傳成功，但沒有取得班表資料。"
                )


            # ====================================================
            # 11-2 店長單日修改班表
            # ====================================================

            if schedule_data:
                st.subheader("✏️ 單日修改班表")
                st.caption(
                    "七天總表維持濃縮顯示；需要調整時再選一天修改。"
                    "固定休假與員工指定班會鎖定，避免誤改。"
                )

                schedule_dates = [
                    day["date"]
                    for day in schedule_data[0].get("days", [])
                ]

                if schedule_dates:
                    edit_date_value = st.selectbox(
                        "選擇要修改的日期",
                        schedule_dates,
                        format_func=lambda value: (
                            date.fromisoformat(value).strftime("%m/%d")
                            + "（"
                            + WEEKDAY_NAMES[
                                date.fromisoformat(value).weekday()
                            ]
                            + "）"
                        ),
                        key="manual_edit_date",
                    )

                    try:
                        manual_fixed_response = (
                            supabase
                            .table("employee_fixed_rules")
                            .select("*")
                            .execute()
                        )
                        manual_fixed_rules = manual_fixed_response.data or []
                    except Exception:
                        manual_fixed_rules = []

                    try:
                        manual_leave_response = (
                            supabase
                            .table("leave_requests")
                            .select("*")
                            .eq("request_date", edit_date_value)
                            .execute()
                        )
                        manual_leave_rules = manual_leave_response.data or []
                    except Exception:
                        manual_leave_rules = []

                    fixed_shift_by_employee = {
                        rule["employee_id"]: rule["shift"]
                        for rule in manual_fixed_rules
                        if rule.get("rule_type") == "FIXED_SHIFT"
                    }
                    fixed_off_employees = {
                        rule["employee_id"]
                        for rule in manual_fixed_rules
                        if (
                            rule.get("rule_type") == "FIXED_OFF"
                            and rule.get("weekday") is not None
                            and int(rule["weekday"])
                            == date.fromisoformat(edit_date_value).weekday()
                        )
                    }
                    assigned_by_employee = {
                        rule["employee_id"]: rule["request_type"]
                        for rule in manual_leave_rules
                    }
                    employee_lookup = {
                        employee["id"]: employee
                        for employee in employees
                    }

                    for employee_result in schedule_data:
                        employee_id = employee_result.get("employee_id")
                        employee_name = (
                            employee_result.get("name") or employee_id
                        )
                        day_result = next(
                            (
                                day
                                for day in employee_result.get("days", [])
                                if day.get("date") == edit_date_value
                            ),
                            None,
                        )
                        if not day_result:
                            continue

                        current_shift = day_result.get("shift", "OFF")
                        locked_reason = None
                        allowed_options = ["OFF", "MORNING", "MIDDLE", "NIGHT"]

                        if employee_id in assigned_by_employee:
                            locked_reason = "員工指定排假 / 指定班"
                            allowed_options = [assigned_by_employee[employee_id]]
                        elif employee_id in fixed_off_employees:
                            locked_reason = "固定休假"
                            allowed_options = ["OFF"]
                        elif employee_id in fixed_shift_by_employee:
                            locked_reason = "固定班"
                            allowed_options = [
                                "OFF",
                                fixed_shift_by_employee[employee_id],
                            ]

                        if current_shift not in allowed_options:
                            allowed_options = [current_shift] + allowed_options

                        col_name, col_shift = st.columns([2, 3])
                        with col_name:
                            prefix = "🔒 " if locked_reason else ""
                            suffix = f"｜{locked_reason}" if locked_reason else ""
                            st.write(f"{prefix}**{employee_name}**{suffix}")

                        with col_shift:
                            selected_shift = st.selectbox(
                                "班別",
                                allowed_options,
                                index=allowed_options.index(current_shift),
                                format_func=lambda code: SHIFT_DISPLAY.get(code, code),
                                key=f"manual_shift_{employee_id}_{edit_date_value}",
                                label_visibility="collapsed",
                                disabled=locked_reason in {
                                    "員工指定排假 / 指定班",
                                    "固定休假",
                                },
                            )

                        if (
                            selected_shift != current_shift
                            and locked_reason not in {
                                "員工指定排假 / 指定班",
                                "固定休假",
                            }
                        ):
                            employee_info = employee_lookup.get(employee_id)
                            if employee_info:
                                day_key = [
                                    "monday", "tuesday", "wednesday",
                                    "thursday", "friday", "saturday", "sunday",
                                ][date.fromisoformat(edit_date_value).weekday()]
                                business = business_hours_ui[day_key]
                                recalculated = calculate_shift_time(
                                    shift=selected_shift,
                                    business_start=business["start"],
                                    business_end=business["end"],
                                    middle_start=middle_start,
                                    hours_per_day=float(
                                        employee_info["hours_per_day"]
                                    ),
                                )
                                day_result["shift"] = selected_shift
                                day_result["start_time"] = recalculated["start_time"]
                                day_result["end_time"] = recalculated["end_time"]
                                day_result["hours"] = recalculated["hours"]

                    # 每次 rerun 都以目前手動班表重新計算總工時與上班天數。
                    for employee_result in schedule_data:
                        employee_result["total_hours"] = sum(
                            float(day.get("hours", 0) or 0)
                            for day in employee_result.get("days", [])
                        )
                        employee_result["work_days"] = sum(
                            1
                            for day in employee_result.get("days", [])
                            if day.get("shift") != "OFF"
                        )

                    ss.manual_schedule = schedule_data

                    if st.button(
                        "💾 儲存本日修改",
                        key=f"save_manual_day_{edit_date_value}",
                        use_container_width=True,
                        type="primary",
                    ):
                        # 這裡儲存的是「本週手動調整中的草稿」。
                        # 正式班表寫入 Supabase 會在正式存檔功能完成後處理。
                        ss.manual_schedule = copy.deepcopy(
                            schedule_data
                        )
                        st.success("✅ 本日修改已儲存")
                        st.rerun()

            # ====================================================
            # 11-3 每日人力：實際 / 需求
            # ====================================================

            if schedule_data:
                st.subheader("👥 每日人力（實際 / 需求）")

                requirements = ss.get("schedule_requirements", {})
                headcount_rows = []

                for weekday_num in range(7):
                    current_day = start_date + timedelta(days=weekday_num)
                    day_date = current_day.isoformat()
                    row = {"日期": current_day.strftime("%m/%d")}

                    for shift_code, label, req_key in [
                        ("MORNING", "早", "morning"),
                        ("MIDDLE", "中", "middle"),
                        ("NIGHT", "晚", "night"),
                    ]:
                        actual = sum(
                            1
                            for employee_result in schedule_data
                            for day in employee_result.get("days", [])
                            if (
                                day.get("date") == day_date
                                and day.get("shift") == shift_code
                            )
                        )
                        required = int(
                            requirements.get(weekday_num, {}).get(req_key, 0)
                        )
                        row[label] = (
                            f"{actual}/{required}"
                            + (" ⚠️" if actual < required else "")
                        )

                    headcount_rows.append(row)

                st.dataframe(
                    headcount_rows,
                    use_container_width=True,
                    hide_index=True,
                )

            # ====================================================
            # 11-4 原始求解人力不足
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

    st.divider()
    st.divider()
    st.markdown("### ⏱️ 本週總工時")

    if "schedule_result" in ss and ss.schedule_result.get("success"):
        current_schedule_for_hours = ss.get(
            "manual_schedule",
            ss.schedule_result.get("schedule", []),
        )

        # 建議總工時：所有員工「每週上班天數 × 一班工時」加總。
        suggested_total_hours = sum(
            float(employee.get("work_days", 0) or 0)
            * float(employee.get("hours_per_day", 0) or 0)
            for employee in employees
        )

        # 實際總工時只計算一般營業班別，不把 MEETING 算進總人力工時。
        actual_total_hours = sum(
            float(day.get("hours", 0) or 0)
            for employee_result in current_schedule_for_hours
            for day in employee_result.get("days", [])
            if day.get("shift") in {"MORNING", "MIDDLE", "NIGHT"}
        )

        hours_difference = actual_total_hours - suggested_total_hours

        col_hours1, col_hours2 = st.columns(2)
        with col_hours1:
            st.metric(
                "本週建議總工時",
                f"{suggested_total_hours:.1f} 小時",
            )
        with col_hours2:
            st.metric(
                "本週實際排班總工時",
                f"{actual_total_hours:.1f} 小時",
            )

        st.caption("會議工時不列入本週實際排班總工時。")

        if hours_difference > 0.01:
            st.warning(
                f"⚠️ 本週總人力超過建議總工時 "
                f"{hours_difference:.1f} 小時。"
            )
        else:
            st.success(
                f"✅ 本週總人力未超過建議總工時"
                f"（尚有 {abs(hours_difference):.1f} 小時）。"
            )

    st.markdown("### 📚 歷史班表")
    st.caption("歷史班表將保留最近 2 週，並用於跨週七休一、晚接早與偏好檢核。")
