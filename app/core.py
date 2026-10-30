# ==============================================================================
# Part 1: Core YAML Request Validation
# ทำไมต้องมีไฟล์นี้:
# ไฟล์นี้ทำหน้าที่เป็น "ด่านแรก" ในการตรวจสอบเนื้อหาของคำขอที่ส่งมาจาก Webex
# เพื่อป้องกันคำขอที่ไม่ถูกต้อง (Invalid Format/Parameters) หรือไม่ปลอดภัย
# ให้ถูกปฏิเสธทันที (Fail-Fast) โดยไม่ต้องเสียเวลาเชื่อมต่อไปยัง Router จริง
# ==============================================================================

import yaml

# กำหนด IP ของ Router ที่อนุญาตให้บอตติดต่อได้เท่านั้น เพื่อความปลอดภัยในห้องแล็บ
ALLOWED_ROUTERS = {
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
}

# Capability Matrix: กำหนดว่า Backend แต่ละตัวรองรับ Action อะไรได้บ้าง
# ทำไมต้องกำหนด: เพื่อป้องกันการเรียกคำสั่งที่ Backend นั้นไม่รองรับ (เช่น RESTCONF ลบ Loopback ไม่ได้)
VALID_CAPABILITIES = {
    "restconf": {"status", "plan", "apply"},
    "netconf": {"status", "plan", "apply"},
    "ansible": {"apply"},
    "netmiko-textfsm": {"status", "delete"},
}


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.
    Return a response dictionary according to specs/response-spec-v1.md.
    """
    # ตรวจว่า Root ของ YAML ถูกแปลงเป็น Python Dictionary หรือไม่
    # ทำไม: ป้องกันกรณีผู้ใช้ส่ง YAML ที่เป็น String ธรรมดา หรือ List เปล่า ๆ มา
    if not isinstance(data, dict):
        return {"status": "error", "result": "invalid_yaml"}

    # 1. ตรวจสอบ version:
    # ทำไมต้องเช็ก bool ด้วย: ใน Python ค่า True เป็น subtype ของ int (True == 1)
    # แต่ spec บังคับว่าต้องเป็นตัวเลข 1 (integer) แท้ ๆ เท่านั้น ห้ามเป็น boolean, float หรือ string
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        return {"status": "error", "result": "invalid_version"}

    # 2. ตรวจสอบ router IP:
    # ทำไม: เพื่อยืนยันว่าระบุปลายทาง และป้องกันไม่ให้บอตถูกนำไปยิง IP นอกเหนือจาก Router ที่จัดไว้
    if "router" not in data:
        return {"status": "error", "result": "missing_router"}
    if data["router"] not in ALLOWED_ROUTERS:
        return {"status": "error", "result": "invalid_router"}

    # 3. ตรวจสอบ method (เทคโนโลยีที่จะใช้คุยกับ router):
    # ทำไม: ต้องมั่นใจว่าวิธีที่ขอมา (RESTCONF/NETCONF/Ansible/Netmiko) เป็นวิธีที่ระบบมี adapter รองรับ
    if "method" not in data:
        return {"status": "error", "result": "missing_method"}
    method = data["method"]
    if method not in VALID_CAPABILITIES:
        return {"status": "error", "result": "invalid_method"}

    # 4. ตรวจสอบ action (สิ่งที่ต้องการทำ):
    # ทำไม: ตรวจสอบความเข้ากันได้ตาม Capability Matrix ทันที หากผิดคู่ (เช่น restconf + delete)
    # จะได้ตัดทิ้งตรงนี้ทันที ก่อนไปตรวจฟิลด์ด้านใน ช่วยลด overhead
    if "action" not in data:
        return {"status": "error", "result": "missing_action"}
    action = data["action"]
    if action not in VALID_CAPABILITIES[method]:
        return {"status": "error", "result": "invalid_action"}

    # 5. ตรวจสอบ desired, interface, name:
    # ทำไม: ทุก action (แม้แต่ status หรือ delete) จำเป็นต้องรู้ว่ากำลังจะทำกับ interface ชื่ออะไร
    if "desired" not in data or not isinstance(data["desired"], dict):
        return {"status": "error", "result": "missing_desired"}

    desired = data["desired"]
    if "interface" not in desired or not isinstance(desired["interface"], dict):
        return {"status": "error", "result": "missing_interface"}

    iface = desired["interface"]
    if "name" not in iface or not iface["name"]:
        return {"status": "error", "result": "missing_interface_name"}

    # 6. ตรวจสอบฟิลด์สมบูรณ์สำหรับการ configure (เฉพาะ plan และ apply):
    # ทำไม: การวางแผน (plan) และการคอนฟิกจริง (apply) จำเป็นต้องมี IP, Description และ Admin State ครบ
    # ส่วน status และ delete อ่าน/ลบจากชื่อ interface อย่างเดียว จึงละเว้นฟิลด์พวกนี้ได้
    if action in ("plan", "apply"):
        if "ipv4" not in iface or not iface["ipv4"]:
            return {"status": "error", "result": "missing_ipv4"}
        if "description" not in iface or iface["description"] is None:
            return {"status": "error", "result": "missing_description"}
        if "admin_state" not in iface or iface["admin_state"] is None:
            return {"status": "error", "result": "missing_admin_state"}
        # admin_state บน router Cisco มีสถานะเป็น up หรือ down เท่านั้น
        if iface["admin_state"] not in ("up", "down"):
            return {"status": "error", "result": "invalid_admin_state"}

    # ผ่านทุกด่าน -> คืนสถานะ accepted ตอบรับคำขอ
    return {"status": "ok", "result": "accepted"}


def process_request_file(path):
    """
    Read a YAML request file, validate it, and return a response dictionary.
    ทำไม: อ่านไฟล์ YAML จาก disk (ที่ดาวน์โหลดมาจาก Webex) แล้วแปลงเป็น object เพื่อส่งต่อให้ validate_request
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        # ดักจับ Syntax error ของไฟล์ YAML เช่น formatting ผิด, ปีกกาไม่ครบ
        return {"status": "error", "result": "invalid_yaml"}

    return validate_request(data)
