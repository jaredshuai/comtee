"""面板深模块界面测试：直接透过 PanelSession 驱动 Comtee，不碰 UI 控件也不摸内部函数。"""

from dataclasses import replace

from comtee import (
    BluetoothIdentity,
    Comtee,
    LineHold,
    UsbIdentity,
)
from comtee.panel_session import Draft, PanelSession
from tests.fakes import FakeHuman, FakeSerial, MemoryStore


def _session() -> tuple[FakeSerial, FakeHuman, Comtee, PanelSession]:
    """装配一份带假串口、假人端入口和面板会话的串通。"""
    serial = FakeSerial()
    human = FakeHuman()
    hub = Comtee(serial, MemoryStore(), human=human)
    return serial, human, hub, PanelSession(hub)


def test_空现场打开新建与弹窗内重扫保留草稿并识别USB与蓝牙() -> None:
    """无设备时禁止保存并给提示；设备出现后重扫不丢失已填草稿。"""
    serial, _human, _hub, session = _session()
    serial.set_unidentified(2)

    empty_snap = session.snapshot()
    assert empty_snap.entries == ()
    assert empty_snap.detail is None

    initial = session.open_editor(None)
    assert initial.creating is True
    assert initial.can_save is False
    assert initial.device_disabled is True
    assert initial.empty_hint is not None
    assert "2 个缺少稳定身份的串口" in initial.empty_hint.message
    assert initial.draft.port == 2222
    assert (
        initial.draft.baud,
        initial.draft.data_bits,
        initial.draft.parity,
        initial.draft.stop_bits,
        initial.draft.flow_control,
        initial.draft.decode,
    ) == (9600, 8, "N", 1, "none", "gbk")

    typed = Draft(
        name="H3C 控制台",
        port=2400,
        baud=115200,
        data_bits=7,
        parity="E",
        stop_bits=2,
        flow_control="rtscts",
        decode="utf-8",
        device_key="",
    )
    still_empty = session.rescan_create(typed)
    assert still_empty.can_save is False
    assert still_empty.empty_hint is not None
    assert still_empty.draft.name == "H3C 控制台"
    assert still_empty.draft.port == 2400
    assert still_empty.draft.baud == 115200
    assert still_empty.draft.flow_control == "rtscts"
    assert still_empty.draft.decode == "utf-8"

    usb = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    bt = BluetoothIdentity(
        hwid=r"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0046\8&2ECCB597&0&04220520037B_C00000000"
    )
    serial.plug(usb, path="COM6")
    serial.plug(bt, path="COM5")

    rescanned = session.rescan_create(typed)
    assert rescanned.can_save is True
    assert rescanned.empty_hint is None
    assert rescanned.show_quiet_rescan is True
    assert rescanned.draft.name == "H3C 控制台"
    assert rescanned.draft.port == 2400
    labels = list(rescanned.device_options.values())
    assert "COM6 · USB 0403:6001 · 序列号 FT123" in labels
    assert "COM5 · 蓝牙 地址 04:22:05:20:03:7B · 实例 C00000000" in labels


def test_创建成功提供可复制连接信息并拦截非法输入与端口冲突() -> None:
    """新建默认 9600 8N1 GBK；异常不留半条线路，已分配设备从下拉过滤。"""
    serial, human, hub, session = _session()
    usb = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    bt = BluetoothIdentity(hwid=r"BTHENUM\LOCAL_04220520037B_C00000000")
    serial.plug(usb, path="COM6")

    opened = session.open_editor(None)
    assert opened.can_save is True

    # 校验各类非法草稿
    bad_cases = [
        (replace(opened.draft, port=0), "port"),
        (replace(opened.draft, baud=0), "baud"),
        (replace(opened.draft, data_bits=9), "bits"),
        (replace(opened.draft, parity="X"), "parity"),
        (replace(opened.draft, stop_bits=3), "stop"),
        (replace(opened.draft, flow_control="invalid"), "flow"),
        (replace(opened.draft, decode="ascii"), "charset"),
        (replace(opened.draft, name="超" * 33), "lineName"),
        (replace(opened.draft, device_key=""), "device"),
    ]
    for bad_draft, field in bad_cases:
        failed = session.submit_editor(None, bad_draft)
        assert failed.ok is False and failed.error is not None
        assert failed.error.field == field

    assert session.submit_editor(None, None).ok is False

    # 人端入口冲突：不留下半条线路，不占设备
    human.blocked.add(2222)
    port_err = session.submit_editor(None, replace(opened.draft, name="核心交换机"))
    assert port_err.ok is False and port_err.error is not None
    assert "2222" in port_err.error.title
    assert "尚未创建" in port_err.error.message
    assert hub.list_lines() == ()
    assert not serial.is_held(usb)

    # 放开端口后创建成功
    human.blocked.discard(2222)
    created = session.submit_editor(None, replace(opened.draft, name="核心交换机"))
    assert created.ok is True and created.snapshot is not None
    detail = created.snapshot.detail
    assert detail is not None
    assert detail.port == 2222
    assert detail.name == "核心交换机"
    assert detail.badge == "占口"
    assert detail.address == "127.0.0.1:2222"
    assert detail.banner is not None and detail.banner.copy_connection is True
    assert detail.connection_copy.address == "127.0.0.1:2222"
    assert "python -m comtee.mcp" in detail.connection_copy.agent_text
    assert r"\\.\pipe\comtee" in detail.connection_copy.agent_text
    assert "2222" in detail.connection_copy.agent_text

    # 再开新建弹窗：已分配的 USB 已被过滤，默认切到建议端口 2223
    serial.plug(bt, path="COM5")
    second_open = session.open_editor(None)
    assert second_open.draft.port == 2223
    assert all("FT123" not in label for label in second_open.device_options.values())

    # 重复端口、重复设备或已拔掉设备均被拦截
    dup_port = session.submit_editor(None, replace(second_open.draft, port=2222))
    assert dup_port.ok is False and dup_port.error is not None
    assert "2222" in dup_port.error.title

    dup_dev = session.submit_editor(
        None, replace(second_open.draft, device_key=opened.draft.device_key)
    )
    assert dup_dev.ok is False and dup_dev.error is not None
    assert "串口设备" in dup_dev.error.title

    serial.unplug(bt)
    missing_dev = session.submit_editor(None, second_open.draft)
    assert missing_dev.ok is False and missing_dev.error is not None
    assert "不在现场" in missing_dev.error.message


