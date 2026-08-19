import copy
import uuid
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
# 永久偏好：Supabase 讀寫
# ============================================================

def load_persistent_preferences(employees):
    preferred_shifts, preferred_days_off, consecutive_off = [], [], []

    for employee in employees:
        employee_id = employee["id"]
        if employee.get("preferred_shift") in ("MORNING", "NIGHT"):
            preferred_shifts.append({
                "employee": employee_id,
                "shift": employee["preferred_shift"],
                "weekday": None,
            })
        if employee.get("prefer_consecutive_off", False):
            consecutive_off.append(employee_id)

    try:
        response = (
            supabase.table("employee_fixed_rules")
            .select("*")
            .eq("rule_type", "PREFERRED_OFF")
            .execute()
        )
        for row in response.data or []:
            if row.get("weekday") is not None:
                preferred_days_off.append({
                    "employee": row["employee_id"],
                    "weekday": int(row["weekday"]),
                })
    except Exception:
        preferred_days_off = []

    different_shift = []
    try:
        response = (
            supabase.table("employee_pair_preferences")
            .select("employee_a,employee_b")
            .eq("preference_type", "DIFFERENT_SHIFT")
            .execute()
        )
        for row in response.data or []:
            a, b = row.get("employee_a"), row.get("employee_b")
            if a and b and a != b:
                different_shift.append({"employees": [a, b]})
    except Exception:
        different_shift = []

    return preferred_shifts, preferred_days_off, consecutive_off, different_shift


def save_preferred_days_off(employee_id, weekdays):
    (
        supabase.table("employee_fixed_rules")
        .delete()
        .eq("employee_id", employee_id)
        .eq("rule_type", "PREFERRED_OFF")
        .execute()
    )
    for weekday in sorted(set(weekdays)):
        (
            supabase.table("employee_fixed_rules")
            .insert({
                "employee_id": employee_id,
                "rule_type": "PREFERRED_OFF",
                "shift": None,
                "weekday": int(weekday),
            })
            .execute()
        )


def save_different_shift_pairs(pairs):
    (
        supabase.table("employee_pair_preferences")
        .delete()
        .eq("preference_type", "DIFFERENT_SHIFT")
        .execute()
    )
    seen = set()
    for rule in pairs:
        pair = rule.get("employees", [])
        if len(pair) != 2 or pair[0] == pair[1]:
            continue
        a, b = sorted(pair)
        if (a, b) in seen:
            continue
        seen.add((a, b))
        (
            supabase.table("employee_pair_preferences")
            .insert({
                "employee_a": a,
                "employee_b": b,
                "preference_type": "DIFFERENT_SHIFT",
            })
            .execute()
        )

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

OPEN_TIME_OPTIONS = [
    f"{minutes // 60:02d}:{minutes % 60:02d}"
    for minutes in range(7 * 60, 11 * 60 + 1, 30)
]

CLOSE_TIME_OPTIONS = [
    f"{minutes // 60:02d}:{minutes % 60:02d}"
    for minutes in range(21 * 60, 24 * 60 + 1, 30)
]

