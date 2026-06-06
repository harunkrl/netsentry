import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import org.kde.kirigami as Kirigami

Item {
    id: compactRoot
    Layout.minimumWidth: contentRow.implicitWidth + 8
    Layout.minimumHeight: contentRow.implicitHeight + 4
    Layout.preferredWidth: contentRow.implicitWidth + 8
    Layout.preferredHeight: contentRow.implicitHeight + 4

    readonly property string shieldIcon: {
        if (root.threatLevel === "critical") return "security-low"
        if (root.threatLevel === "warning") return "security-medium"
        return "security-high"
    }

    Row {
        id: contentRow
        anchors.centerIn: parent
        spacing: 4

        Kirigami.Icon {
            source: compactRoot.shieldIcon
            width: Math.min(compactRoot.width, compactRoot.height) * (root.iconSize / 100.0)
            height: Math.min(compactRoot.width, compactRoot.height) * (root.iconSize / 100.0)
            anchors.verticalCenter: parent.verticalCenter
        }

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(height, badgeLabel.implicitWidth + 8)
            height: Math.min(compactRoot.width, compactRoot.height) * (root.badgeSize / 100.0)
            radius: height / 2
            color: root.threatLevel === "critical" ? "#da4453" :
                   root.threatLevel === "warning" ? "#f67400" : "#27ae60"
            visible: root.listeningCount > 0 && root.showPortCount

            Label {
                id: badgeLabel
                anchors.centerIn: parent
                text: root.listeningCount
                font.pixelSize: parent.height * 0.75
                font.bold: true
                color: "#ffffff"
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        onClicked: (mouse) => {
            if (mouse.button === Qt.MiddleButton) root.launchTUI()
            else if (mouse.button === Qt.LeftButton) root.expanded = !root.expanded
        }
    }
}
