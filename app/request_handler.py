# ==============================================================================
# Part 1: Webex Envelope Validation & Handler
# ทำไมต้องมีไฟล์นี้:
# ไฟล์นี้ทำหน้าที่ตรวจสอบ "ซองจดหมาย (Envelope)" ของ Webex ก่อนที่จะเปิดดูเนื้อหาด้านใน
# เพื่อให้แน่ใจว่าข้อความนี้ตั้งใจส่งถึงบอตตัวนี้จริง ๆ และมีไฟล์คำขอแนบมาด้วย
# ==============================================================================

from app.core import process_request_file


def validate_webex_envelope(
    mentioned_people,
    attachment_path,
    bot_person_id,
):
    """
    Validate the target bot's actual mention and YAML attachment.
    Return an error response, or None when the envelope is valid.
    """
    # 1. ตรวจสอบว่าบอตถูก Mention จริงหรือไม่
    # ทำไมต้องเช็ก personId แทนที่จะดูข้อความตัวหนังสือ:
    # เพราะการพิมพ์ @ชื่อบอต เป็นข้อความธรรมดาใครก็พิมพ์ได้ แต่ Webex API จะส่ง personId
    # ของคนที่ถูก @mention เข้ามาใน array `mentionedPeople` เราจึงต้องเช็กว่า bot_person_id
    # ของบอตเราอยู่ในรายการนี้จริง เพื่อไม่ให้บอตเผลอไปตอบข้อความที่คุยกันทั่วไปในห้อง
    if (
        not isinstance(bot_person_id, str)
        or not bot_person_id
        or not isinstance(mentioned_people, list)
        or bot_person_id not in mentioned_people
    ):
        return {"status": "error", "result": "missing_bot_mention"}

    # 2. ตรวจสอบว่ามีไฟล์แนบมาหรือไม่
    # ทำไม: ระบบนี้ทำงานแบบ File-driven Automation หากผู้ใช้ @mention บอตเฉย ๆ โดยไม่แนบไฟล์ YAML
    # จะต้องแจ้ง error ว่า no_yaml ทันที เพื่อบอกให้ผู้ใช้แนบไฟล์คำขอเข้ามา
    if attachment_path is None:
        return {"status": "error", "result": "no_yaml"}

    return None


def handle_webex_request(
    mentioned_people,
    attachment_path,
    bot_person_id,
):
    """
    Validate the envelope, then validate the attached YAML request.
    Return a response dictionary. Do not dispatch to a router.
    ทำไม: ฟังก์ชันนี้รวมการตรวจสอบ 2 ชั้นใน Part 1 คือ:
    1. ตรวจสอบ Envelope (Mention + ไฟล์แนบ)
    2. ถ้าผ่าน จึงไปตรวจสอบเนื้อหา YAML ผ่าน process_request_file
    หมายเหตุ: ใน Part 1 ต้อง "ห้าม" ติดต่อไปยัง Router เด็ดขาด (คืนแค่ accepted หรือ error)
    """
    envelope_error = validate_webex_envelope(
        mentioned_people, attachment_path, bot_person_id
    )
    if envelope_error is not None:
        return envelope_error

    return process_request_file(attachment_path)
