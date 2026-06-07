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
    property string safePortsStr: plasmoid.configuration.safePorts || ""
    property var safePortsSet: {
        var s = {}
        var parts = root.safePortsStr.split(",")
        for (var i = 0; i < parts.length; i++) {
            var n = parseInt(parts[i].trim())
            if (n > 0 && n <= 65535) s[n] = true
        }
        s
    }

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
    // Per-tab sort state (avoids cross-tab sort conflicts)
    property string sortColumnListening: ""
    property bool sortDescListening: false
    property string sortColumnEstablished: ""
    property bool sortDescEstablished: false
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
            // Delay disconnect to avoid race with timer re-fire
            disconnectTimer.start()
        }
    }

    // Delayed disconnect to prevent race between onNewData clearing sources
    // and the next execQuery() check for connectedSources.length === 0
    Timer {
        id: disconnectTimer
        interval: 50
        onTriggered: dataSource.connectedSources = []
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
        // Sanitize: remove any character that could break shell quoting
        var safeTitle = title.replace(/["'`\\$!?;|&(){}[\]<>\n\r]/g, " ").substring(0, 120)
        var safeBody = body.replace(/["'`\\$!?;|&(){}[\]<>\n\r]/g, " ").substring(0, 200)
        notifySource.connectedSources = [
            "sh -c 'notify-send -a KPortWatch -u " + urg + " \"" + safeTitle + "\" \"" + safeBody + "\" 2>/dev/null || true'"
        ]
    }

    // ── Snapshot parsing ───────────────────────────────────────
    function parseSnapshot(rawJson) {
        try {
            var parsed = JSON.parse(rawJson)
        } catch(e) {
            console.log("KPortWatch parse error: " + e)
            root.dataStale = true
            root.sendDesktopNotification(
                "KPortWatch Error",
                "Failed to parse daemon data: " + e,
                "low"
            )
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

        // ── Filter alerts by threshold & safe ports ────────────
        var allAlerts = parsed.alerts || []
        var filtered = []
        var thresholdOrder = ["INFO", "WARNING", "CRITICAL"]
        var thresholdIdx = thresholdOrder.indexOf(root.alertThreshold)
        for (var i = 0; i < allAlerts.length; i++) {
            var alertLevel = allAlerts[i].level || "INFO"
            var alertIdx = thresholdOrder.indexOf(alertLevel)
            var alertPort = allAlerts[i].port
            if (alertIdx >= thresholdIdx && !root.safePortsSet[alertPort]) { filtered.push(allAlerts[i]) }
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
        if (root.sortColumnListening) {
            newListening = applySort(newListening)
        }
        reconcileModel(connectionsModel, newListening)

        // ── Established connections ────────────────────────────
        var newEstablished = parsed.established || []
        if (filter) {
            newEstablished = applyFilter(newEstablished, filter)
        }
        if (root.sortColumnEstablished) {
            newEstablished = applySort(newEstablished)
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

    // Unique key for a socket entry — avoids inode=0 collisions from psutil
    function itemKey(item) {
        return item.proto + "-" + item.inode + "-" + item.local_ip + "-" + item.local_port + "-" + (item.remote_ip || "0") + "-" + (item.remote_port || 0) + "-" + (item.pid || 0)
    }

    function applySort(items) {
        // Clone to avoid mutating the original
        var sorted = items.slice()
        var col = root.activeTab === 0 ? root.sortColumnListening : root.sortColumnEstablished
        var desc = root.activeTab === 0 ? root.sortDescListening : root.sortDescEstablished
        sorted.sort(function(a, b) {
            var valA = a[col] || ""
            var valB = b[col] || ""
            if (typeof valA === "string") valA = valA.toLowerCase()
            if (typeof valB === "string") valB = valB.toLowerCase()
            var cmp = 0
            if (valA < valB) cmp = -1
            else if (valA > valB) cmp = 1
            return desc ? -cmp : cmp
        })
        return sorted
    }

    // ── List model reconciliation ──────────────────────────────
    function reconcileModel(model, newItems) {
        // Build index of current items by unique key
        var currentMap = {}   // key → index
        for (var i = 0; i < model.count; i++) {
            var m = model.get(i)
            currentMap[itemKey(m)] = i
        }

        // Build set of incoming keys
        var newSet = {}
        for (var i = 0; i < newItems.length; i++) {
            newSet[itemKey(newItems[i])] = true
        }

        // Step 1: Update existing items in-place or append new ones
        for (var i = 0; i < newItems.length; i++) {
            var item = newItems[i]
            var key = itemKey(item)
            if (currentMap[key] !== undefined) {
                model.set(currentMap[key], item)
            } else {
                model.append(item)
            }
        }

        // Step 2: Remove stale entries (no longer in new data)
        for (var i = model.count - 1; i >= 0; i--) {
            var m = model.get(i)
            if (!newSet[itemKey(m)]) {
                model.remove(i)
            }
        }

        // Step 3: Reorder to match incoming sort order (O(n) with key→index map)
        var keyToIdx = {}
        for (var k = 0; k < model.count; k++)
            keyToIdx[itemKey(model.get(k))] = k

        for (var i = 0; i < newItems.length && i < model.count; i++) {
            var expectedKey = itemKey(newItems[i])
            var actualItem = model.get(i)
            if (actualItem && itemKey(actualItem) !== expectedKey) {
                var currentIdx = keyToIdx[expectedKey]
                if (currentIdx !== undefined) {
                    model.move(currentIdx, i, 1)
                    // Update index map after move
                    for (var m = 0; m < model.count; m++)
                        keyToIdx[itemKey(model.get(m))] = m
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
        onNewData: (sourceName, data) => {
            connectedSources = []
        }
    }

    function killProcess(pid) {
        // Validate pid is a positive integer before passing to shell
        var safePid = String(pid).replace(/[^0-9]/g, "")
        if (safePid === "" || parseInt(safePid) <= 0) return
        killExecSource.connectedSources = ["sh -c 'kportwatchctl kill " + safePid + "'"]
    }
}
