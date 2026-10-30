# ==============================================================================
# Part 3: Shared Planning Wrapper for Backends
# ทำไมต้องมีไฟล์นี้:
# ทั้ง RESTCONF และ NETCONF ต่างก็รองรับคำสั่ง "plan"
# เพื่อไม่ให้ต้องเขียนโค้ดเปรียบเทียบ state ซ้ำซ้อนในแต่ละ backend
# ไฟล์นี้จึงทำหน้าที่เป็น Orchestrator กลาง:
# 1. เรียกฟังก์ชันอ่านสถานะปัจจุบันของ backend นั้น ๆ (get_interface_state)
# 2. นำผลลัพธ์ที่ได้ส่งต่อเข้าฟังก์ชันคำนวณ diff กลางของ Part 2 (build_plan)
# ==============================================================================

from app.planner import build_plan


def plan_interface(
    router,
    desired_interface,
    get_interface_state,
):
    """Build a Part 2 plan from backend status."""
    # ขั้นที่ 1: อ่านสถานะปัจจุบันของ Interface จาก Router ผ่าน Backend ที่ระบุ
    status_resp = get_interface_state(router, desired_interface["name"])

    # ทำไมต้องดัก error ตรงนี้: หากเกิดปัญหา เช่น authentication_failed หรือ connection_failed
    # จะต้องส่ง error นั้นกลับไปทันที ไม่สามารถวางแผนต่อได้
    if status_resp.get("status") == "error":
        return status_resp

    # ขั้นที่ 2: ดึงข้อมูล Interface ที่ normalize แล้ว (ถ้าไม่พบคืน None)
    # แล้วส่งให้ฟังก์ชัน build_plan ใน Part 2 ทำการคำนวณ diff
    current_interface = status_resp.get("interface")
    return build_plan(desired_interface, current_interface)
