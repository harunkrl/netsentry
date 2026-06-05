import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ScrollView {
    id: configPage
    contentWidth: availableWidth

    property alias cfg_pollInterval: pollIntervalSpin.value
    property alias cfg_showPortCount: showPortCountCheck.checked
    property string cfg_alertThreshold: "WARNING"
    property alias cfg_tuiCommand: tuiCommandField.text
    property alias cfg_popupWidth: popupWidthSpin.value
    property alias cfg_popupHeight: popupHeightSpin.value
    property alias cfg_iconSize: iconSizeSpin.value
    property alias cfg_badgeSize: badgeSizeSpin.value
    property alias cfg_fontScale: fontScaleSpin.value

    Kirigami.FormLayout {
        width: configPage.availableWidth

        Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Appearance") }
        CheckBox {
            id: showPortCountCheck
            Kirigami.FormData.label: i18n("Badge:")
            text: i18n("Show listening port count in panel"); checked: true
        }

        Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Monitoring") }
        SpinBox {
            id: pollIntervalSpin; Kirigami.FormData.label: i18n("Refresh rate:")
            from: 1; to: 30; stepSize: 1; value: 2
            textFromValue: function(v) { return v + " seconds" }
            valueFromText: function(t) { return Number(t.replace(/[^0-9]/g, "")) }
        }
        ComboBox {
            id: alertThresholdCombo; Kirigami.FormData.label: i18n("Show alerts for:")
            textRole: "label"
            model: [
                { label: i18n("All events (INFO+)"), value: "INFO" },
                { label: i18n("Suspicious (WARNING+)"), value: "WARNING" },
                { label: i18n("Threats only (CRITICAL)"), value: "CRITICAL" }
            ]
            Component.onCompleted: { for (var i = 0; i < model.length; i++) { if (model[i].value === cfg_alertThreshold) { currentIndex = i; break } } }
            onActivated: { cfg_alertThreshold = model[currentIndex].value }
        }

        Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Size & Layout") }
        SpinBox { id: iconSizeSpin; Kirigami.FormData.label: i18n("Icon size:"); from: 30; to: 100; stepSize: 5; value: 70; textFromValue: function(v) { return v + " %" }; valueFromText: function(t) { return Number(t.replace(/[^0-9]/g, "")) } }
        SpinBox { id: badgeSizeSpin; Kirigami.FormData.label: i18n("Badge size:"); from: 30; to: 100; stepSize: 5; value: 60; textFromValue: function(v) { return v + " %" }; valueFromText: function(t) { return Number(t.replace(/[^0-9]/g, "")) } }
        SpinBox { id: fontScaleSpin; Kirigami.FormData.label: i18n("Text scale:"); from: 50; to: 200; stepSize: 10; value: 100; textFromValue: function(v) { return v + " %" }; valueFromText: function(t) { return Number(t.replace(/[^0-9]/g, "")) } }
        SpinBox { id: popupWidthSpin; Kirigami.FormData.label: i18n("Popup width:"); from: 15; to: 100; stepSize: 1; value: 32; textFromValue: function(v) { return v + " units" }; valueFromText: function(t) { return Number(t.replace(/[^0-9]/g, "")) } }
        SpinBox { id: popupHeightSpin; Kirigami.FormData.label: i18n("Popup height:"); from: 10; to: 100; stepSize: 1; value: 22; textFromValue: function(v) { return v + " units" }; valueFromText: function(t) { return Number(t.replace(/[^0-9]/g, "")) } }

        Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Advanced") }
        TextField {
            id: tuiCommandField; Kirigami.FormData.label: i18n("TUI command:"); Layout.fillWidth: true
            placeholderText: "konsole -e bash -c 'source ~/NetSentry/.venv/bin/activate && exec netsentry-tui'"
        }
        Label {
            Kirigami.FormData.label: ""; text: i18n("Command for 'Launch Analyzer' button.")
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize; color: Kirigami.Theme.disabledTextColor
        }
    }
}
