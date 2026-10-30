# ==============================================================================
# Part 3: NETCONF Backend Adapter
# ทำไมต้องมีไฟล์นี้:
# จัดการสื่อสารกับ Router ผ่านโปรโตคอล NETCONF (XML RPC over SSH พอร์ต 830):
# - อ่านสถานะ: ใช้ XML Subtree Filter กับโมเดล ietf-interfaces
# - คอนฟิกจริง: ใช้คำสั่ง edit-config พร้อม attribute nc:operation="replace"
#   เพื่อแทนที่บล็อก Loopback เดิมอย่างหมดจด ป้องกัน IP ค้าง
# ==============================================================================

from ipaddress import IPv4Interface
import xml.etree.ElementTree as ET
from app.backends import planning

# กำหนด XML Namespaces ตามมาตรฐาน IETF และ Cisco Native YANG
NETCONF_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"
IETF_IF_NS = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IETF_IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """
    Return normalized interface status using NETCONF.
    ทำไมใช้ Subtree Filter: เพื่อดึงเฉพาะ Interface ที่ต้องการ ไม่ต้องดึง config ทั้งเครื่องมาประมวลผล
    """
    filter_xml = f"""<interfaces xmlns="{IETF_IF_NS}">
  <interface>
    <name>{interface_name}</name>
  </interface>
</interfaces>"""

    try:
        # netconf_get_config ถูก inject เข้ามาในการทดสอบเพื่อคืนค่า XML จำลอง
        if netconf_get_config is not None:
            xml_text = netconf_get_config(router, filter_xml)
        else:
            from ncclient import manager
            import os
            with manager.connect(
                host=router,
                port=830,
                username=os.getenv("ROUTER_USER", "cisco"),
                password=os.getenv("ROUTER_PASS", "cisco"),
                hostkey_verify=False,
                device_params={"name": "iosxe"},
            ) as m:
                xml_text = m.get_config(source="running", filter=("subtree", filter_xml)).data_xml
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    # หาแท็ก <interface> ใน namespace ของ ietf-interfaces
    # ถ้าหาไม่เจอ แปลว่าไม่มี interface นี้อยู่บน router -> not_found
    iface_elem = root.find(f".//{{{IETF_IF_NS}}}interface")
    if iface_elem is None:
        return {"status": "ok", "result": "not_found", "interface": None}

    # แปลง XML tags เป็น Python Dictionary รูปแบบมาตรฐาน
    name = iface_elem.findtext(f"{{{IETF_IF_NS}}}name", interface_name)
    description = iface_elem.findtext(f"{{{IETF_IF_NS}}}description")
    enabled = iface_elem.findtext(f"{{{IETF_IF_NS}}}enabled")
    admin_state = "up" if enabled == "true" else "down"

    ip = iface_elem.findtext(f".//{{{IETF_IP_NS}}}ip")
    netmask = iface_elem.findtext(f".//{{{IETF_IP_NS}}}netmask")
    ipv4 = str(IPv4Interface(f"{ip}/{netmask}")) if ip and netmask else None

    return {
        "status": "ok",
        "result": "found",
        "interface": {
            "name": name,
            "ipv4": ipv4,
            "description": description,
            "admin_state": admin_state,
        },
    }


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """
    Return create/update/no_change plan using NETCONF status.
    ทำไม: ส่งต่อให้ planning.plan_interface กลาง เพื่อคำนวณ diff
    """
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, netconf_get_config=netconf_get_config),
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """
    Apply complete desired interface state using NETCONF.
    ทำไมต้องใส่ nc:operation="replace":
    เพื่อให้ Router ทำการแทนที่ config ของ Loopback ตัวนี้ใหม่ทั้งหมด
    ถ้าเปลี่ยน IP address จะทำให้ IP เดิมถูกลบออกทันที ไม่ค้างเป็น Secondary IP
    """
    number = desired_interface["name"][len("Loopback"):]
    iface = IPv4Interface(desired_interface["ipv4"])
    address = str(iface.ip)
    mask = str(iface.network.netmask)

    # ทำไม: ใน Cisco Native YANG ถ้าต้องการปิด interface (shutdown) ให้ใส่แท็ก <shutdown/>
    # แต่ถ้าต้องการเปิด (no shutdown) ให้ละเว้นแท็กนี้ออกไป
    shutdown_elem = "<shutdown/>\n          " if desired_interface["admin_state"] == "down" else ""

    config_xml = f"""<config xmlns="{NETCONF_NS}" xmlns:nc="{NETCONF_NS}">
  <native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">
    <interface>
      <Loopback nc:operation="replace">
        <name>{number}</name>
        <description>{desired_interface["description"]}</description>
        <ip>
          <address>
            <primary>
              <address>{address}</address>
              <mask>{mask}</mask>
            </primary>
          </address>
        </ip>
        {shutdown_elem}</Loopback>
    </interface>
  </native>
</config>"""

    try:
        if netconf_edit_config is not None:
            netconf_edit_config(router, config_xml)
        else:
            from ncclient import manager
            import os
            with manager.connect(
                host=router,
                port=830,
                username=os.getenv("ROUTER_USER", "cisco"),
                password=os.getenv("ROUTER_PASS", "cisco"),
                hostkey_verify=False,
                device_params={"name": "iosxe"},
            ) as m:
                m.edit_config(target="running", config=config_xml)
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    return {"status": "ok", "result": "applied"}
