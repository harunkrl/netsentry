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
    property int establishedCount: 0
    property int alertCount: 0
    property string threatLevel: "secure"
    property var alertList: []
    property var portAlertMap: ({})
    property string lastUpdated: ""
    property int fetchFailures: 0
    property bool daemonDown: false
    property bool dataStale: false
    property string searchText: ""
    property string sortColumn: plasmoid.configuration.sortColumn || ""
    property bool sortDescending: plasmoid.configuration.sortDescending || false
    property int activeTab: 0   // 0 = listening, 1 = established

    // Traffic stats
    property string trafficRx: ""
    property string trafficTx: ""
    property string trafficIface: ""

    // Alert tracking for desktop notifications
    property int _lastAlertHash: 0

    ListModel { id: connectionsModel }
    ListModel { id: establishedModel }

    Plasmoid.title: i18n("KPortWatch")
    Plasmoid.icon: "security-high"
    toolTipMainText: i18n("Network Monitor")
    toolTipSubText: listeningCount + " listening, " + establishedCount + " established, " + alertCount + " alerts"

    compactRepresentation: CompactRepresentation {}
    fullRepresentation: FullRepresentation {}

    // ── Data polling timer ─────────────────────────────────────
    Timer {
        id: pollTimer
        interval: root.pollInterval * 1000
        running: true
        repeat: true
        onTriggered: dataSource.execQuery()
    }

    // ── Data source for reading daemon JSON ────────────────────
    Plasma5Support.DataSource {
        id: dataSource
        engine: 'executable'
        connectedSources: []
        property string _cmd: "sh -c 'cat ${XDG_RUNTIME_DIR:-/tmp}/kportwatch-widget-data.json 2>/dev/null'"

        function execQuery() {
            connectedSources = []
            connectedSources = [_cmd]
        }

        Component.onCompleted: connectedSources = [_cmd]

        onNewData: (sourceName, data) => {
            if (data['exit code'] === 0 && data.stdout) {
                root.fetchFailures = 0
                root.daemonDown = false
                root.dataStale = false
                root.parseSnapshot(data.stdout)
            } else {
                root.fetchFailures += 1
                root.dataStale = true
                if (root.fetchFailures >= 3) { root.daemonDown = true }
            }
            connectedSources = []
        }
    }

    // ── Notification source ────────────────────────────────────
    Plasma5Support.DataSource {
        id: notifySource
        engine: 'executable'
        connectedSources: []
        onNewData: (sourceName, data) => { connectedSources = [] }
    }

    function sendDesktopNotification(title, body, urgency) {
        var urg = urgency || "normal"
        notifySource.connectedSources = [
            "sh -c 'notify-send -a KPortWatch -u " + urg + " \"" + title.replace(/"/g, "'") + "\" \"" + body.replace(/"/g, "'") + "\" 2>/dev/null || true'"
        ]
    }

    // ── Snapshot parsing ───────────────────────────────────────
    function parseSnapshot(rawJson) {
        try {
            var parsed = JSON.parse(rawJson)
        } catch(e) {
            console.log("KPortWatch parse error: " + e)
            root.dataStale = true
            return
        }

        root.snapshotData = parsed
        root.listeningCount = parsed.summary ? parsed.summary.total_listening : 0
        root.establishedCount = parsed.summary ? parsed.summary.total_established : 0
        root.alertCount = parsed.summary ? parsed.summary.alert_count : 0
        root.lastUpdated = new Date().toLocaleTimeString(Qt.locale(), "HH:mm:ss")

        // ── Traffic stats ──────────────────────────────────────
        var traffic = parsed.traffic || {}
        var bestIface = ""
        var bestRx = 0
        var bestTx = 0
        var ifaces = Object.keys(traffic)
        for (var i = 0; i < ifaces.length; i++) {
            var iface = traffic[ifaces[i]]
            if (iface && !ifaces[i].startsWith("lo")) {
                var totalRate = (iface.rx_rate || 0) + (iface.tx_rate || 0)
                if (totalRate > bestRx + bestTx || bestIface === "") {
                    bestIface = ifaces[i]
                    bestRx = iface.rx_rate || 0
                    bestTx = iface.tx_rate || 0
                }
            }
        }
        root.trafficIface = bestIface
        root.trafficRx = formatBytes(bestRx) + "/s"
        root.trafficTx = formatBytes(bestTx) + "/s"

        // ── Filter alerts by threshold ─────────────────────────
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

        // ── Desktop notifications for new alerts ───────────────
        var alertHash = 0
        for (var i = 0; i < filtered.length; i++) {
            alertHash = (alertHash * 31 + filtered[i].port + filtered[i].level.charCodeAt(0)) | 0
        }
        if (filtered.length > 0 && alertHash !== root._lastAlertHash && root._lastAlertHash !== 0) {
            // Find new alerts (comparing by port+level)
            var prevMap = root._prevAlertMap || {}
            var newAlerts = []
            for (var i = 0; i < filtered.length; i++) {
                var aKey = filtered[i].port + "-" + filtered[i].level
                if (!prevMap[aKey]) { newAlerts.push(filtered[i]) }
            }
            if (newAlerts.length === 1) {
                var a = newAlerts[0]
                sendDesktopNotification(
                    "KPortWatch Alert: " + a.level,
                    a.message,
                    a.level === "CRITICAL" ? "critical" : "normal"
                )
            } else if (newAlerts.length > 1) {
                sendDesktopNotification(
                    "KPortWatch: " + newAlerts.length + " new alerts",
                    newAlerts[0].message + " (and " + (newAlerts.length - 1) + " more)",
                    "critical"
                )
            }
        }
        root._lastAlertHash = alertHash
        var prevAlertMap = {}
        for (var i = 0; i < filtered.length; i++) {
            prevAlertMap[filtered[i].port + "-" + filtered[i].level] = true
        }
        root._prevAlertMap = prevAlertMap

        // ── Filter and sort listening ports ────────────────────
        var newListening = parsed.listening || []
        var filter = root.searchText
        if (filter) {
            newListening = applyFilter(newListening, filter)
        }
        if (root.sortColumn) {
            newListening = applySort(newListening)
        }
        reconcileModel(connectionsModel, newListening)

        // ── Established connections ────────────────────────────
        var newEstablished = parsed.established || []
        if (filter) {
            newEstablished = applyFilter(newEstablished, filter)
        }
        reconcileModel(establishedModel, newEstablished)
    }

    // ── Utility functions ──────────────────────────────────────
    function formatBytes(bytesPerSec) {
        if (bytesPerSec < 1) return "0 B"
        if (bytesPerSec < 1024) return bytesPerSec.toFixed(0) + " B"
        if (bytesPerSec < 1048576) return (bytesPerSec / 1024).toFixed(1) + " KB"
        return (bytesPerSec / 1048576).toFixed(1) + " MB"
    }

    function applyFilter(items, filter) {
        var result = []
        for (var i = 0; i < items.length; i++) {
            var item = items[i]
            var searchable = [
                item.process_name || "", item.pid || "", item.proto || "",
                item.local_port || "", item.local_ip || "",
                item.remote_ip || "", item.remote_hostname || "",
                item.remote_country || ""
            ].join(" ").toLowerCase()
            if (searchable.indexOf(filter) !== -1) { result.push(item) }
        }
        return result
    }

    function applySort(items) {
        // Clone to avoid mutating the original
        var sorted = items.slice()
        sorted.sort(function(a, b) {
            var valA = a[root.sortColumn] || ""
            var valB = b[root.sortColumn] || ""
            if (typeof valA === "string") valA = valA.toLowerCase()
            if (typeof valB === "string") valB = valB.toLowerCase()
            var cmp = 0
            if (valA < valB) cmp = -1
            else if (valA > valB) cmp = 1
            return root.sortDescending ? -cmp : cmp
        })
        return sorted
    }

    // ── List model reconciliation ──────────────────────────────
    function reconcileModel(model, newItems) {
        var currentKeys = {}
        for (var i = 0; i < model.count; i++) {
            var m = model.get(i)
            currentKeys[m.proto + "-" + m.inode] = i
        }

        var newKeys = {}
        for (var i = 0; i < newItems.length; i++) {
            var item = newItems[i]
            var key = item.proto + "-" + item.inode
            newKeys[key] = true
            if (currentKeys[key] !== undefined) {
                model.set(currentKeys[key], item)
            } else {
                model.append(item)
            }
        }

        for (var i = model.count - 1; i >= 0; i--) {
            var m = model.get(i)
            if (!newKeys[m.proto + "-" + m.inode]) {
                model.remove(i)
            }
        }

        for (var i = 0; i < newItems.length; i++) {
            var expectedKey = newItems[i].proto + "-" + newItems[i].inode
            var actualItem = model.get(i)
            if (actualItem && (actualItem.proto + "-" + actualItem.inode !== expectedKey)) {
                for (var j = i + 1; j < model.count; j++) {
                    var itemJ = model.get(j)
                    if (itemJ.proto + "-" + itemJ.inode === expectedKey) {
                        model.move(j, i, 1)
                        break
                    }
                }
            }
        }
    }

    // ── External actions ───────────────────────────────────────
    function launchTUI() {
        var defaultCmd = "konsole -e kportwatch-tui"
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
        property int _pendingPid: 0
        onNewData: (sourceName, data) => {
            connectedSources = []
            if (_pendingPid > 0 && data['exit code'] === 0) {
                connectedSources = ["sh -c 'kill -0 " + _pendingPid + " 2>/dev/null && kill -9 " + _pendingPid + " || true'"]
                _pendingPid = 0
            }
        }
    }

    function killProcess(pid) {
        killExecSource._pendingPid = pid
        killExecSource.connectedSources = ["sh -c 'kill -15 " + pid + " 2>/dev/null; sleep 1; kill -0 " + pid + " 2>/dev/null'"]
    }
}
