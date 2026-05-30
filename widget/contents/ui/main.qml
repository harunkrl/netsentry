import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    // Config properties
    property int pollInterval: plasmoid.configuration.pollInterval
    property string tuiCommand: plasmoid.configuration.tuiCommand
    property bool showPortCount: plasmoid.configuration.showPortCount
    property string alertThreshold: plasmoid.configuration.alertThreshold
    property bool daemonEnabled: plasmoid.configuration.daemonEnabled

    // Data state
    property var snapshotData: null
    property int listeningCount: 0
    property int alertCount: 0
    property string threatLevel: "secure"  // "secure" | "warning" | "critical"
    property var alertList: []
    property string lastUpdated: ""

    // Tooltip & metadata
    Plasmoid.title: i18n("NetSentry")
    Plasmoid.icon: "security-high"
    toolTipMainText: i18n("Network Monitor")
    toolTipSubText: listeningCount + " listening ports, " + alertCount + " alerts"

    // Representations
    compactRepresentation: CompactRepresentation {}
    fullRepresentation: FullRepresentation {}

    // Data source: poll JSON file via cat command
    // Uses XDG_RUNTIME_DIR for secure data access (mode 0700 directory)
    Plasma5Support.DataSource {
        id: dataSource
        engine: 'executable'
        connectedSources: ["sh -c 'cat ${XDG_RUNTIME_DIR:-/tmp}/netsentry-data.json 2>/dev/null'"]
        interval: pollInterval * 1000

        onNewData: (sourceName, data) => {
            if (data['exit code'] === 0 && data.stdout) {
                try {
                    var parsed = JSON.parse(data.stdout)
                    root.snapshotData = parsed
                    root.listeningCount = parsed.summary ? parsed.summary.total_listening : 0
                    root.alertCount = parsed.summary ? parsed.summary.alert_count : 0
                    root.lastUpdated = new Date().toLocaleTimeString(Qt.locale(), "HH:mm:ss")

                    // Filter alerts based on configured threshold
                    var allAlerts = parsed.alerts || []
                    var filtered = []
                    var thresholdOrder = ["INFO", "WARNING", "CRITICAL"]
                    var thresholdIdx = thresholdOrder.indexOf(root.alertThreshold)
                    for (var i = 0; i < allAlerts.length; i++) {
                        var alertLevel = allAlerts[i].level || "INFO"
                        var alertIdx = thresholdOrder.indexOf(alertLevel)
                        if (alertIdx >= thresholdIdx) {
                            filtered.push(allAlerts[i])
                        }
                    }
                    root.alertList = filtered

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

    // Launch TUI — spawns konsole with the venv-activated TUI
    function launchTUI() {
        execSource.connectedSources = [
            "konsole -e bash -c 'source ~/NetSentry/.venv/bin/activate && exec netsentry-tui'"
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
