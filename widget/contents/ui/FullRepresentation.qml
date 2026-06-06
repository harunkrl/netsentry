import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import org.kde.kirigami as Kirigami

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
            Label {
                visible: fullRoot.hasData
                text: root.alertCount > 0 ? i18n("%1 alert(s)", root.alertCount) : i18n("Secure")
                color: root.threatLevel === "critical" ? "#e03030" : root.threatLevel === "warning" ? "#e0c030" : "#30c030"
                font.pixelSize: fullRoot.sf
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        // ── Status banners ─────────────────────────────────────
        Kirigami.InlineMessage {
            Layout.fillWidth: true; type: Kirigami.MessageType.Error
            text: i18n("Daemon not responding. Data may be stale."); visible: root.daemonDown
        }
        Kirigami.InlineMessage {
            Layout.fillWidth: true; type: Kirigami.MessageType.Warning
            text: i18n("Data may be stale — last fetch failed."); visible: root.dataStale && !root.daemonDown
        }

        // ── Tab bar ────────────────────────────────────────────
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

            header: RowLayout {
                width: portListView.width; spacing: 0
                visible: portListView.count > 0
                height: visible ? Kirigami.Units.gridUnit * 1.5 : 0
                Item { Layout.preferredWidth: Kirigami.Units.smallSpacing }
                Repeater {
                    model: root.activeTab === 0 ? listeningCols : establishedCols
                    delegate: Label {
                        readonly property var m: modelData
                        text: m.label + (root.sortColumn === m.col ? (root.sortDescending ? " ▼" : " ▲") : "")
                        font.bold: true; font.pixelSize: fullRoot.sf
                        Layout.preferredWidth: portListView.width * m.w - (index === 0 ? Kirigami.Units.smallSpacing : 0)
                        MouseArea {
                            anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.sortColumn === m.col) root.sortDescending = !root.sortDescending
                                else { root.sortColumn = m.col; root.sortDescending = false }
                                plasmoid.configuration.sortColumn = root.sortColumn
                                plasmoid.configuration.sortDescending = root.sortDescending
                            }
                        }
                    }
                }
            }

            // Column definitions
            property var listeningCols: [
                { col: "process_name", label: i18n("Process"), w: 0.30 },
                { col: "pid", label: i18n("PID"), w: 0.12 },
                { col: "proto", label: i18n("Proto"), w: 0.12 },
                { col: "local_port", label: i18n("Port"), w: 0.15 },
                { col: "remote_hostname", label: i18n("IP Address"), w: 0.31 }
            ]
            property var establishedCols: [
                { col: "process_name", label: i18n("Process"), w: 0.24 },
                { col: "local_port", label: i18n("Local"), w: 0.10 },
                { col: "remote_ip", label: i18n("Remote"), w: 0.22 },
                { col: "remote_country", label: i18n("Country"), w: 0.14 },
                { col: "remote_hostname", label: i18n("Hostname"), w: 0.20 },
                { col: "state", label: i18n("State"), w: 0.10 }
            ]

            delegate: Item {
                width: portListView.width; height: Kirigami.Units.gridUnit * 1.8
                readonly property var entry: model
                readonly property var ma: root.portAlertMap[entry.local_port] || null

                Rectangle {
                    anchors.fill: parent; color: Kirigami.Theme.highlightColor
                    opacity: lh.hovered ? 0.15 : 0.0; radius: Kirigami.Units.smallSpacing
                    Behavior on opacity { NumberAnimation { duration: 150 } }
                }
                HoverHandler { id: lh }
                ToolTip.visible: lh.hovered && ma !== null
                ToolTip.text: ma ? ma.message : ""
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
                    Item { Layout.preferredWidth: Kirigami.Units.smallSpacing }

                    RowLayout {
                        Layout.preferredWidth: parent.width * 0.30 - Kirigami.Units.smallSpacing
                        spacing: Kirigami.Units.smallSpacing
                        Item {
                            width: 14; height: 14; Layout.alignment: Qt.AlignVCenter
                            ToolTip.visible: dotHover.hovered
                            ToolTip.text: ma ? ma.message : (root.safePortsSet[entry.local_port] ? i18n("Safe port") : i18n("No alert"))
                            HoverHandler { id: dotHover }
                            Rectangle {
                                anchors.centerIn: parent; width: 8; height: 8; radius: 4
                                color: ma ? (ma.level === "CRITICAL" ? "#da4453" : "#f67400") : (root.safePortsSet[entry.local_port] ? "#27ae60" : "#3daee9")
                                opacity: root.safePortsSet[entry.local_port] && !ma ? 0.5 : 1.0
                                Rectangle {
                                    anchors.centerIn: parent; width: 16; height: 16; radius: 8
                                    color: parent.color; opacity: 0.25; visible: ma !== null
                                }
                            }
                        }
                        Label { text: entry.process_name || i18n("unknown"); font.pixelSize: fullRoot.sf; Layout.fillWidth: true; elide: Text.ElideRight }
                    }

                    Label { text: entry.pid ? String(entry.pid) : "-"; font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor; Layout.preferredWidth: parent.width * 0.12 }
                    Label { text: (entry.proto || "?").toUpperCase(); font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor; Layout.preferredWidth: parent.width * 0.12 }
                    Label { text: entry.local_port ? String(entry.local_port) : "-"; font.pixelSize: fullRoot.sf; font.bold: ma !== null; Layout.preferredWidth: parent.width * 0.15 }

                    RowLayout {
                        Layout.preferredWidth: parent.width * 0.31; spacing: 2
                        Label {
                            text: entry.remote_hostname ? entry.remote_hostname : (entry.local_ip || "")
                            font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                            Layout.fillWidth: true; elide: Text.ElideRight
                            ToolTip.visible: th.hovered; ToolTip.text: entry.local_ip
                            HoverHandler { id: th }
                        }
                        Button {
                            icon.name: "application-exit"; visible: lh.hovered && entry.pid > 0
                            implicitWidth: 28; implicitHeight: 28; Layout.alignment: Qt.AlignVCenter
                            ToolTip.text: i18n("Kill (%1)", entry.pid); ToolTip.visible: hovered; flat: true
                            onClicked: { killDialog.targetPid = entry.pid; killDialog.open() }
                        }
                    }
                }

                // ── Established tab delegate ────────────────────
                RowLayout {
                    anchors.fill: parent; spacing: 0
                    visible: root.activeTab === 1
                    Item { Layout.preferredWidth: Kirigami.Units.smallSpacing }

                    Label {
                        text: entry.process_name || i18n("unknown")
                        font.pixelSize: fullRoot.sf; Layout.fillWidth: false
                        Layout.preferredWidth: parent.width * 0.24 - Kirigami.Units.smallSpacing
                        elide: Text.ElideRight
                    }
                    Label { text: entry.local_port ? String(entry.local_port) : "-"; font.pixelSize: fullRoot.sf; Layout.preferredWidth: parent.width * 0.10 }
                    Label {
                        text: entry.remote_ip || "-"
                        font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.22; elide: Text.ElideRight
                        ToolTip.visible: ipHov.hovered; ToolTip.text: entry.remote_ip + ":" + (entry.remote_port || "?")
                        HoverHandler { id: ipHov }
                    }
                    Label {
                        text: entry.remote_country_code ? entry.remote_country_code.toUpperCase() : (entry.remote_country || "-")
                        font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.14
                    }
                    Label {
                        text: entry.remote_hostname || "-"
                        font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.20; elide: Text.ElideRight
                    }
                    Label {
                        text: entry.state || "?"
                        font.pixelSize: fullRoot.sf
                        color: entry.state === "ESTABLISHED" ? "#27ae60" : Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.10
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
                    anchors.horizontalCenter: parent.horizontalCenter
                    source: "view-refresh"
                    implicitWidth: Kirigami.Units.iconSizes.medium
                    implicitHeight: Kirigami.Units.iconSizes.medium
                    opacity: 0.5
                    NumberAnimation on opacity {
                        from: 0.3; to: 0.7; duration: 1200
                        running: parent.visible; loops: Animation.Infinite
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

            Label {
                text: root.lastUpdated ? i18n("Updated: %1", root.lastUpdated) : ""
                font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor
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
                icon.name: "utilities-terminal"; text: i18n("Analyzer")
                implicitHeight: Kirigami.Units.gridUnit * 1.6
                font.pixelSize: fullRoot.sf
                onClicked: root.launchTUI()
            }
        }
    }
}
