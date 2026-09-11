"""B 布局面板样式：左右分栏，不引入第二套视觉体系。"""

PANEL_CSS = """
:root {--blue:#2464c5;--muted:#697b8a;--rule:#e1e8ee}
html, body, #app {height:100%;margin:0;overflow:hidden;}
.q-layout, .q-page-container {height:100% !important;min-height:0 !important;max-height:100%;overflow:hidden;}
.q-page {height:100% !important;min-height:0 !important;max-height:100%;overflow:hidden;padding:0 !important;background:#edf1f5;}
.nicegui-content {padding:0 !important;margin:0;height:100%;max-height:100%;overflow:hidden;display:flex;flex-direction:column;}
.comtee-shell {font-family:'Segoe UI','Microsoft YaHei UI',sans-serif;color:#243443;font-size:14px;-webkit-font-smoothing:antialiased;flex:1;min-height:0;height:100%;max-height:100dvh;overflow:hidden;display:flex;flex-direction:column;background:#fcfdfe;}
.comtee-shell button,.comtee-shell input,.comtee-shell select,.comtee-shell textarea {font:inherit}
.comtee-shell .q-btn {min-height:40px;border:1px solid #d8e1e9;background:white;color:inherit;border-radius:7px;padding:0 13px;box-shadow:none;text-transform:none;letter-spacing:0}
.comtee-shell .q-btn:hover {background:#eef4fa;border-color:#b6c9dc}
.comtee-shell .q-btn:active {transform:scale(.96)}
.comtee-shell .q-btn[disabled] {opacity:.5;transform:none}
.comtee-shell .q-btn.primary {background:var(--blue);border-color:var(--blue);color:white}
.comtee-shell .q-btn.primary:hover {background:#2058aa}
.comtee-shell .q-btn.quiet {border-color:transparent;background:transparent}
.comtee-shell .q-btn.link-button {color:#285f9e}
.comtee-shell .q-btn.danger {color:#b1443c}
.comtee-shell .q-btn.icon-button {width:40px;padding:0;min-width:40px}
.comtee-shell .icon {width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.mono {font-family:Consolas,'Cascadia Mono',monospace;font-variant-numeric:tabular-nums}
.muted {color:var(--muted)}
.tiny {font-size:12px}
.eyebrow {font-size:12px;color:var(--muted);margin-bottom:6px}
.app-header {padding:18px 22px;display:flex;align-items:center;justify-content:space-between;gap:12px;background:white;border-bottom:1px solid var(--rule);flex-shrink:0;position:sticky;top:0;z-index:2}
.brand {display:flex;align-items:center;gap:11px}
.mark {width:34px;height:34px;background:var(--blue);border-radius:9px;display:grid;place-items:center;color:white}
.mark svg {width:24px;height:24px}
.brand h1,.brand-title {font-size:21px;letter-spacing:2px;font-weight:650;margin:0;line-height:1.1}
.subtitle {font-size:12px;color:var(--muted);margin-top:3px}
.header-actions {display:flex;gap:8px;align-items:center}
.comtee-content {flex:1;min-height:0;display:flex;overflow:hidden}
.split {display:grid;grid-template-columns:218px minmax(0,1fr);grid-template-rows:minmax(0,1fr);width:100%;height:100%;min-height:0;overflow:hidden;flex:1}
.rail {background:#f4f7fa;border-right:1px solid var(--rule);padding:18px 12px;overflow-y:auto;min-height:0;height:100%;overscroll-behavior:contain}
.railhead {display:flex;align-items:center;justify-content:space-between;gap:5px;margin:0 4px 12px 8px}
.railhead h2,.rail-title-text {font-size:13px;font-weight:600;white-space:nowrap;margin:0}
.count {font-weight:400;color:#7a8c9b;font-size:12px;margin-left:7px}
.railitem {display:block;width:100%;text-align:left;padding:12px !important;border-color:transparent !important;background:transparent !important;margin-bottom:6px;min-height:78px;height:auto}
.railitem:hover {background:#eaf0f6 !important}
.railitem.active {background:white !important;border-color:#cddce9 !important;box-shadow:0 2px 5px #20394f05}
.rail-line {display:flex;flex-direction:column;align-items:stretch;width:100%;gap:2px}
.rail-title {display:flex;gap:9px;align-items:baseline;overflow:hidden}
.rail-title .mono {font-size:17px;font-weight:650;flex-shrink:0}
.rail-alias {font-size:12px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:#4e6576}
.rail-state {display:flex;align-items:center;gap:6px;font-size:11px;color:#477258;margin-top:6px}
.rail-state:before,.badge:before,.status-item:before {content:'';width:6px;height:6px;background:currentColor;border-radius:50%;flex-shrink:0}
.waiting {color:#916615 !important}
.error-color {color:#ac453e !important}
.split.collapsed {grid-template-columns:80px minmax(0,1fr)}
.split.collapsed .rail {padding:18px 7px}
.split.collapsed .railhead {margin:0 0 12px;justify-content:center}
.split.collapsed .railhead .rail-title-text,.split.collapsed .rail-alias,.split.collapsed .rail-state-text {display:none}
.split.collapsed .railitem {padding:12px 4px !important;min-height:68px;text-align:center}
.split.collapsed .rail-title,.split.collapsed .rail-state {justify-content:center}
.split.collapsed .rail-title .mono {font-size:14px}
.detail {padding:22px 26px 18px;overflow:auto;min-width:0;min-height:0;height:100%;overscroll-behavior:contain}
.detail-top {display:flex;justify-content:space-between;align-items:center;gap:16px}
.port {font-size:42px;letter-spacing:-1.3px;font-weight:650;line-height:1.15;margin:0}
.line-alias {color:#607687;font-size:14px;margin-left:14px;font-weight:400;letter-spacing:0}
.badge {display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:6px 9px;border-radius:5px;background:#eaf5ee;color:#287147;white-space:nowrap;flex-shrink:0}
.badge.waiting {background:#fff3dc;color:#916615}
.badge.error-color {background:#fceeea;color:#ac453e}
.endpoint {display:flex;gap:9px;align-items:center;flex-wrap:wrap;font-size:12px;margin:7px 0 3px;color:#69808f}
.link-status {display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:#738694;margin:4px 0 8px}
.status-item {display:inline-flex;align-items:center;gap:5px}
.sectionhead {display:flex;align-items:center;justify-content:space-between;gap:10px;margin:20px 0 10px}
.sectionhead h3,.section-title {font-size:12px;font-weight:500;color:#607587;margin:0}
.param-grid {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));padding:19px 0;background:#f6f9fd;border:1px solid #dce6ef;border-radius:8px}
.param {padding:0 18px;display:flex;flex-direction:column;gap:10px;min-width:0}
.param + .param {border-left:1px solid #e0e7ee}
.param small {color:#627a8d;font-size:12px}
.param strong,.param-value {font-size:29px;letter-spacing:-1px;font-weight:650;color:#233e58;line-height:1.15}
.param span,.param-note {font-size:11px;color:#738694;line-height:1.6}
.flow-control {font-size:12px;color:#687e8f;padding:12px 1px;display:flex;align-items:center;gap:15px}
.flow-control strong,.flow-value {font-weight:500;color:#3f586c}
.flow-control.configured .flow-value {background:#eaf1fb;color:#225ba7;padding:3px 7px;border-radius:4px}
.clients {display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:16px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);margin:10px 0 14px;font-size:12px}
.clients h3 {font-size:12px;font-weight:500;color:#61798b;margin:0}
.client-values {display:flex;gap:24px;flex-wrap:wrap}
.client-values strong {font-weight:600;margin-left:6px}
.presence {color:#30734d}
.activity {display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:15px;font-size:12px;margin:17px 0 21px}
.activity small {display:block;font-size:11px;color:#738694;margin-bottom:7px}
.activity strong,.activity-value {font-weight:500}
.activity-note {font-size:11px;color:#788b99;margin-top:-11px;margin-bottom:18px;line-height:1.6}
.device-info {border-top:1px solid var(--rule);font-size:12px;padding-top:4px}
.device-info .q-expansion-item__container {border:0;box-shadow:none}
.detail-bottom {display:flex;justify-content:space-between;align-items:center;gap:14px;margin-top:16px;color:#7b8d9b;font-size:11px}
.notice {border-radius:7px;background:#fff6e3;border:1px solid #efdcaf;padding:13px 14px;margin:16px 0 7px;line-height:1.7;font-size:12px;color:#865f1d}
.notice-title {display:block;font-size:13px;margin-bottom:3px;font-weight:650}
.notice.error {color:#aa443b;background:#fff2ef;border-color:#f0d1cb}
.notice.success {color:#2d6b47;background:#eef7f0;border-color:#d2e6d7}
.empty {align-self:center;width:100%;text-align:center;padding:55px 24px}
.empty h2 {font-size:20px;margin:0}
.empty p {margin:12px auto 22px;color:#6c8293;font-size:13px;max-width:330px;line-height:1.8}
.field {margin-bottom:15px}
.field label,.field-label {display:block;font-size:12px;margin-bottom:7px;color:#4e697e}
.form-section {font-size:12px;font-weight:600;color:#36566d;margin:5px 0 14px;padding-top:17px;border-top:1px solid var(--rule)}
.impact {font-size:12px;line-height:1.7;color:#6a8191;background:#f2f6f9;border-radius:6px;padding:11px 13px;margin-top:5px}
.impact.warning {color:#886321;background:#fff5e2}
.settings-preview {font-size:11px;line-height:1.7;color:#698194;margin:-4px 0 14px}
.share-text {width:100%;min-height:140px;font-size:12px;line-height:1.8}
.share-help {font-size:12px;color:#718697;line-height:1.8;margin-bottom:14px}
.dialog-card {width:min(540px,calc(100vw - 28px));max-height:calc(100dvh - 28px);padding:0;border-radius:12px;overflow:hidden}
.dialog-card.small {width:min(430px,calc(100vw - 28px))}
.dialoghead {padding:21px 23px 16px;border-bottom:1px solid var(--rule);display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.dialoghead h2 {font-size:18px;font-weight:650;margin:0}
.dialoghead p {font-size:12px;color:#728697;margin-top:6px;line-height:1.6}
.dialog-body {padding:18px 23px 20px;overflow:auto;max-height:min(70vh,520px)}
.dialog-footer {display:flex;justify-content:flex-end;gap:8px;padding:14px 23px;border-top:1px solid var(--rule);background:#fafcfd}
.switch-row {display:flex;align-items:center;justify-content:space-between;gap:20px;min-height:46px;font-size:13px}
"""
