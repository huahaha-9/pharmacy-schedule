from datetime import date, timedelta
from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

from backend.models import ScheduleRequest


# ============================================================
# 班別常數
# ============================================================

OFF = "OFF"
MORNING = "MORNING"
MIDDLE = "MIDDLE"
NIGHT = "NIGHT"
MEETING = "MEETING"

SHIFTS = [
    OFF,
    MORNING,
    MIDDLE,
    NIGHT,
    MEETING,
]


# ============================================================
# 權重
# ============================================================

WEIGHTS = {
    "coverage_deficit": 10000,
    "senior_present": 200,
    "pharmacist_cap": 300,
    "pharmacist_daily": 300,
    "night_ph_senior": 100,
    "preferred_shift": 20,
    "preferred_day_off": 30,
    "different_shift": 50,
    "consecutive_off": 10,
}


# ============================================================
# 時間工具
# ============================================================

def time_to_minutes(time_str: str) -> int:
    hour, minute = map(int, time_str.split(":"))
    return hour * 60 + minute


def minutes_to_time(minutes: int) -> str:
    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"


def calculate_shift_time(
    shift: str,
    business_start: str,
    business_end: str,
    middle_start: str,
    hours_per_day: float,
):
    """
    早班：
        營業開始 → 完成個人工時

    中班：
        中班設定時間 → 完成個人工時

    晚班：
        營業結束往前回推個人工時
    """

    work_minutes = int(hours_per_day * 60)

    business_start_minutes = time_to_minutes(
        business_start
    )

    business_end_minutes = time_to_minutes(
        business_end
    )

    middle_start_minutes = time_to_minutes(
        middle_start
    )

    if shift == MORNING:

        start = business_start_minutes
        end = start + work_minutes

    elif shift == MIDDLE:

        start = middle_start_minutes
        end = start + work_minutes

    elif shift == NIGHT:

        end = business_end_minutes
        start = end - work_minutes

    else:

        return {
            "start_time": None,
            "end_time": None,
            "hours": 0,
        }

    return {
        "start_time": minutes_to_time(start),
        "end_time": minutes_to_time(end),
        "hours": work_minutes / 60,
    }


# ============================================================
# 日期
# ============================================================

def get_dates(
    start_date: str,
    end_date: str,
) -> List[str]:

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    if end < start:
        raise ValueError(
            "end_date 不能早於 start_date"
        )

    result = []

    current = start

    while current <= end:

        result.append(
            current.isoformat()
        )

        current += timedelta(days=1)

    return result


# ============================================================
# 人員分類
# ============================================================

def get_employee_groups(
    request: ScheduleRequest
):

    employee_ids = [
        employee.id
        for employee in request.employees
    ]

    fts = [
        employee.id
        for employee in request.employees
        if employee.employee_type == "FT"
    ]

    pharmacists = [
        employee.id
        for employee in request.employees
        if employee.is_pharmacist
    ]

    senior_staff = [
        employee.id
        for employee in request.employees
        if employee.is_senior
    ]

    reducible_staff = [
        employee.id
        for employee in request.employees
        if employee.reducible
    ]

    return {
        "employees": employee_ids,
        "fts": fts,
        "pharmacists": pharmacists,
        "senior_staff": senior_staff,
        "reducible_staff": reducible_staff,
    }


# ============================================================
# 每日需求
# ============================================================

def build_demand(
    request: ScheduleRequest,
    dates: List[str],
) -> Dict[Tuple[str, str], int]:

    demand = {}

    demand_by_weekday = [
        request.shifts.demand.monday,
        request.shifts.demand.tuesday,
        request.shifts.demand.wednesday,
        request.shifts.demand.thursday,
        request.shifts.demand.friday,
        request.shifts.demand.saturday,
        request.shifts.demand.sunday,
    ]

    for current_date in dates:

        current = date.fromisoformat(current_date)
        day_demand = demand_by_weekday[current.weekday()]

        demand[
            current_date,
            MORNING
        ] = day_demand.morning

        demand[
            current_date,
            MIDDLE
        ] = day_demand.middle

        demand[
            current_date,
            NIGHT
        ] = day_demand.night
        meeting_count = sum(
            meeting.staff_count
            for meeting in request.meetings
            if meeting.date == current_date
        )

        demand[
            current_date,
            MEETING
        ] = meeting_count
    return demand


