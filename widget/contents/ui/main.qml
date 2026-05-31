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
    property int popupWidth: plasmoid.configuration.popupWidth
    property int popupHeight: plasmoid.configuration.popupHeight
    property int iconSize: plasmoid.configuration.iconSize
    property int badgeSize: plasmoid.configuration.badgeSize
    property int fontScale: plasmoid.configuration.fontScale

    // Data state
    property var snapshotData: null
    property int listeningCount: 0
    property int alertCount: 0
    property string threatLevel: "secure"  // "secure" | "warning" | "critical"
    property var alertList: []
    property var portAlertMap: ({})
    property string lastUpdated: ""
    property int fetchFailures: 0
    property bool daemonDown: false
    property string searchText: ""
    property string sortColumn: ""
    property bool sortDescending: false

    // Diff-based model for listening ports
    ListModel {
        id: connectionsModel
    }

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
                root.fetchFailures = 0
                root.daemonDown = false
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

                    // Task 2.3: Pre-computed alert map
                    var newAlertMap = {}
                    for (var i = 0; i < filtered.length; i++) {
                        var a = filtered[i]
                        newAlertMap[a.port] = a
                    }
                    root.portAlertMap = newAlertMap

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

                    // Task 3.1: Widget Search & Sort
                    var newListening = parsed.listening || []
                    
                    var filter = root.searchText
                    if (filter) {
                        var filteredListening = []
                        for (var i = 0; i < newListening.length; i++) {
                            var item = newListening[i]
                            var searchable = [
                                item.process_name || "",
                                item.pid || "",
                                item.proto || "",
                                item.local_port || "",
                                item.local_ip || "",
                                item.remote_ip || "",
                                item.remote_hostname || ""
                            ].join(" ").toLowerCase()
                            
                            if (searchable.indexOf(filter) !== -1) {
                                filteredListening.push(item)
                            }
                        }
                        newListening = filteredListening
                    }

                    if (root.sortColumn) {
                        newListening.sort(function(a, b) {
                            var valA = a[root.sortColumn] || ""
                            var valB = b[root.sortColumn] || ""
                            if (typeof valA === "string") valA = valA.toLowerCase()
                            if (typeof valB === "string") valB = valB.toLowerCase()
                            
                            var cmp = 0
                            if (valA < valB) cmp = -1
                            else if (valA > valB) cmp = 1
                            
                            return root.sortDescending ? -cmp : cmp
                        })
                    }

                    // Task 2.1: Diff-Based Update for ListModel
                    var currentKeys = {}
                    for (var i = 0; i < connectionsModel.count; i++) {
                        var item = connectionsModel.get(i)
                        var key = item.proto + "-" + item.inode
                        currentKeys[key] = i
                    }
                    
                    var newKeys = {}
                    for (var i = 0; i < newListening.length; i++) {
                        var item = newListening[i]
                        var key = item.proto + "-" + item.inode
                        newKeys[key] = true
                        
                        if (currentKeys[key] !== undefined) {
                            connectionsModel.set(currentKeys[key], item)
                        } else {
                            connectionsModel.append(item)
                        }
                    }
                    
                    for (var i = connectionsModel.count - 1; i >= 0; i--) {
                        var item = connectionsModel.get(i)
                        var key = item.proto + "-" + item.inode
                        if (!newKeys[key]) {
                            connectionsModel.remove(i)
                        }
                    }

                    // Enforce Sort Order
                    for (var i = 0; i < newListening.length; i++) {
                        var expectedKey = newListening[i].proto + "-" + newListening[i].inode;
                        var actualItem = connectionsModel.get(i);
                        if (actualItem && (actualItem.proto + "-" + actualItem.inode !== expectedKey)) {
                            for (var j = i + 1; j < connectionsModel.count; j++) {
                                var itemJ = connectionsModel.get(j);
                                if (itemJ.proto + "-" + itemJ.inode === expectedKey) {
                                    connectionsModel.move(j, i, 1);
                                    break;
                                }
                            }
                        }
                    }

                } catch(e) {
                    console.log("NetSentry parse error: " + e)
                }
            } else {
                root.fetchFailures += 1
                if (root.fetchFailures >= 3) {
                    root.daemonDown = true
                }
            }
        }
    }

    // Launch TUI — spawns konsole with the venv-activated TUI
    function launchTUI() {
        var defaultCmd = "konsole -e bash -c 'source ~/NetSentry/.venv/bin/activate && exec netsentry-tui'"
        var cmd = root.tuiCommand ? root.tuiCommand : defaultCmd
        tuiExecSource.connectedSources = [ cmd ]
    }

    Plasma5Support.DataSource {
        id: tuiExecSource
        engine: 'executable'
        connectedSources: []
        onNewData: (sourceName, data) => {
            connectedSources = []
        }
    }

    Plasma5Support.DataSource {
        id: killExecSource
        engine: 'executable'
        connectedSources: []
        onNewData: (sourceName, data) => {
            connectedSources = []
        }
    }
}
