# ==============================================================================
# Part 2: Deterministic Planning Engine
# ทำไมต้องมีไฟล์นี้:
# ก่อนจะแก้คอนฟิกบนอุปกรณ์ Network ระดับ Production มักต้องมีขั้นตอน "Dry-run / Plan"
# เพื่อให้ Network Engineer เห็นก่อนว่าถ้าสั่ง Apply แล้ว อุปกรณ์จะเกิดความเปลี่ยนแปลงอะไรบ้าง
# ฟังก์ชันนี้เป็น Pure Function (ไม่มีการต่อเน็ตเวิร์ก) คำนวณความแตกต่าง (Diff) ระหว่าง
# สิ่งที่ต้องการ (Desired State) กับสถานะปัจจุบันบน Router (Current State)
# ==============================================================================


def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    # 1. กรณีที่ current_interface เป็น None:
    # แปลว่า Interface ชื่อนี้ยังไม่เคยมีอยู่บน Router มาก่อน
    # การวางแผนจึงต้องเป็น operation = "create"
    # ทำไมต้องแสดงเฉพาะ "to": เพราะไม่มีค่าเดิม (from) ให้เปรียบเทียบ
    # และทำไมไม่ใส่ฟิลด์ "name" ใน changes: เพราะ name เป็นตัวระบุตัวตน (Identifier) ของ Interface
    # ฟิลด์ที่บริหารจัดการ (Managed Fields) มีเพียง ipv4, description และ admin_state
    if current_interface is None:
        return {
            "status": "ok",
            "result": "planned",
            "operation": "create",
            "changes": {
                "ipv4": {"to": desired_interface["ipv4"]},
                "description": {"to": desired_interface["description"]},
                "admin_state": {"to": desired_interface["admin_state"]},
            },
        }

    # 2. กรณีที่ Interface มีอยู่แล้วบน Router:
    # ต้องเปรียบเทียบทีละฟิลด์เฉพาะ 3 ฟิลด์หลัก (ipv4, description, admin_state)
    # ทำไมต้องเก็บทั้ง "from" และ "to": เพื่อให้ผู้ใช้เห็นว่าของเดิมคืออะไร และจะถูกเปลี่ยนไปเป็นอะไร
    changes = {}
    for field in ("ipv4", "description", "admin_state"):
        desired_val = desired_interface.get(field)
        current_val = current_interface.get(field)
        if desired_val != current_val:
            changes[field] = {
                "from": current_val,
                "to": desired_val,
            }

    # 3. สรุปผลการเปรียบเทียบ:
    # - ถ้ามีฟิลด์ต่างกันอย่างน้อย 1 ฟิลด์ -> operation = "update"
    # - ถ้าทุกฟิลด์ตรงกันหมดแล้ว -> operation = "no_change" พร้อม changes: {}
    # ทำไม: เพื่อให้เกิดคุณสมบัติ Idempotency (ถ้าค่าตรงอยู่แล้ว รันซ้ำก็ต้องบอกว่าไม่ต้องทำอะไร)
    if changes:
        operation = "update"
    else:
        operation = "no_change"

    return {
        "status": "ok",
        "result": "planned",
        "operation": operation,
        "changes": changes,
    }