# ============================================================
# OR-Tools 變數
# ============================================================

def create_variables(
    model,
    request: ScheduleRequest,
    dates: List[str],
):

    employee_ids = [
        employee.id
        for employee in request.employees
    ]

    x = {}

    for employee in employee_ids:

        for current_date in dates:

            for shift in SHIFTS:

                x[
                    employee,
                    current_date,
                    shift
                ] = model.NewBoolVar(
                    f"x_{employee}_{current_date}_{shift}"
                )

    # 每人每天只能有一個班別
    for employee in employee_ids:

        for current_date in dates:

            model.AddExactlyOne(
                x[
                    employee,
                    current_date,
                    shift
                ]
                for shift in SHIFTS
            )

    return x


# ============================================================
# 硬性限制
# ============================================================

def add_hard_constraints(
    model,
    x,
    request: ScheduleRequest,
    dates: List[str],
    demand,
):

    groups = get_employee_groups(request)

    employee_ids = groups["employees"]
    fts = groups["fts"]

    # --------------------------------------------------------
    # 1. 上班天數
    # --------------------------------------------------------

    for employee in request.employees:

        work_count = sum(
            1 - x[
                employee.id,
                current_date,
                OFF
            ]
            for current_date in dates
        )

        # 正式排假（AssignmentRule shift == OFF）會降低該週應上班天數。
        # 例如原設定 5 天，本週正式排假 3 天 -> 本週目標 2 天。
        # 固定休假不在這裡扣除；固定休假仍維持原本的硬限制語意。
        leave_dates = {
            rule.date
            for rule in request.assignments
            if (
                rule.employee == employee.id
                and rule.shift == OFF
                and rule.date in dates
            )
        }

        effective_work_days = max(
            0,
            employee.work_days - len(leave_dates),
        )

        # 可減班人員：
        # 排假後不可超過調整後的上班天數
        if employee.reducible:

            model.Add(
                work_count <= effective_work_days
            )

        # 不可減班：
        # 排假後上班天數固定為調整後的目標
        else:

            model.Add(
                work_count == effective_work_days
            )

    # --------------------------------------------------------
    # 2. 晚班不能接隔天早班
    # --------------------------------------------------------

    for employee in employee_ids:

        for index in range(
            len(dates) - 1
        ):

            today = dates[index]
            tomorrow = dates[index + 1]

            model.AddBoolOr([
                x[
                    employee,
                    today,
                    NIGHT
                ].Not(),

                x[
                    employee,
                    tomorrow,
                    MORNING
                ].Not(),
            ])

            # --------------------------------------------------------
        # 3. 固定班別
        # --------------------------------------------------------
        # 員工上班時只能排指定班別，但仍可正常休假
    
        for rule in request.fixed_shifts:
    
            if rule.employee not in employee_ids:
                continue
    
            for current_date in dates:
    
                for shift in [MORNING, MIDDLE, NIGHT, MEETING]:
    
                    if shift != rule.shift:
                        model.Add(
                            x[
                                rule.employee,
                                current_date,
                                shift
                            ] == 0
                        )
    
            

    # --------------------------------------------------------
    # 4. 固定休星期
    # --------------------------------------------------------

    for rule in request.fixed_days_off:

        if rule.employee not in employee_ids:
            continue

        for current_date in dates:

            weekday = date.fromisoformat(
                current_date
            ).weekday()

            if weekday == rule.weekday:

                model.Add(
                    x[
                        rule.employee,
                        current_date,
                        OFF
                    ] == 1
                )

    # --------------------------------------------------------
    # 5. 指定排假 / 指定班
    # --------------------------------------------------------

    for rule in request.assignments:

        if rule.employee not in employee_ids:
            continue

        if rule.date not in dates:
            continue

        model.Add(
            x[
                rule.employee,
                rule.date,
                rule.shift
            ] == 1
        )

    # --------------------------------------------------------
    # 6. 早班至少一位 FT
    # --------------------------------------------------------

    for current_date in dates:

        if demand[
            current_date,
            MORNING
        ] > 0:

            model.Add(
                sum(
                    x[
                        employee,
                        current_date,
                        MORNING
                    ]
                    for employee in fts
                ) >= 1
            )

    # --------------------------------------------------------
    # 7. 晚班至少一位 FT
    # --------------------------------------------------------

    for current_date in dates:

        if demand[
            current_date,
            NIGHT
        ] > 0:

            model.Add(
                sum(
                    x[
                        employee,
                        current_date,
                        NIGHT
                    ]
                    for employee in fts
                ) >= 1
            )

    # --------------------------------------------------------
    # 8. 沒有會議就不能排會議班
    # --------------------------------------------------------

    for current_date in dates:

        if demand[
            current_date,
            MEETING
        ] == 0:

            for employee in employee_ids:

                model.Add(
                    x[
                        employee,
                        current_date,
                        MEETING
                    ] == 0
                )


