import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: configPage

    property alias cfg_pollInterval: pollIntervalSpin.value
    property alias cfg_showPortCount: showPortCountCheck.checked
    property string cfg_alertThreshold: "WARNING"
    property alias cfg_knownSafePorts: knownSafePortsField.text
    property alias cfg_tuiCommand: tuiCommandField.text

    SpinBox {
        id: pollIntervalSpin
        Kirigami.FormData.label: i18n("Poll interval (seconds):")
        from: 1
        to: 30
        stepSize: 1
        value: 2

        textFromValue: function(value) { return value + " s" }
        valueFromText: function(text) { return Number(text.replace(" s", "")) }
    }

    CheckBox {
        id: showPortCountCheck
        Kirigami.FormData.label: i18n("Show port count badge:")
        checked: true
    }

    ComboBox {
        id: alertThresholdCombo
        Kirigami.FormData.label: i18n("Alert threshold:")
        textRole: "label"
        model: [
            { label: i18n("INFO"), value: "INFO" },
            { label: i18n("WARNING"), value: "WARNING" },
            { label: i18n("CRITICAL"), value: "CRITICAL" }
        ]

        Component.onCompleted: {
            for (var i = 0; i < model.length; i++) {
                if (model[i].value === cfg_alertThreshold) {
                    currentIndex = i
                    break
                }
            }
        }

        onActivated: {
            cfg_alertThreshold = model[currentIndex].value
        }
    }

    TextField {
        id: knownSafePortsField
        Kirigami.FormData.label: i18n("Known safe ports:")
        placeholderText: "22,80,443,631,5353"
    }

    TextField {
        id: tuiCommandField
        Kirigami.FormData.label: i18n("TUI launch command:")
        placeholderText: "konsole -e bash -c 'source ~/NetSentry/.venv/bin/activate && exec netsentry-tui'"
    }
}
