# ==============================================================================
# Part 4: Backend Dispatcher
# ทำไมต้องมีไฟล์นี้:
# ไฟล์นี้ทำหน้าที่เป็น "Traffic Controller / Router" ของระบบหลังบ้าน
# รับคำขอที่ผ่านการ validate ใน Part 1 มาแล้ว จากนั้นตรวจสอบ method และ action
# เพื่อส่งต่องานไปยัง adapter ที่ถูกต้องตาม 9 รูปแบบที่ระบุใน Capability Matrix
# ==============================================================================

from app.backends import ansible, netconf, netmiko_textfsm, restconf


def dispatch_request(data):
    """
    Dispatch a validated request to the corresponding backend function.
    ทำไมต้องแยกพารามิเตอร์ target:
    - ถ้าเป็น status หรือ delete: ใช้เพียงชื่อ interface ('name') ไปอ่านหรือลบ
    - ถ้าเป็น plan หรือ apply: ต้องส่งทั้งก้อน desired dictionary (name, ipv4, description, admin_state)
    """
    method = data["method"]
    action = data["action"]
    router = data["router"]
    iface = data["desired"]["interface"]

    target = iface["name"] if action in ("status", "delete") else iface

    # 1. RESTCONF: รองรับ status, plan, apply
    if method == "restconf":
        if action == "status":
            return restconf.get_interface_state(router, target)
        if action == "plan":
            return restconf.plan_interface(router, target)
        if action == "apply":
            return restconf.apply_interface(router, target)

    # 2. NETCONF: รองรับ status, plan, apply
    elif method == "netconf":
        if action == "status":
            return netconf.get_interface_state(router, target)
        if action == "plan":
            return netconf.plan_interface(router, target)
        if action == "apply":
            return netconf.apply_interface(router, target)

    # 3. Ansible: รองรับเฉพาะ apply
    elif method == "ansible":
        if action == "apply":
            return ansible.apply_interface(router, target)

    # 4. Netmiko + TextFSM: รองรับ status และ delete
    elif method == "netmiko-textfsm":
        if action == "status":
            return netmiko_textfsm.get_interface_state(router, target)
        if action == "delete":
            return netmiko_textfsm.delete_interface(router, target)

    return {"status": "error", "result": "invalid_action"}
