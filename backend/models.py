from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ============================================================
# 基本型別
# ============================================================

ShiftType = Literal[
    "OFF",
    "MORNING",
    "MIDDLE",
    "NIGHT",
    "MEETING",
]

EmployeeType = Literal["FT", "PT"]


# ============================================================
# 1. 人員設定
# ============================================================

class Employee(BaseModel):
    id: str
    name: str

    employee_type: EmployeeType

    # 是否為藥師
    is_pharmacist: bool = False

    # 是否為成熟人力
    is_senior: bool = False

    # 是否允許減少上班天數 / 時數
    reducible: bool = False

    # 每週預設上班天數
    work_days: int = Field(ge=0, le=7)

    # 每日預設工時
    hours_per_day: float = Field(gt=0, le=24)


# ============================================================
# 2. 營業時間
# ============================================================

class BusinessHours(BaseModel):
    start: str
    end: str


class BusinessHoursConfig(BaseModel):
    # 週一～週五
    weekday: BusinessHours

    # 週六、週日
    weekend: BusinessHours


# ============================================================
# 3. 班別需求
# ============================================================

class ShiftDemand(BaseModel):
    morning: int = Field(default=2, ge=0)
    middle: int = Field(default=0, ge=0)
    night: int = Field(default=3, ge=0)


class ShiftConfig(BaseModel):
    demand: ShiftDemand

    # 中班預設開始時間
    middle_start: str = "12:00"


# ============================================================
# 4. 會議
# ============================================================

class MeetingRule(BaseModel):
    date: str

    # 會議需要的人數
    staff_count: int = Field(default=1, ge=1)


# ============================================================
# 5. 固定班
# ============================================================

class FixedShiftRule(BaseModel):
    employee: str
    shift: ShiftType


# ============================================================
# 6. 固定休星期
# ============================================================

class FixedDayOffRule(BaseModel):
    employee: str

    # 0 = 星期一
    # 1 = 星期二
    # ...
    # 6 = 星期日
    weekday: int = Field(ge=0, le=6)


# ============================================================
# 7. 指定排假 / 指定班
# ============================================================

class AssignmentRule(BaseModel):
    employee: str
    date: str
    shift: ShiftType

    # 特殊指定時間
    # 例如：
    # F4 早班 15:00 下班
    # P4 晚班 18:00 上班
    start_time: Optional[str] = None
    end_time: Optional[str] = None


# ============================================================
# 8. 偏好班別
# ============================================================

class PreferredShiftRule(BaseModel):
    employee: str
    shift: ShiftType

    # 如果有指定星期：
    # 例如 P5 偏好週三早班
    weekday: Optional[int] = Field(
        default=None,
        ge=0,
        le=6
    )


# ============================================================
# 9. 偏好休星期
# ============================================================

class PreferredDayOffRule(BaseModel):
    employee: str
    weekday: int = Field(ge=0, le=6)


# ============================================================
# 10. 連續休假偏好
# ============================================================

class ConsecutiveOffRule(BaseModel):
    employee: str


# ============================================================
# 11. 不同班偏好
# ============================================================

class DifferentShiftRule(BaseModel):
    employees: List[str]


# ============================================================
# 12. 所有偏好
# ============================================================

class PreferenceConfig(BaseModel):
    preferred_shifts: List[PreferredShiftRule] = Field(
        default_factory=list
    )

    preferred_days_off: List[PreferredDayOffRule] = Field(
        default_factory=list
    )

    consecutive_off: List[ConsecutiveOffRule] = Field(
        default_factory=list
    )

    different_shift: List[DifferentShiftRule] = Field(
        default_factory=list
    )


# ============================================================
# 13. 完整排班 Request
# ============================================================

class ScheduleRequest(BaseModel):

    # 排班日期範圍
    start_date: str
    end_date: str

    # 人員設定
    employees: List[Employee]

    # 營業時間
    business_hours: BusinessHoursConfig

    # 班別、人力需求
    shifts: ShiftConfig

    # 會議
    meetings: List[MeetingRule] = Field(
        default_factory=list
    )

    # 固定班
    fixed_shifts: List[FixedShiftRule] = Field(
        default_factory=list
    )

    # 固定休星期
    fixed_days_off: List[FixedDayOffRule] = Field(
        default_factory=list
    )

    # 指定排假 / 指定班
    assignments: List[AssignmentRule] = Field(
        default_factory=list
    )

    # 偏好
    preferences: PreferenceConfig = Field(
        default_factory=PreferenceConfig
    )
