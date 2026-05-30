import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami

Item {
    id: compactRoot
    anchors.fill: parent

    readonly property string shieldIcon: {
        if (root.threatLevel === "critical") return "security-low"
        if (root.threatLevel === "warning") return "security-medium"
        return "security-high"
    }

    Kirigami.Icon {
        id: shieldIconItem
        source: compactRoot.shieldIcon
        anchors.centerIn: parent
        width: Math.min(parent.width, parent.height) * 0.7
        height: Math.min(parent.width, parent.height) * 0.7
    }

    Label {
        id: badge
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 2
        text: root.listeningCount
        font.pixelSize: Math.min(parent.width, parent.height) * 0.35
        font.bold: true
        color: root.threatLevel === "critical" ? "#e03030" :
               root.threatLevel === "warning" ? "#e0c030" :
               Kirigami.Theme.textColor
        visible: root.listeningCount > 0
    }

    MouseArea {
        anchors.fill: parent
        onClicked: {
            root.expanded = !root.expanded
        }
    }
}
