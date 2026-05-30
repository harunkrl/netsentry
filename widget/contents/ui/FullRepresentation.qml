import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import org.kde.kirigami as Kirigami

Item {
    id: fullRoot

    readonly property bool hasData: root.snapshotData !== null
    readonly property var listeningPorts: hasData ? (root.snapshotData.listening || []) : []

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
                source: "security-high"
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
                        Layout.preferredWidth: parent.width * 0.25
                        elide: Text.ElideRight
                    }

                    Label {
                        text: entry.pid ? String(entry.pid) : "-"
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        Layout.preferredWidth: parent.width * 0.12
                    }

                    Label {
                        text: (entry.proto || "?").toUpperCase()
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        Layout.preferredWidth: parent.width * 0.1
                    }

                    Label {
                        text: entry.local_port ? String(entry.local_port) : "-"
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        font.bold: matchingAlert !== null
                        Layout.preferredWidth: parent.width * 0.1
                    }

                    Label {
                        text: entry.local_ip || ""
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        color: Kirigami.Theme.disabledTextColor
                        Layout.fillWidth: true
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

        // Footer: launch button
        Button {
            Layout.fillWidth: true
            icon.name: "utilities-terminal"
            text: i18n("Launch Advanced Network Analyzer")
            onClicked: root.launchTUI()
        }
    }
}