MIDDLE_START_OPTIONS = [
    f"{minutes // 60:02d}:{minutes % 60:02d}"
    for minutes in range(10 * 60, 13 * 60 + 31, 30)
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


def diagnose_infeasible_inputs(
    employees,
    start_date,
    end_date,
    staffing,
    fixed_shifts,
    fixed_days_off,
    assignments,
):
    """針對已知硬限制做可讀性診斷；不修改 solver。"""
    reasons = []
    employee_map = {
        employee["id"]: employee
        for employee in employees
    }
    employee_name = {
        employee["id"]: employee["name"]
        for employee in employees
    }

    dates = [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]

    fixed_shift_map = {
        rule["employee"]: rule["shift"]
        for rule in fixed_shifts
    }

    fixed_off_map = {}
    for rule in fixed_days_off:
        fixed_off_map.setdefault(
            rule["employee"],
            set(),
        ).add(int(rule["weekday"]))

    assignment_map = {}
    for rule in assignments:
        assignment_map[
            (
                rule["employee"],
                rule["date"],
            )
        ] = rule["shift"]

    # 1. 不可減班員工：可排日期不足以達到固定上班天數
    for employee in employees:
        if employee.get("reducible"):
            continue

        forced_off_dates = set()

        for current_date in dates:
            date_text = current_date.isoformat()

            if (
                current_date.weekday()
                in fixed_off_map.get(employee["id"], set())
            ):
                forced_off_dates.add(date_text)

            if assignment_map.get(
                (employee["id"], date_text)
            ) == "OFF":
                forced_off_dates.add(date_text)

        available_days = len(dates) - len(forced_off_dates)
        required_days = int(employee.get("work_days", 0) or 0)

        if available_days < required_days:
            reasons.append(
                f"{employee['name']} 本週設定必須上 {required_days} 天，"
                f"但固定休假 / 排假後最多只剩 {available_days} 天可排。"
            )

    # 2. 固定班和指定班 / 會議互撞
    for rule in assignments:
        employee_id = rule["employee"]
        forced_shift = fixed_shift_map.get(employee_id)

        if (
            forced_shift
            and rule["shift"] not in {"OFF", forced_shift}
        ):
            reasons.append(
                f"{employee_name.get(employee_id, employee_id)} "
                f"{rule['date']} 設定固定"
                f"{SHIFT_DISPLAY.get(forced_shift, forced_shift)}，"
                f"但又指定"
                f"{SHIFT_DISPLAY.get(rule['shift'], rule['shift'])}。"
            )

        try:
            assignment_date = date.fromisoformat(rule["date"])
        except Exception:
            assignment_date = None

        if (
            assignment_date
            and assignment_date.weekday()
            in fixed_off_map.get(employee_id, set())
            and rule["shift"] != "OFF"
        ):
            reasons.append(
                f"{employee_name.get(employee_id, employee_id)} "
                f"{rule['date']} 是固定休假，"
                f"但又指定"
                f"{SHIFT_DISPLAY.get(rule['shift'], rule['shift'])}。"
            )

    # 3. 被硬指定成「晚接早」
    for employee_id in employee_map:
        for idx in range(len(dates) - 1):
            today = dates[idx].isoformat()
            tomorrow = dates[idx + 1].isoformat()

            if (
                assignment_map.get((employee_id, today)) == "NIGHT"
                and assignment_map.get((employee_id, tomorrow))
                == "MORNING"
            ):
                reasons.append(
                    f"{employee_name.get(employee_id, employee_id)} "
                    f"{today} 被指定晚班、{tomorrow} 又被指定早班，"
                    "違反晚班不能接隔日早班。"
                )

    # 4. 早 / 晚班只要有需求，就至少要有一位 FT 可合法排入
    full_time_ids = [
        employee["id"]
        for employee in employees
        if employee.get("employee_type") == "FT"
    ]

    weekday_keys = [
        "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday",
    ]

    for current_date in dates:
        weekday_num = current_date.weekday()
        date_text = current_date.isoformat()
        demand_row = staffing.get(weekday_num, {})

        for shift_code, demand_key, display_name in [
            ("MORNING", "morning", "早班"),
            ("NIGHT", "night", "晚班"),
        ]:
            if int(demand_row.get(demand_key, 0) or 0) <= 0:
                continue

            candidates = []

            for employee_id in full_time_ids:
                assigned = assignment_map.get(
                    (employee_id, date_text)
                )
                fixed_shift = fixed_shift_map.get(employee_id)
                fixed_off = (
                    weekday_num
                    in fixed_off_map.get(employee_id, set())
                )

                if fixed_off:
                    continue

                if assigned == "OFF":
                    continue

                if assigned and assigned != shift_code:
                    continue

                if fixed_shift and fixed_shift != shift_code:
                    continue

                candidates.append(employee_id)

            if not candidates:
                reasons.append(
                    f"{date_text} {display_name}有需求，"
                    "但沒有任何 FT 員工能合法排入。"
                )

    # 去重
    unique_reasons = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    if not unique_reasons:
        unique_reasons.append(
            "目前沒有找到單一明確衝突。較可能是多個硬限制組合後"
            "造成無解，例如固定上班天數、固定班 / 休假、"
            "指定班與晚接早同時壓縮可排組合。"
        )

    return unique_reasons


def audit_schedule(
    schedule,
    preferred_shifts,
    preferred_days_off,
    consecutive_off,
    different_shift,
    previous_schedule=None,
):
    """歷史班表檢核：七休一、晚接早、偏好滿足程度。"""
    previous_schedule = previous_schedule or []
    combined = {}

    for source_schedule in [previous_schedule, schedule]:
        for employee_result in source_schedule:
            employee_id = employee_result.get("employee_id")
            if not employee_id:
                continue

            combined.setdefault(
                employee_id,
                {
                    "name": employee_result.get("name", employee_id),
                    "days": {},
                },
            )

            for day in employee_result.get("days", []):
                combined[employee_id]["days"][day["date"]] = day

    seven_day_violations = []
    night_to_morning = []

    for employee_id, employee_data in combined.items():
        ordered_days = sorted(
            employee_data["days"].values(),
            key=lambda item: item["date"],
        )

        work_run = 0
        last_date = None
        last_shift = None

        for day in ordered_days:
            current_date = date.fromisoformat(day["date"])

            if (
                last_date is not None
                and (current_date - last_date).days != 1
            ):
                work_run = 0
                last_shift = None

            shift = day.get("shift", "OFF")

            if shift == "OFF":
                work_run = 0
            else:
                work_run += 1

            if work_run >= 7:
                seven_day_violations.append(
                    f"{employee_data['name']} 在 {day['date']} "
                    "形成連續 7 天以上上班。"
                )

            if (
                last_shift == "NIGHT"
                and shift == "MORNING"
                and last_date is not None
                and (current_date - last_date).days == 1
            ):
                night_to_morning.append(
                    f"{employee_data['name']}："
                    f"{last_date.isoformat()} 晚班 → "
                    f"{day['date']} 早班"
                )

            last_date = current_date
            last_shift = shift

    # 偏好班別
    preferred_shift_map = {}
    for rule in preferred_shifts:
        preferred_shift_map.setdefault(
            rule.get("employee"),
            set(),
        ).add(rule.get("shift"))

    shift_pref_total = 0
    shift_pref_met = 0

    for employee_result in schedule:
        employee_id = employee_result.get("employee_id")
        wanted = preferred_shift_map.get(employee_id, set())

        if not wanted:
            continue

        for day in employee_result.get("days", []):
            if day.get("shift") in {
                "MORNING", "MIDDLE", "NIGHT"
            }:
                shift_pref_total += 1
                if day.get("shift") in wanted:
                    shift_pref_met += 1

    # 偏好休星期
    preferred_off_map = {}
    for rule in preferred_days_off:
        preferred_off_map.setdefault(
            rule.get("employee"),
            set(),
        ).add(int(rule.get("weekday")))

    off_pref_total = 0
    off_pref_met = 0

    for employee_result in schedule:
        employee_id = employee_result.get("employee_id")
        wanted_days = preferred_off_map.get(employee_id, set())

        if not wanted_days:
            continue

        for day in employee_result.get("days", []):
            if date.fromisoformat(day["date"]).weekday() in wanted_days:
                off_pref_total += 1
                if day.get("shift") == "OFF":
                    off_pref_met += 1

    # 偏好連休
    consecutive_total = 0
    consecutive_met = 0

    for employee_result in schedule:
        employee_id = employee_result.get("employee_id")

        if employee_id not in consecutive_off:
            continue

        consecutive_total += 1
        ordered = sorted(
            employee_result.get("days", []),
            key=lambda item: item["date"],
        )

        has_consecutive_off = any(
            ordered[index].get("shift") == "OFF"
            and ordered[index + 1].get("shift") == "OFF"
            for index in range(len(ordered) - 1)
        )

        if has_consecutive_off:
            consecutive_met += 1

    # 避免同班
    different_total = 0
    different_met = 0

    schedule_by_employee = {
        employee_result.get("employee_id"): {
            day["date"]: day.get("shift")
            for day in employee_result.get("days", [])
        }
        for employee_result in schedule
    }

    for rule in different_shift:
        pair = rule.get("employees", [])
        if len(pair) != 2:
            continue

        employee_a, employee_b = pair
        dates_a = schedule_by_employee.get(employee_a, {})
        dates_b = schedule_by_employee.get(employee_b, {})

        for date_text in set(dates_a) & set(dates_b):
            shift_a = dates_a[date_text]
            shift_b = dates_b[date_text]

            if (
                shift_a in {"MORNING", "MIDDLE", "NIGHT"}
                and shift_b in {"MORNING", "MIDDLE", "NIGHT"}
            ):
                different_total += 1
                if shift_a != shift_b:
                    different_met += 1

    total_opportunities = (
        shift_pref_total
        + off_pref_total
        + consecutive_total
        + different_total
    )
    total_met = (
        shift_pref_met
        + off_pref_met
        + consecutive_met
        + different_met
    )

    preference_percent = (
        round(total_met / total_opportunities * 100, 1)
        if total_opportunities
        else 100.0
    )

    return {
        "preference_percent": preference_percent,
        "preference_met": total_met,
        "preference_total": total_opportunities,
        "seven_day_violations": seven_day_violations,
        "night_to_morning": night_to_morning,
    }

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

if any(
    key not in ss
    for key in (
        "preferred_shifts",
        "preferred_days_off",
        "consecutive_off",
        "different_shift",
    )
):
    (
        ss.preferred_shifts,
        ss.preferred_days_off,
        ss.consecutive_off,
        ss.different_shift,
    ) = load_persistent_preferences(ss.employees)

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
    
    leave_note = st.text_area(
        "備註（選填）",
        placeholder="例如：短會議、特殊需求、人工排班提醒。此欄不參與自動排班計算。",
        key="leave_note",
        height=80,
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
                "note": leave_note.strip() or None,
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
    
    selected_employee_name = employee_name_map.get(employee_id, employee_id)
    st.subheader(f"📋 {selected_employee_name} 的排假紀錄")
    st.caption(f"目前選擇員工：{selected_employee_name}")
    
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
            f"{selected_employee_name}｜"
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

            if record.get("note"):
                st.write(f"備註：{record['note']}")
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
            
            edit_note = st.text_area(
                "修改備註（選填）",
                value=record.get("note") or "",
                key=f"edit_note_{record['id']}",
                height=80,
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
                        "note": edit_note.strip() or None,
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
    
            note_text = (
                f"｜📝 {item['note']}"
                if item.get("note")
                else ""
            )

            st.write(
                f"👤 **{person_name}**｜{type_text}{extra_text}{note_text}"
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

        # Supabase 是員工主資料來源；避免刪除後畫面仍拿舊 session_state。
        ss.employees = load_employees()
        valid_employee_ids_now = {
            employee["id"] for employee in ss.employees
        }
        if (
            ss.get("delete_employee_id") is not None
            and ss.get("delete_employee_id") not in valid_employee_ids_now
        ):
            ss.pop("delete_employee_id", None)
            ss.pop("confirm_delete_employee", None)
        # ============================================================
        # 2. 人員設定
        # ============================================================
        
        st.header("👥 人員設定")
        
        st.caption(
            "姓名、FT/PT、藥師、成熟人力、可減班、上班天數與工時皆可修改。"
        )
        
        employees = []
        
        employee_display_no = {
            employee["id"]: f"{display_no:02d}"
            for display_no, employee in enumerate(ss.employees, start=1)
        }

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
                f"{employee_display_no.get(employee['id'], f'{i + 1:02d}')}｜{employee['name']}",
                expanded=False,
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
                    "preferred_shift": (
                        "MORNING" if prefer_morning
                        else "NIGHT" if prefer_night
                        else None
                    ),
                    "prefer_consecutive_off": bool(prefer_consecutive),
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
        
        with st.expander("➕ 新增員工", expanded=False):
            st.caption(
                "員工編號 01/02/03… 由畫面自動排序；"
                "後台使用隱藏固定 ID，所以姓名可以正常修改。"
            )
            new_name = st.text_input("員工姓名", key="new_name")

            if st.button("新增員工", key="add_employee", use_container_width=True):
                if not new_name.strip():
                    st.warning("請填寫員工姓名")
                else:
                    try:
                        internal_employee_id = "EMP_" + uuid.uuid4().hex[:10].upper()
                        supabase.table("employees").insert({
                            "employee_id": internal_employee_id,
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
            if not employee_ids:
                st.info("目前沒有可刪除的員工。")
                delete_employee_id = None
            else:
                delete_employee_id = st.selectbox(
                    "選擇要刪除的員工",
                    employee_ids,
                    format_func=lambda employee_id: (
                        f"{employee_display_no.get(employee_id, '')}｜"
                        f"{employee_name_map.get(employee_id, employee_id)}"
                    ),
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
        
                        supabase.table("leave_requests").delete().eq(
                            "employee_id", delete_employee_id
                        ).execute()
                        supabase.table("employee_fixed_rules").delete().eq(
                            "employee_id", delete_employee_id
                        ).execute()
                        supabase.table("employees").delete().eq(
                            "employee_id", delete_employee_id
                        ).execute()

                        ss.meetings = [
                            item for item in ss.meetings
                            if item.get("employee") != delete_employee_id
                        ]
                        ss.preferred_shifts = [
                            item for item in ss.preferred_shifts
                            if item.get("employee") != delete_employee_id
                        ]
                        ss.preferred_days_off = [
                            item for item in ss.preferred_days_off
                            if item.get("employee") != delete_employee_id
                        ]
                        ss.consecutive_off = [
                            employee_id for employee_id in ss.consecutive_off
                            if employee_id != delete_employee_id
                        ]
                        ss.different_shift = [
                            item for item in ss.different_shift
                            if delete_employee_id not in item.get("employees", [])
                        ]
                        ss.assignments = [
                            item for item in ss.assignments
                            if item.get("employee") != delete_employee_id
                        ]
                        ss.fixed_shifts = [
                            item for item in ss.fixed_shifts
                            if item.get("employee") != delete_employee_id
                        ]
                        ss.fixed_days_off = [
                            item for item in ss.fixed_days_off
                            if item.get("employee") != delete_employee_id
                        ]
                        ss.pop("schedule_result", None)
                        ss.pop("manual_schedule", None)

                        ss.employees = load_employees()
                        ss.pop("delete_employee_id", None)
                        ss.pop("confirm_delete_employee", None)

                        (
                            ss.preferred_shifts,
                            ss.preferred_days_off,
                            ss.consecutive_off,
                            ss.different_shift,
                        ) = load_persistent_preferences(ss.employees)

                        st.success(
                            f"✅ 已刪除 {delete_employee['name']} 與相關設定"
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
        
                for employee in employees:
                    employee_preferred_off = [
                        int(rule["weekday"])
                        for rule in ss.preferred_days_off
                        if rule.get("employee") == employee["id"]
                        and rule.get("weekday") is not None
                    ]
                    save_preferred_days_off(
                        employee["id"],
                        employee_preferred_off,
                    )

                ss.employees = load_employees()
                (
                    ss.preferred_shifts,
                    ss.preferred_days_off,
                    ss.consecutive_off,
                    ss.different_shift,
                ) = load_persistent_preferences(ss.employees)
                st.success("✅ 員工資料與偏好已永久儲存")
                st.rerun()
        
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

            if default_start not in OPEN_TIME_OPTIONS:
                default_start = fallback_start
            if default_end not in CLOSE_TIME_OPTIONS:
                default_end = fallback_end
        
            st.subheader(day_name)
        
            col_start, col_end = st.columns(2)
        
            with col_start:
                day_start = st.selectbox(
                    "開始營業",
                    OPEN_TIME_OPTIONS,
                    index=OPEN_TIME_OPTIONS.index(default_start),
                    key=f"{day_key}_start",
                )
        
            with col_end:
                day_end = st.selectbox(
                    "結束營業",
                    CLOSE_TIME_OPTIONS,
                    index=CLOSE_TIME_OPTIONS.index(default_end),
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
        
        if saved_middle_start not in MIDDLE_START_OPTIONS:
            saved_middle_start = "12:00"
        
        middle_start = st.selectbox(
            "中班開始時間",
            MIDDLE_START_OPTIONS,
            index=MIDDLE_START_OPTIONS.index(saved_middle_start),
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

                note_text = (
                    f"｜📝 {item['note']}"
                    if item.get("note")
                    else ""
                )

                st.write(
                    f"📅 {item['request_date']}｜"
                    f"👤 {employee_name}｜"
                    f"{request_text}{extra_text}{note_text}"
                )

        st.divider()
              
        # --------------------------------------------------------
        with st.expander("📣 會議", expanded=False):
            st.caption("會議算上班。需要新增或修改時再展開。")

            meeting_delete = None

            current_week_meetings = [
                (i, meeting)
                for i, meeting in enumerate(ss.meetings)
                if (
                    meeting.get("employee") in employee_ids
                    and start_date <= meeting.get("date") <= end_date
                )
            ]

            for i, meeting in current_week_meetings:
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
                note_marker = (
                    "｜📝 有備註"
                    if item.get("note")
                    else ""
                )

                with st.expander(
                    f"{item['request_date']}｜{employee_label}｜{request_label}{note_marker}",
                    expanded=False,
                ):
                    if item.get("note"):
                        st.write(f"備註：{item['note']}")
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

            manager_leave_note = st.text_area(
                "店長備註（選填）",
                placeholder="例如：短會議、人工排班提醒。此欄不參與自動排班計算。",
                key="manager_leave_note",
                height=80,
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
                            "note": manager_leave_note.strip() or None,
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
                format_func=lambda employee_id: employee_name_map.get(
                    employee_id, employee_id
                ),
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
                format_func=lambda employee_id: employee_name_map.get(
                    employee_id, employee_id
                ),
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

        st.markdown("### ⏱️ 本週建議總工時")

        default_recommended_total_hours = sum(
            float(employee.get("work_days", 0) or 0)
            * float(employee.get("hours_per_day", 0) or 0)
            for employee in employees
        )
        saved_recommended_total_hours = default_recommended_total_hours
        weekly_settings_available = True

        try:
            weekly_settings_response = (
                supabase.table("weekly_settings")
                .select("*")
                .eq("week_start", summary_start.isoformat())
                .limit(1)
                .execute()
            )
            if weekly_settings_response.data:
                saved_recommended_total_hours = float(
                    weekly_settings_response.data[0]["recommended_total_hours"]
                )
        except Exception:
            weekly_settings_available = False

        weekly_recommended_total_hours = st.number_input(
            "本週建議總工時（不含會議）",
            min_value=0.0,
            max_value=1000.0,
            value=float(saved_recommended_total_hours),
            step=0.5,
            key=f"weekly_recommended_hours_{summary_start.isoformat()}",
        )

        if st.button(
            "💾 儲存本週建議總工時",
            key=f"save_weekly_hours_{summary_start.isoformat()}",
            use_container_width=True,
        ):
            if not weekly_settings_available:
                st.error(
                    "❌ 尚未建立 weekly_settings 資料表。"
                    "請先執行 weekly_settings_setup.sql。"
                )
            else:
                try:
                    supabase.table("weekly_settings").upsert(
                        {
                            "week_start": summary_start.isoformat(),
                            "recommended_total_hours": float(
                                weekly_recommended_total_hours
                            ),
                        },
                        on_conflict="week_start",
                    ).execute()
                    st.success("✅ 本週建議總工時已儲存")
                except Exception as error:
                    st.error("❌ 儲存本週建議總工時失敗")
                    st.exception(error)

        if not weekly_settings_available:
            st.caption(
                "目前先顯示依員工設定自動計算的值；"
                "建立 weekly_settings 後可每週獨立保存。"
            )

        st.divider()

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

                # 人力需求一旦修改，舊班表與舊的「實際 / 需求」已失效。
                # 清除舊結果，避免畫面繼續顯示上一輪需求，造成看起來像 solver 沒吃到新設定。
                for stale_key in (
                    "schedule_result",
                    "manual_schedule",
                    "schedule_requirements",
                    "last_schedule_inputs",
                ):
                    ss.pop(stale_key, None)

                st.success("✅ 本週人力配置已儲存；請到『生成班表』重新排班。")
                st.rerun()

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

    cleaned_different_shift = []
    seen_pairs = set()
    for rule in ss.different_shift:
        pair = [
            employee_id
            for employee_id in rule.get("employees", [])
            if employee_id in employee_ids
        ]
        if len(pair) != 2 or pair[0] == pair[1]:
            continue
        pair_key = tuple(sorted(pair))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        cleaned_different_shift.append({"employees": pair})
    ss.different_shift = cleaned_different_shift

    with st.expander("↔️ 兩人避免同班", expanded=False):
        if ss.different_shift:
            st.markdown("**目前已儲存：**")
            for rule in ss.different_shift:
                a, b = rule["employees"]
                st.write(
                    f"• {employee_name_map.get(a, a)} ↔ "
                    f"{employee_name_map.get(b, b)}"
                )
        else:
            st.info("目前沒有避免同班設定。")

        different_delete = None
        for i, rule in enumerate(ss.different_shift):
            current_a, current_b = rule["employees"]
            with st.expander(
                f"{employee_name_map.get(current_a, current_a)} ↔ "
                f"{employee_name_map.get(current_b, current_b)}",
                expanded=False,
            ):
                employee_a = st.selectbox(
                    "人員 A", employee_ids,
                    index=safe_index(employee_ids, current_a),
                    format_func=lambda employee_id: employee_name_map.get(
                        employee_id, employee_id
                    ),
                    key=f"different_a_{i}",
                )
                available_b = [
                    employee_id for employee_id in employee_ids
                    if employee_id != employee_a
                ]
                employee_b = st.selectbox(
                    "人員 B", available_b,
                    index=safe_index(available_b, current_b),
                    format_func=lambda employee_id: employee_name_map.get(
                        employee_id, employee_id
                    ),
                    key=f"different_b_{i}",
                )
                col_save, col_delete = st.columns(2)
                with col_save:
                    if st.button(
                        "💾 儲存", key=f"save_different_{i}",
                        use_container_width=True,
                    ):
                        key_pair = tuple(sorted([employee_a, employee_b]))
                        duplicate = any(
                            j != i and tuple(sorted(item["employees"])) == key_pair
                            for j, item in enumerate(ss.different_shift)
                        )
                        if duplicate:
                            st.warning("⚠️ 這組避免同班已存在，不會重複新增。")
                        else:
                            ss.different_shift[i] = {
                                "employees": [employee_a, employee_b]
                            }
                            save_different_shift_pairs(ss.different_shift)
                            st.success("✅ 已永久儲存避免同班設定")
                            st.rerun()
                with col_delete:
                    if st.button(
                        "🗑️ 刪除", key=f"delete_different_{i}",
                        use_container_width=True,
                    ):
                        different_delete = i

        if different_delete is not None:
            ss.different_shift.pop(different_delete)
            try:
                save_different_shift_pairs(ss.different_shift)
                st.rerun()
            except Exception as error:
                st.error("❌ 刪除避免同班失敗")
                st.exception(error)

        with st.expander("＋ 新增避免同班", expanded=False):
            if len(employee_ids) >= 2:
                new_a = st.selectbox(
                    "人員 A", employee_ids,
                    format_func=lambda employee_id: employee_name_map.get(
                        employee_id, employee_id
                    ),
                    key="new_different_a",
                )
                new_b_options = [
                    employee_id for employee_id in employee_ids
                    if employee_id != new_a
                ]
                new_b = st.selectbox(
                    "人員 B", new_b_options,
                    format_func=lambda employee_id: employee_name_map.get(
                        employee_id, employee_id
                    ),
                    key="new_different_b",
                )
                if st.button(
                    "💾 儲存新組合", key="save_new_different",
                    use_container_width=True, type="primary",
                ):
                    key_pair = tuple(sorted([new_a, new_b]))
                    duplicate = any(
                        tuple(sorted(item["employees"])) == key_pair
                        for item in ss.different_shift
                    )
                    if duplicate:
                        st.warning("⚠️ 這組避免同班已存在，不會重複新增。")
                    else:
                        ss.different_shift.append({
                            "employees": [new_a, new_b]
                        })
                        try:
                            save_different_shift_pairs(ss.different_shift)
                            st.success("✅ 已永久新增避免同班設定")
                            st.rerun()
                        except Exception as error:
                            ss.different_shift.pop()
                            st.error("❌ 儲存避免同班失敗，請先執行 Supabase SQL migration")
                            st.exception(error)
            else:
                st.warning("至少需要兩位員工。")



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

        # ========================================================
        # 10-6-1 讀取緊鄰上一週歷史，供跨週晚接早 / 七休一
        # ========================================================
        previous_schedule_payload = []

        try:
            previous_history_response = (
                supabase.table("schedule_history")
                .select("week_start,week_end,schedule_json")
                .lt("week_start", start_date.isoformat())
                .order("week_start", desc=True)
                .limit(1)
                .execute()
            )

            if previous_history_response.data:
                previous_row = previous_history_response.data[0]

                if (
                    date.fromisoformat(previous_row["week_end"])
                    + timedelta(days=1)
                    == start_date
                ):
                    for employee_result in (
                        previous_row.get("schedule_json") or []
                    ):
                        employee_id = employee_result.get("employee_id")

                        if not employee_id:
                            continue

                        for day in employee_result.get("days", []):
                            if day.get("date") and day.get("shift"):
                                previous_schedule_payload.append({
                                    "employee": employee_id,
                                    "date": day["date"],
                                    "shift": day["shift"],
                                })
        except Exception as error:
            errors.append(
                f"無法讀取上一週歷史班表，跨週限制無法安全檢查：{error}"
            )

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

            "previous_schedule":
                previous_schedule_payload,
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

                ss.last_schedule_inputs = {
                    "employees": copy.deepcopy(employees),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "staffing": copy.deepcopy(
                        weekly_staffing_for_schedule
                    ),
                    "fixed_shifts": copy.deepcopy(
                        fixed_shifts_payload
                    ),
                    "fixed_days_off": copy.deepcopy(
                        fixed_days_off_payload
                    ),
                    "assignments": copy.deepcopy(
                        assignments_payload
                    ),
                    "previous_schedule": copy.deepcopy(
                        previous_schedule_payload
                    ),
                }

                # 保存這次「實際送進 Solver」的人力需求。
                # 不論成功或失敗都保留，方便核對資料鏈。
                ss.schedule_requirements = {
                    weekday_num: dict(values)
                    for weekday_num, values
                    in weekly_staffing_for_schedule.items()
                }

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
        # 除錯資訊（正式畫面預設收合）
        # ========================================================
        solver_requirements = ss.get(
            "schedule_requirements",
            {}
        )

        if solver_requirements:
            with st.expander(
                "🔧 除錯資訊",
                expanded=False,
            ):
                st.caption(
                    "以下僅供核對 Solver 實際收到的資料，"
                    "不影響正式排班計算。"
                )

                if result.get("scheduler_build"):
                    st.write(
                        f"Solver 版本：{result['scheduler_build']}"
                    )

                st.markdown(
                    "**本次送入 Solver 的人力需求**"
                )

                solver_requirement_rows = []

                for weekday_num in range(7):
                    current_day = start_date + timedelta(
                        days=weekday_num
                    )
                    values = solver_requirements.get(
                        weekday_num,
                        {}
                    )

                    solver_requirement_rows.append({
                        "日期": current_day.strftime("%m/%d"),
                        "早": int(values.get("morning", 0)),
                        "中": int(values.get("middle", 0)),
                        "晚": int(values.get("night", 0)),
                    })

                st.dataframe(
                    solver_requirement_rows,
                    use_container_width=True,
                    hide_index=True,
                )

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

            st.caption(
                "人數需求本身允許以『缺口』處理；"
                "但早班需求只要 > 0，就仍有『至少 1 位 FT』硬限制，"
                "晚班需求只要 > 0 也一樣。"
                "因此把需求從 3 改成 1 不一定會解除 INFEASIBLE；"
                "要測 FT 硬限制是否解除，該班需求需設為 0。"
            )

            if result.get("scheduler_build"):
                st.caption(
                    f"Solver 版本：{result['scheduler_build']}"
                )

            st.markdown("### 🔎 無解原因診斷")

            solver_diagnostics = (
                result.get("diagnostics")
                or []
            )

            if solver_diagnostics:
                for reason in solver_diagnostics:
                    st.write(f"• {reason}")

                st.caption(
                    "以上由後端只含硬限制的 CP-SAT 診斷模型產生。"
                    "診斷只用來找出造成無解的硬限制組合，不會修改正式班表計算。"
                )
            else:
                last_inputs = ss.get("last_schedule_inputs")

                if last_inputs:
                    st.info(
                        "⚠️ 後端沒有回傳精準 diagnostics，以下為前端備援診斷。"
                    )

                    diagnostic_reasons = diagnose_infeasible_inputs(
                        employees=last_inputs["employees"],
                        start_date=date.fromisoformat(
                            last_inputs["start_date"]
                        ),
                        end_date=date.fromisoformat(
                            last_inputs["end_date"]
                        ),
                        staffing=last_inputs["staffing"],
                        fixed_shifts=last_inputs["fixed_shifts"],
                        fixed_days_off=last_inputs["fixed_days_off"],
                        assignments=last_inputs["assignments"],
                    )

                    for reason in diagnostic_reasons:
                        st.write(f"• {reason}")


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

            if result.get("scheduler_build"):
                st.caption(
                    f"Solver 版本：{result['scheduler_build']}"
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

        # 使用店長針對該週設定的建議總工時。
        suggested_total_hours = float(weekly_recommended_total_hours)

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
    st.caption(
        "正式儲存後保留最近 2 週。歷史檢核包含偏好滿足程度、"
        "七休一與跨週晚接早。"
    )

    history_table_available = True

    try:
        history_response = (
            supabase.table("schedule_history")
            .select("*")
            .order("week_start", desc=True)
            .limit(10)
            .execute()
        )
        history_rows = history_response.data or []
    except Exception:
        history_table_available = False
        history_rows = []

    if "schedule_result" in ss and ss.schedule_result.get("success"):
        current_schedule_for_history = ss.get(
            "manual_schedule",
            ss.schedule_result.get("schedule", []),
        )

        if st.button(
            "✅ 確認並正式儲存本週班表",
            key=f"save_official_schedule_{start_date.isoformat()}",
            use_container_width=True,
            type="primary",
        ):
            if not history_table_available:
                st.error(
                    "❌ 尚未建立 schedule_history 資料表。"
                    "請先執行我提供的 schedule_history_setup.sql。"
                )
            else:
                try:
                    previous_history_response = (
                        supabase.table("schedule_history")
                        .select("week_start,week_end,schedule_json")
                        .lt("week_start", start_date.isoformat())
                        .order("week_start", desc=True)
                        .limit(1)
                        .execute()
                    )

                    previous_schedule = []

                    if previous_history_response.data:
                        previous_row = previous_history_response.data[0]

                        if (
                            date.fromisoformat(
                                previous_row["week_end"]
                            )
                            + timedelta(days=1)
                            == start_date
                        ):
                            previous_schedule = (
                                previous_row.get("schedule_json")
                                or []
                            )

                    audit_result = audit_schedule(
                        schedule=current_schedule_for_history,
                        preferred_shifts=ss.preferred_shifts,
                        preferred_days_off=ss.preferred_days_off,
                        consecutive_off=ss.consecutive_off,
                        different_shift=ss.different_shift,
                        previous_schedule=previous_schedule,
                    )

                    requirements_for_history = ss.get(
                        "schedule_requirements",
                        {},
                    )

                    current_deficits = []

                    for weekday_num in range(7):
                        current_day = (
                            start_date
                            + timedelta(days=weekday_num)
                        )
                        day_text = current_day.isoformat()

                        for shift_code, req_key in [
                            ("MORNING", "morning"),
                            ("MIDDLE", "middle"),
                            ("NIGHT", "night"),
                        ]:
                            actual = sum(
                                1
                                for employee_result
                                in current_schedule_for_history
                                for day
                                in employee_result.get("days", [])
                                if (
                                    day.get("date") == day_text
                                    and day.get("shift")
                                    == shift_code
                                )
                            )

                            required = int(
                                requirements_for_history
                                .get(weekday_num, {})
                                .get(req_key, 0)
                            )

                            if actual < required:
                                current_deficits.append({
                                    "date": day_text,
                                    "shift": shift_code,
                                    "deficit": required - actual,
                                })

                    official_actual_hours = sum(
                        float(day.get("hours", 0) or 0)
                        for employee_result
                        in current_schedule_for_history
                        for day
                        in employee_result.get("days", [])
                        if day.get("shift")
                        in {"MORNING", "MIDDLE", "NIGHT"}
                    )

                    supabase.table("schedule_history").upsert(
                        {
                            "week_start": start_date.isoformat(),
                            "week_end": end_date.isoformat(),
                            "schedule_json": current_schedule_for_history,
                            "audit_json": audit_result,
                            "deficits_json": current_deficits,
                            "recommended_total_hours": float(
                                weekly_recommended_total_hours
                            ),
                            "actual_total_hours": float(
                                official_actual_hours
                            ),
                        },
                        on_conflict="week_start",
                    ).execute()

                    # 只保留最近兩週
                    saved_rows = (
                        supabase.table("schedule_history")
                        .select("week_start")
                        .order("week_start", desc=True)
                        .execute()
                    ).data or []

                    for old_row in saved_rows[2:]:
                        supabase.table("schedule_history").delete().eq(
                            "week_start",
                            old_row["week_start"],
                        ).execute()

                    st.success("✅ 本週班表已正式儲存")
                    st.rerun()

                except Exception as error:
                    st.error("❌ 正式儲存班表失敗")
                    st.exception(error)

    if history_table_available:
        history_rows = (
            supabase.table("schedule_history")
            .select("*")
            .order("week_start", desc=True)
            .limit(2)
            .execute()
        ).data or []

        if not history_rows:
            st.info("目前沒有正式歷史班表。")

        for history_row in history_rows:
            audit = history_row.get("audit_json") or {}
            week_start_text = history_row["week_start"]
            week_end_text = history_row["week_end"]

            with st.expander(
                f"📅 {week_start_text} ～ {week_end_text}",
                expanded=False,
            ):
                col_a, col_b, col_c = st.columns(3)

                with col_a:
                    st.metric(
                        "偏好滿足",
                        f"{float(audit.get('preference_percent', 100)):.1f}%",
                    )

                with col_b:
                    st.metric(
                        "建議總工時",
                        f"{float(history_row.get('recommended_total_hours', 0)):.1f}",
                    )

                with col_c:
                    st.metric(
                        "實際總工時",
                        f"{float(history_row.get('actual_total_hours', 0)):.1f}",
                    )

                seven_day = audit.get(
                    "seven_day_violations",
                    [],
                )
                night_morning = audit.get(
                    "night_to_morning",
                    [],
                )

                if seven_day:
                    st.error("⚠️ 七休一檢核異常")
                    for item in seven_day:
                        st.write(f"• {item}")
                else:
                    st.success("✅ 七休一檢核通過")

                if night_morning:
                    st.error("⚠️ 晚接早檢核異常")
                    for item in night_morning:
                        st.write(f"• {item}")
                else:
                    st.success("✅ 晚接早檢核通過")

                historical_schedule = (
                    history_row.get("schedule_json")
                    or []
                )

                history_table_rows = []

                for employee_result in historical_schedule:
                    row = {
                        "人員": employee_result.get(
                            "name",
                            employee_result.get("employee_id"),
                        )
                    }

                    for day in employee_result.get("days", []):
                        day_date = date.fromisoformat(day["date"])
                        shift = day.get("shift", "OFF")

                        if shift == "OFF":
                            display = "休假"
                        elif shift == "MEETING":
                            display = "會議"
                        else:
                            display = (
                                f"{SHIFT_DISPLAY.get(shift, shift)} "
                                f"{day.get('start_time') or ''}-"
                                f"{day.get('end_time') or ''}"
                            ).strip("-")

                        row[
                            day_date.strftime("%m/%d")
                        ] = display

                    row["總工時"] = employee_result.get(
                        "total_hours",
                        0,
                    )
                    history_table_rows.append(row)

                st.dataframe(
                    history_table_rows,
                    use_container_width=True,
                    hide_index=True,
                )

                if st.button(
                    "🗑️ 刪除此週歷史班表",
                    key=f"delete_history_{week_start_text}",
                    use_container_width=True,
                ):
                    supabase.table("schedule_history").delete().eq(
                        "week_start",
                        week_start_text,
                    ).execute()
                    st.success("✅ 歷史班表已刪除")
                    st.rerun()

        if history_rows:
            with st.expander("⚠️ 清除測試歷史資料", expanded=False):
                confirm_clear_history = st.checkbox(
                    "我確認要清除全部歷史班表",
                    key="confirm_clear_all_history",
                )

                if st.button(
                    "🗑️ 清空全部歷史班表",
                    key="clear_all_history",
                    disabled=not confirm_clear_history,
                    use_container_width=True,
                ):
                    for history_row in history_rows:
                        supabase.table("schedule_history").delete().eq(
                            "week_start",
                            history_row["week_start"],
                        ).execute()

                    st.success("✅ 歷史班表已清空")
                    st.rerun()
    else:
        st.info(
            "歷史班表功能尚未建立資料表。"
            "執行 schedule_history_setup.sql 後即可使用。"
        )
