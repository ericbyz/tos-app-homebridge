#!/usr/bin/env python3
"""Generate homebridge.lang for the TOS App Center (26 locales, English fill)."""
NAME_EN = "Homebridge Smart Home Bridge"
AUTHOR = "ericbyz"
DESC_EN = (
    "Bridge hundreds of smart-home accessories that don't natively support "
    "HomeKit into Apple Home — lights, blinds, sensors, switches and more — "
    "and manage everything from the web UI at http://<NAS>:18246: one-click "
    "plugin marketplace, device pairing, logs and backup. Ships its own "
    "Node.js runtime (zero system dependencies). Packaged unmodified from "
    "the official upstream deb (Apache-2.0)."
)
NOTE_EN = "1. Repackaged the official upstream homebridge-apt-pkg deb (Apache-2.0) unmodified for TOS."
NOTE_ZH = "1. 将上游官方 homebridge-apt-pkg deb(Apache-2.0)原样封装为 TOS 应用。"

PRIMARY = [
    ("zh-cn", "Homebridge 智能家居桥接",
     "把数百种不支持 HomeKit 的智能家居设备(灯光、窗帘、传感器、开关等)接入苹果"
     "\u201c家庭\u201dApp,并全程用网页控制台管理:http://<NAS>:18246。插件市场一键安装、"
     "设备配对、日志与备份一应俱全。自带独立 Node.js 运行时,不依赖系统组件;"
     "上游官方 deb 原样封装(Apache-2.0)。"),
    ("zh-hk", "Homebridge 智能家居橋接",
     "把數百種不支持 HomeKit 的智能家居設備(燈光、窗簾、傳感器、開關等)接入蘋果"
     "\u201c家庭\u201dApp,並全程用網頁控制台管理:http://<NAS>:18246。插件市場一鍵安裝、"
     "設備配對、日誌與備份一應俱全。自帶獨立 Node.js 運行時,不依賴系統組件;"
     "上游官方 deb 原樣封裝(Apache-2.0)。"),
]

ORDER = ["zh-cn", "zh-hk", "en-us", "ko-kr", "ja-jp", "de-de", "fr-fr", "it-it",
         "es-es", "hu-hu", "pl-pl", "tr-tr", "ru-ru", "pt-pt", "cs-cz", "da-dk",
         "nl-nl", "nb-no", "sv-se", "el-gr", "ro-ro", "th-th", "vi-vn", "id-id",
         "ar-sa", "he-il"]

NATIVE = {
    "ja-jp": "HomeKit 非対応のスマートホーム機器(照明・ブラインド・センサー・スイッチなど)数百種を"
             "Apple Home にブリッジし、Web UI(http://<NAS>:18246)で一元管理:プラグイン市場の"
             "ワンクリック導入、デバイス ペアリング、ログとバックアップに対応。専用の Node.js "
             "ランタイム同梱でシステム依存なし。公式 upstream deb を無改修でパッケージ化(Apache-2.0)。",
    "ko-kr": "HomeKit을 지원하지 않는 수백 가지 스마트홈 기기(조명·블라인드·센서·스위치 등)를 Apple 홈으로 "
             "연결하고, 웹 UI(http://<NAS>:18246)에서 통합 관리하세요: 플러그인 마켓 원클릭 설치, 기기 페어링, "
             "로그·백업 지원. 자체 Node.js 런타임 포함, 시스템 의존성 없음. 공식 업스트림 deb 무수정 패키징(Apache-2.0).",
    "de-de": "Binden Sie hunderte Smart-Home-Geräte ohne native HomeKit-Unterstützung (Lampen, Rollos, "
             "Sensoren, Schalter u.v.m.) in Apple Home ein und verwalten Sie alles über das Web-UI unter "
             "http://<NAS>:18246: Plugin-Marktplatz mit einem Klick, Gerät Pairing, Protokolle und Backup. "
             "Eigenes Node.js-Runtime, keine Systemabhängigkeiten. Offizielles Upstream-deb unverändert (Apache-2.0).",
    "fr-fr": "Intégrez des centaines d'accessoires domotiques sans HomeKit natif (lampes, volets, capteurs, "
             "interrupteurs…) dans Apple Home et gérez tout depuis l'interface web http://<NAS>:18246 : "
             "marché de plugins en un clic, appairage des appareils, journaux et sauvegardes. Runtime Node.js "
             "intégré, aucune dépendance système. deb officiel upstream empaqueté sans modification (Apache-2.0).",
    "es-es": "Conecta cientos de accesorios domóticos sin soporte nativo de HomeKit (luces, persianas, sensores, "
             "interruptores…) a Apple Home y gestiona todo desde la interfaz web http://<NAS>:18246: mercado de "
             "plugins de un clic, emparejamiento de dispositivos, registros y copias de seguridad. Incluye su "
             "propio runtime de Node.js, sin dependencias del sistema. deb oficial upstream sin modificar (Apache-2.0).",
    "ru-ru": "Подключите сотни устройств умного дома без встроенной поддержки HomeKit (свет, шторы, датчики, "
             "выключатели и др.) к Apple Home и управляйте ими через веб-интерфейс http://<NAS>:18246: "
             "магазин плагинов в один клик, сопряжение устройств, журналы и резервные копии. Собственный "
             "рантайм Node.js, без системных зависимостей. Официальный deb без изменений (Apache-2.0).",
}

def render(out_path="homebridge.lang"):
    lines = []
    for loc in ORDER:
        name, desc = NAME_EN, NATIVE.get(loc, DESC_EN)
        for l, n, d in PRIMARY:
            if l == loc:
                name, desc = n, d
                break
        note = NOTE_ZH if loc in ("zh-cn", "zh-hk") else NOTE_EN
        lines += [f"[{loc}]", f'name = "{name}"', f'auth = "{AUTHOR}"',
                  f'descript = "{desc}"', f'note = "{note}"', ""]
    open(out_path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    print("wrote", out_path, len(ORDER), "locales")

if __name__ == "__main__":
    render()
