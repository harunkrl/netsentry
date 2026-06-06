import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import org.kde.kirigami as Kirigami

Item {
    id: fullRoot
    Layout.preferredWidth: Kirigami.Units.gridUnit * root.popupWidth
    Layout.preferredHeight: Kirigami.Units.gridUnit * root.popupHeight

    readonly property bool hasData: root.snapshotData !== null
    readonly property int sf: Kirigami.Theme.smallFont.pixelSize * (root.fontScale / 100.0)
    readonly property int df: Kirigami.Theme.defaultFont.pixelSize * (root.fontScale / 100.0)

    readonly property string hi: {
        if (root.threatLevel === "critical") return "security-low"
        if (root.threatLevel === "warning") return "security-medium"
        return "security-high"
    }

    Kirigami.PromptDialog {
        id: killDialog
        property int targetPid: 0
        title: i18n("Kill Process")
        subtitle: i18n("Are you sure you want to terminate process %1?", targetPid)
        standardButtons: Kirigami.Dialog.Ok | Kirigami.Dialog.Cancel
        onAccepted: { killExecSource.connectedSources = ["kill -15 " + targetPid] }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

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

        Kirigami.InlineMessage {
            Layout.fillWidth: true; type: Kirigami.MessageType.Error
            text: i18n("Daemon not responding. Data may be stale."); visible: root.daemonDown
        }

        Kirigami.SearchField {
            Layout.fillWidth: true
            placeholderText: i18n("Search ports, processes, IP...")
            onTextChanged: root.searchText = text.toLowerCase()
        }

        ListView {
            id: portListView
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; model: connectionsModel; spacing: 1
            ScrollBar.vertical: ScrollBar {}

            header: RowLayout {
                width: portListView.width; spacing: 0
                visible: connectionsModel.count > 0
                height: visible ? Kirigami.Units.gridUnit * 1.5 : 0
                Item { Layout.preferredWidth: Kirigami.Units.smallSpacing }
                Repeater {
                    model: [
                        { col: "process_name", label: i18n("Process"), w: 0.30 },
                        { col: "pid", label: i18n("PID"), w: 0.12 },
                        { col: "proto", label: i18n("Proto"), w: 0.12 },
                        { col: "local_port", label: i18n("Port"), w: 0.15 },
                        { col: "remote_hostname", label: i18n("IP Address"), w: 0.31 }
                    ]
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
                            }
                        }
                    }
                }
            }

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
                    MenuItem { text: i18n("Copy IP"); onTriggered: { clip.text = entry.local_ip || ""; clip.selectAll(); clip.copy() } }
                    MenuSeparator {}
                    MenuItem { text: i18n("Kill Process"); icon.name: "application-exit"; enabled: entry.pid > 0
                        onTriggered: { killDialog.targetPid = entry.pid; killDialog.open() } }
                }

                RowLayout {
                    anchors.fill: parent; spacing: 0
                    Item { Layout.preferredWidth: Kirigami.Units.smallSpacing }

                    RowLayout {
                        Layout.preferredWidth: parent.width * 0.30 - Kirigami.Units.smallSpacing
                        spacing: Kirigami.Units.smallSpacing
                        Item {
                            width: 14; height: 14; Layout.alignment: Qt.AlignVCenter
                            Rectangle {
                                anchors.centerIn: parent; width: 8; height: 8; radius: 4
                                color: ma ? (ma.level === "CRITICAL" ? "#da4453" : "#f67400") : "#27ae60"
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
                            icon.name: "application-exit"; visible: entry.pid > 0
                            implicitWidth: 28; implicitHeight: 28; Layout.alignment: Qt.AlignVCenter
                            ToolTip.text: i18n("Kill (%1)", entry.pid); ToolTip.visible: hovered; flat: true
                            onClicked: { killDialog.targetPid = entry.pid; killDialog.open() }
                        }
                    }
                }
            }

            Label {
                anchors.fill: parent; visible: portListView.count === 0
                text: fullRoot.hasData ? i18n("No listening ports detected") : i18n("Waiting for data…\nMake sure kportwatch-daemon is running.")
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor; wrapMode: Text.WordWrap
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        RowLayout {
            Layout.fillWidth: true
            Label { text: root.lastUpdated ? i18n("Updated: %1", root.lastUpdated) : ""; font.pixelSize: fullRoot.sf; color: Kirigami.Theme.disabledTextColor }
            Item { Layout.fillWidth: true }
            Button { icon.name: "utilities-terminal"; text: i18n("Launch Analyzer"); onClicked: root.launchTUI() }
        }
    }
}