def test_编辑线路区分保活改参换端口与换设备及失败回滚() -> None:
    """只改名称/解码不重开串口；改入口/参数/换设备冲突时原配置和占口保持。"""
    serial, human, hub, session = _session()
    usb1 = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT111")
    bt2 = BluetoothIdentity(hwid=r"BTHENUM\LOCAL_04220520037B_C00000000")
    serial.plug(usb1, path="COM6")
    serial.plug(bt2, path="COM5")
    hub.create_line(2222, usb1, name="原名")

    occupy_before = serial.occupy_calls
    state = session.open_editor(2222)
    assert state.device_disabled is False
    assert len(state.device_options) == 2

    # 1. 仅改名称与解码：预览不重开，保存不增加 occupy 调用
    meta_draft = replace(state.draft, name="新控制台", decode="utf-8")
    meta_preview = session.preview_editor(2222, meta_draft)
    assert meta_preview.impact.reopens_serial is False
    assert "不重新打开串口" in meta_preview.impact.message

    meta_saved = session.submit_editor(2222, meta_draft)
    assert meta_saved.ok is True and meta_saved.snapshot is not None
    assert serial.occupy_calls == occupy_before
    assert meta_saved.snapshot.detail is not None
    assert meta_saved.snapshot.detail.banner is not None
    assert "串口未重新打开" in meta_saved.snapshot.detail.banner.message

    # 2. 改串口参数：在场时提示重开并重占；不在场时仅保存等待插回
    param_draft = replace(meta_draft, baud=115200)
    assert session.preview_editor(2222, param_draft).impact.reopens_serial is True
    param_saved = session.submit_editor(2222, param_draft)
    assert param_saved.ok is True
    assert serial.held_params(usb1).baudrate == 115200

    # 3. 迁移入口到被占端口失败后回滚，保留原配置；到空闲端口成功并带 reconnect 提示
    human.blocked.add(3333)
    port_fail = session.submit_editor(2222, replace(param_draft, port=3333))
    assert port_fail.ok is False and port_fail.error is not None
    assert "保持不变" in port_fail.error.message
    assert hub.list_lines()[0].human_entry == 2222

    human.blocked.discard(3333)
    port_ok = session.submit_editor(2222, replace(param_draft, port=3333))
    assert port_ok.ok is True and port_ok.snapshot is not None
    assert port_ok.snapshot.selected_port == 3333
    assert port_ok.snapshot.detail is not None
    assert port_ok.snapshot.detail.banner is not None
    assert port_ok.snapshot.detail.banner.reconnect is True

    # 4. 换设备失败（新设备被占用）给出准确的设备回滚说明，并保留旧设备占口
    edit_3333 = session.open_editor(3333)
    bt_key = next(k for k in edit_3333.device_options if k.startswith("BT|"))
    serial.mark_busy(bt2)
    dev_fail = session.submit_editor(3333, replace(edit_3333.draft, device_key=bt_key))
    assert dev_fail.ok is False and dev_fail.error is not None
    assert "原设备绑定已保留" in dev_fail.error.message
    assert serial.is_held(usb1)

    # 释放新设备后成功切换绑定
    serial.clear_busy(bt2)
    dev_ok = session.submit_editor(3333, replace(edit_3333.draft, device_key=bt_key))
    assert dev_ok.ok is True and dev_ok.snapshot is not None
    assert not serial.is_held(usb1)
    assert serial.is_held(bt2)
    assert dev_ok.snapshot.detail is not None
    assert dev_ok.snapshot.detail.banner is not None
    assert "切换到新设备" in dev_ok.snapshot.detail.banner.message


