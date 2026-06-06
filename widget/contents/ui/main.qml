import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    property int pollInterval: plasmoid.configuration.pollInterval
    property string tuiCommand: plasmoid.configuration.tuiCommand
    property bool showPortCount: plasmoid.configuration.showPortCount
    property string alertThreshold: plasmoid.configuration.alertThreshold
    property int popupWidth: plasmoid.configuration.popupWidth
    property int popupHeight: plasmoid.configuration.popupHeight
    property int iconSize: plasmoid.configuration.iconSize
    property int badgeSize: plasmoid.configuration.badgeSize
    property int fontScale: plasmoid.configuration.fontScale

    property var snapshotData: null
    property int listeningCount: 0
    property int alertCount: 0
    property string threatLevel: "secure"
    property var alertList: []
    property var portAlertMap: ({})
    property string lastUpdated: ""
    property int fetchFailures: 0
    property bool daemonDown: false
    property string searchText: ""
    property string sortColumn: ""
    property bool sortDescending: false

    ListModel { id: connectionsModel }

    Plasmoid.title: i18n("NetSentry")
    Plasmoid.icon: "security-high"
    toolTipMainText: i18n("Network Monitor")
    toolTipSubText: listeningCount + " listening ports, " + alertCount + " alerts"

    compactRepresentation: CompactRepresentation {}
    fullRepresentation: FullRepresentation {}

    // ── Data polling timer (top-level, not inside DataSource) ──────
    Timer {
        id: pollTimer
        interval: root.pollInterval * 1000
        running: true
        repeat: true
        onTriggered: dataSource.execQuery()
    }

    // ── Data source for reading daemon JSON ────────────────────────
    Plasma5Support.DataSource {
        id: dataSource
        engine: 'executable'
        connectedSources: []

        property string _cmd: "sh -c 'cat ${XDG_RUNTIME_DIR:-/tmp}/netsentry-data.json 2>/dev/null'"

        function execQuery() {
            if (connectedSources.length === 0) {
                connectedSources = [_cmd]
            }
        }

        Component.onCompleted: connectedSources = [_cmd]

        onNewData: (sourceName, data) => {
            connectedSources = []

            if (data['exit code'] === 0 && data.stdout) {
                root.fetchFailures = 0
                root.daemonDown = false
                try {
                    var parsed = JSON.parse(data.stdout)
                    root.snapshotData = parsed
                    root.listeningCount = parsed.summary ? parsed.summary.total_listening : 0
                    root.alertCount = parsed.summary ? parsed.summary.alert_count : 0
                    root.lastUpdated = new Date().toLocaleTimeString(Qt.locale(), "HH:mm:ss")

                    var allAlerts = parsed.alerts || []
                    var filtered = []
                    var thresholdOrder = ["INFO", "WARNING", "CRITICAL"]
                    var thresholdIdx = thresholdOrder.indexOf(root.alertThreshold)
                    for (var i = 0; i < allAlerts.length; i++) {
                        var alertLevel = allAlerts[i].level || "INFO"
                        var alertIdx = thresholdOrder.indexOf(alertLevel)
                        if (alertIdx >= thresholdIdx) { filtered.push(allAlerts[i]) }
                    }
                    root.alertList = filtered

                    var newAlertMap = {}
                    for (var i = 0; i < filtered.length; i++) {
                        newAlertMap[filtered[i].port] = filtered[i]
                    }
                    root.portAlertMap = newAlertMap

                    if (root.alertList.length > 0) {
                        var hasCritical = false
                        for (var i = 0; i < root.alertList.length; i++) {
                            if (root.alertList[i].level === "CRITICAL") { hasCritical = true; break }
                        }
                        root.threatLevel = hasCritical ? "critical" : "warning"
                    } else {
                        root.threatLevel = "secure"
                    }

                    var newListening = parsed.listening || []
                    var filter = root.searchText
                    if (filter) {
                        var filteredListening = []
                        for (var i = 0; i < newListening.length; i++) {
                            var item = newListening[i]
                            var searchable = [
                                item.process_name || "", item.pid || "", item.proto || "",
                                item.local_port || "", item.local_ip || "",
                                item.remote_ip || "", item.remote_hostname || ""
                            ].join(" ").toLowerCase()
                            if (searchable.indexOf(filter) !== -1) { filteredListening.push(item) }
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

                    var currentKeys = {}
                    for (var i = 0; i < connectionsModel.count; i++) {
                        var m = connectionsModel.get(i)
                        currentKeys[m.proto + "-" + m.inode] = i
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
                        var m = connectionsModel.get(i)
                        if (!newKeys[m.proto + "-" + m.inode]) { connectionsModel.remove(i) }
                    }
                    for (var i = 0; i < newListening.length; i++) {
                        var expectedKey = newListening[i].proto + "-" + newListening[i].inode
                        var actualItem = connectionsModel.get(i)
                        if (actualItem && (actualItem.proto + "-" + actualItem.inode !== expectedKey)) {
                            for (var j = i + 1; j < connectionsModel.count; j++) {
                                var itemJ = connectionsModel.get(j)
                                if (itemJ.proto + "-" + itemJ.inode === expectedKey) {
                                    connectionsModel.move(j, i, 1); break
                                }
                            }
                        }
                    }
                } catch(e) { console.log("NetSentry parse error: " + e) }
            } else {
                root.fetchFailures += 1
                if (root.fetchFailures >= 3) { root.daemonDown = true }
            }
        }
    }

    function launchTUI() {
        var defaultCmd = "konsole -e bash -c 'source ~/Projects/NetSentry/.venv/bin/activate && exec netsentry-tui'"
        tuiExecSource.connectedSources = [root.tuiCommand ? root.tuiCommand : defaultCmd]
    }

    Plasma5Support.DataSource {
        id: tuiExecSource
        engine: 'executable'
        connectedSources: []
        onNewData: (sourceName, data) => { connectedSources = [] }
    }

    Plasma5Support.DataSource {
        id: killExecSource
        engine: 'executable'
        connectedSources: []
        onNewData: (sourceName, data) => { connectedSources = [] }
    }
}