# ============================================================
# 軟性限制
# ============================================================

def add_soft_constraints(
    model,
    x,
    request: ScheduleRequest,
    dates: List[str],
    demand,
):

    groups = get_employee_groups(request)

    employee_ids = groups["employees"]
    pharmacists = groups["pharmacists"]
    senior_staff = groups["senior_staff"]

    penalty_terms = []
    shift_deficits = {}

    # --------------------------------------------------------
    # 1. 基礎人力缺口
    # --------------------------------------------------------

    for current_date in dates:

        for shift in [
            MORNING,
            MIDDLE,
            NIGHT,
            MEETING,
        ]:

            requirement = demand[
                current_date,
                shift
            ]

            if requirement <= 0:
                continue

            deficit = model.NewIntVar(
                0,
                requirement,
                f"deficit_{current_date}_{shift}",
            )

            model.Add(
                sum(
                    x[
                        employee,
                        current_date,
                        shift
                    ]
                    for employee in employee_ids
                )
                + deficit
                >= requirement
            )

            shift_deficits[
                current_date,
                shift
            ] = deficit

            penalty_terms.append(
                deficit
                * WEIGHTS["coverage_deficit"]
            )

    # --------------------------------------------------------
    # 2. 早 / 晚班成熟人力
    # --------------------------------------------------------

    if senior_staff:

        for current_date in dates:

            for shift in [
                MORNING,
                NIGHT,
            ]:

                if demand[
                    current_date,
                    shift
                ] <= 0:
                    continue

                has_senior = model.NewBoolVar(
                    f"senior_{current_date}_{shift}"
                )

                senior_count = sum(
                    x[
                        employee,
                        current_date,
                        shift
                    ]
                    for employee in senior_staff
                )

                model.Add(
                    senior_count >= 1
                ).OnlyEnforceIf(
                    has_senior
                )

                model.Add(
                    senior_count == 0
                ).OnlyEnforceIf(
                    has_senior.Not()
                )

                penalty_terms.append(
                    has_senior.Not()
                    * WEIGHTS["senior_present"]
                )

    # --------------------------------------------------------
    # 3. 單一營業班最多一位藥師
    # --------------------------------------------------------

    if pharmacists:

        for current_date in dates:

            for shift in [
                MORNING,
                MIDDLE,
                NIGHT,
            ]:

                pharmacist_count = sum(
                    x[
                        employee,
                        current_date,
                        shift
                    ]
                    for employee in pharmacists
                )

                exceed = model.NewBoolVar(
                    f"ph_exceed_{current_date}_{shift}"
                )

                model.Add(
                    pharmacist_count >= 2
                ).OnlyEnforceIf(
                    exceed
                )

                model.Add(
                    pharmacist_count <= 1
                ).OnlyEnforceIf(
                    exceed.Not()
                )

                penalty_terms.append(
                    exceed
                    * WEIGHTS["pharmacist_cap"]
                )

    # --------------------------------------------------------
    # 4. 每天至少一位藥師
    # --------------------------------------------------------

    if pharmacists:

        for current_date in dates:

            total_pharmacists = sum(
                x[
                    employee,
                    current_date,
                    shift
                ]
                for employee in pharmacists
                for shift in [
                    MORNING,
                    MIDDLE,
                    NIGHT,
                ]
            )

            has_pharmacist = model.NewBoolVar(
                f"has_ph_{current_date}"
            )

            model.Add(
                total_pharmacists >= 1
            ).OnlyEnforceIf(
                has_pharmacist
            )

            model.Add(
                total_pharmacists == 0
            ).OnlyEnforceIf(
                has_pharmacist.Not()
            )

            penalty_terms.append(
                has_pharmacist.Not()
                * WEIGHTS["pharmacist_daily"]
            )

    # --------------------------------------------------------
    # 5. 晚班藥師需搭配另一位成熟人力
    # --------------------------------------------------------

    if pharmacists and senior_staff:

        for current_date in dates:

            night_pharmacists = sum(
                x[
                    employee,
                    current_date,
                    NIGHT
                ]
                for employee in pharmacists
            )

            night_seniors = sum(
                x[
                    employee,
                    current_date,
                    NIGHT
                ]
                for employee in senior_staff
            )

            has_night_ph = model.NewBoolVar(
                f"night_ph_{current_date}"
            )

            enough_senior = model.NewBoolVar(
                f"night_senior_{current_date}"
            )

            model.Add(
                night_pharmacists >= 1
            ).OnlyEnforceIf(
                has_night_ph
            )

            model.Add(
                night_pharmacists == 0
            ).OnlyEnforceIf(
                has_night_ph.Not()
            )

            model.Add(
                night_seniors >= 2
            ).OnlyEnforceIf(
                enough_senior
            )

            model.Add(
                night_seniors <= 1
            ).OnlyEnforceIf(
                enough_senior.Not()
            )

            penalty = model.NewBoolVar(
                f"night_ph_senior_penalty_{current_date}"
            )

            model.AddBoolAnd([
                has_night_ph,
                enough_senior.Not(),
            ]).OnlyEnforceIf(
                penalty
            )

            model.AddBoolOr([
                has_night_ph.Not(),
                enough_senior,
            ]).OnlyEnforceIf(
                penalty.Not()
            )

            penalty_terms.append(
                penalty
                * WEIGHTS["night_ph_senior"]
            )

    # --------------------------------------------------------
    # 6. 偏好班別
    # --------------------------------------------------------

    for preference in (
        request.preferences.preferred_shifts
    ):

        if preference.employee not in employee_ids:
            continue

        for current_date in dates:

            current_weekday = (
                date.fromisoformat(
                    current_date
                ).weekday()
            )

            # 有指定星期，只在該星期套用
            if (
                preference.weekday is not None
                and current_weekday
                != preference.weekday
            ):
                continue

            penalty_terms.append(
                x[
                    preference.employee,
                    current_date,
                    preference.shift
                ].Not()
                * WEIGHTS["preferred_shift"]
            )

    # --------------------------------------------------------
    # 7. 偏好休星期
    # --------------------------------------------------------

    for preference in (
        request.preferences.preferred_days_off
    ):

        if preference.employee not in employee_ids:
            continue

        for current_date in dates:

            current_weekday = (
                date.fromisoformat(
                    current_date
                ).weekday()
            )

            if (
                current_weekday
                == preference.weekday
            ):

                penalty_terms.append(
                    x[
                        preference.employee,
                        current_date,
                        OFF
                    ].Not()
                    * WEIGHTS["preferred_day_off"]
                )

    # --------------------------------------------------------
    # 8. 偏好連休
    # --------------------------------------------------------

    for preference in (
        request.preferences.consecutive_off
    ):

        employee = preference.employee

        if employee not in employee_ids:
            continue

        consecutive_pairs = []

        for index in range(
            len(dates) - 1
        ):

            first_day = dates[index]
            second_day = dates[index + 1]

            consecutive = model.NewBoolVar(
                f"consecutive_{employee}_{index}"
            )

            model.Add(
                x[
                    employee,
                    first_day,
                    OFF
                ]
                +
                x[
                    employee,
                    second_day,
                    OFF
                ]
                == 2
            ).OnlyEnforceIf(
                consecutive
            )

            model.Add(
                x[
                    employee,
                    first_day,
                    OFF
                ]
                +
                x[
                    employee,
                    second_day,
                    OFF
                ]
                <= 1
            ).OnlyEnforceIf(
                consecutive.Not()
            )

            consecutive_pairs.append(
                consecutive
            )

        # 只要有一組連休就視為滿足偏好
        if consecutive_pairs:

            has_consecutive = model.NewBoolVar(
                f"has_consecutive_{employee}"
            )

            model.AddMaxEquality(
                has_consecutive,
                consecutive_pairs
            )

            penalty_terms.append(
                has_consecutive.Not()
                * WEIGHTS["consecutive_off"]
            )

    # --------------------------------------------------------
    # 9. 兩人避免同班
    # --------------------------------------------------------

    for preference in (
        request.preferences.different_shift
    ):

        if len(preference.employees) != 2:
            continue

        employee_a = preference.employees[0]
        employee_b = preference.employees[1]

        if (
            employee_a not in employee_ids
            or employee_b not in employee_ids
        ):
            continue

        for current_date in dates:

            for shift in [
                MORNING,
                MIDDLE,
                NIGHT,
            ]:

                same_shift = model.NewBoolVar(
                    f"same_{employee_a}_{employee_b}_"
                    f"{current_date}_{shift}"
                )

                model.Add(
                    x[
                        employee_a,
                        current_date,
                        shift
                    ]
                    +
                    x[
                        employee_b,
                        current_date,
                        shift
                    ]
                    == 2
                ).OnlyEnforceIf(
                    same_shift
                )

                model.Add(
                    x[
                        employee_a,
                        current_date,
                        shift
                    ]
                    +
                    x[
                        employee_b,
                        current_date,
                        shift
                    ]
                    <= 1
                ).OnlyEnforceIf(
                    same_shift.Not()
                )

                penalty_terms.append(
                    same_shift
                    * WEIGHTS["different_shift"]
                )

    return (
        penalty_terms,
        shift_deficits,
    )


