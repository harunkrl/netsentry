import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import org.kde.kirigami as Kirigami

Item {
    id: fullRoot

    Layout.preferredWidth: Kirigami.Units.gridUnit * 28
    Layout.preferredHeight: Kirigami.Units.gridUnit * 22

    readonly property bool hasData: root.snapshotData !== null
    readonly property var listeningPorts: hasData ? (root.snapshotData.listening || []) : []

    readonly property string headerIcon: {
        if (root.threatLevel === "critical") return "security-low"
        if (root.threatLevel === "warning") return "security-medium"
        return "security-high"
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
                font.pixelSize: Kirigami.Theme.defaultFont.pixelSize
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
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        // Port list
        ListView {
            id: portListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: fullRoot.listeningPorts
            spacing: 1

            ScrollBar.vertical: ScrollBar {}

            header: RowLayout {
                width: portListView.width
                spacing: Kirigami.Units.smallSpacing
                visible: fullRoot.listeningPorts.length > 0
                height: visible ? Kirigami.Units.gridUnit : 0

                Label {
                    text: i18n("Process")
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    Layout.fillWidth: true
                    Layout.minimumWidth: 80
                }
                Label {
                    text: i18n("PID")
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    Layout.minimumWidth: 40
                    Layout.preferredWidth: 50
                }
                Label {
                    text: i18n("Proto")
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    Layout.minimumWidth: 36
                    Layout.preferredWidth: 42
                }
                Label {
                    text: i18n("Port")
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    Layout.minimumWidth: 36
                    Layout.preferredWidth: 42
                }
                Label {
                    text: i18n("IP Address")
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    Layout.fillWidth: true
                    Layout.minimumWidth: 80
                }
            }

            delegate: Item {
                id: listItem
                width: portListView.width
                height: Kirigami.Units.gridUnit * 1.5

                readonly property var entry: modelData
                readonly property var matchingAlert: {
                    for (var i = 0; i < root.alertList.length; i++) {
                        if (root.alertList[i].port === entry.local_port) {
                            return root.alertList[i]
                        }
                    }
                    return null
                }

                RowLayout {
                    anchors.fill: parent
                    spacing: Kirigami.Units.smallSpacing

                    // Alert indicator dot
                    Rectangle {
                        width: 8
                        height: 8
                        radius: 4
                        color: matchingAlert
                               ? (matchingAlert.level === "CRITICAL" ? "#e03030" : "#e0c030")
                               : "#30c030"
                    }

                    Label {
                        text: entry.process_name || i18n("unknown")
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        Layout.fillWidth: true
                        Layout.minimumWidth: 80
                        elide: Text.ElideRight
                    }

                    Label {
                        text: entry.pid ? String(entry.pid) : "-"
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        Layout.minimumWidth: 40
                        Layout.preferredWidth: 50
                    }

                    Label {
                        text: (entry.proto || "?").toUpperCase()
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        Layout.minimumWidth: 36
                        Layout.preferredWidth: 42
                    }

                    Label {
                        text: entry.local_port ? String(entry.local_port) : "-"
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        font.bold: matchingAlert !== null
                        Layout.minimumWidth: 36
                        Layout.preferredWidth: 42
                    }

                    Label {
                        text: entry.local_ip || ""
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        color: Kirigami.Theme.disabledTextColor
                        Layout.fillWidth: true
                        Layout.minimumWidth: 80
                        elide: Text.ElideRight
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
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
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
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
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
