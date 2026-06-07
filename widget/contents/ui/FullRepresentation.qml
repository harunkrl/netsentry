import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as Plasma5Support

Item {
    id: fullRoot
    Layout.preferredWidth: Kirigami.Units.gridUnit * root.popupWidth
    Layout.preferredHeight: Kirigami.Units.gridUnit * root.popupHeight

    readonly property bool hasData: root.snapshotData !== null
    readonly property real sf: Math.round(Kirigami.Theme.smallFont.pixelSize * (root.fontScale / 100.0))
    readonly property real df: Math.round(Kirigami.Theme.defaultFont.pixelSize * (root.fontScale / 100.0))

    readonly property string hi: {
        if (root.threatLevel === "critical") return "security-low"
        if (root.threatLevel === "warning") return "security-medium"
        return "security-high"
    }

    readonly property var activeModel: root.activeTab === 0 ? connectionsModel : establishedModel

    // Current sort properties for the active tab
    readonly property string currentSortColumn: root.activeTab === 0 ? root.sortColumnListening : root.sortColumnEstablished
    readonly property bool currentSortDesc: root.activeTab === 0 ? root.sortDescListening : root.sortDescEstablished

    // Column definitions — Listening tab
    property var listeningCols: [
        { col: "process_name", label: i18n("Process"), w: 0.32 },
        { col: "local_port", label: i18n("Port"), w: 0.14 },
        { col: "proto", label: i18n("Proto"), w: 0.12 },
        { col: "state", label: i18n("State"), w: 0.16 },
        { col: "local_ip", label: i18n("Address"), w: 0.26 }
    ]
    // Column definitions — Established tab
    property var establishedCols: [
        { col: "process_name", label: i18n("Process"), w: 0.24 },
        { col: "local_port", label: i18n("Local:Port"), w: 0.16 },
        { col: "remote_ip", label: i18n("Remote:Port"), w: 0.22 },
        { col: "remote_country", label: i18n("Country"), w: 0.12 },
        { col: "state", label: i18n("State"), w: 0.14 },
        { col: "duration", label: i18n("Duration"), w: 0.12 }
    ]

    Kirigami.PromptDialog {
        id: killDialog
        property int targetPid: 0
        title: i18n("Kill Process")
        subtitle: i18n("Are you sure you want to terminate process %1?", targetPid)
        standardButtons: Kirigami.Dialog.Ok | Kirigami.Dialog.Cancel
        onAccepted: { root.killProcess(targetPid) }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        // ── Header row ─────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon { source: fullRoot.hi; implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: Kirigami.Units.iconSizes.small }
            Label { text: i18n("KPortWatch"); font.bold: true; font.pixelSize: fullRoot.df }
            Item { Layout.fillWidth: true }
            RowLayout {
                visible: fullRoot.hasData
                spacing: Kirigami.Units.smallSpacing / 2
                Kirigami.Icon {
                    source: root.alertCount > 0 ? "dialog-warning" : "security-high"
                    implicitWidth: Kirigami.Units.iconSizes.small * 0.8
                    implicitHeight: Kirigami.Units.iconSizes.small * 0.8
                    color: root.threatLevel === "critical" ? "#da4453" : root.threatLevel === "warning" ? "#f67400" : "#27ae60"
                }
                Label {
                    text: root.alertCount > 0 ? i18n("%1 alert(s)", root.alertCount) : i18n("Secure")
                    color: root.threatLevel === "critical" ? "#da4453" : root.threatLevel === "warning" ? "#f67400" : "#27ae60"
                    font.pixelSize: fullRoot.sf
                    font.bold: root.alertCount > 0
                }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        // ── Status banners ─────────────────────────────────────
        Kirigami.InlineMessage {
            Layout.fillWidth: true; type: Kirigami.MessageType.Error
            visible: root.daemonDown
            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Label { text: i18n("Daemon not responding."); Layout.fillWidth: true; color: Kirigami.Theme.textColor }
                Button {
                    text: i18n("Start")
                    icon.name: "system-run"
                    flat: true
                    implicitHeight: Kirigami.Units.gridUnit * 1.4
                    font.pixelSize: fullRoot.sf
                    onClicked: daemonStartSource.connectedSources = ["sh -c 'systemctl --user start kportwatch 2>/dev/null || kportwatch-daemon &'"]
                }
            }
        }
        Kirigami.InlineMessage {
            Layout.fillWidth: true; type: Kirigami.MessageType.Warning
            text: i18n("Data may be stale — last fetch failed."); visible: root.dataStale && !root.daemonDown
        }

        // ── Tab bar with underline indicator ────────────────────
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                spacing: 0

                Button {
                    text: i18n("Listening (%1)", root.listeningCount)
                    font.pixelSize: fullRoot.sf
                    flat: true
                    highlighted: root.activeTab === 0
                    onClicked: root.activeTab = 0
                    Layout.fillWidth: true
                }
                Button {
                    text: i18n("Established (%1)", root.establishedCount)
                    font.pixelSize: fullRoot.sf
                    flat: true
                    highlighted: root.activeTab === 1
                    onClicked: root.activeTab = 1
                    Layout.fillWidth: true
                }
            }

            // Underline indicator
            Item {
                Layout.fillWidth: true
                height: 2

                Rectangle {
                    height: parent.height
                    width: parent.width / 2
                    x: root.activeTab === 0 ? 0 : parent.width / 2
                    color: Kirigami.Theme.highlightColor
                    Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        // ── Search ─────────────────────────────────────────────
        Kirigami.SearchField {
            Layout.fillWidth: true
            placeholderText: i18n("Search ports, processes, IP...")
            onTextChanged: root.searchText = text.toLowerCase()
        }

        // ── Connection list ────────────────────────────────────
        ListView {
            id: portListView
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; model: fullRoot.activeModel; spacing: 1
            ScrollBar.vertical: ScrollBar {}

            header: Column {
                width: portListView.width - (portListView.ScrollBar.vertical.visible ? portListView.ScrollBar.vertical.width : 0)
                visible: portListView.count > 0

                RowLayout {
                    width: parent.width; spacing: 0
                    height: Kirigami.Units.gridUnit * 1.5
                    Item { Layout.preferredWidth: 6 }  // space for alert border
                    Repeater {
                        model: root.activeTab === 0 ? listeningCols : establishedCols
                        delegate: Label {
                            readonly property var m: modelData
                            text: m.label + (fullRoot.currentSortColumn === m.col ? (fullRoot.currentSortDesc ? " ▼" : " ▲") : "")
                            font.bold: true; font.pixelSize: fullRoot.sf
                            Layout.preferredWidth: parent.width * m.w - 6
                            MouseArea {
                                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (root.activeTab === 0) {
                                        if (root.sortColumnListening === m.col) root.sortDescListening = !root.sortDescListening
                                        else { root.sortColumnListening = m.col; root.sortDescListening = false }
                                    } else {
                                        if (root.sortColumnEstablished === m.col) root.sortDescEstablished = !root.sortDescEstablished
                                        else { root.sortColumnEstablished = m.col; root.sortDescEstablished = false }
                                    }
                                }
                            }
                        }
                    }
                }
                Kirigami.Separator { width: parent.width }
            }

            delegate: Item {
                width: portListView.width - (portListView.ScrollBar.vertical.visible ? portListView.ScrollBar.vertical.width : 0)
                height: Kirigami.Units.gridUnit * 1.8
                readonly property var entry: model
                readonly property var ma: root.portAlertMap[entry.local_port] || null

                // Hover highlight
                Rectangle {
                    anchors.fill: parent; color: Kirigami.Theme.highlightColor
                    opacity: lh.hovered ? 0.15 : 0.0; radius: Kirigami.Units.smallSpacing
                    Behavior on opacity { NumberAnimation { duration: 150 } }
                }

                // Alert indicator — colored left border (replaces dot)
                Rectangle {
                    width: 3; height: parent.height
                    color: ma ? (ma.level === "CRITICAL" ? "#da4453" : "#f67400") : (root.safePortsSet[entry.local_port] ? "#27ae60" : "transparent")
                    visible: ma !== null || (root.safePortsSet[entry.local_port] === true)
                    anchors.left: parent.left
                    ToolTip.visible: alertHover.hovered && ma !== null
                    ToolTip.text: ma ? ma.message : (root.safePortsSet[entry.local_port] ? i18n("Safe port") : "")
                    HoverHandler { id: alertHover }
                }

                HoverHandler { id: lh }

                // Context menu
                TextEdit { id: clip; visible: false }
                MouseArea {
                    anchors.fill: parent; acceptedButtons: Qt.RightButton
                    onClicked: (mouse) => { if (mouse.button === Qt.RightButton) ctxMenu.popup() }
                }

                Menu {
                    id: ctxMenu
                    MenuItem { text: i18n("Copy Process"); onTriggered: { clip.text = entry.process_name || ""; clip.selectAll(); clip.copy() } }
                    MenuItem { text: i18n("Copy PID"); onTriggered: { clip.text = entry.pid ? String(entry.pid) : ""; clip.selectAll(); clip.copy() } }
                    MenuItem { text: i18n("Copy Port"); onTriggered: { clip.text = entry.local_port ? String(entry.local_port) : ""; clip.selectAll(); clip.copy() } }
                    MenuItem { text: i18n("Copy IP"); onTriggered: { clip.text = entry.remote_ip || entry.local_ip || ""; clip.selectAll(); clip.copy() } }
                    MenuSeparator {}
                    MenuItem { text: i18n("Kill Process"); icon.name: "application-exit"; enabled: entry.pid > 0
                        onTriggered: { killDialog.targetPid = entry.pid; killDialog.open() } }
                }

                // ── Listening tab delegate ─────────────────────
                RowLayout {
                    anchors.fill: parent; spacing: 0
                    visible: root.activeTab === 0
                    Item { Layout.preferredWidth: 6 }  // space for alert border

                    Label {
                        text: entry.process_name || i18n("unknown")
                        font.pixelSize: fullRoot.sf; Layout.fillWidth: true
                        Layout.preferredWidth: parent.width * 0.32 - 6
                        elide: Text.ElideRight
                    }
                    Label {
                        text: entry.local_port ? String(entry.local_port) : "-"
                        font.pixelSize: fullRoot.sf
                        opacity: entry.local_port ? 1.0 : 0.5
                        color: ma ? (ma.level === "CRITICAL" ? "#da4453" : "#f67400") : Kirigami.Theme.textColor
                        Layout.preferredWidth: parent.width * 0.14
                    }
                    Label {
                        text: (entry.proto || "?").toUpperCase()
                        font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.12
                    }
                    Label {
                        text: entry.state || "-"
                        font.pixelSize: fullRoot.sf
                        color: entry.state === "LISTEN" ? "#27ae60" : Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.16
                    }
                    RowLayout {
                        Layout.preferredWidth: parent.width * 0.26; spacing: 2
                        Label {
                            text: entry.local_ip || ""
                            font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                            Layout.fillWidth: true; elide: Text.ElideRight
                        }
                        Button {
                            icon.name: "process-stop"; opacity: lh.hovered ? 1.0 : 0.0
                            visible: entry.pid > 0
                            implicitWidth: 28; implicitHeight: 28; Layout.alignment: Qt.AlignVCenter
                            ToolTip.text: i18n("Kill (%1)", entry.pid); ToolTip.visible: hovered; flat: true
                            onClicked: { killDialog.targetPid = entry.pid; killDialog.open() }
                            enabled: opacity > 0
                        }
                    }
                }

                // ── Established tab delegate ────────────────────
                RowLayout {
                    anchors.fill: parent; spacing: 0
                    visible: root.activeTab === 1
                    Item { Layout.preferredWidth: 6 }  // space for alert border

                    Label {
                        text: entry.process_name || i18n("unknown")
                        font.pixelSize: fullRoot.sf; Layout.fillWidth: false
                        Layout.preferredWidth: parent.width * 0.24 - 6
                        elide: Text.ElideRight
                    }
                    Label {
                        text: (entry.local_ip ? entry.local_ip : "") + ":" + (entry.local_port || "-")
                        font.pixelSize: fullRoot.sf
                        Layout.preferredWidth: parent.width * 0.16; elide: Text.ElideRight
                        ToolTip.visible: lpHov.hovered; ToolTip.text: entry.local_ip + ":" + (entry.local_port || "?")
                        HoverHandler { id: lpHov }
                    }
                    Label {
                        text: {
                            var host = entry.remote_hostname || entry.remote_ip || "-"
                            return host + ":" + (entry.remote_port || "-")
                        }
                        font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.22; elide: Text.ElideRight
                        ToolTip.visible: rpHov.hovered; ToolTip.text: (entry.remote_ip || "") + ":" + (entry.remote_port || "?") + " " + (entry.remote_hostname || "")
                        HoverHandler { id: rpHov }
                    }
                    Label {
                        text: entry.remote_country_code ? entry.remote_country_code.toUpperCase() : (entry.remote_country || "-")
                        font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.12
                    }
                    Label {
                        text: entry.state || "?"
                        font.pixelSize: fullRoot.sf
                        color: entry.state === "ESTABLISHED" ? "#27ae60" :
                               entry.state === "TIME_WAIT" ? "#888" :
                               entry.state === "CLOSE_WAIT" ? "#da4453" :
                               Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.14
                    }
                    Label {
                        text: formatDuration(entry.first_seen)
                        font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.12
                    }
                }
            }

            // ── Empty states ───────────────────────────────────
            Label {
                anchors.fill: parent; visible: portListView.count === 0 && fullRoot.hasData
                text: root.activeTab === 0 ? i18n("No listening ports detected") : i18n("No active connections")
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor; wrapMode: Text.WordWrap
            }

            Column {
                anchors.fill: parent; visible: portListView.count === 0 && !fullRoot.hasData
                spacing: Kirigami.Units.smallSpacing

                Item { Layout.fillHeight: true }

                Kirigami.Icon {
                    id: refreshIcon
                    anchors.horizontalCenter: parent.horizontalCenter
                    source: "view-refresh"
                    implicitWidth: Kirigami.Units.iconSizes.medium
                    implicitHeight: Kirigami.Units.iconSizes.medium
                    opacity: 0.5
                    NumberAnimation on opacity {
                        from: 0.3; to: 0.7; duration: 1200
                        running: refreshIcon.visible; loops: Animation.Infinite
                        easing.type: Easing.InOutSine
                    }
                }

                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: i18n("Waiting for data…")
                    font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                }

                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: i18n("Make sure kportwatch-daemon is running.")
                    font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor; opacity: 0.7
                }

                Item { Layout.fillHeight: true }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        // ── Footer: traffic + timestamp + actions ──────────────
        RowLayout {
            Layout.fillWidth: true

            RowLayout {
                spacing: Kirigami.Units.smallSpacing / 2
                Kirigami.Icon {
                    source: "view-refresh"
                    implicitWidth: Kirigami.Units.iconSizes.small * 0.8
                    implicitHeight: Kirigami.Units.iconSizes.small * 0.8
                    opacity: 0.6
                }
                Label {
                    text: root.lastUpdated ? i18n("Updated: %1", root.lastUpdated) : ""
                    font.pixelSize: fullRoot.sf
                    color: root.dataStale ? "#da4453" : Kirigami.Theme.disabledTextColor
                }
            }

            Item { Layout.fillWidth: true }

            // Traffic indicator
            RowLayout {
                visible: root.trafficIface !== ""
                spacing: Kirigami.Units.smallSpacing
                Kirigami.Icon {
                    source: "network-wireless"
                    implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: Kirigami.Units.iconSizes.small
                    opacity: 0.6
                }
                Label {
                    text: "↓" + root.trafficRx
                    font.pixelSize: fullRoot.sf; color: "#27ae60"
                    font.bold: root.trafficRx !== "0 B/s"
                }
                Label {
                    text: "↑" + root.trafficTx
                    font.pixelSize: fullRoot.sf; color: "#3498db"
                    font.bold: root.trafficTx !== "0 B/s"
                }
            }

            Button {
                icon.name: "utilities-system-monitor"; text: i18n("Analyzer")
                implicitHeight: Kirigami.Units.gridUnit * 1.6
                font.pixelSize: fullRoot.sf
                onClicked: root.launchTUI()
            }
        }
    }

    // ── Daemon start helper ────────────────────────────────────
    Plasma5Support.DataSource {
        id: daemonStartSource
        engine: 'executable'
        connectedSources: []
        onNewData: (sourceName, data) => { connectedSources = [] }
    }

    // ── Duration formatter ─────────────────────────────────────
    function formatDuration(firstSeenEpoch) {
        if (!firstSeenEpoch || firstSeenEpoch <= 0) return "-"
        var elapsed = Math.floor((Date.now() / 1000) - firstSeenEpoch)
        if (elapsed < 0) return "-"
        if (elapsed < 60) return elapsed + "s"
        if (elapsed < 3600) return Math.floor(elapsed / 60) + "m"
        if (elapsed < 86400) return Math.floor(elapsed / 3600) + "h"
        return Math.floor(elapsed / 86400) + "d"
    }
}