# ============================================================
# 找指定排班
# ============================================================

def get_assignment_rule(
    request: ScheduleRequest,
    employee: str,
    current_date: str,
):

    for rule in request.assignments:

        if (
            rule.employee == employee
            and rule.date == current_date
        ):
            return rule

    return None


# ============================================================
# 計算實際上下班時間
# ============================================================

def calculate_actual_shift_time(
    request: ScheduleRequest,
    employee,
    current_date: str,
    shift: str,
):

    if shift == OFF:

        return {
            "start_time": None,
            "end_time": None,
            "hours": 0,
        }

    # 會議算出勤。
    # 目前尚未設定會議開始/結束時間，
    # 因此先回傳每日設定工時。
    if shift == MEETING:

        return {
            "start_time": None,
            "end_time": None,
            "hours": employee.hours_per_day,
        }
    current = date.fromisoformat(
        current_date
    )

    # 依星期取得當天營業時間
    business_hours_by_weekday = [
        request.business_hours.monday,
        request.business_hours.tuesday,
        request.business_hours.wednesday,
        request.business_hours.thursday,
        request.business_hours.friday,
        request.business_hours.saturday,
        request.business_hours.sunday,
    ]

    business = business_hours_by_weekday[current.weekday()]

    result = calculate_shift_time(
        shift=shift,
        business_start=business.start,
        business_end=business.end,
        middle_start=request.shifts.middle_start,
        hours_per_day=employee.hours_per_day,
    )

    # 特別指定的上 / 下班時間覆蓋預設
    assignment = get_assignment_rule(
        request,
        employee.id,
        current_date,
    )

    if assignment:

        if assignment.start_time:
            result["start_time"] = (
                assignment.start_time
            )

        if assignment.end_time:
            result["end_time"] = (
                assignment.end_time
            )

    # 重新計算實際工時
    if (
        result["start_time"] is not None
        and result["end_time"] is not None
    ):

        start_minutes = time_to_minutes(
            result["start_time"]
        )

        end_minutes = time_to_minutes(
            result["end_time"]
        )

        result["hours"] = (
            end_minutes - start_minutes
        ) / 60

    return result


