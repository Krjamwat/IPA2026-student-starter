# ==============================================================================
# Part 4: Integration Pipeline
# ทำไมต้องมีไฟล์นี้:
# รวมขั้นตอนทั้งหมดของระบบเข้าด้วยกันเป็น Pipeline เดียวอย่างเป็นลำดับ:
# 1. validate_webex_envelope: ตรวจว่า Mention บอตจริงไหม และมีไฟล์แนบไหม
# 2. yaml.safe_load: อ่านและ parse ไฟล์ YAML
# 3. validate_request: ตรวจโครงสร้างและค่าพารามิเตอร์ของคำขอ
# 4. dispatch_request: ส่งงานไปรันบน Router ผ่าน Backend ที่ระบุ
# หากขั้นตอนไหนผิดพลาด จะหยุดและคืน Error ทันที (ไม่หลุดไปถึง Router)
# ==============================================================================

import yaml
from app.core import validate_request
from app.dispatcher import dispatch_request
from app.request_handler import validate_webex_envelope


def process_request(mentioned_people, attachment_path, bot_person_id):
    """
    Validate the envelope, load YAML, validate the request, and dispatch to router.
    """
    # ด่าน 1: ตรวจ Mention และไฟล์แนบ
    envelope_error = validate_webex_envelope(
        mentioned_people, attachment_path, bot_person_id
    )
    if envelope_error is not None:
        return envelope_error

    # ด่าน 2: อ่านไฟล์และ Parse YAML
    try:
        with open(attachment_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return {"status": "error", "result": "invalid_yaml"}

    # ด่าน 3: ตรวจสอบความถูกต้องของคำขอ (Part 1 validation)
    validation_result = validate_request(data)
    if validation_result.get("status") != "ok":
        return validation_result

    # ด่าน 4: ส่งต่อให้ Dispatcher นำคำขอไปทำงานกับ Router จริง
    return dispatch_request(data)