def test_故障诊断恢复一次通知与单次扫描不风暴() -> None:
    """tick 每次只触发一次底层 scan，清晰呈现等待/冲突并只报一次恢复反馈。"""
    serial, _human, hub, session = _session()
    usb1 = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT1")
    usb2 = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT2")
    usb3 = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT3")
    for dev, port, path in [
        (usb1, 2222, "COM6"),
        (usb2, 2223, "COM7"),
        (usb3, 2224, "COM8"),
    ]:
        serial.plug(dev, path=path)
        hub.create_line(port, dev, name=f"线{port}")
    session.snapshot()

    # 单次 tick 对 3 条线路只触发 1 次 scan（消除 2N+1 扫描风暴）
    scans_before = serial.scan_calls
    tick_idle = session.tick(dialog_open=False)
    assert serial.scan_calls - scans_before == 1
    assert tick_idle.snapshot is not None and tick_idle.toasts == ()

    # dialog_open=True 仍刷新串通，但跳过面板快照渲染
    assert session.tick(dialog_open=True).snapshot is None

    # 1. 拔掉设备 + 未识别串口说明 -> 等待设备 -> 插回恢复一次通知
    serial.set_unidentified(1)
    serial.unplug(usb1)
    waiting = session.tick().snapshot
    assert waiting is not None and waiting.detail is not None
    assert waiting.detail.badge == "等待设备"
    assert waiting.detail.rw_label == "不可写"
    assert any(
        card.kind == "waiting" and "1 个缺少稳定身份" in card.reason
        for card in waiting.detail.failures
    )

    serial.plug(usb1, path="COM12")
    recovered = session.tick()
    assert recovered.toasts == ("设备已插回并占口",)
    assert recovered.snapshot is not None and recovered.snapshot.detail is not None
    assert recovered.snapshot.detail.banner is not None
    assert recovered.snapshot.detail.banner.title == "设备已插回并占口"
    assert "COM12" in recovered.snapshot.detail.device_path_text
    assert session.tick().toasts == ()

    # 2. 设备占用冲突 -> retry_line 失败提示 -> 放口后再 retry 恢复
    serial.unplug(usb1)
    serial.mark_busy(usb1)
    serial.plug(usb1, path="COM12")
    conflict_snap = session.tick().snapshot
    assert conflict_snap is not None and conflict_snap.detail is not None
    assert conflict_snap.detail.badge == "占用冲突"
    assert conflict_snap.detail.retry_hold is True
    retry_still_busy = session.retry(2222)
    assert "仍未恢复，请按提示处理后再试" in retry_still_busy.toasts

    serial.clear_busy(usb1)
    retry_ok = session.retry(2222)
    assert "占用冲突已解除" in retry_ok.toasts
    assert retry_ok.snapshot.detail is not None
    assert retry_ok.snapshot.detail.badge == "占口"

    # 3. 不存在的线路重试不崩溃并给出提示
    assert session.retry(9999).toasts == ("没有这条线路",)


def test_多线路折叠切换与拆线路清理释放设备() -> None:
    """折叠左栏保留名称/入口/占口，切线清理旧提示，拆线停监听放占口。"""
    serial = FakeSerial()
    human = FakeHuman()
    store = MemoryStore()
    hub = Comtee(serial, store, human=human)
    session = PanelSession(hub)
    usb1 = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT1")
    usb2 = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT2")
    serial.plug(usb1, path="COM6")
    serial.plug(usb2, path="COM7")
    hub.create_line(2222, usb1, name="路由 A")
    hub.create_line(3333, usb2, name="交换机 B")

    client = hub.attach_client(2222)
    assert client is not None

    collapsed = session.toggle_rail()
    assert collapsed.collapsed is True
    assert [(item.port, item.name, item.badge) for item in collapsed.rail] == [
        (2222, "路由 A", LineHold.HELD),
        (3333, "交换机 B", LineHold.HELD),
    ]

    switched = session.select(3333)
    assert switched.collapsed is True
    assert switched.selected_port == 3333
    assert switched.detail is not None and switched.detail.name == "交换机 B"

    prompt = session.remove_prompt(2222)
    assert prompt is not None
    assert "2222" in prompt.title
    assert "1 个已连接人端将断开" in prompt.message
    assert "释放这台设备的占口" in prompt.message

    removed = session.remove(2222)
    assert removed.toasts == ("线路已拆掉",)
    assert not serial.is_held(usb1)
    assert 2222 in human.release_calls
    assert removed.snapshot.entries == (3333,)

    # 端口冲突重试场景
    human.blocked.add(4444)
    blocked_store = MemoryStore()
    blocked_store.save(
        (replace(store.load()[0], human_entry=4444, device=usb1, name="冲突端口"),)
    )
    hub2 = Comtee(serial, blocked_store, human=human)
    s2 = PanelSession(hub2)
    snap2 = s2.snapshot()
    assert snap2.detail is not None
    assert snap2.detail.badge == "端口冲突"
    assert snap2.detail.retry_listen is True
    human.blocked.discard(4444)
    port_rec = s2.retry(4444)
    assert "人端入口已恢复监听" in port_rec.toasts
    assert port_rec.snapshot.detail is not None
    assert port_rec.snapshot.detail.badge == "占口"

    dismissed = s2.dismiss_notice()
    assert dismissed.detail is not None and dismissed.detail.banner is None