# ============================================================
# 主要求解
# ============================================================

def solve_schedule(
    request: ScheduleRequest
):

    dates = get_dates(
        request.start_date,
        request.end_date,
    )

    if len(dates) != 7:

        return {
            "success": False,
            "message": "目前排班週期必須為 7 天",
        }

    demand = build_demand(
        request,
        dates,
    )
    # 確保每天都有 MEETING demand
    for current_date in dates:
        meeting_count = sum(
            meeting.staff_count
            for meeting in request.meetings
            if meeting.date == current_date
        )

        demand[
            current_date,
            MEETING
        ] = meeting_count
    model = cp_model.CpModel()

    x = create_variables(
        model,
        request,
        dates,
    )

    add_hard_constraints(
        model,
        x,
        request,
        dates,
        demand,
    )

    (
        penalty_terms,
        shift_deficits,
    ) = add_soft_constraints(
        model,
        x,
        request,
        dates,
        demand,
    )

    model.Minimize(
        sum(penalty_terms)
    )

    solver = cp_model.CpSolver()

    solver.parameters.max_time_in_seconds = 10.0
    
    status = solver.Solve(model)
    
    status_name = solver.StatusName(status)
    
    if status not in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    ):
        return {
            "success": False,
            "status": status_name,
            "message": (
                f"排班求解失敗，OR-Tools 狀態：{status_name}。"
            ),
        }

    # ========================================================
    # 班表結果
    # ========================================================

    schedule = []

    for employee in request.employees:

        employee_result = {
            "employee_id": employee.id,
            "name": employee.name,
            "days": [],
            "total_hours": 0,
            "work_days": 0,
        }

        for current_date in dates:

            assigned_shift = None

            for shift in SHIFTS:

                if solver.Value(
                    x[
                        employee.id,
                        current_date,
                        shift
                    ]
                ) == 1:

                    assigned_shift = shift
                    break

            shift_time = (
                calculate_actual_shift_time(
                    request=request,
                    employee=employee,
                    current_date=current_date,
                    shift=assigned_shift,
                )
            )

            employee_result[
                "days"
            ].append({
                "date": current_date,
                "shift": assigned_shift,
                "start_time": (
                    shift_time["start_time"]
                ),
                "end_time": (
                    shift_time["end_time"]
                ),
                "hours": shift_time["hours"],
            })

            employee_result[
                "total_hours"
            ] += shift_time["hours"]

            if assigned_shift != OFF:

                employee_result[
                    "work_days"
                ] += 1

        schedule.append(
            employee_result
        )

    # ========================================================
    # 人力缺口
    # ========================================================

    deficits = []

    for (
        current_date,
        shift
    ), variable in shift_deficits.items():

        value = solver.Value(
            variable
        )

        if value > 0:

            deficits.append({
                "date": current_date,
                "shift": shift,
                "deficit": value,
            })

    return {
        "success": True,
        "status": (
            "OPTIMAL"
            if status == cp_model.OPTIMAL
            else "FEASIBLE"
        ),
        "schedule": schedule,
        "deficits": deficits,
    }
