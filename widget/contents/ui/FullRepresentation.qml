import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import org.kde.kirigami as Kirigami

Item {
    id: fullRoot

    Layout.preferredWidth: Kirigami.Units.gridUnit * root.popupWidth
    Layout.preferredHeight: Kirigami.Units.gridUnit * root.popupHeight

    readonly property bool hasData: root.snapshotData !== null
    readonly property int scaledSmallFont: Kirigami.Theme.smallFont.pixelSize * (root.fontScale / 100.0)
    readonly property int scaledDefaultFont: Kirigami.Theme.defaultFont.pixelSize * (root.fontScale / 100.0)

    readonly property string headerIcon: {
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
        onAccepted: {
            killExecSource.connectedSources = ["kill -15 " + targetPid]
        }
    }

    ColumnLayout {
        id: mainLayout
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        // Header
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: fullRoot.headerIcon
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
            }

            Label {
                text: i18n("NetSentry — Network Security Monitor")
                font.bold: true
                font.pixelSize: fullRoot.scaledDefaultFont
            }

            Item { Layout.fillWidth: true }

            Label {
                visible: fullRoot.hasData
                text: root.alertCount > 0
                      ? i18n("%1 alert(s)", root.alertCount)
                      : i18n("Secure")
                color: root.threatLevel === "critical" ? "#e03030" :
                       root.threatLevel === "warning" ? "#e0c030" :
                       "#30c030"
                font.pixelSize: fullRoot.scaledSmallFont
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        // Task 3.3: Daemon-Down Warning
        Kirigami.InlineMessage {
            Layout.fillWidth: true
            type: Kirigami.MessageType.Error
            text: i18n("⚠ Daemon not responding. Data may be stale.")
            visible: root.daemonDown
        }

        // Task 3.1: Search Field
        Kirigami.SearchField {
            id: searchField
            Layout.fillWidth: true
            placeholderText: i18n("Search ports, processes, IP...")
            onTextChanged: root.searchText = text.toLowerCase()
        }

        // Port list
        ListView {
            id: portListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: connectionsModel
            spacing: 1

            ScrollBar.vertical: ScrollBar {}

            header: RowLayout {
                width: portListView.width
                spacing: 0
                visible: connectionsModel.count > 0
                height: visible ? Kirigami.Units.gridUnit * 1.5 : 0

                // Add left padding matching the delegate
                Item { Layout.preferredWidth: Kirigami.Units.smallSpacing }

                Label {
                    text: i18n("Process") + (root.sortColumn === "process_name" ? (root.sortDescending ? " ▼" : " ▲") : "")
                    font.bold: true
                    font.pixelSize: fullRoot.scaledSmallFont
                    Layout.preferredWidth: parent.width * 0.30 - Kirigami.Units.smallSpacing
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.sortColumn === "process_name") root.sortDescending = !root.sortDescending;
                            else { root.sortColumn = "process_name"; root.sortDescending = false; }
                        }
                    }
                }
                Label {
                    text: i18n("PID") + (root.sortColumn === "pid" ? (root.sortDescending ? " ▼" : " ▲") : "")
                    font.bold: true
                    font.pixelSize: fullRoot.scaledSmallFont
                    Layout.preferredWidth: parent.width * 0.12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.sortColumn === "pid") root.sortDescending = !root.sortDescending;
                            else { root.sortColumn = "pid"; root.sortDescending = false; }
                        }
                    }
                }
                Label {
                    text: i18n("Proto") + (root.sortColumn === "proto" ? (root.sortDescending ? " ▼" : " ▲") : "")
                    font.bold: true
                    font.pixelSize: fullRoot.scaledSmallFont
                    Layout.preferredWidth: parent.width * 0.12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.sortColumn === "proto") root.sortDescending = !root.sortDescending;
                            else { root.sortColumn = "proto"; root.sortDescending = false; }
                        }
                    }
                }
                Label {
                    text: i18n("Port") + (root.sortColumn === "local_port" ? (root.sortDescending ? " ▼" : " ▲") : "")
                    font.bold: true
                    font.pixelSize: fullRoot.scaledSmallFont
                    Layout.preferredWidth: parent.width * 0.15
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.sortColumn === "local_port") root.sortDescending = !root.sortDescending;
                            else { root.sortColumn = "local_port"; root.sortDescending = false; }
                        }
                    }
                }
                Label {
                    text: i18n("IP Address") + (root.sortColumn === "remote_hostname" ? (root.sortDescending ? " ▼" : " ▲") : "")
                    font.bold: true
                    font.pixelSize: fullRoot.scaledSmallFont
                    Layout.preferredWidth: parent.width * 0.31
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.sortColumn === "remote_hostname") root.sortDescending = !root.sortDescending;
                            else { root.sortColumn = "remote_hostname"; root.sortDescending = false; }
                        }
                    }
                }
            }

            delegate: Item {
                id: listItem
                width: portListView.width
                height: Kirigami.Units.gridUnit * 1.8 // Slightly taller for breathing room

                readonly property var entry: model
                readonly property var matchingAlert: root.portAlertMap[entry.local_port] || null

                // Hover Background Highlight
                Rectangle {
                    anchors.fill: parent
                    color: Kirigami.Theme.highlightColor
                    opacity: listHover.hovered ? 0.15 : 0.0
                    radius: Kirigami.Units.smallSpacing
                    Behavior on opacity { NumberAnimation { duration: 150 } }
                }
                HoverHandler { id: listHover }

                // Task 3.2: Alert Details Display
                ToolTip.visible: listHover.hovered && matchingAlert !== null
                ToolTip.text: matchingAlert ? matchingAlert.message : ""

                // Task 3.5: Context Menu & Copy to Clipboard
                TextEdit {
                    id: clipboardHelper
                    visible: false
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.RightButton
                    onClicked: (mouse) => {
                        if (mouse.button === Qt.RightButton) {
                            contextMenu.popup()
                        }
                    }
                }

                Menu {
                    id: contextMenu
                    MenuItem {
                        text: i18n("Copy Process Name")
                        onTriggered: {
                            clipboardHelper.text = entry.process_name || ""
                            clipboardHelper.selectAll(); clipboardHelper.copy()
                        }
                    }
                    MenuItem {
                        text: i18n("Copy PID")
                        onTriggered: {
                            clipboardHelper.text = entry.pid ? String(entry.pid) : ""
                            clipboardHelper.selectAll(); clipboardHelper.copy()
                        }
                    }
                    MenuItem {
                        text: i18n("Copy Port")
                        onTriggered: {
                            clipboardHelper.text = entry.local_port ? String(entry.local_port) : ""
                            clipboardHelper.selectAll(); clipboardHelper.copy()
                        }
                    }
                    MenuItem {
                        text: i18n("Copy IP Address")
                        onTriggered: {
                            clipboardHelper.text = entry.local_ip || ""
                            clipboardHelper.selectAll(); clipboardHelper.copy()
                        }
                    }
                    MenuSeparator {}
                    MenuItem {
                        text: i18n("Kill Process")
                        icon.name: "application-exit"
                        enabled: entry.pid > 0
                        onTriggered: {
                            killDialog.targetPid = entry.pid
                            killDialog.open()
                        }
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Left margin to match header
                    Item { Layout.preferredWidth: Kirigami.Units.smallSpacing }

                    // 1. Process
                    RowLayout {
                        Layout.preferredWidth: parent.width * 0.30 - Kirigami.Units.smallSpacing
                        spacing: Kirigami.Units.smallSpacing
                        
                        Item {
                            width: 14
                            height: 14
                            Layout.alignment: Qt.AlignVCenter
                            Rectangle {
                                anchors.centerIn: parent
                                width: 8; height: 8; radius: 4
                                color: matchingAlert
                                       ? (matchingAlert.level === "CRITICAL" ? "#da4453" : "#f67400")
                                       : "#27ae60"
                                Rectangle {
                                    anchors.centerIn: parent
                                    width: 16; height: 16; radius: 8
                                    color: parent.color
                                    opacity: 0.25
                                    visible: matchingAlert !== null
                                }
                            }
                        }
                        Label {
                            text: entry.process_name || i18n("unknown")
                            font.pixelSize: fullRoot.scaledSmallFont
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        Item { width: 4 } // padding
                    }

                    // 2. PID
                    Label {
                        text: entry.pid ? String(entry.pid) : "-"
                        font.pixelSize: fullRoot.scaledSmallFont
                        color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.12
                    }

                    // 3. Proto
                    Label {
                        text: (entry.proto || "?").toUpperCase()
                        font.pixelSize: fullRoot.scaledSmallFont
                        color: Kirigami.Theme.disabledTextColor
                        Layout.preferredWidth: parent.width * 0.12
                    }

                    // 4. Port
                    Label {
                        text: entry.local_port ? String(entry.local_port) : "-"
                        font.pixelSize: fullRoot.scaledSmallFont
                        font.bold: matchingAlert !== null
                        Layout.preferredWidth: parent.width * 0.15
                    }

                    // 5. IP Address
                    RowLayout {
                        Layout.preferredWidth: parent.width * 0.31
                        spacing: 2
                        
                        Label {
                            text: entry.remote_hostname ? entry.remote_hostname : (entry.local_ip || "")
                            font.pixelSize: fullRoot.scaledSmallFont
                            color: Kirigami.Theme.disabledTextColor
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            ToolTip.visible: t.hovered
                            ToolTip.text: entry.local_ip
                            HoverHandler { id: t }
                        }

                        Button {
                            icon.name: "application-exit"
                            text: ""
                            visible: entry.pid > 0
                            implicitWidth: 28
                            implicitHeight: 28
                            Layout.alignment: Qt.AlignVCenter
                            ToolTip.text: i18n("Kill Process (%1)", entry.pid)
                            ToolTip.visible: hovered
                            flat: true
                            
                            onClicked: {
                                killDialog.targetPid = entry.pid
                                killDialog.open()
                            }
                        }
                    }
                }
            }

            // Empty state
            Label {
                anchors.fill: parent
                visible: portListView.count === 0
                text: fullRoot.hasData
                      ? i18n("No listening ports detected")
                      : i18n("Waiting for data…\nMake sure netsentry-daemon is running.")
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                font.pixelSize: fullRoot.scaledSmallFont
                color: Kirigami.Theme.disabledTextColor
                wrapMode: Text.WordWrap
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        // Footer: last updated + launch button
        RowLayout {
            Layout.fillWidth: true

            Label {
                text: root.lastUpdated ? i18n("Updated: %1", root.lastUpdated) : ""
                font.pixelSize: fullRoot.scaledSmallFont
                color: Kirigami.Theme.disabledTextColor
            }

            Item { Layout.fillWidth: true }

            Button {
                icon.name: "utilities-terminal"
                text: i18n("Launch Analyzer")
                onClicked: root.launchTUI()
            }
        }
    }
}
