import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    // Config properties
    property int pollInterval: plasmoid.configuration.pollInterval
    property string tuiCommand: plasmoid.configuration.tuiCommand

    // Data state
    property var snapshotData: null
    property int listeningCount: 0
    property int alertCount: 0
    property string threatLevel: "secure"  // "secure" | "warning" | "critical"
    property var alertList: []

    // Tooltip & metadata
    Plasmoid.title: i18n("NetSentry")
    Plasmoid.icon: "security-high"
    toolTipMainText: i18n("Network Monitor")
    toolTipSubText: listeningCount + " listening ports, " + alertCount + " alerts"

    // Representations
    compactRepresentation: CompactRepresentation {}
    fullRepresentation: FullRepresentation {}

    // Data source: poll JSON file via cat command
    Plasma5Support.DataSource {
        id: dataSource
        engine: 'executable'
        connectedSources: ["cat /tmp/netsentry-data.json"]
        interval: pollInterval * 1000

        onNewData: (sourceName, data) => {
            if (data['exit code'] === 0 && data.stdout) {
                try {
                    var parsed = JSON.parse(data.stdout)
                    root.snapshotData = parsed
                    root.listeningCount = parsed.summary ? parsed.summary.total_listening : 0
                    root.alertCount = parsed.summary ? parsed.summary.alert_count : 0
                    root.alertList = parsed.alerts || []

                    if (root.alertList.length > 0) {
                        var hasCritical = false
                        for (var i = 0; i < root.alertList.length; i++) {
                            if (root.alertList[i].level === "CRITICAL") {
                                hasCritical = true
                                break
                            }
                        }
                        root.threatLevel = hasCritical ? "critical" : "warning"
                    } else {
                        root.threatLevel = "secure"
                    }
                } catch(e) {
                    console.log("NetSentry parse error: " + e)
                }
            }
        }
    }

    // Launch TUI action
    function launchTUI() {
        execSource.connectedSources = [
            "konsole -e bash ~/NetSentry/widget/contents/scripts/launch-tui.sh"
        ]
    }

    Plasma5Support.DataSource {
        id: execSource
        engine: 'executable'
        connectedSources: []
        onNewData: (sourceName, data) => {
            connectedSources = []
        }
    }
}
